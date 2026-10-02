"""
probables.py - Postseason probable starters + their regular-season
first-inning stats.

Run main.py first (with the full regular season loaded) so mlb.db exists.
Keep both files in the same folder.

Setup:
    pip install requests

Run:
    python probables.py                          # today through the next 3 days
    python probables.py 2026-10-02               # one date
    python probables.py 2026-10-02 2026-10-08    # a date range
"""

import sqlite3
import sys
from datetime import date, timedelta

import pandas as pd
import requests

# Importing from main.py doesn't re-run the data pull, because main.py
# only calls main() when run directly (the __name__ check).
from main import DB_PATH

SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"

# MLB game type codes for the postseason:
#   F = Wild Card, D = Division Series, L = League Championship, W = World Series
POSTSEASON_TYPES = {"F", "D", "L", "W"}


# ---------------------------------------------------------------------------
# Fetch the schedule + announced starters
# ---------------------------------------------------------------------------

def fetch_probable_pitchers(start_date: str, end_date: str,
                            postseason_only: bool = True) -> pd.DataFrame:
    """
    Return one row per team per game: that team's probable starter.
    Pitcher fields are None if the team hasn't announced a starter yet
    (postseason starters usually get announced only a day or two ahead).
    """
    params = {
        "sportId": 1,                                # 1 = MLB
        "startDate": start_date,
        "endDate": end_date,
        "hydrate": "probablePitcher,team,venue",     # ask for extra detail
    }
    response = requests.get(SCHEDULE_URL, params=params, timeout=15)
    response.raise_for_status()  # raises on 4xx/5xx instead of failing silently
    data = response.json()

    rows = []
    # The response nests like: dates -> games -> teams -> away/home
    for day in data.get("dates", []):
        for game in day["games"]:
            # Skip regular-season/other games when we only want the postseason.
            if postseason_only and game.get("gameType") not in POSTSEASON_TYPES:
                continue

            for side, other_side in (("away", "home"), ("home", "away")):
                team = game["teams"][side]
                opponent = game["teams"][other_side]
                # .get() returns None instead of crashing if the key is missing
                pitcher = team.get("probablePitcher") or {}

                rows.append({
                    "date": game.get("officialDate"),
                    "game_pk": game["gamePk"],
                    "game_type": game.get("gameType"),
                    "venue": game.get("venue", {}).get("name"),
                    "side": side,
                    "team": team["team"]["name"],
                    "opponent": opponent["team"]["name"],
                    "pitcher_id": pitcher.get("id"),
                    "pitcher_name": pitcher.get("fullName"),
                })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Join with the stats we saved in main.py
# ---------------------------------------------------------------------------

def attach_first_inning_stats(probables: pd.DataFrame) -> pd.DataFrame:
    """Add regular-season first-inning numbers to each probable starter."""
    with sqlite3.connect(DB_PATH) as conn:
        stats = pd.read_sql("SELECT * FROM pitcher_first_inning", conn)

    # The MLB Stats API and Statcast both use the same player IDs
    # (MLBAM IDs), so we can join on them directly.
    stats = stats.rename(columns={"pitcher": "pitcher_id", "starts": "fi_starts"})
    stats = stats.drop(columns=["pitcher_name"])  # keep the API's name instead

    # how="left" keeps every probable starter, even ones with no stats
    # (rookies, or pitchers outside the date range you pulled in main.py).
    return probables.merge(stats, on="pitcher_id", how="left")


# ---------------------------------------------------------------------------
# Run it
# ---------------------------------------------------------------------------

def main() -> None:
    # sys.argv holds command-line arguments; [0] is the script name.
    args = sys.argv[1:]
    if len(args) == 0:
        start = date.today()
        end = start + timedelta(days=3)
        start_date, end_date = start.isoformat(), end.isoformat()
    elif len(args) == 1:
        start_date = end_date = args[0]
    else:
        start_date, end_date = args[0], args[1]

    probables = fetch_probable_pitchers(start_date, end_date)
    if probables.empty:
        print(f"No postseason games found for {start_date} to {end_date}.")
        return

    combined = attach_first_inning_stats(probables)
    combined = combined.sort_values(["date", "game_pk", "side"])

    cols = ["date", "team", "opponent", "pitcher_name", "fi_starts",
            "raw_nrfi_rate", "shrunk_nrfi_rate",
            "raw_1st_inn_era", "shrunk_1st_inn_era"]
    print(f"\nPostseason probable starters, {start_date} to {end_date}:\n")
    print(combined[cols].round(2).to_string(index=False))

    tbd = combined["pitcher_id"].isna().sum()
    if tbd:
        print(f"\n{tbd} team(s) haven't announced a starter yet - rerun closer to game time.")


if __name__ == "__main__":
    main()