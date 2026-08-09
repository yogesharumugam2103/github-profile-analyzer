from flask import Flask, render_template
import requests

app = Flask(__name__)

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/test-github")
def test_github():
    response = requests.get("https://api.github.com/users/octocat")
    return response.json()

if __name__ == "__main__":
    app.run(debug=True)