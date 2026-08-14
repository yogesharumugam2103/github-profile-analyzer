from flask import Flask, render_template, request
import requests
from dotenv import load_dotenv
from datetime import datetime, timedelta
import os
import re
from collections import defaultdict

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

if not GITHUB_TOKEN:
    raise RuntimeError(
        "GITHUB_TOKEN is missing. Please add it to your .env file."
    )

GITHUB_HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "X-GitHub-Api-Version": "2022-11-28"
}

app = Flask(__name__)

def rate_limit_message(response):
    return (
        response.status_code == 403
        and response.headers.get("X-RateLimit-Remaining") == "0"
    )

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/analyze")
def analyze():
    username = request.args.get("username", "").strip()

    if not username:
        return "Please enter a GitHub username."

    if not re.fullmatch(r"[A-Za-z0-9-]+", username):
        return "Invalid GitHub username. Please use only letters, numbers, and hyphens."

    try:
        response = requests.get(
            f"https://api.github.com/users/{username}",
            headers=GITHUB_HEADERS,
            timeout=10
        )

    except requests.exceptions.Timeout:
        return "GitHub took too long to respond. Please try again."

    except requests.exceptions.RequestException:
        return "Unable to connect to GitHub. Please check your internet connection and try again."

    if response.status_code == 404:
        return "GitHub user not found."

    if rate_limit_message(response):
        return "GitHub API rate limit reached. Please try again later."

    if response.status_code != 200:
        return "Something went wrong while contacting GitHub."

    user_data = response.json()

    profile_fields = [
        user_data.get("name"),
        user_data.get("bio"),
        user_data.get("location"),
        user_data.get("company"),
        user_data.get("blog"),
        user_data.get("twitter_username"),
        user_data.get("avatar_url"),
        user_data.get("email")
    ]
    
    completed_profile_fields = sum(
        1 for field in profile_fields
        if field
    )

    total_profile_fields = len(profile_fields)

    profile_completeness = round(
        (completed_profile_fields / total_profile_fields) * 100
    )

    profile_field_names = [
        ("Name", user_data.get("name")),
        ("Bio", user_data.get("bio")),
        ("Location", user_data.get("location")),
        ("Company", user_data.get("company")),
        ("Website", user_data.get("blog")),
        ("Twitter/X", user_data.get("twitter_username")),
        ("Profile Picture", user_data.get("avatar_url")),
        ("Public Email", user_data.get("email"))
    ]

    missing_profile_fields = [
        name
        for name, value in profile_field_names
        if not value
    ]

    repos = []

    page = 1

    while True:
        try:
            repos_response = requests.get(
                f"https://api.github.com/users/{username}/repos",
                params={
                    "per_page": 100,
                    "page": page
                },
                headers=GITHUB_HEADERS,
                timeout=10
            )

        except requests.exceptions.Timeout:
            return "GitHub took too long to respond while fetching repositories."

        except requests.exceptions.RequestException:
            return "Unable to fetch repositories from GitHub. Please try again."

        if rate_limit_message(repos_response):
            return "GitHub API rate limit reached. Please try again later."
        
        if repos_response.status_code != 200:
            return "Unable to fetch repositories from GitHub."
    
        page_repos = repos_response.json()
    
        if not page_repos:
            break
    
        repos.extend(page_repos)
    
        if len(page_repos) < 100:
            break
    
        page += 1

    recent_repos = sorted(
        repos,
        key=lambda repo: repo["updated_at"],
        reverse=True
    )[:3]

    active_repositories = []

    for repo in recent_repos:
        commit_count = 0
        page = 1

        while True:
            try:
                commits_response = requests.get(
                    f"https://api.github.com/repos/{username}/{repo['name']}/commits",
                    params={
                        "since": (
                            datetime.utcnow() - timedelta(days=30)
                        ).isoformat() + "Z",
                        "per_page": 100,
                        "page": page
                    },
                    headers=GITHUB_HEADERS,
                    timeout=10
                )
            except requests.exceptions.Timeout:
                commit_count = None
                break
            except requests.exceptions.RequestException:
                commit_count = None
                break
    
            if rate_limit_message(commits_response):
                commit_count = None
                break
    
            if commits_response.status_code != 200:
                commit_count = None
                break
    
            commits = commits_response.json()
    
            commit_count += len(commits)
    
            if len(commits) < 100:
                break
    
            page += 1
    
        if commit_count is not None:
            active_repositories.append({
                "name": repo["name"],
                "html_url": repo["html_url"],
                "commit_count": commit_count
            })
  
    graphql_query = """
    query($username: String!) {
        user(login: $username) {
            contributionsCollection {
                totalCommitContributions
                contributionCalendar {
                    totalContributions
                    weeks {
                        contributionDays {
                            contributionCount
                            date
                        }
                    }
                }
            }
        }
    }
    """

    try:
        graphql_response = requests.post(
            "https://api.github.com/graphql",
            json={
                "query": graphql_query,
                "variables": {
                    "username": username
                }
            },
            headers={
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "X-GitHub-Api-Version": "2022-11-28"
            },
            timeout=10
        )
    
        graphql_data = graphql_response.json()

        print("GRAPHQL STATUS:", graphql_response.status_code)
        print("GRAPHQL RESPONSE:", graphql_data)

        if rate_limit_message(graphql_response):
            graphql_data = {}

    except requests.exceptions.Timeout:
        graphql_data = {}

    except requests.exceptions.RequestException:
        graphql_data = {}

    contributions_available = False
    total_contributions = None

    contribution_days = []

    if (
        "data" in graphql_data
        and graphql_data["data"].get("user")
        and "contributionsCollection" in graphql_data["data"]["user"]
    ):
        contributions_available = True
    
        weeks = (
            graphql_data["data"]["user"]
            ["contributionsCollection"]
            ["contributionCalendar"]
            ["weeks"]
        )
    
        for week in weeks:
            for day in week["contributionDays"]:
                contribution_days.append(day)

    active_days = sum(
        1 for day in contribution_days
        if day["contributionCount"] > 0
    )

    total_days = len(contribution_days)

    if total_days > 0:
        contribution_frequency = round(
            (active_days / total_days) * 100,
            2
        )
    else:
        contribution_frequency = 0
    
    longest_streak = 0
    current_streak = 0

    for day in contribution_days:
        if day["contributionCount"] > 0:
            current_streak += 1
            longest_streak = max(longest_streak, current_streak)
        else:
            current_streak = 0
    
    if contributions_available:
        total_contributions = (
            graphql_data["data"]["user"]
            ["contributionsCollection"]
            ["contributionCalendar"]
            ["totalContributions"]
        )

    if contributions_available and total_contributions is not None and active_days > 0:
        average_contributions = round(
            total_contributions / active_days,
            2
        )
    else:
        average_contributions = 0

    most_active_day = None

    if contribution_days:
        most_active_day = max(
            contribution_days,
            key=lambda day: day["contributionCount"]
        )

    monthly_contributions = defaultdict(int)

    for day in contribution_days:
        month = day["date"][:7]
        monthly_contributions[month] += day["contributionCount"]
    
    if contribution_days:
        first_month = datetime.strptime(
            contribution_days[0]["date"],
            "%Y-%m-%d"
        ).replace(day=1)
    
        last_month = datetime.strptime(
            contribution_days[-1]["date"],
            "%Y-%m-%d"
        ).replace(day=1)
    
        current_month = first_month
    
        while current_month <= last_month:
            month_key = current_month.strftime("%Y-%m")
    
            if month_key not in monthly_contributions:
                monthly_contributions[month_key] = 0
    
            if current_month.month == 12:
                current_month = current_month.replace(
                    year=current_month.year + 1,
                    month=1
                )
            else:
                current_month = current_month.replace(
                    month=current_month.month + 1
                )

    most_active_month = None

    if monthly_contributions:
        most_active_month = max(
            monthly_contributions,
            key=monthly_contributions.get
        )

    most_active_month_count = (
        monthly_contributions[most_active_month]
        if most_active_month
        else 0
    )    

    if most_active_month:
        most_active_month_display = datetime.strptime(
            most_active_month,
            "%Y-%m"
        ).strftime("%B %Y")
    else:
        most_active_month_display = "—"


    contribution_heatmap = []

    if "data" in graphql_data and graphql_data["data"].get("user"):
        weeks = (
            graphql_data["data"]["user"]
            ["contributionsCollection"]
            ["contributionCalendar"]
            ["weeks"]
        )
    
        for week in weeks:
            week_data = []
    
            for day in week["contributionDays"]:
                count = day["contributionCount"]
    
                if count == 0:
                    level = 0
                elif count <= 2:
                    level = 1
                elif count <= 5:
                    level = 2
                elif count <= 10:
                    level = 3
                else:
                    level = 4
    
                week_data.append({
                    "date": day["date"],
                    "count": count,
                    "level": level
                })
    
            contribution_heatmap.append(week_data)


    if contributions_available and monthly_contributions:
        sorted_months = sorted(monthly_contributions.keys())

        recent_months = sorted_months[-3:]
        previous_months = sorted_months[-6:-3]
    
        recent_total = sum(
            monthly_contributions[month]
            for month in recent_months
        )
    
        previous_total = sum(
            monthly_contributions[month]
            for month in previous_months
        )
    
        if recent_total > previous_total:
            contribution_trend = "Increasing"
        elif recent_total < previous_total:
            contribution_trend = "Decreasing"
        else:
            contribution_trend = "Stable"
    else:
        contribution_trend = None


    total_stars = sum(repo["stargazers_count"] for repo in repos)
    total_forks = sum(repo["forks_count"] for repo in repos)

    language_counts = {}

    for repo in repos:
        language = repo["language"]

        if language:
            language_counts[language] = language_counts.get(language, 0) + 1

    most_used_language = "Not available"

    if language_counts:
        most_used_language = max(
            language_counts,
            key=language_counts.get
        )

    most_starred_repo = None

    if repos:
        most_starred_repo = max(
            repos,
            key=lambda repo: repo["stargazers_count"]
        )    
    most_forked_repo = None

    if repos:
        most_forked_repo = max(
            repos,
            key=lambda repo: repo["forks_count"]
        )

    average_stars = 0

    if repos:
        average_stars = round(total_stars / len(repos), 2)

    original_repos = sum(1 for repo in repos if not repo["fork"])
    forked_repos = sum(1 for repo in repos if repo["fork"]) 

    archived_repos = sum(
        1 for repo in repos
        if repo["archived"]
    )

    repo_size_distribution = {
        "Small": 0,
        "Medium": 0,
        "Large": 0
    }
    
    for repo in repos:
        size = repo.get("size", 0)
    
        if size < 1000:
            repo_size_distribution["Small"] += 1
        elif size < 10000:
            repo_size_distribution["Medium"] += 1
        else:
            repo_size_distribution["Large"] += 1

    total_language_repos = sum(language_counts.values())

    language_percentages = {}

    for language, count in language_counts.items():
        percentage = round((count / total_language_repos) * 100, 1)
        language_percentages[language] = percentage
    
    return render_template(
        "profile.html",
        user=user_data,
        repos=repos,
        total_stars=total_stars,
        total_forks=total_forks,
        most_used_language=most_used_language,
        language_percentages=language_percentages,
        most_starred_repo=most_starred_repo,
        most_forked_repo=most_forked_repo,
        average_stars=average_stars,
        original_repos=original_repos,
        forked_repos=forked_repos,
        total_contributions=total_contributions,
        contribution_days=contribution_days,
        active_days=active_days,
        longest_streak=longest_streak,
        contribution_heatmap=contribution_heatmap,
        average_contributions=average_contributions,
        most_active_day=most_active_day,
        most_active_month=most_active_month,
        most_active_month_count=most_active_month_count,
        most_active_month_display=most_active_month_display,
        contribution_frequency=contribution_frequency,
        contribution_trend=contribution_trend,
        archived_repos=archived_repos,
        repo_size_distribution=repo_size_distribution,
        completed_profile_fields=completed_profile_fields,
        total_profile_fields=total_profile_fields,
        profile_completeness=profile_completeness,
        missing_profile_fields=missing_profile_fields,
        monthly_contributions=monthly_contributions,
        contributions_available=contributions_available,
        recent_repos=recent_repos,
        active_repositories=active_repositories
    )

def contribution_metrics(username):
    graphql_query = """
    query($username: String!) {
        user(login: $username) {
            contributionsCollection {
                totalCommitContributions
                contributionCalendar {
                    totalContributions
                    weeks {
                        contributionDays {
                            contributionCount
                            date
                        }
                    }
                }
            }
        }
    }
    """

    try:
        response = requests.post(
            "https://api.github.com/graphql",
            json={
                "query": graphql_query,
                "variables": {
                    "username": username
                }
            },
            headers=GITHUB_HEADERS,
            timeout=10
        )
    except requests.exceptions.Timeout:
        return None
    except requests.exceptions.RequestException:
        return None

    if rate_limit_message(response):
        return None

    if response.status_code != 200:
        return None

    try:
        data = response.json()
    except ValueError:
        return None

    print("GRAPHQL STATUS:", response.status_code)
    print("GRAPHQL RESPONSE:", data)

    if data.get("errors"):
        return None

    if (
        "data" not in data
        or not data["data"].get("user")
    ):
        return None

    contributions_collection = (
        data["data"]["user"]
        ["contributionsCollection"]
    )

    calendar = contributions_collection.get("contributionCalendar", {})
    contribution_days = []

    for week in calendar["weeks"]:
        for day in week["contributionDays"]:
            contribution_days.append(day)

    total_contributions = calendar.get("totalContributions", 0)
    total_commits = contributions_collection.get("totalCommitContributions", 0)

    active_days = sum(
        1
        for day in contribution_days
        if day["contributionCount"] > 0
    )

    longest_streak = 0
    current_streak = 0

    for day in contribution_days:
        if day["contributionCount"] > 0:
            current_streak += 1
            longest_streak = max(
                longest_streak,
                current_streak
            )
        else:
            current_streak = 0

    if active_days > 0:
        average_contributions = round(
            total_contributions / active_days,
            2
        )
    else:
        average_contributions = 0

    monthly_contributions = defaultdict(int)

    for day in contribution_days:
        month = day["date"][:7]
        monthly_contributions[month] += day["contributionCount"]

    most_active_month = None

    if monthly_contributions:
        most_active_month = max(
            monthly_contributions,
            key=monthly_contributions.get
        )

    most_active_month_count = (
        monthly_contributions[most_active_month]
        if most_active_month
        else 0
    )

    sorted_months = sorted(monthly_contributions.keys())

    if len(sorted_months) >= 6:
        recent_months = sorted_months[-3:]
        previous_months = sorted_months[-6:-3]

        recent_total = sum(
            monthly_contributions[month]
            for month in recent_months
        )

        previous_total = sum(
            monthly_contributions[month]
            for month in previous_months
        )

        if recent_total > previous_total:
            contribution_trend = "Increasing"
        elif recent_total < previous_total:
            contribution_trend = "Decreasing"
        else:
            contribution_trend = "Stable"
    else:
        contribution_trend = "Not enough data"

    return {
        "total_contributions": total_contributions,
        "total_commits": total_commits,
        "active_days": active_days,
        "longest_streak": longest_streak,
        "average_contributions": average_contributions,
        "most_active_month": most_active_month,
        "most_active_month_count": most_active_month_count,
        "contribution_trend": contribution_trend
    }

@app.route("/compare")
def compare():
    username1 = request.args.get("username1", "").strip()
    username2 = request.args.get("username2", "").strip()

    if not username1 or not username2:
        return render_template("compare.html")

    if not re.fullmatch(r"[A-Za-z0-9-]+", username1):
        return "Invalid first GitHub username."

    if not re.fullmatch(r"[A-Za-z0-9-]+", username2):
        return "Invalid second GitHub username."

    if username1.lower() == username2.lower():
        return "Please enter two different GitHub usernames."

    users = []

    for username in [username1, username2]:
        try:
            response = requests.get(
                f"https://api.github.com/users/{username}",
                headers=GITHUB_HEADERS,
                timeout=10
            )

        except requests.exceptions.Timeout:
            return "GitHub took too long to respond. Please try again."

        except requests.exceptions.RequestException:
            return "Unable to connect to GitHub. Please check your internet connection and try again."

        if response.status_code == 404:
            return f"GitHub user '{username}' not found."

        if rate_limit_message(response):
            return "GitHub API rate limit reached. Please try again later."

        if response.status_code != 200:
            return "Something went wrong while contacting GitHub."

        users.append(response.json())

    user1 = users[0]
    user2 = users[1]

    comparison_metrics = [
        {
            "name": "Followers",
            "value1": user1["followers"],
            "value2": user2["followers"]
        },
        {
            "name": "Following",
            "value1": user1["following"],
            "value2": user2["following"]
        },
        {
            "name": "Public Repositories",
            "value1": user1["public_repos"],
            "value2": user2["public_repos"]
        }
    ]

    user_repositories = []

    for username in [username1, username2]:
        repositories = []
        page = 1

        while True:
            try:
                repos_response = requests.get(
                    f"https://api.github.com/users/{username}/repos",
                    params={
                        "per_page": 100,
                        "page": page
                    },
                    headers=GITHUB_HEADERS,
                    timeout=10
                )
            except requests.exceptions.Timeout:
                return "GitHub took too long to respond while fetching repositories."
            except requests.exceptions.RequestException:
                return "Unable to fetch repositories from GitHub."
    
            if rate_limit_message(repos_response):
                return "GitHub API rate limit reached. Please try again later."
    
            if repos_response.status_code != 200:
                return "Unable to fetch repositories from GitHub."
    
            page_repositories = repos_response.json()
    
            if not page_repositories:
                break
    
            repositories.extend(page_repositories)
    
            if len(page_repositories) < 100:
                break
    
            page += 1
    
        user_repositories.append(repositories)

    repos1 = user_repositories[0]
    repos2 = user_repositories[1]

    def repository_metrics(repositories):
        total_stars = sum(
            repo["stargazers_count"]
            for repo in repositories
        )
    
        total_forks = sum(
            repo["forks_count"]
            for repo in repositories
        )

        average_stars = 0

        if repositories:
            average_stars = round(
                total_stars / len(repositories),
                2
            )
    
        original_repos = sum(
            1 for repo in repositories
            if not repo["fork"]
        )

        forked_repos = sum(
            1 for repo in repositories
            if repo["fork"]
        )
    
        archived_repos = sum(
            1 for repo in repositories
            if repo["archived"]
        )
    
        language_counts = {}
    
        for repo in repositories:
            language = repo["language"]
    
            if language:
                language_counts[language] = (
                    language_counts.get(language, 0) + 1
                )
    
        most_used_language = "Not available"
    
        if language_counts:
            most_used_language = max(
                language_counts,
                key=language_counts.get
            )
    
        return {
            "total_stars": total_stars,
            "total_forks": total_forks,
            "average_stars": average_stars,
            "original_repos": original_repos,
            "forked_repos": forked_repos,
            "archived_repos": archived_repos,
            "most_used_language": most_used_language
        }

    repo_metrics1 = repository_metrics(repos1)
    repo_metrics2 = repository_metrics(repos2)
    contribution_metrics1 = contribution_metrics(username1)
    contribution_metrics2 = contribution_metrics(username2)

    comparison_metrics.extend([
        {
            "name": "Total Stars",
            "value1": repo_metrics1["total_stars"],
            "value2": repo_metrics2["total_stars"]
        },
        {
            "name": "Total Forks",
            "value1": repo_metrics1["total_forks"],
            "value2": repo_metrics2["total_forks"]
        },
        {
            "name": "Average Stars / Repository",
            "value1": repo_metrics1["average_stars"],
            "value2": repo_metrics2["average_stars"]
        },
        {
            "name": "Original Repositories",
            "value1": repo_metrics1["original_repos"],
            "value2": repo_metrics2["original_repos"]
        },
        {
            "name": "Forked Repositories",
            "value1": repo_metrics1["forked_repos"],
            "value2": repo_metrics2["forked_repos"]
        },
        {
            "name": "Archived Repositories",
            "value1": repo_metrics1["archived_repos"],
            "value2": repo_metrics2["archived_repos"]
        },
        {
            "name": "Most Used Language",
            "value1": repo_metrics1["most_used_language"],
            "value2": repo_metrics2["most_used_language"]
        }
    ])

    if contribution_metrics1 and contribution_metrics2:
        comparison_metrics.extend([
            {
                "name": "Total Contributions",
                "value1": contribution_metrics1["total_contributions"],
                "value2": contribution_metrics2["total_contributions"]
            },
            {
                "name": "Total Commits",
                "value1": contribution_metrics1["total_commits"],
                "value2": contribution_metrics2["total_commits"]
            },
            {
                "name": "Active Contribution Days",
                "value1": contribution_metrics1["active_days"],
                "value2": contribution_metrics2["active_days"]
            },
            {
                "name": "Longest Contribution Streak",
                "value1": contribution_metrics1["longest_streak"],
                "value2": contribution_metrics2["longest_streak"]
            },
            {
                "name": "Average Contributions / Active Day",
                "value1": contribution_metrics1["average_contributions"],
                "value2": contribution_metrics2["average_contributions"]
            },
            {
                "name": "Most Active Month",
                "value1": contribution_metrics1["most_active_month"],
                "value2": contribution_metrics2["most_active_month"]
            },
            {
                "name": "Contribution Trend",
                "value1": contribution_metrics1["contribution_trend"],
                "value2": contribution_metrics2["contribution_trend"]
            }
        ])

    comparison_categories = {
        "visibility": {
            "label": "Visibility",
            "metrics": [
                {
                    "name": "Followers",
                    "value1": user1["followers"],
                    "value2": user2["followers"]
                }
            ]
        },
    
        "project_impact": {
            "label": "Project Impact",
            "metrics": [
                {
                    "name": "Total Stars",
                    "value1": repo_metrics1["total_stars"],
                    "value2": repo_metrics2["total_stars"]
                },
                {
                    "name": "Total Forks",
                    "value1": repo_metrics1["total_forks"],
                    "value2": repo_metrics2["total_forks"]
                },
                {
                    "name": "Average Stars / Repository",
                    "value1": repo_metrics1["average_stars"],
                    "value2": repo_metrics2["average_stars"]
                }
            ]
        },
    
        "repository_portfolio": {
            "label": "Repository Portfolio",
            "metrics": [
                {
                    "name": "Original Repositories",
                    "value1": repo_metrics1["original_repos"],
                    "value2": repo_metrics2["original_repos"]
                }
            ]
        }
    }

    if contribution_metrics1 and contribution_metrics2:
        comparison_categories["development_activity"] = {
            "label": "Development Activity",
            "metrics": [
                {
                    "name": "Total Contributions",
                    "value1": contribution_metrics1["total_contributions"],
                    "value2": contribution_metrics2["total_contributions"]
                },
                {
                    "name": "Total Commits",
                    "value1": contribution_metrics1["total_commits"],
                    "value2": contribution_metrics2["total_commits"]
                },
                {
                    "name": "Active Contribution Days",
                    "value1": contribution_metrics1["active_days"],
                    "value2": contribution_metrics2["active_days"]
                },
                {
                    "name": "Longest Contribution Streak",
                    "value1": contribution_metrics1["longest_streak"],
                    "value2": contribution_metrics2["longest_streak"]
                },
                {
                    "name": "Average Contributions / Active Day",
                    "value1": contribution_metrics1["average_contributions"],
                    "value2": contribution_metrics2["average_contributions"]
                }
            ]
        }

    # ============================================================
# WEIGHTED NORMALIZED PROFILE SCORING
# ============================================================

    def normalized_metric_score(value, other_value, higher_is_better=True):
        """
        Converts two metric values into relative scores between 0 and 100.
    
        The score is based on the proportion of the combined value.
        This means the actual magnitude of the difference matters.
    
        Example:
            100 vs 50
            -> 66.67 vs 33.33
    
            10 vs 9
            -> 52.63 vs 47.37
        """
    
        if not isinstance(value, (int, float)):
            return None
    
        if not isinstance(other_value, (int, float)):
            return None
    
        if value < 0 or other_value < 0:
            return None
    
        total = value + other_value
    
        if total == 0:
            return 50.0
    
        if higher_is_better:
            score = (value / total) * 100
        else:
            score = (other_value / total) * 100
    
        return round(score, 2)
    

# ------------------------------------------------------------
# Metric importance weights
# ------------------------------------------------------------

    metric_weights = {
        "Followers": 0.75,

        "Total Stars": 1.00,
        "Total Forks": 0.85,
        "Average Stars / Repository": 1.00,
    
        "Original Repositories": 0.90,
    
        "Total Contributions": 0.80,
        "Total Commits": 0.85,
        "Active Contribution Days": 0.75,
        "Longest Contribution Streak": 0.65,
        "Average Contributions / Active Day": 0.70
    }

    category_weights = {
        "visibility": 0.75,
        "project_impact": 1.00,
        "repository_portfolio": 0.90,
        "development_activity": 1.00
    }


# ------------------------------------------------------------
# Calculate weighted scores for every metric
# ------------------------------------------------------------

    category_scores = {}

    overall_weighted_score1 = 0
    overall_weighted_score2 = 0
    overall_weight = 0

    for category_key, category in comparison_categories.items():

        category_score1 = 0
        category_score2 = 0
        category_weight_total = 0
    
        metric_results = []
    
        for metric in category["metrics"]:
    
            name = metric["name"]
            value1 = metric["value1"]
            value2 = metric["value2"]
    
            weight = metric_weights.get(name, 1.0)
    
            score1 = normalized_metric_score(
                value1,
                value2,
                higher_is_better=True
            )
    
            score2 = normalized_metric_score(
                value2,
                value1,
                higher_is_better=True
            )
    
            # Ignore metrics that cannot be numerically compared
            if score1 is None or score2 is None:
                continue
    
            category_score1 += score1 * weight
            category_score2 += score2 * weight
            category_weight_total += weight
    
            metric_results.append({
                "name": name,
                "value1": value1,
                "value2": value2,
                "score1": round(score1, 2),
                "score2": round(score2, 2),
                "weight": weight
            })
    
    # --------------------------------------------------------
    # Normalize category score to 0–100
        # --------------------------------------------------------
    
        if category_weight_total > 0:
    
            category_score1 = (
                category_score1 / category_weight_total
            )
    
            category_score2 = (
                category_score2 / category_weight_total
            )
    
            category_weight = category_weights.get(
                category_key,
                1.0
            )
    
            overall_weighted_score1 += (
                category_score1 * category_weight
            )
    
            overall_weighted_score2 += (
                category_score2 * category_weight
            )
    
            overall_weight += category_weight
    
            if category_score1 > category_score2:
                category_winner = user1["login"]
    
            elif category_score2 > category_score1:
                category_winner = user2["login"]
    
            else:
                category_winner = "Tie"
    
        else:
            category_score1 = None
            category_score2 = None
            category_winner = "Insufficient Data"
    
        category_scores[category_key] = {
            "label": category["label"],
            "score1": (
                round(category_score1, 2)
                if category_score1 is not None
                else None
            ),
            "score2": (
                round(category_score2, 2)
                if category_score2 is not None
                else None
            ),
            "winner": category_winner,
            "metrics": metric_results
        }


# ------------------------------------------------------------
# Final overall scores
# ------------------------------------------------------------

    if overall_weight > 0:

        overall_score1 = round(
            overall_weighted_score1 / overall_weight,
            2
        )

        overall_score2 = round(
            overall_weighted_score2 / overall_weight,
            2
        )

    else:

        overall_score1 = 0
        overall_score2 = 0
    

# ------------------------------------------------------------
# Determine overall result
# ------------------------------------------------------------

    score_difference = abs(
        overall_score1 - overall_score2
    )

    if score_difference < 0.01:

        overall_winner = "Tie"

    elif overall_score1 > overall_score2:

        overall_winner = user1["login"]

    else:

        overall_winner = user2["login"]


    overall_tie_count = sum(
        1
        for category in category_scores.values()
        if category["winner"] == "Tie"
    )

    return render_template(
        "compare.html",
        user1=user1,
        user2=user2,
        comparison_metrics=comparison_metrics,
        comparison_categories=comparison_categories,
        category_scores=category_scores,
        overall_score1=overall_score1,
        overall_score2=overall_score2,
        overall_tie_count=overall_tie_count,
        overall_winner=overall_winner
    )

if __name__ == "__main__":
    app.run(debug=True)