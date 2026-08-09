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

    return response.json()

if __name__ == "__main__":
    app.run(debug=True)