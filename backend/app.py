"""
app.py - Step 3: a tiny Flask API around probables.py.

Setup:
    pip install flask flask-cors

Run:
    python app.py
Then open in your browser:
    http://127.0.0.1:5000/api/probables
    http://127.0.0.1:5000/api/probables?start=2026-10-02&end=2026-10-08
    http://127.0.0.1:5000/api/probables?postseason=false   (all games, not just postseason)
"""

from datetime import date, timedelta

import requests
from flask import Flask, Response, jsonify, request
from flask_cors import CORS

# Reuse the functions you already wrote - the model/data code stays separate
# from the web code, so you can test and backtest it without Flask.
from backend.probables import attach_first_inning_stats, fetch_probable_pitchers

app = Flask(__name__)
CORS(app)  # lets your React dev server (a different port) call this API


@app.route("/api/probables")
def probables_endpoint():
    # request.args holds the ?key=value parts of the URL.
    start = request.args.get("start", date.today().isoformat())
    default_end = (date.fromisoformat(start) + timedelta(days=3)).isoformat()
    end = request.args.get("end", default_end)
    postseason_only = request.args.get("postseason", "true").lower() == "true"

    try:
        games = fetch_probable_pitchers(start, end, postseason_only)
    except requests.RequestException as err:
        # The MLB API was unreachable or returned an error.
        return jsonify({"error": f"MLB API request failed: {err}"}), 502

    if games.empty:
        return jsonify([])

    combined = attach_first_inning_stats(games)
    combined = combined.sort_values(["date", "game_pk", "side"])

    # to_json turns NaN into null (plain jsonify would produce invalid JSON)
    # and handles numpy number types for us.
    return Response(combined.to_json(orient="records"), mimetype="application/json")


if __name__ == "__main__":
    app.run(debug=True)  # debug=True auto-reloads when you save the file