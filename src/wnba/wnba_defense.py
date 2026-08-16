"""
wnba_defense.py
---------------
Builds and caches fantasy points allowed by each WNBA team to opposing
Guards vs Forwards/Centers, using ESPN's public scoreboard/boxscore APIs.

Fantasy points use this league's scoring settings:
    PTS x1, REB x1, AST x1, 3PM x1, STL x2, BLK x2
    (statIds 0/6/3/17 at 1.0 and 2/1 at 2.0 in scoringSettings)

Position groups mirror the league's lineup slots:
    "G"  — boxscore position starting with G
    "FC" — everything else (F, C, F/C)

Usage:
    python wnba_defense.py             # update cache with any new final games
    python wnba_defense.py --rebuild   # re-fetch every game from scratch

Output:
    data/wnba/wnba_defense_2026.json
"""

import argparse
import json
import time
import requests
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from wnba import paths

ET     = ZoneInfo("America/New_York")
DEBUG  = False
SEASON = 2026

SEASON_START = "2026-05-08"
DEFENSE_FILE = paths.WNBA_DATA / "wnba_defense_2026.json"

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard"
SUMMARY_URL    = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/summary"

# Real WNBA teams only — filters out All-Star / exhibition squads (COOP, SPO, ...)
VALID_ABBREVS = {
    "ATL", "CHI", "CON", "DAL", "GS", "IND", "LA", "LV",
    "MIN", "NY", "PHX", "POR", "SEA", "TOR", "WSH",
}

# Note: ESPN's edge rejects partial browser User-Agents (e.g. bare "Mozilla/5.0")
HEADERS = {"Accept": "application/json"}


def position_group(pos_abbrev: str) -> str:
    return "G" if (pos_abbrev or "").upper().startswith("G") else "FC"


def fantasy_points(keys: list[str], stats: list[str]) -> float:
    """Score one boxscore stat line with the league's point values."""
    line = dict(zip(keys, stats))

    def num(field: str) -> float:
        raw = line.get(field, "0")
        if "-" in raw:  # "made-attempted" pairs
            raw = raw.split("-")[0]
        try:
            return float(raw)
        except ValueError:
            return 0.0

    return (
        num("points")
        + num("rebounds")
        + num("assists")
        + num("threePointFieldGoalsMade-threePointFieldGoalsAttempted")
        + 2 * num("steals")
        + 2 * num("blocks")
    )


# ── Fetch ─────────────────────────────────────────────────────────────────────

def fetch_final_events(start: str = SEASON_START, end: str | None = None) -> list[dict]:
    """All completed regular-matchup games between two dates (one request)."""
    end = end or datetime.now(ET).date().isoformat()
    dates = f"{start.replace('-', '')}-{end.replace('-', '')}"

    r = requests.get(
        SCOREBOARD_URL,
        params={"dates": dates, "limit": 500},
        headers=HEADERS,
        timeout=20,
    )
    r.raise_for_status()

    events = []
    for e in r.json().get("events", []):
        if e.get("status", {}).get("type", {}).get("state") != "post":
            continue
        comps = e.get("competitions", [{}])[0].get("competitors", [])
        abbrevs = {c["team"]["abbreviation"] for c in comps}
        if not abbrevs <= VALID_ABBREVS:
            continue
        events.append({"id": e["id"], "date": e["date"][:10]})
    return events


def fetch_game_allowed(event_id: str) -> tuple[dict, dict]:
    """
    One game's box score, twice-digested:
      allowed — fantasy points each team ALLOWED, by position group:
                {"PHX": {"G": 55.0, "FC": 61.0}, "CON": {...}}
      players — every player's fantasy line for the game:
                {"PHX": [[name, "G"|"FC", fpts], ...], "CON": [...]}
    """
    r = requests.get(SUMMARY_URL, params={"event": event_id}, headers=HEADERS, timeout=20)
    r.raise_for_status()

    sides = r.json()["boxscore"]["players"]
    scored = {}   # abbrev -> {"G": pts, "FC": pts} scored BY that team
    players = {}  # abbrev -> [[name, group, fpts], ...]
    for side in sides:
        abbrev = side["team"]["abbreviation"]
        totals = {"G": 0.0, "FC": 0.0}
        lines = []
        block = side["statistics"][0]
        keys = block["keys"]
        for a in block["athletes"]:
            stats = a.get("stats") or []
            if not stats:  # DNP
                continue
            group = position_group(a["athlete"].get("position", {}).get("abbreviation"))
            pts = fantasy_points(keys, stats)
            totals[group] += pts
            lines.append([a["athlete"]["displayName"], group, round(pts, 1)])
        scored[abbrev] = totals
        players[abbrev] = lines

    if len(scored) != 2:
        raise ValueError(f"Event {event_id}: expected 2 teams, got {list(scored)}")

    a, b = scored
    allowed = {a: scored[b], b: scored[a]}  # allowed = opponent's scored
    return allowed, players


# ── Live game clock ───────────────────────────────────────────────────────────

REGULATION_MINUTES = 40  # 4 x 10-minute quarters

def _parse_clock(display_clock: str) -> float:
    """Minutes remaining in the current period from '5:32' / '0.0' formats."""
    raw = (display_clock or "0").strip()
    try:
        if ":" in raw:
            m, s = raw.split(":", 1)
            return int(m) + float(s) / 60
        return float(raw) / 60  # bare seconds
    except ValueError:
        return 0.0


def game_minutes_left(status: dict) -> float:
    """
    Max minutes left in one game from an ESPN scoreboard status object.
    Unstarted → 40, final → 0, live → current clock + remaining periods
    (OT periods count only the clock).
    """
    state = status.get("type", {}).get("state")
    if state == "pre":
        return float(REGULATION_MINUTES)
    if state != "in":
        return 0.0
    period = status.get("period") or 4
    clock = _parse_clock(status.get("displayClock"))
    if period > 4:  # overtime
        return clock
    return clock + (4 - period) * 10


def live_minutes_by_team(date_str: str) -> dict:
    """
    Max minutes each WNBA team has left to play on a date, from the live
    scoreboard: {"PHX": 27.5, "NY": 40.0, ...}. Teams already done (or not
    playing) simply don't appear. Doubleheaders sum.
    """
    r = requests.get(
        SCOREBOARD_URL,
        params={"dates": date_str.replace("-", "")},
        headers=HEADERS,
        timeout=20,
    )
    r.raise_for_status()

    minutes = {}
    for e in r.json().get("events", []):
        left = game_minutes_left(e.get("status", {}))
        for c in e.get("competitions", [{}])[0].get("competitors", []):
            ab = c["team"]["abbreviation"]
            if ab in VALID_ABBREVS:
                minutes[ab] = minutes.get(ab, 0.0) + left
    return minutes


# ── Cache ─────────────────────────────────────────────────────────────────────

def load_cache(path: Path = DEFENSE_FILE) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {"season": SEASON, "updated": None, "games": {}}


def update_cache(rebuild: bool = False, path: Path = DEFENSE_FILE) -> dict:
    """Fetch box scores for any final games not already cached."""
    cache = {"season": SEASON, "updated": None, "games": {}} if rebuild else load_cache(path)
    games = cache["games"]

    events = fetch_final_events()
    # "players" missing means the entry predates per-player lines — refetch it
    new = [e for e in events
           if e["id"] not in games or "players" not in games[e["id"]]]

    if new:
        print(f"Fetching box scores for {len(new)} new game(s)...")
    for e in new:
        try:
            allowed, players = fetch_game_allowed(e["id"])
            games[e["id"]] = {"date": e["date"], "allowed": allowed, "players": players}
        except Exception as err:
            print(f"  ⚠ event {e['id']}: {err}")
        time.sleep(0.15)

    cache["updated"] = datetime.now(ET).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(cache, f, indent=1)

    if DEBUG or new:
        print(f"Defense cache: {len(games)} games total ({len(new)} added)")
    return cache


def player_game_log(cache: dict | None = None) -> dict:
    """
    Per-player fantasy game log from the cached box scores:
      {"Kelsey Plum": [{"date","team","opp","grp","pts"}, ...], ...}
    Names are ESPN display names, which match fantasy fullName.
    """
    cache = cache or load_cache()
    log = {}
    for g in cache["games"].values():
        players = g.get("players")
        if not players or len(players) != 2:
            continue
        a, b = players
        opps = {a: b, b: a}
        for ab, lines in players.items():
            for name, grp, pts in lines:
                log.setdefault(name, []).append({
                    "date": g["date"], "team": ab, "opp": opps[ab],
                    "grp": grp, "pts": pts,
                })
    for entries in log.values():
        entries.sort(key=lambda e: e["date"])
    return log


# ── Factors ───────────────────────────────────────────────────────────────────

def defense_factors(cache: dict | None = None) -> dict:
    """
    Per-team defensive factors vs each position group, normalized so the
    league average is 1.0. Factor > 1 means the team allows more fantasy
    points than average to that group.

    Returns {"PHX": {"G": 1.07, "FC": 0.94}, ...}
    """
    cache = cache or load_cache()
    sums = {}    # abbrev -> {"G": total allowed, "FC": total, "n": games}
    for g in cache["games"].values():
        for abbrev, allowed in g["allowed"].items():
            t = sums.setdefault(abbrev, {"G": 0.0, "FC": 0.0, "n": 0})
            t["G"] += allowed["G"]
            t["FC"] += allowed["FC"]
            t["n"] += 1

    if not sums:
        return {}

    avgs = {
        ab: {"G": t["G"] / t["n"], "FC": t["FC"] / t["n"]}
        for ab, t in sums.items() if t["n"]
    }
    league = {
        grp: sum(a[grp] for a in avgs.values()) / len(avgs)
        for grp in ("G", "FC")
    }

    return {
        ab: {grp: (a[grp] / league[grp] if league[grp] else 1.0) for grp in ("G", "FC")}
        for ab, a in avgs.items()
    }


def get_defense_factors(refresh: bool = False) -> dict:
    """Load factors from cache, building/refreshing it if asked or missing."""
    if refresh or not DEFENSE_FILE.exists():
        return defense_factors(update_cache())
    return defense_factors()


# ── CLI ───────────────────────────────────────────────────────────────────────

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Update fantasy-points-allowed-by-position cache from ESPN box scores."
    )
    parser.add_argument("--rebuild", action="store_true", help="Re-fetch all games")
    args = parser.parse_args(argv)

    cache = update_cache(rebuild=args.rebuild)
    factors = defense_factors(cache)
    print(f"\n{'Team':<6} {'vs G':>6} {'vs F/C':>7}")
    for ab in sorted(factors):
        print(f"{ab:<6} {factors[ab]['G']:>6.2f} {factors[ab]['FC']:>7.2f}")


if __name__ == "__main__":
    main()
