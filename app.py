from flask import Flask, render_template, request
import requests
from dotenv import load_dotenv
from datetime import datetime, timedelta
import os
import re
from collections import defaultdict
import math


# ============================================================
# CONFIGURATION
# ============================================================

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


# ============================================================
# GITHUB API HELPERS
# ============================================================

def rate_limit_message(response):
    return (
        response.status_code == 403
        and response.headers.get("X-RateLimit-Remaining") == "0"
    )


def get_user(username):
    try:
        response = requests.get(
            f"https://api.github.com/users/{username}",
            headers=GITHUB_HEADERS,
            timeout=10
        )

    except requests.exceptions.Timeout:
        return None, "GitHub took too long to respond. Please try again."

    except requests.exceptions.RequestException:
        return (
            None,
            "Unable to connect to GitHub. Please check your internet connection and try again."
        )

    if response.status_code == 404:
        return None, f"GitHub user '{username}' not found."

    if rate_limit_message(response):
        return None, "GitHub API rate limit reached. Please try again later."

    if response.status_code != 200:
        return None, "Something went wrong while contacting GitHub."

    return response.json(), None


def get_repositories(username):
    repositories = []
    page = 1

    while True:
        try:
            response = requests.get(
                f"https://api.github.com/users/{username}/repos",
                params={
                    "per_page": 100,
                    "page": page
                },
                headers=GITHUB_HEADERS,
                timeout=10
            )

        except requests.exceptions.Timeout:
            return None, (
                "GitHub took too long to respond while fetching repositories."
            )

        except requests.exceptions.RequestException:
            return None, (
                "Unable to fetch repositories from GitHub. Please try again."
            )

        if rate_limit_message(response):
            return None, "GitHub API rate limit reached. Please try again later."

        if response.status_code != 200:
            return None, "Unable to fetch repositories from GitHub."

        page_repositories = response.json()

        if not page_repositories:
            break

        repositories.extend(page_repositories)

        if len(page_repositories) < 100:
            break

        page += 1

    return repositories, None


# ============================================================
# PROFILE COMPLETENESS
# ============================================================

PROFILE_FIELDS = [
    ("Name", "name"),
    ("Bio", "bio"),
    ("Location", "location"),
    ("Company", "company"),
    ("Website", "blog"),
    ("Twitter/X", "twitter_username"),
    ("Profile Picture", "avatar_url"),
    ("Public Email", "email")
]


def calculate_profile_completeness(user):
    completed_fields = 0
    missing_fields = []

    for field_name, field_key in PROFILE_FIELDS:
        value = user.get(field_key)

        if value:
            completed_fields += 1
        else:
            missing_fields.append(field_name)

    total_fields = len(PROFILE_FIELDS)

    if total_fields > 0:
        completeness = round(
            (completed_fields / total_fields) * 100
        )
    else:
        completeness = 0

    return {
        "completed_fields": completed_fields,
        "total_fields": total_fields,
        "percentage": completeness,
        "missing_fields": missing_fields
    }


# ============================================================
# REPOSITORY METRICS
# ============================================================

def repository_metrics(repositories):
    total_stars = sum(
        repo.get("stargazers_count", 0)
        for repo in repositories
    )

    total_forks = sum(
        repo.get("forks_count", 0)
        for repo in repositories
    )

    average_stars = 0

    if repositories:
        average_stars = round(
            total_stars / len(repositories),
            2
        )

    original_repos = sum(
        1
        for repo in repositories
        if not repo.get("fork", False)
    )

    forked_repos = sum(
        1
        for repo in repositories
        if repo.get("fork", False)
    )

    archived_repos = sum(
        1
        for repo in repositories
        if repo.get("archived", False)
    )

    language_counts = {}

    for repo in repositories:
        language = repo.get("language")

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

    most_starred_repo = None

    if repositories:
        most_starred_repo = max(
            repositories,
            key=lambda repo: repo.get("stargazers_count", 0)
        )

    most_forked_repo = None

    if repositories:
        most_forked_repo = max(
            repositories,
            key=lambda repo: repo.get("forks_count", 0)
        )

    repo_size_distribution = {
        "Small": 0,
        "Medium": 0,
        "Large": 0
    }

    for repo in repositories:
        size = repo.get("size", 0)

        if size < 1000:
            repo_size_distribution["Small"] += 1

        elif size < 10000:
            repo_size_distribution["Medium"] += 1

        else:
            repo_size_distribution["Large"] += 1

    total_language_repos = sum(
        language_counts.values()
    )

    language_percentages = {}

    if total_language_repos > 0:
        for language, count in language_counts.items():
            percentage = round(
                (count / total_language_repos) * 100,
                1
            )

            language_percentages[language] = percentage

    return {
        "total_stars": total_stars,
        "total_forks": total_forks,
        "average_stars": average_stars,
        "original_repos": original_repos,
        "forked_repos": forked_repos,
        "archived_repos": archived_repos,
        "most_used_language": most_used_language,
        "language_counts": language_counts,
        "language_count": len(language_counts),
        "language_percentages": language_percentages,
        "most_starred_repo": most_starred_repo,
        "most_forked_repo": most_forked_repo,
        "repo_size_distribution": repo_size_distribution
    }


# ============================================================
# CONTRIBUTION METRICS
# ============================================================

def contribution_metrics(username, user_created_at=None):
    """
    Fetch lifetime contribution metrics by querying GitHub
    year-by-year, while keeping the graph data limited to
    the most recent 12 months.

    Lifetime metrics:
        - Total contributions
        - Total commits
        - Active contribution days
        - Longest streak
        - Average contributions / active day
        - Most active month

    Graph metrics:
        - Last 12 months of contribution days
        - Last 12 months of monthly contributions
        - Last 12 months contribution trend
    """

    graphql_query = """
    query(
        $username: String!,
        $from: DateTime!,
        $to: DateTime!
    ) {
        user(login: $username) {

            contributionsCollection(
                from: $from,
                to: $to
            ) {

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

    # --------------------------------------------------------
    # Determine account start date
    # --------------------------------------------------------

    if user_created_at:

        try:
            account_created = datetime.strptime(
                user_created_at,
                "%Y-%m-%dT%H:%M:%SZ"
            )

        except ValueError:

            try:
                account_created = datetime.fromisoformat(
                    user_created_at.replace("Z", "+00:00")
                ).replace(tzinfo=None)

            except ValueError:
                account_created = datetime.utcnow() - timedelta(days=365)

    else:

        # Fallback.
        # The caller should normally provide created_at.
        account_created = datetime.utcnow() - timedelta(days=365)

    now = datetime.utcnow()

    # --------------------------------------------------------
    # Store lifetime contribution data
    # --------------------------------------------------------

    lifetime_contribution_days = []

    lifetime_total_contributions = 0
    lifetime_total_commits = 0

    # --------------------------------------------------------
    # Query GitHub year-by-year
    # --------------------------------------------------------
    #
    # GitHub's contribution collection is queried in chunks
    # rather than relying on its default recent-year window.
    #
    # Each request covers at most one year.
    # --------------------------------------------------------

    current_start = account_created

    while current_start < now:

        current_end = min(
            current_start + timedelta(days=365),
            now
        )

        # GitHub DateTime values are UTC ISO timestamps.
        from_value = (
            current_start.strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        )

        to_value = (
            current_end.strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        )

        try:

            response = requests.post(

                "https://api.github.com/graphql",

                json={
                    "query": graphql_query,

                    "variables": {
                        "username": username,
                        "from": from_value,
                        "to": to_value
                    }
                },

                headers=GITHUB_HEADERS,

                timeout=15
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

        if data.get("errors"):
            return None

        if (
            "data" not in data
            or not data["data"].get("user")
        ):
            return None

        contributions_collection = (
            data["data"]["user"]
            .get(
                "contributionsCollection",
                {}
            )
        )

        # ----------------------------------------------------
        # Lifetime totals
        # ----------------------------------------------------

        lifetime_total_contributions += (
            contributions_collection.get(
                "contributionCalendar",
                {}
            ).get(
                "totalContributions",
                0
            )
        )

        lifetime_total_commits += (
            contributions_collection.get(
                "totalCommitContributions",
                0
            )
        )

        # ----------------------------------------------------
        # Lifetime daily data
        # ----------------------------------------------------

        calendar = contributions_collection.get(
            "contributionCalendar",
            {}
        )

        for week in calendar.get("weeks", []):

            for day in week.get(
                "contributionDays",
                []
            ):

                lifetime_contribution_days.append(
                    day
                )

        # Move to next period.
        current_start = current_end

        # Prevent an accidental infinite loop.
        if current_start >= now:
            break

    # --------------------------------------------------------
    # Remove duplicate dates
    # --------------------------------------------------------
    #
    # This protects against boundary overlap between yearly
    # queries.
    # --------------------------------------------------------

    unique_days = {}

    for day in lifetime_contribution_days:

        unique_days[
            day["date"]
        ] = day

    lifetime_contribution_days = [
        unique_days[date]
        for date in sorted(unique_days)
    ]

    # ========================================================
    # LIFETIME METRICS
    # ========================================================

    lifetime_active_days = sum(
        1
        for day in lifetime_contribution_days
        if day["contributionCount"] > 0
    )

    # --------------------------------------------------------
    # Lifetime longest streak
    # --------------------------------------------------------

    lifetime_longest_streak = 0
    current_streak = 0

    for day in lifetime_contribution_days:

        if day["contributionCount"] > 0:

            current_streak += 1

            lifetime_longest_streak = max(
                lifetime_longest_streak,
                current_streak
            )

        else:

            current_streak = 0

    # --------------------------------------------------------
    # Lifetime average
    # --------------------------------------------------------

    if lifetime_active_days > 0:

        lifetime_average_contributions = round(
            lifetime_total_contributions
            / lifetime_active_days,
            2
        )

    else:

        lifetime_average_contributions = 0

    # --------------------------------------------------------
    # Lifetime monthly contributions
    # --------------------------------------------------------

    lifetime_monthly_contributions = defaultdict(int)

    for day in lifetime_contribution_days:

        month = day["date"][:7]

        lifetime_monthly_contributions[
            month
        ] += day["contributionCount"]

    # --------------------------------------------------------
    # Lifetime most active month
    # --------------------------------------------------------

    if lifetime_monthly_contributions:

        lifetime_most_active_month = max(
            lifetime_monthly_contributions,
            key=lifetime_monthly_contributions.get
        )

        lifetime_most_active_month_count = (
            lifetime_monthly_contributions[
                lifetime_most_active_month
            ]
        )

    else:

        lifetime_most_active_month = None
        lifetime_most_active_month_count = 0

    # ========================================================
    # LAST 12 MONTHS — GRAPH DATA ONLY
    # ========================================================

    graph_start_date = (
        now - timedelta(days=365)
    ).date()

    graph_contribution_days = [

        day

        for day in lifetime_contribution_days

        if datetime.strptime(
            day["date"],
            "%Y-%m-%d"
        ).date() >= graph_start_date
    ]

    # --------------------------------------------------------
    # Last 12 months monthly contributions
    # --------------------------------------------------------

    graph_monthly_contributions = defaultdict(int)

    for day in graph_contribution_days:

        month = day["date"][:7]

        graph_monthly_contributions[
            month
        ] += day["contributionCount"]

    # --------------------------------------------------------
    # Fill missing months
    # --------------------------------------------------------

    graph_start_month = (
        datetime(
            graph_start_date.year,
            graph_start_date.month,
            1
        )
    )

    graph_end_month = datetime(
        now.year,
        now.month,
        1
    )

    current_month = graph_start_month

    while current_month <= graph_end_month:

        month_key = current_month.strftime(
            "%Y-%m"
        )

        if month_key not in graph_monthly_contributions:

            graph_monthly_contributions[
                month_key
            ] = 0

        if current_month.month == 12:

            current_month = current_month.replace(
                year=current_month.year + 1,
                month=1
            )

        else:

            current_month = current_month.replace(
                month=current_month.month + 1
            )

    # --------------------------------------------------------
    # Last 12 months contribution trend
    # --------------------------------------------------------

    sorted_graph_months = sorted(
        graph_monthly_contributions.keys()
    )

    if len(sorted_graph_months) >= 6:

        recent_months = sorted_graph_months[-3:]

        previous_months = sorted_graph_months[-6:-3]

        recent_total = sum(
            graph_monthly_contributions[month]
            for month in recent_months
        )

        previous_total = sum(
            graph_monthly_contributions[month]
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

    # ========================================================
    # RETURN
    # ========================================================

    return {

        # ----------------------------------------------------
        # LIFETIME
        # ----------------------------------------------------

        "total_contributions":
            lifetime_total_contributions,

        "total_commits":
            lifetime_total_commits,

        "active_days":
            lifetime_active_days,

        "longest_streak":
            lifetime_longest_streak,

        "average_contributions":
            lifetime_average_contributions,

        "most_active_month":
            lifetime_most_active_month,

        "most_active_month_count":
            lifetime_most_active_month_count,

        "most_active_day":
            max(
                lifetime_contribution_days,
                key=lambda day: day["contributionCount"]
            )
            if lifetime_contribution_days
            else None,        

        "lifetime_monthly_contributions":
            lifetime_monthly_contributions,

        "lifetime_total_days":
            len(lifetime_contribution_days),

        # ----------------------------------------------------
        # LAST 12 MONTHS — GRAPH DATA
        # ----------------------------------------------------

        "contribution_days":
            graph_contribution_days,

        "monthly_contributions":
            graph_monthly_contributions,

        "contribution_trend":
            contribution_trend
    }

# ============================================================
# PROFILE SCORING SYSTEM
# ============================================================

# The weights always add up to 100.
#
# Higher weights are assigned to actual development activity.
#
# Core:
#   Original repositories  -> 15
#   Contributions           -> 20
#   Commits                 -> 20
#
# Secondary:
#   Active contribution days -> 10
#   Contribution streak      -> 5
#   Languages                -> 8
#   Profile completeness     -> 7
#
# Lower importance:
#   Stars                    -> 5
#   Followers                -> 5
#   Forks                    -> 5
#
# TOTAL = 100

PROFILE_SCORE_WEIGHTS = {
    "original_repositories": 15,
    "total_contributions": 20,
    "total_commits": 20,
    "active_days": 10,
    "longest_streak": 5,
    "languages": 8,
    "profile_completeness": 7,
    "stars": 5,
    "followers": 5,
    "forks": 5
}


# ------------------------------------------------------------
# Scoring targets
# ------------------------------------------------------------
#
# These are common fixed benchmarks.
#
# They are NOT calculated from the other profile.
# Therefore every profile is scored independently.
#
# Logarithmic scaling provides diminishing returns.
#
# Example:
#   Going from 0 -> 10 commits matters more than
#   going from 1000 -> 1010 commits.
#
# Once a profile reaches the target, that metric receives
# its maximum available points.
# ------------------------------------------------------------

PROFILE_SCORE_TARGETS = {
    "original_repositories": 20,
    "total_contributions": 1000,
    "total_commits": 500,
    "active_days": 150,
    "longest_streak": 30,
    "languages": 5,
    "stars": 100,
    "followers": 100,
    "forks": 20
}


def logarithmic_metric_score(value, target, weight):
    """
    Converts a metric into weighted points using logarithmic
    diminishing returns.

    The result is always between 0 and the supplied weight.

    Importantly, this function uses ONLY:
        - the profile's own value
        - a fixed project benchmark
        - the metric weight

    It never uses another user's value.
    """

    if value is None:
        return 0

    try:
        value = float(value)
        target = float(target)
        weight = float(weight)

    except (TypeError, ValueError):
        return 0

    if value <= 0:
        return 0

    if target <= 0 or weight <= 0:
        return 0

    normalized = (
        math.log1p(value)
        / math.log1p(target)
    )

    normalized = min(
        max(normalized, 0),
        1
    )

    return round(
        normalized * weight,
        2
    )


def percentage_metric_score(
    percentage,
    weight
):
    """
    Converts a 0-100 percentage directly into weighted points.
    """

    if percentage is None:
        return 0

    try:
        percentage = float(percentage)
        weight = float(weight)

    except (TypeError, ValueError):
        return 0

    percentage = min(
        max(percentage, 0),
        100
    )

    return round(
        (percentage / 100) * weight,
        2
    )


def calculate_profile_score(
    original_repositories,
    total_contributions,
    total_commits,
    active_days,
    longest_streak,
    language_count,
    profile_completeness,
    total_stars,
    followers,
    total_forks
):
    """
    Calculates ONE independent Profile Score out of 100.

    This function NEVER compares two users.

    Therefore:

        User A -> 72.35

    remains:

        User A -> 72.35

    regardless of which other profile is being compared.
    """

    scores = {}

    # --------------------------------------------------------
    # 1. Original repositories - 15 points
    # --------------------------------------------------------

    scores["repositories"] = logarithmic_metric_score(
        original_repositories,
        PROFILE_SCORE_TARGETS["original_repositories"],
        PROFILE_SCORE_WEIGHTS["original_repositories"]
    )

    # --------------------------------------------------------
    # 2. Total contributions - 20 points
    # --------------------------------------------------------

    scores["contributions"] = logarithmic_metric_score(
        total_contributions,
        PROFILE_SCORE_TARGETS["total_contributions"],
        PROFILE_SCORE_WEIGHTS["total_contributions"]
    )

    # --------------------------------------------------------
    # 3. Total commits - 20 points
    # --------------------------------------------------------

    scores["commits"] = logarithmic_metric_score(
        total_commits,
        PROFILE_SCORE_TARGETS["total_commits"],
        PROFILE_SCORE_WEIGHTS["total_commits"]
    )

    # --------------------------------------------------------
    # 4. Active contribution days - 10 points
    # --------------------------------------------------------

    scores["active_days"] = logarithmic_metric_score(
        active_days,
        PROFILE_SCORE_TARGETS["active_days"],
        PROFILE_SCORE_WEIGHTS["active_days"]
    )

    # --------------------------------------------------------
    # 5. Longest contribution streak - 5 points
    # --------------------------------------------------------

    scores["longest_streak"] = logarithmic_metric_score(
        longest_streak,
        PROFILE_SCORE_TARGETS["longest_streak"],
        PROFILE_SCORE_WEIGHTS["longest_streak"]
    )

    # --------------------------------------------------------
    # 6. Languages - 8 points
    # --------------------------------------------------------

    scores["languages"] = logarithmic_metric_score(
        language_count,
        PROFILE_SCORE_TARGETS["languages"],
        PROFILE_SCORE_WEIGHTS["languages"]
    )

    # --------------------------------------------------------
    # 7. Profile completeness - 7 points
    # --------------------------------------------------------

    scores["profile_completeness"] = (
        percentage_metric_score(
            profile_completeness,
            PROFILE_SCORE_WEIGHTS["profile_completeness"]
        )
    )

    # --------------------------------------------------------
    # 8. Stars - 5 points
    # --------------------------------------------------------

    scores["stars"] = logarithmic_metric_score(
        total_stars,
        PROFILE_SCORE_TARGETS["stars"],
        PROFILE_SCORE_WEIGHTS["stars"]
    )

    # --------------------------------------------------------
    # 9. Followers - 5 points
    # --------------------------------------------------------

    scores["followers"] = logarithmic_metric_score(
        followers,
        PROFILE_SCORE_TARGETS["followers"],
        PROFILE_SCORE_WEIGHTS["followers"]
    )

    # --------------------------------------------------------
    # 10. Forks - 3 points
    # --------------------------------------------------------

    scores["forks"] = logarithmic_metric_score(
        total_forks,
        PROFILE_SCORE_TARGETS["forks"],
        PROFILE_SCORE_WEIGHTS["forks"]
    )


    # --------------------------------------------------------
    # Final score
    # --------------------------------------------------------

    total_score = round(
        sum(scores.values()),
        2
    )

    # Floating point protection.
    total_score = min(
        max(total_score, 0),
        100
    )

    scores["total"] = total_score

    return scores


# ============================================================
# ANALYZE ROUTE
# ============================================================

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/analyze")
def analyze():

    username = request.args.get(
        "username",
        ""
    ).strip()

    if not username:
        return "Please enter a GitHub username."

    if not re.fullmatch(
        r"[A-Za-z0-9-]+",
        username
    ):
        return (
            "Invalid GitHub username. "
            "Please use only letters, numbers, and hyphens."
        )

    # --------------------------------------------------------
    # Fetch user
    # --------------------------------------------------------

    user_data, error = get_user(username)

    if error:
        return error

    # --------------------------------------------------------
    # Profile completeness
    # --------------------------------------------------------

    completeness_data = calculate_profile_completeness(
        user_data
    )

    completed_profile_fields = (
        completeness_data["completed_fields"]
    )

    total_profile_fields = (
        completeness_data["total_fields"]
    )

    profile_completeness = (
        completeness_data["percentage"]
    )

    missing_profile_fields = (
        completeness_data["missing_fields"]
    )

    profile_field_names = []

    for field_name, field_key in PROFILE_FIELDS:
        profile_field_names.append(
            (
                field_name,
                user_data.get(field_key)
            )
        )

    # --------------------------------------------------------
    # Fetch repositories
    # --------------------------------------------------------

    repos, error = get_repositories(username)

    if error:
        return error

    # --------------------------------------------------------
    # Recent repositories
    # --------------------------------------------------------

    recent_repos = sorted(
        repos,
        key=lambda repo: repo.get(
            "updated_at",
            ""
        ),
        reverse=True
    )[:3]

    # --------------------------------------------------------
    # Active repositories
    #
    # Counts commits made during the last 30 days for the
    # three most recently updated repositories.
    # --------------------------------------------------------

    # --------------------------------------------------------
    # Recent repository commit activity
    #
    # Fetches commits from the last 30 days for the
    # three most recently updated repositories and groups
    # them by day.
    # --------------------------------------------------------

    active_repositories = []

    activity_start = datetime.utcnow() - timedelta(days=30)

    for repo in recent_repos:

        daily_commits = defaultdict(int)

        page = 1

        while True:

            try:

                commits_response = requests.get(
                    f"https://api.github.com/repos/"
                    f"{username}/{repo['name']}/commits",
    
                    params={
                        "since": (
                            activity_start.isoformat()
                            + "Z"
                        ),
                        "until": (
                            datetime.utcnow().isoformat()
                            + "Z"
                        ),
                        "per_page": 100,
                        "page": page
                    },
    
                    headers=GITHUB_HEADERS,
                    timeout=10
                )
    
            except requests.exceptions.Timeout:
                daily_commits = None
                break
        
            except requests.exceptions.RequestException:
                daily_commits = None
                break
    
            if rate_limit_message(commits_response):
                daily_commits = None
                break
    
            if commits_response.status_code != 200:
                daily_commits = None
                break
    
            commits = commits_response.json()
    
            if not commits:
                break
    
            # --------------------------------------------
            # Group commits by calendar date
            # --------------------------------------------
    
            for commit in commits:

                commit_data = commit.get(
                    "commit",
                    {}
                )
    
                author_data = commit_data.get(
                    "author",
                    {}
                )
    
                commit_date = author_data.get(
                    "date"
                )
    
                if commit_date:
    
                    date_key = commit_date[:10]
    
                    daily_commits[date_key] += 1
    
            if len(commits) < 100:
                break
    
            page += 1
    
        # --------------------------------------------
        # Build complete 30-day timeline
        # --------------------------------------------
    
        if daily_commits is not None:
    
            complete_daily_commits = {}
        
            current_date = activity_start.date()
            end_date = datetime.utcnow().date()
        
            while current_date <= end_date:
        
                date_key = current_date.isoformat()
    
                complete_daily_commits[date_key] = (
                    daily_commits.get(
                        date_key,
                        0
                    )
                )
    
                current_date += timedelta(days=1)
    
            total_commit_count = sum(
                complete_daily_commits.values()
            )
    
            active_repositories.append({
    
                "name": repo["name"],
    
                "html_url": repo["html_url"],
    
                "commit_count": total_commit_count,
    
                "daily_commits": (
                    complete_daily_commits
                )
            })

    # --------------------------------------------------------
    # Contribution data
    # --------------------------------------------------------

    contribution_data = contribution_metrics(
        username,
        user_data.get("created_at")
    )

    contributions_available = (
        contribution_data is not None
    )

    if contributions_available:

        total_contributions = (
            contribution_data["total_contributions"]
        )

        total_commits = (
            contribution_data["total_commits"]
        )

        active_days = (
            contribution_data["active_days"]
        )

        longest_streak = (
            contribution_data["longest_streak"]
        )

        average_contributions = (
            contribution_data["average_contributions"]
        )

        most_active_month = (
            contribution_data["most_active_month"]
        )

        most_active_month_count = (
            contribution_data["most_active_month_count"]
        )

        contribution_trend = (
            contribution_data["contribution_trend"]
        )

        contribution_days = (
            contribution_data["contribution_days"]
        )

    else:

        total_contributions = None
        total_commits = None
        active_days = 0
        longest_streak = 0
        average_contributions = 0
        most_active_month = None
        most_active_month_count = 0
        contribution_trend = None
        contribution_days = []

    # --------------------------------------------------------
    # Contribution frequency
    # --------------------------------------------------------

    if contribution_data:

        total_days = contribution_data[
            "lifetime_total_days"
        ]

    else:

        total_days = 0

    if total_days > 0:

        contribution_frequency = round(
            (
                active_days
                / total_days
            ) * 100,
            2
        )

    else:
        contribution_frequency = 0

    # --------------------------------------------------------
    # Most active day
    # --------------------------------------------------------

    if contribution_data:

        most_active_day = contribution_data[
           "most_active_day"
        ]

    else:

        most_active_day = None

    # --------------------------------------------------------
    # Monthly contributions — LAST 12 MONTHS ONLY
    # --------------------------------------------------------

    if contribution_data:

        monthly_contributions = (
            contribution_data[
                "monthly_contributions"
            ]
        )

    else:

        monthly_contributions = defaultdict(int)

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

            month_key = current_month.strftime(
                "%Y-%m"
            )

            if month_key not in monthly_contributions:
                monthly_contributions[
                    month_key
                ] = 0

            if current_month.month == 12:

                current_month = current_month.replace(
                    year=current_month.year + 1,
                    month=1
                )

            else:

                current_month = current_month.replace(
                    month=current_month.month + 1
                )

    # --------------------------------------------------------
    # Most active month display
    # --------------------------------------------------------

    if monthly_contributions:

        most_active_month = max(
            monthly_contributions,
            key=monthly_contributions.get
        )

        most_active_month_count = (
            monthly_contributions[
                most_active_month
            ]
        )

        most_active_month_display = (
            datetime.strptime(
                most_active_month,
                "%Y-%m"
            ).strftime("%B %Y")
        )

    else:

        most_active_month = None
        most_active_month_count = 0
        most_active_month_display = "—"

    # --------------------------------------------------------
    # Contribution heatmap
    # --------------------------------------------------------

    contribution_heatmap = []

    if contribution_data:

        # Reconstruct weeks from contribution days.
        current_week = []

        for day in contribution_days:

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

            current_week.append({
                "date": day["date"],
                "count": count,
                "level": level
            })

            # GitHub contribution calendars normally contain
            # seven days per week.
            if len(current_week) == 7:
                contribution_heatmap.append(
                    current_week
                )
                current_week = []

        if current_week:
            contribution_heatmap.append(
                current_week
            )

    # --------------------------------------------------------
    # Repository metrics
    # --------------------------------------------------------

    repo_data = repository_metrics(
        repos
    )

    total_stars = repo_data["total_stars"]
    total_forks = repo_data["total_forks"]
    average_stars = repo_data["average_stars"]

    original_repos = repo_data["original_repos"]
    forked_repos = repo_data["forked_repos"]
    archived_repos = repo_data["archived_repos"]

    language_counts = repo_data[
        "language_counts"
    ]

    language_count = repo_data[
        "language_count"
    ]

    most_used_language = repo_data[
        "most_used_language"
    ]

    language_percentages = repo_data[
        "language_percentages"
    ]

    most_starred_repo = repo_data[
        "most_starred_repo"
    ]

    most_forked_repo = repo_data[
        "most_forked_repo"
    ]

    repo_size_distribution = repo_data[
        "repo_size_distribution"
    ]

    # --------------------------------------------------------
    # PROFILE SCORE
    # --------------------------------------------------------
    #
    # This score is completely independent.
    # It does NOT use another profile.
    # --------------------------------------------------------

    profile_score = calculate_profile_score(

        original_repositories=original_repos,

        total_contributions=(
            total_contributions or 0
        ),

        total_commits=(
            total_commits or 0
        ),

        active_days=active_days,

        longest_streak=longest_streak,

        language_count=language_count,

        profile_completeness=(
            profile_completeness
        ),

        total_stars=total_stars,

        followers=user_data.get(
            "followers",
            0
        ),

        total_forks=total_forks,

    )

    return render_template(

        "profile.html",

        user=user_data,

        repos=repos,

        # ----------------------------------------------------
        # Repository data
        # ----------------------------------------------------

        total_stars=total_stars,

        total_forks=total_forks,

        most_used_language=(
            most_used_language
        ),

        language_percentages=(
            language_percentages
        ),

        most_starred_repo=(
            most_starred_repo
        ),

        most_forked_repo=(
            most_forked_repo
        ),

        average_stars=average_stars,

        original_repos=(
            original_repos
        ),

        forked_repos=(
            forked_repos
        ),

        archived_repos=(
            archived_repos
        ),

        repo_size_distribution=(
            repo_size_distribution
        ),

        # ----------------------------------------------------
        # Contribution data
        # ----------------------------------------------------

        total_contributions=(
            total_contributions
        ),

        total_commits=(
            total_commits
        ),

        contribution_days=(
            contribution_days
        ),

        active_days=(
            active_days
        ),

        longest_streak=(
            longest_streak
        ),

        contribution_heatmap=(
            contribution_heatmap
        ),

        average_contributions=(
            average_contributions
        ),

        most_active_day=(
            most_active_day
        ),

        most_active_month=(
            most_active_month
        ),

        most_active_month_count=(
            most_active_month_count
        ),

        most_active_month_display=(
            most_active_month_display
        ),

        contribution_frequency=(
            contribution_frequency
        ),

        contribution_trend=(
            contribution_trend
        ),

        contributions_available=(
            contributions_available
        ),

        monthly_contributions=(
            monthly_contributions
        ),

        # ----------------------------------------------------
        # Profile completeness
        # ----------------------------------------------------

        profile_field_names=(
            profile_field_names
        ),

        completed_profile_fields=(
            completed_profile_fields
        ),

        total_profile_fields=(
            total_profile_fields
        ),

        profile_completeness=(
            profile_completeness
        ),

        missing_profile_fields=(
            missing_profile_fields
        ),

        # ----------------------------------------------------
        # Recent / active repositories
        # ----------------------------------------------------

        recent_repos=(
            recent_repos
        ),

        active_repositories=(
            active_repositories
        ),

        # ----------------------------------------------------
        # PROFILE SCORE
        # ----------------------------------------------------

        profile_score=(
            profile_score
        )
    )


# ============================================================
# COMPARE ROUTE
# ============================================================

@app.route("/compare")
def compare():

    username1 = request.args.get(
        "username1",
        ""
    ).strip()

    username2 = request.args.get(
        "username2",
        ""
    ).strip()

    if not username1 or not username2:
        return render_template(
            "compare.html"
        )

    # --------------------------------------------------------
    # Validate usernames
    # --------------------------------------------------------

    if not re.fullmatch(
        r"[A-Za-z0-9-]+",
        username1
    ):
        return "Invalid first GitHub username."

    if not re.fullmatch(
        r"[A-Za-z0-9-]+",
        username2
    ):
        return "Invalid second GitHub username."

    if username1.lower() == username2.lower():
        return (
            "Please enter two different GitHub usernames."
        )

    # --------------------------------------------------------
    # Fetch both users
    # --------------------------------------------------------

    user1, error = get_user(
        username1
    )

    if error:
        return error

    user2, error = get_user(
        username2
    )

    if error:
        return error

    # --------------------------------------------------------
    # Fetch repositories
    # --------------------------------------------------------

    repos1, error = get_repositories(
        username1
    )

    if error:
        return error

    repos2, error = get_repositories(
        username2
    )

    if error:
        return error

    # --------------------------------------------------------
    # Repository metrics
    # --------------------------------------------------------

    repo_metrics1 = repository_metrics(
        repos1
    )

    repo_metrics2 = repository_metrics(
        repos2
    )

    # --------------------------------------------------------
    # Contribution metrics
    # --------------------------------------------------------

    contribution_metrics1 = contribution_metrics(
        username1,
        user1.get("created_at")
    )

    contribution_metrics2 = contribution_metrics(
        username2,
        user2.get("created_at")
    )

    # --------------------------------------------------------
    # Profile completeness
    # --------------------------------------------------------

    completeness1 = calculate_profile_completeness(
        user1
    )

    completeness2 = calculate_profile_completeness(
        user2
    )

    # ========================================================
    # INDEPENDENT PROFILE SCORES
    # ========================================================
    #
    # IMPORTANT:
    #
    # There is NO comparison between user1 and user2 here.
    #
    # Each score uses fixed project benchmarks.
    #
    # Therefore:
    #
    # User A = 72.50
    #
    # remains 72.50 regardless of the opponent.
    # ========================================================

    profile_score1 = calculate_profile_score(

        original_repositories=(
            repo_metrics1["original_repos"]
        ),

        total_contributions=(
            contribution_metrics1[
                "total_contributions"
            ]
            if contribution_metrics1
            else 0
        ),

        total_commits=(
            contribution_metrics1[
                "total_commits"
            ]
            if contribution_metrics1
            else 0
        ),

        active_days=(
            contribution_metrics1[
                "active_days"
            ]
            if contribution_metrics1
            else 0
        ),

        longest_streak=(
            contribution_metrics1[
                "longest_streak"
            ]
            if contribution_metrics1
            else 0
        ),

        language_count=(
            repo_metrics1["language_count"]
        ),

        profile_completeness=(
            completeness1["percentage"]
        ),

        total_stars=(
            repo_metrics1["total_stars"]
        ),

        followers=user1.get(
            "followers",
            0
        ),

        total_forks=(
            repo_metrics1["total_forks"]
        ),

    )

    profile_score2 = calculate_profile_score(

        original_repositories=(
            repo_metrics2["original_repos"]
        ),

        total_contributions=(
            contribution_metrics2[
                "total_contributions"
            ]
            if contribution_metrics2
            else 0
        ),

        total_commits=(
            contribution_metrics2[
                "total_commits"
            ]
            if contribution_metrics2
            else 0
        ),

        active_days=(
            contribution_metrics2[
                "active_days"
            ]
            if contribution_metrics2
            else 0
        ),

        longest_streak=(
            contribution_metrics2[
                "longest_streak"
            ]
            if contribution_metrics2
            else 0
        ),

        language_count=(
            repo_metrics2["language_count"]
        ),

        profile_completeness=(
            completeness2["percentage"]
        ),

        total_stars=(
            repo_metrics2["total_stars"]
        ),

        followers=user2.get(
            "followers",
            0
        ),

        total_forks=(
            repo_metrics2["total_forks"]
        ),

    )

    # --------------------------------------------------------
    # Basic comparison metrics
    # --------------------------------------------------------

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

    comparison_metrics.extend([

        {
            "name": "Total Stars",
            "value1": repo_metrics1[
                "total_stars"
            ],
            "value2": repo_metrics2[
                "total_stars"
            ]
        },

        {
            "name": "Total Forks",
            "value1": repo_metrics1[
                "total_forks"
            ],
            "value2": repo_metrics2[
                "total_forks"
            ]
        },

        {
            "name": "Average Stars / Repository",
            "value1": repo_metrics1[
                "average_stars"
            ],
            "value2": repo_metrics2[
                "average_stars"
            ]
        },

        {
            "name": "Original Repositories",
            "value1": repo_metrics1[
                "original_repos"
            ],
            "value2": repo_metrics2[
                "original_repos"
            ]
        },

        {
            "name": "Forked Repositories",
            "value1": repo_metrics1[
                "forked_repos"
            ],
            "value2": repo_metrics2[
                "forked_repos"
            ]
        },

        {
            "name": "Archived Repositories",
            "value1": repo_metrics1[
                "archived_repos"
            ],
            "value2": repo_metrics2[
                "archived_repos"
            ]
        },

        {
            "name": "Most Used Language",
            "value1": repo_metrics1[
                "most_used_language"
            ],
            "value2": repo_metrics2[
                "most_used_language"
            ]
        },

        {
            "name": "Languages",
            "value1": repo_metrics1[
                "language_count"
            ],
            "value2": repo_metrics2[
                "language_count"
            ]
        },

        {
            "name": "Profile Completeness",
            "value1": completeness1[
                "percentage"
            ],
            "value2": completeness2[
                "percentage"
            ]
        }
    ])

    # --------------------------------------------------------
    # Contribution comparison
    # --------------------------------------------------------

    if (
        contribution_metrics1
        and contribution_metrics2
    ):

        comparison_metrics.extend([

            {
                "name": "Total Contributions",
                "value1": contribution_metrics1[
                    "total_contributions"
                ],
                "value2": contribution_metrics2[
                    "total_contributions"
                ]
            },

            {
                "name": "Total Commits",
                "value1": contribution_metrics1[
                    "total_commits"
                ],
                "value2": contribution_metrics2[
                    "total_commits"
                ]
            },

            {
                "name": "Active Contribution Days",
                "value1": contribution_metrics1[
                    "active_days"
                ],
                "value2": contribution_metrics2[
                    "active_days"
                ]
            },

            {
                "name": "Longest Contribution Streak",
                "value1": contribution_metrics1[
                    "longest_streak"
                ],
                "value2": contribution_metrics2[
                    "longest_streak"
                ]
            },

            {
                "name": "Average Contributions / Active Day",
                "value1": contribution_metrics1[
                    "average_contributions"
                ],
                "value2": contribution_metrics2[
                    "average_contributions"
                ]
            },

            {
                "name": "Most Active Month",
                "value1": contribution_metrics1[
                    "most_active_month"
                ],
                "value2": contribution_metrics2[
                    "most_active_month"
                ]
            },

            {
                "name": "Contribution Trend",
                "value1": contribution_metrics1[
                    "contribution_trend"
                ],
                "value2": contribution_metrics2[
                    "contribution_trend"
                ]
            }
        ])

    # ========================================================
    # COMPARISON CATEGORIES
    # ========================================================

    comparison_categories = {

        "visibility": {

            "label": "Visibility",

            "metrics": [

                {
                    "name": "Followers",
                    "value1": user1["followers"],
                    "value2": user2["followers"]
                },

                {
                    "name": "Following",
                    "value1": user1["following"],
                    "value2": user2["following"]
                }
            ]
        },

        "project_impact": {

            "label": "Project Impact",

            "metrics": [

                {
                    "name": "Total Stars",
                    "value1": repo_metrics1[
                        "total_stars"
                    ],
                    "value2": repo_metrics2[
                        "total_stars"
                    ]
                },

                {
                    "name": "Total Forks",
                    "value1": repo_metrics1[
                        "total_forks"
                    ],
                    "value2": repo_metrics2[
                        "total_forks"
                    ]
                },

                {
                    "name": "Average Stars / Repository",
                    "value1": repo_metrics1[
                        "average_stars"
                    ],
                    "value2": repo_metrics2[
                        "average_stars"
                    ]
                }
            ]
        },

        "repository_portfolio": {

            "label": "Repository Portfolio",

            "metrics": [

                {
                    "name": "Public Repositories",
                    "value1": user1[
                        "public_repos"
                    ],
                    "value2": user2[
                        "public_repos"
                    ]
                },

                {
                    "name": "Original Repositories",
                    "value1": repo_metrics1[
                        "original_repos"
                    ],
                    "value2": repo_metrics2[
                        "original_repos"
                    ]
                },

                {
                    "name": "Forked Repositories",
                    "value1": repo_metrics1[
                        "forked_repos"
                    ],
                    "value2": repo_metrics2[
                        "forked_repos"
                    ]
                },

                {
                    "name": "Archived Repositories",
                    "value1": repo_metrics1[
                        "archived_repos"
                    ],
                    "value2": repo_metrics2[
                        "archived_repos"
                    ]
                }
            ]
        },

        "technical_profile": {

            "label": "Technical Profile",

            "metrics": [

                {
                    "name": "Languages",
                    "value1": repo_metrics1[
                        "language_count"
                    ],
                    "value2": repo_metrics2[
                        "language_count"
                    ]
                },

                {
                    "name": "Most Used Language",
                    "value1": repo_metrics1[
                        "most_used_language"
                    ],
                    "value2": repo_metrics2[
                        "most_used_language"
                    ]
                },

                {
                    "name": "Profile Completeness",
                    "value1": completeness1[
                        "percentage"
                    ],
                    "value2": completeness2[
                        "percentage"
                    ]
                }
            ]
        }
    }

    # --------------------------------------------------------
    # Development activity category
    # --------------------------------------------------------

    if (
        contribution_metrics1
        and contribution_metrics2
    ):

        comparison_categories[
            "development_activity"
        ] = {

            "label": "Development Activity",

            "metrics": [

                {
                    "name": "Total Contributions",
                    "value1": contribution_metrics1[
                        "total_contributions"
                    ],
                    "value2": contribution_metrics2[
                        "total_contributions"
                    ]
                },

                {
                    "name": "Total Commits",
                    "value1": contribution_metrics1[
                        "total_commits"
                    ],
                    "value2": contribution_metrics2[
                        "total_commits"
                    ]
                },

                {
                    "name": "Active Contribution Days",
                    "value1": contribution_metrics1[
                        "active_days"
                    ],
                    "value2": contribution_metrics2[
                        "active_days"
                    ]
                },

                {
                    "name": "Longest Contribution Streak",
                    "value1": contribution_metrics1[
                        "longest_streak"
                    ],
                    "value2": contribution_metrics2[
                        "longest_streak"
                    ]
                },

                {
                    "name": "Average Contributions / Active Day",
                    "value1": contribution_metrics1[
                        "average_contributions"
                    ],
                    "value2": contribution_metrics2[
                        "average_contributions"
                    ]
                }
            ]
        }

    # ========================================================
    # CATEGORY WINNERS
    # ========================================================
    #
    # These are NOT used to calculate the Profile Score.
    #
    # They simply tell the comparison page who has the higher
    # value for each category.
    # ========================================================

    category_scores = {}

    category_metric_weights = {
        "visibility": {
            "Followers": 1.0,
            "Following": 0.25
        },

        "project_impact": {
            "Total Stars": 1.0,
            "Total Forks": 0.5,
            "Average Stars / Repository": 1.0
        },

        "repository_portfolio": {
            "Public Repositories": 0.5,
            "Original Repositories": 1.0,
            "Forked Repositories": 0.25,
            "Archived Repositories": 0.1
        },

        "technical_profile": {
            "Languages": 1.0,
            "Profile Completeness": 0.75
        },

        "development_activity": {
            "Total Contributions": 1.0,
            "Total Commits": 1.0,
            "Active Contribution Days": 0.8,
            "Longest Contribution Streak": 0.6,
            "Average Contributions / Active Day": 0.7
        }
    }

    for category_key, category in comparison_categories.items():

        metrics = category["metrics"]

        weighted_advantage1 = 0
        weighted_advantage2 = 0

        comparable_metrics = 0

        for metric in metrics:

            value1 = metric["value1"]
            value2 = metric["value2"]

            if not isinstance(
                value1,
                (int, float)
            ):
                continue

            if not isinstance(
                value2,
                (int, float)
            ):
                continue

            weight = category_metric_weights.get(
                category_key,
                {}
            ).get(
                metric["name"],
                1.0
            )

            if value1 > value2:

                weighted_advantage1 += weight

            elif value2 > value1:

                weighted_advantage2 += weight

            comparable_metrics += 1

        if comparable_metrics == 0:

            category_winner = "Insufficient Data"

        elif weighted_advantage1 > weighted_advantage2:

            category_winner = user1["login"]

        elif weighted_advantage2 > weighted_advantage1:

            category_winner = user2["login"]

        else:

            category_winner = "Tie"

        category_scores[
            category_key
        ] = {

            "label": category["label"],

            "winner": category_winner,

            "metrics": metrics
        }

    # ========================================================
    # OVERALL PROFILE SCORE COMPARISON
    # ========================================================

    overall_score1 = (
        profile_score1["total"]
    )

    overall_score2 = (
        profile_score2["total"]
    )

    score_difference = round(
        abs(
            overall_score1
            - overall_score2
        ),
        2
    )

    if score_difference < 0.01:

        overall_winner = "Tie"

    elif overall_score1 > overall_score2:

        overall_winner = user1["login"]

    else:

        overall_winner = user2["login"]

    # --------------------------------------------------------
    # Count category ties
    # --------------------------------------------------------

    overall_tie_count = sum(
        1
        for category in category_scores.values()
        if category["winner"] == "Tie"
    )

    # ========================================================
    # RENDER
    # ========================================================

    return render_template(

        "compare.html",

        user1=user1,

        user2=user2,

        comparison_metrics=(
            comparison_metrics
        ),

        comparison_categories=(
            comparison_categories
        ),

        category_scores=(
            category_scores
        ),

        # ----------------------------------------------------
        # Independent Profile Scores
        # ----------------------------------------------------

        profile_score1=(
            profile_score1
        ),

        profile_score2=(
            profile_score2
        ),

        overall_score1=(
            overall_score1
        ),

        overall_score2=(
            overall_score2
        ),

        overall_tie_count=(
            overall_tie_count
        ),

        overall_winner=(
            overall_winner
        ),

        score_difference=(
            score_difference
        ),

        # ----------------------------------------------------
        # Additional data if compare.html needs it later
        # ----------------------------------------------------

        repo_metrics1=(
            repo_metrics1
        ),

        repo_metrics2=(
            repo_metrics2
        ),

        contribution_metrics1=(
            contribution_metrics1
        ),

        contribution_metrics2=(
            contribution_metrics2
        ),

        completeness1=(
            completeness1
        ),

        completeness2=(
            completeness2
        )
    )


# ============================================================
# APPLICATION START
# ============================================================

if __name__ == "__main__":
    app.run(debug=True)

