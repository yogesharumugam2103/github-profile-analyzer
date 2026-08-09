from flask import Flask, render_template, request
import requests

app = Flask(__name__)

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/analyze")
def analyze():
    username = request.args.get("username")

    if not username:
        return "Please enter a GitHub username."

    response = requests.get(f"https://api.github.com/users/{username}")

    if response.status_code == 404:
        return "GitHub user not found."

    if response.status_code != 200:
        return "Something went wrong while contacting GitHub."

    user_data = response.json()

    repos_response = requests.get(
        f"https://api.github.com/users/{username}/repos"
    )

    repos = repos_response.json()

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
        forked_repos=forked_repos
    )

if __name__ == "__main__":
    app.run(debug=True)