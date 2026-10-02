"""
Every NFL game since 2014, from ESPN's scoreboard (data/nfl/games/{year}.parquet).

ESPN serves completed seasons exactly as it serves the current one, one
request per week and no key: 18 regular-season weeks plus the four rounds of
the playoffs, 2014-2025 is ~3,300 games in ~260 requests. The Super Bowl is a
neutral site and says so. Which postseason week holds which round is read
from ESPN's own calendar (postseason_rounds): through 2025 the Pro Bowl was
week 4 and the Super Bowl week 5; from 2026 there is no Pro Bowl week and the
Super Bowl is week 4 - asking for week 5 that season returns nothing, which
is how the 2026 Super Bowl went missing. The Pro Bowl is never fetched, and
each playoff row carries the calendar's name for its round in `round`.

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
from gordstats import stable

_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
# ESPN 403s a browser-like User-Agent from python-requests (TLS fingerprint)
# but answers the library's own, so no header is sent - see cfb.espn.
_TIMEOUT = 25
_PAUSE = 0.3
GAMES_DIR = DATA_DIR / "games"
FIRST_SEASON = 2014
REGULAR_WEEKS = 18                 # 17 before 2021; the extra requests come back empty
MAX_AGE_HOURS = 3
SUPER_BOWL = "Super Bowl"
# The rounds when ESPN's calendar is not there to say: the Pro Bowl held
# week 4 through the 2025 season, and from 2026 it is gone.
_ROUNDS_TO_2025 = {1: "Wild Card", 2: "Divisional Round", 3: "Conference Championship",
                   5: SUPER_BOWL}
_ROUNDS_FROM_2026 = {1: "Wild Card", 2: "Divisional Round", 3: "Conference Championship",
                     4: SUPER_BOWL}
# The pages' names by postseason week. The Pro Bowl is never fetched, so a
# week 4 on file is the Super Bowl (2026 on) and so is a week 5 (to 2025).
ROUND_NAMES = {1: "Wild Card", 2: "Divisional", 3: "Conference", 4: SUPER_BOWL, 5: SUPER_BOWL}
ROUND_SHORT = {1: "WC", 2: "Div", 3: "Conf", 4: "SB", 5: "SB"}
# The game-row numbers that must be numbers. A week with no line anywhere
# (every `spread` None) made an all-None column, which pandas keeps as
# objects, and `-games["spread"]` on the bets card raised on it.
_NUMERIC = ("home_score", "away_score", "book_spread", "book_total")


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


def _week(season: int, week: int, seasontype: int) -> tuple:
    """(the week's game rows, ESPN's calendar for the season) - every
    scoreboard answer carries the calendar, so reading it costs no request."""
    data = _get({"week": week, "dates": season, "seasontype": seasontype, "limit": 100})
    rows = []
    for event in data.get("events", []):
        if not event.get("competitions"):
            continue
        try:
            rows.append(_game_row(event, week, seasontype))
        except (KeyError, IndexError, TypeError):
            continue
    league = (data.get("leagues") or [{}])[0] or {}
    return rows, league.get("calendar")


def _week_rows(season: int, week: int, seasontype: int) -> list:
    return _week(season, week, seasontype)[0]


def postseason_rounds(calendar, season: int) -> dict:
    """{postseason week: round name} from ESPN's calendar (the entry valued
    "3"), the Pro Bowl left out; the known layout for the season when the
    calendar is missing or says nothing."""
    for block in calendar or []:
        if not isinstance(block, dict) or str(block.get("value")) != "3":
            continue
        out = {}
        for entry in block.get("entries") or []:
            label = str((entry or {}).get("label") or "").strip()
            try:
                week = int(entry.get("value"))
            except (TypeError, ValueError):
                continue
            if label and "pro bowl" not in label.lower():
                out[week] = label
        if out:
            return out
    return dict(_ROUNDS_TO_2025 if season <= 2025 else _ROUNDS_FROM_2026)


def fetch_season(season: int, postseason: bool = True) -> pd.DataFrame:
    rows, calendar = [], None
    for week in range(1, REGULAR_WEEKS + 1):
        got, cal = _week(season, week, 2)
        rows.extend(got)
        calendar = calendar or cal
        time.sleep(_PAUSE)
    if postseason:
        for week, label in sorted(postseason_rounds(calendar, season).items()):
            for row in _week_rows(season, week, 3):
                rows.append({**row, "round": label})
            time.sleep(_PAUSE)
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    frame["season"] = season
    frame["round"] = frame["round"].fillna("") if "round" in frame else ""
    for col in _NUMERIC:
        frame[col] = pd.to_numeric(frame[col], errors="coerce").astype(float)
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
    try:
        frame = fetch_season(SEASON)
    except (requests.RequestException, ValueError) as exc:
        # An ESPN outage took the whole NFL section down with it, with
        # yesterday's schedule sitting on disk: the pages are better a few
        # hours stale than missing.
        if not path.exists():
            raise
        print(f"  ! NFL schedule: ESPN failed ({exc}); using the cached copy")
        return pd.read_parquet(path)
    if frame.empty:
        return pd.read_parquet(path) if path.exists() else frame
    GAMES_DIR.mkdir(parents=True, exist_ok=True)
    stable.write_parquet(frame, path)     # unchanged: mtime only, no new git version
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


def called_off(games: pd.DataFrame) -> pd.Series:
    """A game ESPN has closed ("post") without a result to count - cancelled
    like Bills-Bengals in January 2023 (post, completed false, 0-0) or
    postponed off the week. It will never be played as scheduled: left open,
    it held "the current week" on its week forever and the playoff
    simulation played it, so the season never ended."""
    if "state" not in games or games.empty:
        return pd.Series(False, index=games.index)
    return (games["state"] == "post") & ~games.index.isin(played(games).index)


def tbd(g) -> bool:
    """A playoff game before its teams are known: ESPN's -1 and -2."""
    return str(g["home_id"]).startswith("-") or str(g["away_id"]).startswith("-")


def time_known(g) -> bool:
    """ESPN files a game without a kickoff (week 18's, before the league
    sets its slots) at midnight Eastern and says TBD."""
    return str(g.get("detail") or "").strip().upper() != "TBD"


def round_of(g) -> int:
    """A playoff game's round, 1 (Wild Card) to 4 (the Super Bowl), from the
    calendar's name where the row carries it and ESPN's week where not - the
    Super Bowl is week 5 to 2025 and week 4 from 2026, the Pro Bowl's week
    never being on file."""
    label = g.get("round")
    if isinstance(label, str) and label:
        if label == SUPER_BOWL:
            return 4
        for week, name in _ROUNDS_FROM_2026.items():
            if name == label:
                return week
    return min(int(g["week"]), 4)


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
