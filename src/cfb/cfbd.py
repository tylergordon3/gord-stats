"""
CollegeFootballData, this season: second opinions for the schedule page.

`cfb.lines` uses the same key for the historical betting archive the model is
backtested on. This is the live side: what CFBD says about the games coming
up, cached as JSON under data/cfb/cfbd/ and read by the schedule page from
the cache only, never from the network at render time.

  - lines(week)        every book CFBD carries per game (DraftKings, Bovada,
                       ESPN Bet as they post), with the open, total and
                       moneylines. Keyed on the ESPN event id, which CFBD
                       shares, so it joins without touching a team name.
  - sp_ratings()       Bill Connelly's SP+ per team: overall, offence, defence
                       ratings and ranks (preseason projections until real
                       games replace them).
  - pregame_wp(week)   CFBD's own pregame home win probability per game.
  - records()          each team's record with home/away/conference splits,
                       and - the useful part - CFBD's teamId, which is ESPN's,
                       so SP+ (names only) can be keyed by id.

The free tier allows about a thousand calls a month (`X-CallLimit-Remaining`
comes back on every response), and the site builds several times a day, so
every fetch here is gated on the cache's age: lines every LINES_AGE_HOURS for
the weeks inside WINDOW_DAYS, everything else once a day. A build that cannot
reach CFBD keeps serving the last cache.

    python -m cfb.cfbd              # refresh what is stale, print coverage
    python -m cfb.cfbd --refresh
"""
import json
import os
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests
from dotenv import load_dotenv

from cfb import espn
from cfb.config import DATA_DIR, SEASON
from gordstats import paths

CFBD_DIR = DATA_DIR / "cfbd"
API = "https://api.collegefootballdata.com"
_TIMEOUT = 40

WINDOW_DAYS = 21
LINES_AGE_HOURS = 6
DAILY_AGE_HOURS = 24


def _key() -> str | None:
    load_dotenv(paths.ROOT / ".env")
    return os.getenv("CFBD_KEY")


def _path(name: str):
    return CFBD_DIR / f"{name}_{SEASON}.json"


def _fresh(path, hours: float) -> bool:
    return path.exists() and (time.time() - path.stat().st_mtime) < hours * 3600


def _read(name: str):
    path = _path(name)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _write(name: str, data) -> None:
    CFBD_DIR.mkdir(parents=True, exist_ok=True)
    _path(name).write_text(json.dumps(data), encoding="utf-8")


def _get(path: str, **params):
    key = _key()
    if not key:
        raise RuntimeError("CFBD_KEY is not set; put it in .env")
    r = requests.get(f"{API}/{path}", headers={"Authorization": f"Bearer {key}"},
                     params=params, timeout=_TIMEOUT)
    r.raise_for_status()
    left = r.headers.get("X-CallLimit-Remaining")
    if left is not None and int(left) < 100:
        print(f"  ! CFBD calls left this month: {left}")
    return r.json()


def get(path: str, **params):
    """One CFBD call, uncached - for modules that keep their own archive
    (cfb.usage, cfb.excitement) rather than a refreshed JSON blob."""
    return _get(path.lstrip("/"), **params)


def _cached(name: str, hours: float, fetch, refresh: bool = False):
    """The cached payload, refetched when older than `hours` (or on refresh);
    the old cache survives a failed fetch."""
    if _fresh(_path(name), hours) and not refresh:
        return _read(name)
    try:
        data = fetch()
    except Exception as exc:
        print(f"  ! CFBD {name} fetch failed ({exc}); using the cache")
        return _read(name)
    _write(name, data)
    return data


# ---------------------------------------------------------------------------
# Per-endpoint parsers: the payloads are trimmed to what the page uses so the
# cache stays small and the page never has to know CFBD's field names.

def _parse_lines(payload) -> dict:
    """game id -> [{book, spread, spread_open, total, total_open, ml_home, ml_away}]"""
    out = {}
    for game in payload or []:
        books = []
        for line in game.get("lines") or []:
            if line.get("spread") is None and line.get("overUnder") is None:
                continue
            books.append({
                "book": line.get("provider") or "",
                # CFBD's spread is home-team book convention, like ESPN's.
                "spread": line.get("spread"), "spread_open": line.get("spreadOpen"),
                "total": line.get("overUnder"), "total_open": line.get("overUnderOpen"),
                "ml_home": line.get("homeMoneyline"), "ml_away": line.get("awayMoneyline"),
            })
        if books:
            out[str(game.get("id"))] = books
    return out


def _parse_sp(payload) -> dict:
    """team name -> {rating, rank, off, off_rank, def, def_rank}"""
    out = {}
    for t in payload or []:
        if not t.get("team"):
            continue
        off, dfn = t.get("offense") or {}, t.get("defense") or {}
        out[t["team"]] = {"rating": t.get("rating"), "rank": t.get("ranking"),
                          "off": off.get("rating"), "off_rank": off.get("ranking"),
                          "def": dfn.get("rating"), "def_rank": dfn.get("ranking")}
    return out


def _parse_wp(payload) -> dict:
    """game id -> home win probability"""
    return {str(g["gameId"]): g["homeWinProbability"] for g in payload or []
            if g.get("gameId") is not None and g.get("homeWinProbability") is not None}


def _parse_records(payload) -> dict:
    """ESPN team id -> {team, total, home, away, conf} with 'W-L' strings"""
    def wl(block):
        block = block or {}
        w, l, t = block.get("wins", 0), block.get("losses", 0), block.get("ties", 0)
        return f"{w}-{l}" + (f"-{t}" if t else "")
    out = {}
    for r in payload or []:
        if r.get("teamId") is None:
            continue
        out[str(r["teamId"])] = {"team": r.get("team"), "total": wl(r.get("total")),
                                 "home": wl(r.get("homeGames")), "away": wl(r.get("awayGames")),
                                 "conf": wl(r.get("conferenceGames"))}
    return out


# ---------------------------------------------------------------------------

def _window_weeks() -> list[int]:
    """ESPN week numbers with a game still to play inside the window."""
    schedule = espn.schedule()
    if schedule.empty:
        return []
    now = datetime.now(timezone.utc)
    kick = pd.to_datetime(schedule["date_utc"], utc=True, format="ISO8601")
    ahead = schedule[(kick > now) & (kick <= now + timedelta(days=WINDOW_DAYS))]
    return sorted(int(w) for w in ahead["week"].unique())


def capture(refresh: bool = False) -> dict:
    """Bring every cache up to date; returns {name: number of entries}."""
    counts = {}
    weeks = _window_weeks()

    def pull_lines():
        merged = _read("lines") or {}
        for week in weeks:
            merged.update(_parse_lines(_get("lines", year=SEASON, week=week)))
        return merged

    def pull_wp():
        merged = _read("wp") or {}
        for week in weeks:
            merged.update(_parse_wp(_get("metrics/wp/pregame", year=SEASON, week=week)))
        return merged

    if weeks:
        counts["lines"] = len(_cached("lines", LINES_AGE_HOURS, pull_lines, refresh) or {})
        counts["wp"] = len(_cached("wp", DAILY_AGE_HOURS, pull_wp, refresh) or {})
    counts["sp"] = len(_cached("sp", DAILY_AGE_HOURS,
                               lambda: _parse_sp(_get("ratings/sp", year=SEASON)), refresh) or {})
    counts["records"] = len(_cached("records", DAILY_AGE_HOURS,
                                    lambda: _parse_records(_get("records", year=SEASON)),
                                    refresh) or {})
    return counts


# Readers for the page: cache only.
def lines() -> dict:
    return _read("lines") or {}


def sp_ratings() -> dict:
    return _read("sp") or {}


def pregame_wp() -> dict:
    return _read("wp") or {}


def records() -> dict:
    return _read("records") or {}


def sp_by_id() -> dict:
    """ESPN team id -> SP+ entry, bridged through the records feed's ids."""
    sp = sp_ratings()
    return {tid: sp[r["team"]] for tid, r in records().items() if r.get("team") in sp}


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--refresh", action="store_true")
    args = p.parse_args()
    print(capture(refresh=args.refresh))
