"""
Every NFL game since 2014, from ESPN's scoreboard (data/nfl/games/{year}.parquet).

ESPN serves completed seasons exactly as it serves the current one, one
request per week and no key: 18 regular-season weeks plus the four rounds of
the playoffs, 2014-2025 is ~3,300 games in ~260 requests. The Super Bowl is a
neutral site and says so; the Pro Bowl is postseason "week 4" and is skipped.

Two traps, the same two the college archive has:
  * A cancelled game (Bills-Bengals, January 2023) is filed "post" with a 0-0
    score. The NFL has never had a 0-0 tie in the overtime era, so any 0-0 is
    a game that was not played.
  * Team ids, not names or abbreviations: the Rams, Chargers and Raiders moved
    and Washington renamed twice inside this archive, and the id is the only
    thing that followed them.

    python -m nfl.games --backfill
    python -m nfl.games                 # summarise what is on disk
"""
import time
from datetime import datetime, timedelta

import pandas as pd
import requests

from nfl.config import DATA_DIR, SEASON

_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
# ESPN 403s a browser-like User-Agent from python-requests (TLS fingerprint)
# but answers the library's own, so no header is sent - see cfb.espn.
_TIMEOUT = 25
_PAUSE = 0.3
GAMES_DIR = DATA_DIR / "games"
FIRST_SEASON = 2014
REGULAR_WEEKS = 18                 # 17 before 2021; the extra requests come back empty
POSTSEASON_WEEKS = (1, 2, 3, 5)    # wild card, divisional, conference, Super Bowl
MAX_AGE_HOURS = 3


def _get(params: dict) -> dict:
    r = requests.get(_SCOREBOARD, params=params, timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json()


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _implied(odds: dict) -> tuple:
    """(home implied, away implied) from a spread and total; ESPN's `spread`
    is the home line, negative when the home side is favoured."""
    total, spread = _num(odds.get("overUnder")), _num(odds.get("spread"))
    if total is None or spread is None:
        return None, None
    return (total - spread) / 2, (total + spread) / 2


def _game_row(event: dict, week: int, seasontype: int) -> dict:
    comp = event["competitions"][0]
    sides = {c["homeAway"]: c for c in comp["competitors"]}
    home, away = sides["home"], sides["away"]
    status = (comp.get("status") or event.get("status") or {}).get("type") or {}
    odds = (comp.get("odds") or [{}])[0]
    venue = comp.get("venue") or {}
    address = venue.get("address") or {}
    place = ", ".join(x for x in (address.get("city"), address.get("state")) if x)
    if address.get("country") not in (None, "USA"):
        place = ", ".join(x for x in (place, address.get("country")) if x)
    return {
        "week": week, "seasontype": seasontype,
        "game_id": str(event.get("id", "")),
        "date_utc": event["date"],
        "home_id": str(home["team"].get("id", "")),
        "away_id": str(away["team"].get("id", "")),
        "home": home["team"].get("shortDisplayName") or home["team"]["displayName"],
        "away": away["team"].get("shortDisplayName") or away["team"]["displayName"],
        "home_abbr": home["team"].get("abbreviation", ""),
        "away_abbr": away["team"].get("abbreviation", ""),
        "home_score": _num(home.get("score")),
        "away_score": _num(away.get("score")),
        "home_record": next((r.get("summary") for r in home.get("records") or []
                             if r.get("type") == "total"), ""),
        "away_record": next((r.get("summary") for r in away.get("records") or []
                             if r.get("type") == "total"), ""),
        "neutral": bool(comp.get("neutralSite")),
        "venue": venue.get("fullName", ""), "place": place,
        "indoor": bool(venue.get("indoor")),
        "tv": ", ".join(n for b in comp.get("broadcasts") or [] for n in (b.get("names") or [])),
        "state": status.get("state", "pre"),
        "completed": bool(status.get("completed")),
        "detail": status.get("shortDetail", ""),
        # The book, where ESPN carries one (the current season only).
        "book_spread": _num(odds.get("spread")), "book_total": _num(odds.get("overUnder")),
        "odds_detail": odds.get("details") or "",
    }


def _week_rows(season: int, week: int, seasontype: int) -> list:
    data = _get({"week": week, "dates": season, "seasontype": seasontype, "limit": 100})
    rows = []
    for event in data.get("events", []):
        if not event.get("competitions"):
            continue
        try:
            rows.append(_game_row(event, week, seasontype))
        except (KeyError, IndexError, TypeError):
            continue
    return rows


def fetch_season(season: int, postseason: bool = True) -> pd.DataFrame:
    rows = []
    for week in range(1, REGULAR_WEEKS + 1):
        rows.extend(_week_rows(season, week, 2))
        time.sleep(_PAUSE)
    if postseason:
        for week in POSTSEASON_WEEKS:
            rows.extend(_week_rows(season, week, 3))
            time.sleep(_PAUSE)
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    frame["season"] = season
    return frame.sort_values(["seasontype", "week", "date_utc"]).reset_index(drop=True)


def season_path(season: int):
    return GAMES_DIR / f"{season}.parquet"


def backfill(first: int = FIRST_SEASON, last: int = SEASON - 1, refresh: bool = False):
    GAMES_DIR.mkdir(parents=True, exist_ok=True)
    for season in range(first, last + 1):
        path = season_path(season)
        if path.exists() and not refresh:
            print(f"  {season}: already on disk ({len(pd.read_parquet(path))} games)")
            continue
        frame = fetch_season(season)
        if frame.empty:
            print(f"  {season}: nothing returned")
            continue
        frame.to_parquet(path, index=False)
        print(f"  {season}: {len(frame)} games, {int(frame['completed'].sum())} completed")


def schedule(refresh: bool = False, max_age_hours: float = MAX_AGE_HOURS) -> pd.DataFrame:
    """This season, every game, refetched when the cache is older than
    `max_age_hours` - the scores and the book move; last year's do not."""
    path = season_path(SEASON)
    if path.exists() and not refresh:
        age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
        if age < timedelta(hours=max_age_hours):
            return pd.read_parquet(path)
    frame = fetch_season(SEASON)
    if frame.empty:
        return pd.read_parquet(path) if path.exists() else frame
    GAMES_DIR.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return frame


def _derive(games: pd.DataFrame) -> pd.DataFrame:
    games = games.copy()
    games["date"] = pd.to_datetime(games["date_utc"], format="ISO8601", utc=True)
    games["margin"] = games["home_score"] - games["away_score"]
    games["total"] = games["home_score"] + games["away_score"]
    # The model's team identity is ESPN's id, which survives a move.
    games["home_team"] = games["home_id"]
    games["away_team"] = games["away_id"]
    return games


def played(games: pd.DataFrame) -> pd.DataFrame:
    """Finished games only: completed, scored, and not the 0-0 of a game
    that was never played."""
    done = games[games["completed"].astype(bool) & (games["state"] == "post")]
    done = done.dropna(subset=["home_score", "away_score"])
    return done[(done["home_score"] > 0) | (done["away_score"] > 0)]


def load(first: int = FIRST_SEASON, last: int = SEASON, played_only: bool = True) -> pd.DataFrame:
    """Every stored season stacked, with `date`, `margin`, `total` and the
    model's `home_team`/`away_team` derived."""
    frames = [pd.read_parquet(season_path(s)) for s in range(first, last + 1)
              if season_path(s).exists()]
    if not frames:
        return pd.DataFrame()
    games = pd.concat(frames, ignore_index=True)
    if played_only:
        games = played(games)
    return _derive(games).sort_values("date").reset_index(drop=True)


def team_names(games: pd.DataFrame) -> dict:
    """id -> the name and abbreviation it carried most recently."""
    latest = games.sort_values("date_utc")
    out = {}
    for side in ("home", "away"):
        for tid, name, abbr in zip(latest[f"{side}_id"], latest[side], latest[f"{side}_abbr"]):
            out[str(tid)] = (name, abbr)
    return out


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--backfill", action="store_true")
    p.add_argument("--refresh", action="store_true")
    args = p.parse_args()
    if args.backfill:
        backfill(refresh=args.refresh)
    games = load()
    if games.empty:
        raise SystemExit("nothing on disk")
    print(f"{len(games)} played games, {games['season'].min()}-{games['season'].max()}, "
          f"{games['home_team'].nunique()} teams")
    print(games.groupby("season").size().to_string())
