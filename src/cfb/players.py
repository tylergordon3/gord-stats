"""
College player production, scored in this league's own currency.

The Yahoo board (cfb.yahoo.board) ranks players but never says what a player is
worth in points, and Yahoo publishes no projections for the college game - its
season stat lines are all zeroes until games are played. So the points have to
come from somewhere else, and the only honest source is what players actually
did: CFBD's season stat lines, run through this league's scoring modifiers.

That gives two things the draft model needs:

  * a points scale - what a WR12 or a QB8 is actually worth in a season, which
    is what turns a board rank into value over replacement;
  * last year's production per player, which is the one piece of evidence the
    board's rank is not already made of.

Season totals only. CFBD serves a games-played count per player nowhere in this
endpoint, so per-game rates would need the box-score feed (60 games x 15 weeks);
for a draft model the season total is the number that matters anyway - a player
who missed four games is worth less over a fantasy season, and the total says so.

    python -m cfb.players               # 2025, from cache if fresh
    python -m cfb.players --refresh
"""
import os
import time

import pandas as pd
import requests
from dotenv import load_dotenv

from cfb.config import DATA_DIR, SEASON
from gordstats import paths

API = "https://api.collegefootballdata.com"
_TIMEOUT = 120
PLAYERS_DIR = DATA_DIR / "players"

# A season's stat lines are a fact once the season is over, so the cache for a
# finished season never expires. Only the season in progress is refetched.
MAX_AGE_HOURS = 12

# CFBD's (category, statType) -> the league modifier it feeds. Everything else
# it serves (defensive tackles, punting, kicking, the AVG/LONG/PCT rate stats)
# scores nothing in this league and is dropped.
_STATS = {
    ("passing", "YDS"): "pass_yds",
    ("passing", "TD"): "pass_td",
    ("passing", "INT"): "pass_int",
    ("rushing", "YDS"): "rush_yds",
    ("rushing", "TD"): "rush_td",
    ("rushing", "CAR"): "carries",
    ("receiving", "REC"): "rec",
    ("receiving", "YDS"): "rec_yds",
    ("receiving", "TD"): "rec_td",
    ("fumbles", "LOST"): "fum_lost",
    ("kickReturns", "TD"): "kr_td",
    ("puntReturns", "TD"): "pr_td",
}

# Yahoo's modifier names, as cfb.yahoo.league() reports them, against the column
# each one multiplies. Reading the values off the league rather than hardcoding
# them means a scoring change in the settings reprices the whole board.
_SCORING = {
    "Pass Yds": "pass_yds",
    "Pass TD": "pass_td",
    "Rush Yds": "rush_yds",
    "Rush TD": "rush_td",
    "Rec": "rec",
    "Rec Yds": "rec_yds",
    "Rec TD": "rec_td",
    "Fum Lost": "fum_lost",
}

_COLS = sorted(set(_STATS.values()))


def _key() -> str:
    load_dotenv(paths.ROOT / ".env")
    key = os.getenv("CFBD_KEY")
    if not key:
        raise RuntimeError("CFBD_KEY is not set; put it in .env")
    return key


def season_path(season: int):
    return PLAYERS_DIR / f"{season}.parquet"


def fetch_season(season: int) -> pd.DataFrame:
    """One row per player-season, with every scoring stat as a column."""
    r = requests.get(f"{API}/stats/player/season", timeout=_TIMEOUT,
                     headers={"Authorization": f"Bearer {_key()}"},
                     params={"year": season})
    r.raise_for_status()
    rows = []
    for s in r.json():
        col = _STATS.get((s.get("category"), s.get("statType")))
        if col is None:
            continue
        try:
            value = float(s["stat"])
        except (TypeError, ValueError, KeyError):
            continue
        rows.append({"player_id": str(s.get("playerId")), "player": s.get("player"),
                     "pos": s.get("position") or "", "school": s.get("team"),
                     "conference": s.get("conference"), "col": col, "value": value})
    if not rows:
        return pd.DataFrame(columns=["player_id", "player", "pos", "school",
                                     "conference", *_COLS])

    long = pd.DataFrame(rows)
    # A player traded between categories still has one identity; sum in case the
    # feed ever repeats a (player, stat) pair rather than silently keeping one.
    wide = (long.pivot_table(index=["player_id", "player", "pos", "school", "conference"],
                             columns="col", values="value", aggfunc="sum")
            .reset_index().rename_axis(columns=None))
    for c in _COLS:
        if c not in wide:
            wide[c] = 0.0
    wide[_COLS] = wide[_COLS].fillna(0.0)
    wide["season"] = season
    return wide


def _is_fresh(path, max_age_hours) -> bool:
    return (time.time() - path.stat().st_mtime) < max_age_hours * 3600


def season_stats(season: int, refresh: bool = False,
                 max_age_hours: float = MAX_AGE_HOURS) -> pd.DataFrame:
    """Cached season stat lines for every player CFBD has one for.

    A finished season is a fact and its cache never expires; only the one being
    played is refetched. The pull is 25MB and the draft board asks for two of
    them, so this is the difference between a page build that is instant and one
    that spends half a minute re-downloading last year.
    """
    path = season_path(season)
    settled = season < SEASON
    if path.exists() and not refresh and (settled or _is_fresh(path, max_age_hours)):
        return pd.read_parquet(path)
    try:
        df = fetch_season(season)
    except Exception:
        if path.exists():
            return pd.read_parquet(path)
        raise
    PLAYERS_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return df


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #

def modifiers(league: dict) -> dict:
    """{column: points per unit} for this league, from its own settings.

    Yahoo names the passing interception and the team-defense interception both
    "Int", and the two carry opposite signs; the offensive one sorts first, so
    the first occurrence is the one taken. Return touchdowns are one modifier in
    the settings and two columns here, so they are mapped by hand.
    """
    seen = {}
    for m in league["modifiers"]:
        if m["name"] and m["name"] not in seen:
            seen[m["name"]] = float(m["value"])
    out = {col: seen[name] for name, col in _SCORING.items() if name in seen}
    if "Int" in seen:
        out["pass_int"] = seen["Int"]
    if "Ret TD" in seen:
        out["kr_td"] = out["pr_td"] = seen["Ret TD"]
    return out


def fantasy_points(df: pd.DataFrame, league: dict) -> pd.Series:
    """Each row's season fantasy points under this league's scoring."""
    total = pd.Series(0.0, index=df.index)
    for col, points in modifiers(league).items():
        if col in df:
            total += df[col].fillna(0.0) * points
    return total


def scored(season: int, league: dict = None, refresh: bool = False) -> pd.DataFrame:
    """Season stat lines plus a `points` column, sorted best first."""
    if league is None:
        from cfb import yahoo
        league = yahoo.league()
    df = season_stats(season, refresh=refresh).copy()
    df["points"] = fantasy_points(df, league)
    return df.sort_values("points", ascending=False, ignore_index=True)


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="College player production, scored.")
    p.add_argument("--season", type=int, default=2025)
    p.add_argument("--refresh", action="store_true")
    args = p.parse_args()

    df = scored(args.season, refresh=args.refresh)
    print(f"{len(df)} player-seasons for {args.season}")
    cols = ["player", "pos", "school", "points", "pass_yds", "pass_td",
            "rush_yds", "rush_td", "rec", "rec_yds", "rec_td"]
    print(df.head(25)[cols].to_string(index=False))
