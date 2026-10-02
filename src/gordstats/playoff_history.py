"""
Playoff odds kept build by build (data/<sport>/playoff_history/<season>.json),
for /cfb/playoff/ and /nfl/playoff/: a week's change now, a season's chart
later. The odds cannot be rebuilt after the fact - the simulation is fitted
on the results as they stood - so they are kept as they are printed.

A snapshot is written only when the odds differ from the last one. The pages
are fitted as of the last finished game, so a rebuild without new results
prints the same numbers and adds nothing; a season comes to a few snapshots a
week, each team as [playoff, title] to four places, the long shots left out.

    {"season": 2026, "snapshots": [{"at": "2026-10-04T23:30-04:00",
                                    "odds": {"333": [0.73, 0.11], ...}}, ...]}
"""
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
KEEP_MIN = 0.0005          # a team under this in both figures is not written
WEEK_DAYS = 6              # "a week ago": the newest snapshot at least this old


def _load(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _odds(odds: dict) -> dict:
    return {str(k): [round(float(v[0]), 4), round(float(v[1]), 4)]
            for k, v in odds.items() if max(float(v[0]), float(v[1])) >= KEEP_MIN}


def record(path: Path, season: int, odds: dict, now: datetime = None) -> bool:
    """Add a snapshot of {team id: (playoff, title)} unless it is the last one
    over again. Returns whether anything was written."""
    snap = _odds(odds)
    if not snap:
        return False
    data = _load(path)
    if data.get("season") != season:
        data = {"season": season, "snapshots": []}
    if data["snapshots"] and data["snapshots"][-1].get("odds") == snap:
        return False
    when = (now or datetime.now(ET)).isoformat(timespec="minutes")
    data["snapshots"].append({"at": when, "odds": snap})
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    return True


def baseline(path: Path, season: int, now: datetime = None,
             days: int = WEEK_DAYS) -> tuple:
    """(when, {team id: [playoff, title]}) of the newest snapshot at least
    `days` old, or (None, None) before the season has one."""
    data = _load(path)
    if data.get("season") != season:
        return None, None
    cutoff = (now or datetime.now(ET)) - timedelta(days=days)
    for snap in reversed(data.get("snapshots") or []):
        try:
            at = datetime.fromisoformat(snap["at"])
        except (KeyError, ValueError):
            continue
        if at <= cutoff:
            return at, snap.get("odds") or {}
    return None, None


def change(now: float, base: dict, team_id) -> float:
    """This team's playoff chance minus the baseline's - a team the baseline
    left out (a long shot then) counts from zero."""
    then = (base or {}).get(str(team_id))
    return float(now) - (float(then[0]) if then else 0.0)
