"""
Example: top fantasy scorers for a season, built on the new player DB.

This is the core pattern for the whole system: take any nflverse stat table and
join it to the identity registry on `gsis_id` to get clean, cross-source player
info - no name matching required.

    python -m src.examples.top_scorers                      # last season, PPR
    python -m src.examples.top_scorers --season 2024 --n 25
    python -m src.examples.top_scorers --pos RB --scoring fantasy_points
"""
import argparse

import nflreadpy as nfl

from src.identity.registry import load_registry
from src.normalize import clean_id_series


def top_scorers(season: int, n: int = 15, pos: str | None = None,
                scoring: str = "fantasy_points_ppr"):
    # 1. Season-total stats from nflverse (keyed on player_id == gsis_id).
    stats = nfl.load_player_stats(seasons=[season], summary_level="reg").to_pandas()
    stats["gsis_id"] = clean_id_series(stats["player_id"])
    stats = stats.dropna(subset=["gsis_id"])   # join hygiene: never join on null keys

    # 2. Identity from our registry; rename to avoid colliding with stats columns.
    reg = load_registry()[["gsis_id", "full_name", "position", "team"]].rename(
        columns={"position": "reg_position", "team": "reg_team"}
    )

    # 3. Join on the universal key, prefer registry identity, fall back to stats.
    df = stats.merge(reg, on="gsis_id", how="left")
    df["name"] = df["full_name"].fillna(df["player_display_name"])
    df["position"] = df["reg_position"].fillna(df.get("position"))
    # Stats tables name the team column "team" (weekly) or "recent_team" (season).
    stats_team = next((c for c in ("team", "recent_team") if c in df.columns), None)
    df["team"] = df["reg_team"].fillna(df[stats_team]) if stats_team else df["reg_team"]

    if pos:
        df = df[df["position"] == pos.upper()]

    cols = ["name", "position", "team", scoring]
    if "games" in df.columns:
        df["ppg"] = (df[scoring] / df["games"]).round(1)
        cols.append("ppg")

    return df.sort_values(scoring, ascending=False).head(n)[cols].reset_index(drop=True)


def _parse_args():
    p = argparse.ArgumentParser(description="Top fantasy scorers for a season.")
    p.add_argument("--season", type=int, default=nfl.get_current_season(),
                   help="Season year (default: current/last season).")
    p.add_argument("--n", type=int, default=15, help="How many players to show.")
    p.add_argument("--pos", help="Filter to a position (QB/RB/WR/TE/K).")
    p.add_argument("--scoring", default="fantasy_points_ppr",
                   help="Stat column to rank by (e.g. fantasy_points, fantasy_points_ppr).")
    return p.parse_args()


if __name__ == "__main__":
    a = _parse_args()
    print(f"Top {a.n} {a.pos or ''} scorers - {a.season} ({a.scoring}):\n")
    print(top_scorers(a.season, n=a.n, pos=a.pos, scoring=a.scoring).to_string(index=True))
