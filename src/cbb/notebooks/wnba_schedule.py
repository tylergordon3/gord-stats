"""
wnba_schedule.py
----------------
Fetches, caches, and queries the WNBA season schedule from BallDontLie.

Usage:
    python wnba_schedule.py               # smart load (fetch if stale)
    python wnba_schedule.py --refresh     # force re-fetch from API

Requires:
    pip install requests python-dotenv

.env file:
    BALL_DONT_LIE_KEY=your_actual_key_here
"""

import argparse
import json
import os
import requests
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from cbb.lib import paths

ET = ZoneInfo("America/New_York")

def today_et() -> str:
    """Current date in Eastern Time as YYYY-MM-DD."""
    return datetime.now(ET).date().isoformat()

# ── Config ────────────────────────────────────────────────────────────────────

load_dotenv()

API_KEY       = os.getenv("BALL_DONT_LIE_KEY")
BASE_URL      = "https://api.balldontlie.io"
HEADERS       = {"Authorization": API_KEY}
SCHEDULE_FILE =  paths.WNBA_DATA / "wnba_schedule_2026.json"
SEASON        = 2026

# ── Team dictionary ───────────────────────────────────────────────────────────

TEAM_DICT = {
    "3":      {"Name": "Wings",     "City": "Dallas",       "Abbreviation": "DAL"},
    "5":      {"Name": "Fever",     "City": "Indiana",      "Abbreviation": "IND"},
    "6":      {"Name": "Sparks",    "City": "Los Angeles",  "Abbreviation": "LA"},
    "8":      {"Name": "Lynx",      "City": "Minnesota",    "Abbreviation": "MIN"},
    "9":      {"Name": "Liberty",   "City": "New York",     "Abbreviation": "NY"},
    "11":     {"Name": "Mercury",   "City": "Phoenix",      "Abbreviation": "PHX"},
    "129689": {"Name": "Valkyries", "City": "Golden State", "Abbreviation": "GS"},
    "131935": {"Name": "Tempo",     "City": "Toronto",      "Abbreviation": "TOR"},
    "132052": {"Name": "Fire",      "City": "Portland",     "Abbreviation": "POR"},
    "14":     {"Name": "Storm",     "City": "Seattle",      "Abbreviation": "SEA"},
    "16":     {"Name": "Mystics",   "City": "Washington",   "Abbreviation": "WSH"},
    "17":     {"Name": "Aces",      "City": "Las Vegas",    "Abbreviation": "LV"},
    "18":     {"Name": "Sun",       "City": "Connecticut",  "Abbreviation": "CON"},
    "19":     {"Name": "Sky",       "City": "Chicago",      "Abbreviation": "CHI"},
    "20":     {"Name": "Dream",     "City": "Atlanta",      "Abbreviation": "ATL"},
}

# Reverse lookup: abbreviation → team info
ABBREV_TO_TEAM = {v["Abbreviation"]: v for v in TEAM_DICT.values()}

# BallDontLie uses slightly different abbreviations for some teams
API_ABBREV_MAP = {
    "NYL": "NY",
    "LVA": "LV",
    "LAS": "LA",
    "GSV": "GS",
    "WAS": "WSH",
    "PDX": "POR",
}

def normalize_abbrev(abbrev: str) -> str:
    """Convert BDL API abbreviation → your TEAM_DICT abbreviation."""
    return API_ABBREV_MAP.get(abbrev, abbrev)

# ── Indexing ──────────────────────────────────────────────────────────────────

def _index_schedule(raw_games: list) -> dict:
    """
    Build nested dict from raw BDL game objects:
        { "YYYY-MM-DD": { "ABBREV": [game, ...] } }
    Each team appears under both home and away keys for easy lookup.
    """
    schedule = defaultdict(lambda: defaultdict(list))

    for g in raw_games:
        home     = normalize_abbrev(g["home_team"]["abbreviation"])
        away     = normalize_abbrev(g["visitor_team"]["abbreviation"])
        utc_time = datetime.fromisoformat(g['date'])
        eastern_time = utc_time.astimezone(ET)
        date_key = eastern_time.strftime("%Y-%m-%d")
        
        entry = {
            "id":         g["id"],
            "home":       home,
            "away":       away,
            "status":     g["status"],
            "home_score": g.get("home_team_score"),
            "away_score": g.get("visitor_team_score"),
            "date":       date_key,
        }

        # Index under both teams
        schedule[date_key][home].append(entry)
        schedule[date_key][away].append(entry)

    # Convert nested defaultdicts to plain dicts for JSON serialisation
    return {d: dict(teams) for d, teams in schedule.items()}

# ── Fetch & Save ──────────────────────────────────────────────────────────────

def fetch_and_save_schedule(season: int = SEASON, path: Path = SCHEDULE_FILE) -> dict:
    """
    Pull the full season schedule from BallDontLie (handles pagination),
    index it, and write to disk as JSON. Returns the indexed schedule.
    """
    raw_games = []
    cursor    = None

    print(f"Fetching {season} WNBA schedule from BallDontLie...")
    while True:
        params = {"seasons[]": season, "per_page": 100}
        if cursor:
            params["cursor"] = cursor

        resp = requests.get(f"{BASE_URL}/wnba/v1/games", headers=HEADERS, params=params)
        resp.raise_for_status()
        data = resp.json()
        raw_games.extend(data["data"])
        print(f"  {len(raw_games)} games fetched...")

        cursor = data.get("meta", {}).get("next_cursor")
        if not cursor:
            break

    schedule = _index_schedule(raw_games)

    payload = {
        "fetched_on":  today_et(),
        "season":      season,
        "total_games": len(raw_games),
        "schedule":    schedule,
    }

    with open(path, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"Saved {len(raw_games)} games → {path}")
    return schedule

# ── Load ──────────────────────────────────────────────────────────────────────

def load_schedule(path: Path = SCHEDULE_FILE) -> dict:
    """Load the indexed schedule from disk."""
    with open(path) as f:
        payload = json.load(f)
    print(f"Loaded schedule (fetched {payload['fetched_on']}, {payload['total_games']} games)")
    return payload["schedule"]

def is_stale(path: Path = SCHEDULE_FILE, max_age_days: int = 1) -> bool:
    """
    Returns True if the cache file is missing or stale.
    Also considers stale if fetched before noon ET today — late-night games
    from the previous evening may still show status=pre until BDL updates.
    """
    if not path.exists():
        return True
    with open(path) as f:
        payload = json.load(f)
    fetched_on = payload["fetched_on"]
    today      = today_et()
    if (date.fromisoformat(today) - date.fromisoformat(fetched_on)).days >= max_age_days:
        return True
    # Fetched today but before noon ET — statuses from last night may be stale
    if fetched_on == today and datetime.now(ET).hour < 12:
        return True
    return False

def get_schedule(season: int = SEASON, max_age_days: int = 1, force: bool = False) -> dict:
    """
    Smart loader: returns cached schedule if fresh, otherwise re-fetches.

    Args:
        season:       WNBA season year (default: 2026)
        max_age_days: Re-fetch if cache is older than this many days (default: 1)
        force:        Force re-fetch even if cache is fresh (default: False)
    """
    if force or is_stale(SCHEDULE_FILE, max_age_days):
        return fetch_and_save_schedule(season)
    return load_schedule()

# ── Accessors ─────────────────────────────────────────────────────────────────

def get_games_on(schedule: dict, date_str: str) -> dict:
    """
    All games on a given date.

    Args:
        date_str: "YYYY-MM-DD"

    Returns:
        { "ABBREV": [game, ...] }
    """
    return dict(schedule.get(date_str, {}))

def get_team_games_on(schedule: dict, date_str: str, abbrev: str) -> list:
    """
    Games for a specific team on a given date.

    Args:
        date_str: "YYYY-MM-DD"
        abbrev:   Team abbreviation from TEAM_DICT (e.g. "NY", "LV", "IND")
    """
    return schedule.get(date_str, {}).get(abbrev, [])

def get_team_schedule(schedule: dict, abbrev: str) -> dict:
    """
    All games for a team across the full season, keyed by date.

    Returns:
        { "YYYY-MM-DD": [game, ...] }
    """
    return {
        d: games[abbrev]
        for d, games in schedule.items()
        if abbrev in games
    }

def get_today_games(schedule: dict) -> dict:
    """Shortcut for get_games_on(schedule, today)."""
    return get_games_on(schedule, today_et())

# ── CLI / demo ────────────────────────────────────────────────────────────────

def _print_game(g: dict) -> None:
    score = (
        f"{g['away_score']} - {g['home_score']}"
        if g["away_score"] is not None
        else "vs"
    )
    print(f"  {g['away']:>3} @ {g['home']:<3}  |  {score:^9}  |  {g['status']}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WNBA schedule utility")
    parser.add_argument("--refresh", action="store_true", help="Force re-fetch from API")
    parser.add_argument("--team",    type=str, help="Show full schedule for a team (e.g. IND)")
    parser.add_argument("--date",    type=str, help="Show all games on a date (YYYY-MM-DD)")
    args = parser.parse_args()

    schedule = get_schedule(force=args.refresh)

    if args.team:
        abbrev = args.team.upper()
        team   = ABBREV_TO_TEAM.get(abbrev, {})
        label  = f"{team.get('City', '')} {team.get('Name', abbrev)}".strip()
        print(f"\n=== {label} — 2026 Schedule ===")
        for d, games in sorted(get_team_schedule(schedule, abbrev).items()):
            for g in games:
                _print_game(g)

    elif args.date:
        print(f"\n=== Games on {args.date} ===")
        for abbrev, games in get_games_on(schedule, args.date).items():
            for g in games:
                _print_game(g)

    else:
        today = today_et()
        print(f"\n=== Today's Games ({today}) ===")
        seen = set()
        for abbrev, games in get_today_games(schedule).items():
            for g in games:
                if g["id"] not in seen and g.get("status") != "post":
                    _print_game(g)
                    seen.add(g["id"])