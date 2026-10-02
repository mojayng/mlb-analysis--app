import sqlite3


import pandas as pd
from pybaseball import cache, statcast


START_DATE = '2026-03-25'
END_DATE = "2026-09-30"

DB_PATH = "mlb.db"



SHRINK_STRENGTH = 30 

def fetch_first_inning_pitches(start: str, end: str) -> pd.DataFrame:
    """Download Statcast pitches and keep only 1st-inning, regular-season ones."""
    cache.enable()  # saves downloads to disk so re-running doesn't re-download

    pitches = statcast(start_dt=start, end_dt=end)

    # game_type "R" = regular season (filters out spring training/playoffs)
    mask = (pitches["game_type"] == "R") & (pitches["inning"] == 1)
    return pitches[mask].copy()



def build_first_inning_starts(pitches: pd.DataFrame) -> pd.DataFrame:
    """
    Each game has two first-inning halves:
      - top of the 1st: the home team's starter pitches
      - bottom of the 1st: the away team's starter pitches
    For each half, record who pitched first and how many runs scored.
 
    Simplification: if a pitcher gets pulled mid-inning, the runs after
    the change still count against the starter. That's rare, so fine for now.
    """
    # Sort so that "first" below really means the first pitch thrown.
    pitches = pitches.sort_values(
        ["game_pk", "inning_topbot", "at_bat_number", "pitch_number"]
    )
 
    # groupby splits the table into chunks (one per game + half-inning),
    # then agg() summarizes each chunk into a single row.
    starts = (
        pitches.groupby(["game_pk", "inning_topbot"])
        .agg(
            game_date=("game_date", "first"),
            pitcher=("pitcher", "first"),          # MLB player ID
            pitcher_name=("player_name", "first"),  # "Last, First"
            # post_bat_score = batting team's score after each pitch.
            # The batting team starts the 1st at 0, so the max = runs scored.
            runs=("post_bat_score", "max"),
            batters_faced=("at_bat_number", "nunique"),
        )
        .reset_index()
    )
    return starts
 
 
# ---------------------------------------------------------------------------
# Step 3: per-pitcher summary with shrinkage
# ---------------------------------------------------------------------------
 
def summarize_by_pitcher(starts: pd.DataFrame, k: int = SHRINK_STRENGTH) -> pd.DataFrame:
    """Turn the per-start table into one row per pitcher."""
    starts = starts.copy()
    starts["nrfi"] = (starts["runs"] == 0).astype(int)  # 1 = no run in 1st
 
    # League-wide averages: what an "average" starter looks like.
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
    # ERA = runs per 9 innings, and each sample here is 1 inning, so x9.
    # (Uses ALL runs, not just earned - Statcast doesn't label earned runs.)
    by_pitcher["raw_1st_inn_era"] = by_pitcher["runs_allowed"] * 9 / n
 
    # Shrunk numbers: add k "fake average starts" to every pitcher.
    # Few real starts -> fake ones dominate -> close to league average.
    # Many real starts -> real ones dominate -> close to his own numbers.
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
# Step 4: save to the database
# ---------------------------------------------------------------------------
 
def save_table(df: pd.DataFrame, table_name: str) -> None:
    """Write a DataFrame to SQLite, replacing the table if it exists."""
    # "with" closes the connection automatically when the block ends.
    with sqlite3.connect(DB_PATH) as conn:
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
 
    # Quick look at the results. Only show pitchers with enough starts
    # for the numbers to mean anything at all.
    shown = summary[summary["starts"] >= 4].sort_values("shrunk_1st_inn_era")
    cols = ["pitcher_name", "starts", "raw_1st_inn_era", "shrunk_1st_inn_era",
            "raw_nrfi_rate", "shrunk_nrfi_rate"]
    print("\nBest first-inning pitchers (shrunk ERA):")
    print(shown[cols].head(10).round(2).to_string(index=False))
    print("\nWorst first-inning pitchers (shrunk ERA):")
    print(shown[cols].tail(10).round(2).to_string(index=False))
 
 
# This line means "only run main() if I run this file directly",
# not if another file imports it later (like your Flask app will).
if __name__ == "__main__":
    main()