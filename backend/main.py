"""
main.py - Data ingest: turn raw Statcast pitches into first-inning pitcher stats.

PIPELINE (say this out loud in an interview):
    Statcast (one row per pitch)
      -> keep only regular-season 1st-inning pitches
      -> collapse to one row per (game, half-inning) = one "first-inning start"
      -> collapse again to one row per pitcher, with shrinkage
      -> save both tables to SQLite

Run:  python main.py        (slow the first time; pybaseball caches downloads)
"""

import sqlite3
from contextlib import closing
from pathlib import Path

import pandas as pd

START_DATE = "2026-03-25"
END_DATE = "2026-09-30"

# Resolve the DB path relative to THIS file, not the current working directory.
# Otherwise `python main.py` and `python app.py` from different folders would
# silently create/read two different mlb.db files.
DB_PATH = Path(__file__).parent / "mlb.db"

# Shrinkage strength k: how many "fake average starts" we add to every pitcher.
# Bigger k = more skepticism about small samples. 30 is a judgment call; the
# honest way to pick it is to backtest several values (a good "next step" answer).
SHRINK_STRENGTH = 30


# ---------------------------------------------------------------------------
# Step 1: download + filter
# ---------------------------------------------------------------------------

def fetch_first_inning_pitches(start: str, end: str) -> pd.DataFrame:
    """Download Statcast pitches and keep only regular-season 1st-inning ones."""
    # Imported here, not at the top of the file, on purpose: probables.py imports
    # DB_PATH from this module, and we don't want that import to drag in
    # pybaseball (slow, heavy) just to read a constant.
    from pybaseball import cache, statcast

    cache.enable()  # cache downloads to disk so re-runs don't hit the network

    pitches = statcast(start_dt=start, end_dt=end)

    # Boolean mask = vectorized filter. Much faster than looping over rows.
    # game_type "R" = regular season (drops spring training and playoffs).
    mask = (pitches["game_type"] == "R") & (pitches["inning"] == 1)
    return pitches[mask].copy()  # .copy() avoids pandas' SettingWithCopy warning


# ---------------------------------------------------------------------------
# Step 2: one row per first-inning start
# ---------------------------------------------------------------------------

def build_first_inning_starts(pitches: pd.DataFrame) -> pd.DataFrame:
    """
    Each game has two first-inning halves:
      - top of the 1st:    the HOME team's starter pitches
      - bottom of the 1st: the AWAY team's starter pitches
    For each half, record who threw the first pitch and how many runs scored.

    Known simplification: if the starter is pulled mid-inning, runs after the
    change are still charged to him. Rare, so I accepted it. (Good thing to
    mention: knowing your model's limits is part of the job.)
    """
    # Sort so "first" in the aggregation really means the first pitch thrown.
    # groupby().agg(first) depends on row order, so this sort is load-bearing.
    pitches = pitches.sort_values(
        ["game_pk", "inning_topbot", "at_bat_number", "pitch_number"]
    )

    # groupby splits the table into chunks (one per game + half-inning);
    # agg() reduces each chunk to a single row. Same idea as SQL GROUP BY.
    starts = (
        pitches.groupby(["game_pk", "inning_topbot"])
        .agg(
            game_date=("game_date", "first"),
            pitcher=("pitcher", "first"),           # MLBAM player ID
            pitcher_name=("player_name", "first"),  # "Last, First"
            # post_bat_score = batting team's score after each pitch. The
            # batting team starts the 1st at 0, so the max = runs scored.
            runs=("post_bat_score", "max"),
            batters_faced=("at_bat_number", "nunique"),
        )
        .reset_index()
    )
    return starts


# ---------------------------------------------------------------------------
# Step 3: one row per pitcher, with shrinkage
# ---------------------------------------------------------------------------

def summarize_by_pitcher(starts: pd.DataFrame, k: int = SHRINK_STRENGTH) -> pd.DataFrame:
    """
    Turn the per-start table into one row per pitcher.

    WHY SHRINKAGE: a pitcher with 3 starts and 0 runs has a raw 1st-inning ERA
    of 0.00, which is mostly luck. Shrinkage (a simple empirical-Bayes idea)
    pulls small samples toward the league average and trusts big samples more.
    """
    starts = starts.copy()
    starts["nrfi"] = (starts["runs"] == 0).astype(int)  # NRFI = "no run first inning"

    # League-wide averages = what an "average" starter looks like (the prior).
    league_nrfi_rate = starts["nrfi"].mean()
    league_runs_per_start = starts["runs"].mean()

    by_pitcher = (
        starts.groupby(["pitcher", "pitcher_name"])
        .agg(
            starts=("nrfi", "size"),
            nrfi_count=("nrfi", "sum"),
            runs_allowed=("runs", "sum"),
        )
        .reset_index()
    )

    n = by_pitcher["starts"]

    # Raw numbers: exactly what happened, no adjustment.
    by_pitcher["raw_nrfi_rate"] = by_pitcher["nrfi_count"] / n
    # ERA = runs per 9 innings. Each sample here is exactly 1 inning, so x9.
    # Caveat: this counts ALL runs, not just earned; Statcast doesn't label them.
    by_pitcher["raw_1st_inn_era"] = by_pitcher["runs_allowed"] * 9 / n

    # Shrunk numbers: (real successes + k * league rate) / (real starts + k)
    # Few real starts  -> the k fake ones dominate -> near league average.
    # Many real starts -> the real ones dominate   -> near his own numbers.
    by_pitcher["shrunk_nrfi_rate"] = (
        by_pitcher["nrfi_count"] + k * league_nrfi_rate
    ) / (n + k)
    by_pitcher["shrunk_1st_inn_era"] = 9 * (
        by_pitcher["runs_allowed"] + k * league_runs_per_start
    ) / (n + k)

    print(f"League NRFI rate: {league_nrfi_rate:.3f} | "
          f"League 1st-inning ERA: {league_runs_per_start * 9:.2f}")
    return by_pitcher


# ---------------------------------------------------------------------------
# Step 4: persist to SQLite
# ---------------------------------------------------------------------------

def save_table(df: pd.DataFrame, table_name: str) -> None:
    """Write a DataFrame to SQLite, replacing the table if it exists."""
    # NOTE: `with sqlite3.connect(...)` only commits or rolls back the
    # transaction; it does NOT close the connection. closing() does that.
    with closing(sqlite3.connect(DB_PATH)) as conn:
        with conn:  # commit on success, roll back on error
            df.to_sql(table_name, conn, if_exists="replace", index=False)


# ---------------------------------------------------------------------------
# Run everything
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"Fetching Statcast data {START_DATE} to {END_DATE}...")
    pitches = fetch_first_inning_pitches(START_DATE, END_DATE)
    print(f"  {len(pitches):,} first-inning pitches")

    starts = build_first_inning_starts(pitches)
    print(f"  {len(starts):,} first-inning starts")

    summary = summarize_by_pitcher(starts)

    save_table(starts, "first_inning_starts")
    save_table(summary, "pitcher_first_inning")
    print(f"Saved to {DB_PATH}")

    # Quick sanity check. Only show pitchers with a few starts so the
    # leaderboard isn't dominated by tiny samples.
    shown = summary[summary["starts"] >= 4].sort_values("shrunk_1st_inn_era")
    cols = ["pitcher_name", "starts", "raw_1st_inn_era", "shrunk_1st_inn_era",
            "raw_nrfi_rate", "shrunk_nrfi_rate"]
    print("\nBest first-inning pitchers (shrunk ERA):")
    print(shown[cols].head(10).round(2).to_string(index=False))
    print("\nWorst first-inning pitchers (shrunk ERA):")
    print(shown[cols].tail(10).round(2).to_string(index=False))


# Only run main() when this file is executed directly, not when another
# module (probables.py, app.py) imports it.
if __name__ == "__main__":
    main()