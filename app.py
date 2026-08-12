from flask import Flask, render_template, request
import requests
from dotenv import load_dotenv
from datetime import datetime
import os
import re
from collections import defaultdict

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

if not GITHUB_TOKEN:
    raise RuntimeError(
        "GITHUB_TOKEN is missing. Please add it to your .env file."
    )

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
  
    graphql_query = """
    query($username: String!) {
        user(login: $username) {
            contributionsCollection {
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

    if active_days > 0:
        average_contributions = round(total_contributions / active_days, 2)
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


    midpoint = len(contribution_days) // 2

    earlier_days = contribution_days[:midpoint]
    recent_days = contribution_days[midpoint:]

    earlier_contributions = sum(
        day["contributionCount"]
        for day in earlier_days
    )

    recent_contributions = sum(
        day["contributionCount"]
        for day in recent_days
    )

    if recent_contributions > earlier_contributions:
        contribution_trend = "Increasing"
    elif recent_contributions < earlier_contributions:
        contribution_trend = "Decreasing"
    else:
        contribution_trend = "Stable"
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

    total_language_repos = sum(language_counts.values())

    language_percentages = {}

    for language, count in language_counts.items():
        percentage = round((count / total_language_repos) * 100, 1)
        language_percentages[language] = percentage
    
    return render_template(
        "index.html",
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
        completed_profile_fields=completed_profile_fields,
        total_profile_fields=total_profile_fields,
        profile_completeness=profile_completeness,
        missing_profile_fields=missing_profile_fields,
        monthly_contributions=monthly_contributions,
        contributions_available=contributions_available,
        recent_repos=recent_repos
    )

if __name__ == "__main__":
    app.run(debug=True)