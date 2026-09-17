"""
What each NFL defence gives up to each position, in fantasy points.

Sleeper's weekly stats feed already does the accounting: every team defence's
row carries `fan_pts_allow_qb`, `_rb`, `_wr`, `_te`, `_k` and `_def` - the
fantasy points the players across from it scored that week. So a week is one
request, and a finished week never changes; each is fetched once into
data/fantasy/dvp/{year}.json.

A rating is a defence's points allowed per game at a position over the league
average at that position: 1.00 is par, above it a defence to attack. Under
FULL_WEIGHT_GAMES games it is pulled toward par, so one shootout in week 1
does not brand a defence for the season - the same rule the college
matchup-strength page uses.

    python -m fantasy.league.defense
"""
import json

import pandas as pd

from fantasy import paths
from fantasy.config import UPCOMING_YEAR
from fantasy.league import matchups as matchups_mod

POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")
FULL_WEIGHT_GAMES = 5
DVP_DIR = paths.DATA_DIR / "dvp"


def _path(year: int):
    return DVP_DIR / f"{year}.json"


def load(year: int = UPCOMING_YEAR) -> dict:
    """{week: {defence: {position: points allowed}}} as archived."""
    try:
        return json.loads(_path(year).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _fetch_week(week: int, year: int) -> dict:
    rows = matchups_mod._get(
        f"{matchups_mod.SLEEPER_ROOT}/stats/nfl/{year}/{week}?season_type=regular&"
        "position[]=DEF&order_by=pts_ppr") or []
    out = {}
    for r in rows:
        stats, team = r.get("stats") or {}, r.get("team")
        if not team or not stats.get("gp", 1):
            continue
        if stats.get("fan_pts_allow") is None:
            continue                                    # a bye: nothing was allowed to anyone
        # Sleeper drops a zero rather than sending it, so a position that is
        # missing from a defence that played is a shutout at that position.
        out[str(team)] = {pos: float(stats.get(f"fan_pts_allow_{pos.lower()}") or 0.0)
                          for pos in POSITIONS}
    return out


def capture(year: int = UPCOMING_YEAR) -> dict:
    """Archive every finished week not yet on disk."""
    have = load(year)
    changed = False
    for week in matchups_mod.archived_weeks(year):
        if str(week) in have:
            continue
        if not matchups_mod.week_final(matchups_mod.week_matchups(week, year)):
            continue
        got = _fetch_week(week, year)
        if got:
            have[str(week)] = got
            changed = True
            print(f"[dvp] week {week}: {len(got)} defences")
    if changed:
        DVP_DIR.mkdir(parents=True, exist_ok=True)
        _path(year).write_text(json.dumps(have), encoding="utf-8")
    return have


def ratings(year: int = UPCOMING_YEAR, data: dict = None) -> pd.DataFrame:
    """One row per defence, a column per position: allowed against the league
    average, shrunk toward 1.00 while the sample is thin. Plus `games`."""
    data = load(year) if data is None else data
    rows = [{"team": team, "week": int(week), **allowed}
            for week, teams in data.items() for team, allowed in teams.items()]
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    cols = [p for p in POSITIONS if p in frame]
    league = frame[cols].mean()
    per_team = frame.groupby("team")[cols].mean()
    games = frame.groupby("team")["week"].nunique()
    weight = (games / FULL_WEIGHT_GAMES).clip(upper=1.0)
    out = (per_team / league - 1.0).mul(weight, axis=0) + 1.0
    out["games"] = games
    return out


def ranks(table: pd.DataFrame) -> dict:
    """{position: {team: rank}}, 1 = gives up the most."""
    return {pos: table[pos].rank(ascending=False, method="min").astype(int).to_dict()
            for pos in POSITIONS if pos in table}


if __name__ == "__main__":
    table = ratings(data=capture())
    print(table.sort_values("RB", ascending=False).round(2).head(8).to_string()
          if not table.empty else "no finished weeks yet")
