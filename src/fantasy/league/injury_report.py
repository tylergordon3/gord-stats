"""
ESPN's NFL injury report: who is hurt, and when each is expected back.

Sleeper's tag says Out or IR and nothing about for how long, so the season
simulations used to guess - four weeks for any reserve list, one for an Out -
and a torn ACL and a tight hamstring were the same four weeks. ESPN publishes
the league's whole report in one request, and every player it lists as
anything but active carries an expected return date, kept up to date through
the week (Achane's ACL: back after the season; a fractured fibula: mid
December; a hamstring on IR: the earliest he can come off it).

    https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries

The report is kept trimmed (data/players/injury_report.json, keyed by Sleeper
id through players_index.espn_ids): status, the date he is due back, the body
part, when ESPN last updated it. Refetched after HOURS; a failed fetch keeps
the last copy, since a day-old return date beats none. ESPN's notes are news
copy and are not kept or shown - only the facts are.

    report()                 {sleeper id: {status, back, part, updated}}
    sundays(year)            {NFL week: its Sunday} from the season's schedule
    weeks_out(entry, ...)    the weeks from a given one a player misses
    held_out(...)            {sleeper id: weeks} for the season simulations -
                             ESPN's date where it has one, Sleeper's tag
                             (power.FORCED_OUT) where it does not

    python -m fantasy.league.injury_report      # print who is out, how long
"""
import json
import re
import time
from datetime import date, datetime, timedelta

import requests

from fantasy import paths

URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries"
CACHE = paths.DATA_DIR / "players" / "injury_report.json"
HOURS = 2.0
TIMEOUT = 20

# ESPN's statuses that keep a player off the field until his return date.
# Questionable is a this-week question (fantasy.league.availability's), not a
# held-out week; Doubtful is held out for the week it is about.
HOLDS = {"Out", "Injured Reserve", "Doubtful", "Suspension", "Physically Unable to Perform",
         "PUP", "Non Football Injury", "Commissioner Exempt"}

_ID = re.compile(r"/id/(\d+)")


def _espn_to_sleeper() -> dict:
    from fantasy.site import players_index
    return players_index.espn_ids()


def _trim(payload: dict, ids: dict) -> dict:
    """The report keyed by Sleeper id, facts only."""
    out = {}
    for team in payload.get("injuries") or []:
        for row in team.get("injuries") or []:
            athlete = row.get("athlete") or {}
            espn = next((m.group(1) for link in athlete.get("links") or []
                         if (m := _ID.search(link.get("href") or ""))), None)
            pid = ids.get(espn) if espn else None
            if not pid:
                continue
            details = row.get("details") or {}
            out[pid] = {"status": row.get("status") or "",
                        "back": (details.get("returnDate") or "")[:10] or None,
                        "part": details.get("type") or None,
                        "updated": (row.get("date") or "")[:10] or None}
    return out


def report(refresh: bool = False) -> dict:
    """{sleeper id: {status, back, part, updated}} - the cached copy unless it
    is stale or `refresh`; the last good copy if the fetch fails."""
    fresh = CACHE.exists() and time.time() - CACHE.stat().st_mtime < HOURS * 3600
    if refresh or not fresh:
        try:
            r = requests.get(URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=TIMEOUT)
            r.raise_for_status()
            trimmed = _trim(r.json(), _espn_to_sleeper())
            if trimmed:
                CACHE.parent.mkdir(parents=True, exist_ok=True)
                old = CACHE.read_text(encoding="utf-8") if CACHE.exists() else ""
                text = json.dumps(trimmed, separators=(",", ":"), sort_keys=True)
                if text != old:                     # the Pi commits data/: only on change
                    CACHE.write_text(text, encoding="utf-8")
                else:
                    CACHE.touch()
                return trimmed
        except Exception as exc:                            # noqa: BLE001
            print(f"  ! ESPN injury report unavailable ({exc}); using the last copy")
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def sundays(year: int) -> dict:
    """{week: date} - each regular-season week's main day, the date most of
    its games kick off on (Eastern), from the season's schedule."""
    from zoneinfo import ZoneInfo

    import pandas as pd

    from nfl import games
    et = ZoneInfo("America/New_York")
    frame = games.schedule()
    if frame is None or not len(frame):
        return {}
    frame = frame[(frame["seasontype"] == 2) & (frame["season"] == year)] \
        if "season" in frame else frame[frame["seasontype"] == 2]
    days = pd.to_datetime(frame["date_utc"], utc=True).dt.tz_convert(et).dt.date
    out = {}
    for week, group in days.groupby(frame["week"]):
        out[int(week)] = group.mode().iloc[0]
    return out


def weeks_out(entry: dict, from_week: int, week_days: dict, weeks: int) -> int | None:
    """How many of weeks from_week+1 .. `weeks` (1-based NFL weeks) the player
    misses by ESPN's return date: every week whose main day is before it. A
    held status with a date already past still costs the week at hand (the
    date has not caught up). None when the entry says nothing - no date, or a
    status that holds nobody out."""
    if not entry or entry.get("status") not in HOLDS:
        return None
    back = entry.get("back")
    if not back:
        return None
    try:
        due = date.fromisoformat(back)
    except ValueError:
        return None
    missed = 0
    for week in range(from_week + 1, weeks + 1):
        day = week_days.get(week)
        if day is None:                         # past the schedule: a week after the last
            last = max(week_days) if week_days else None
            day = (week_days[last] + timedelta(days=7 * (week - last))) if last else None
        if day is None or day >= due:
            break
        missed += 1
    return max(missed, 1)


def held_out(sleeper_tags: dict, from_week: int, weeks: int, year: int,
             entries: dict = None, week_days: dict = None) -> dict:
    """{sleeper id: weeks held out} for the season simulations: ESPN's return
    date where the report has one, Sleeper's tag priced by power.FORCED_OUT
    where it does not. `sleeper_tags` is {id: Sleeper designation} (any
    players; the report adds those Sleeper has not tagged yet)."""
    from fantasy.league.power import FORCED_OUT
    entries = report() if entries is None else entries
    if week_days is None:
        try:
            week_days = sundays(year)
        except Exception as exc:                            # noqa: BLE001
            print(f"  ! no NFL schedule for injury return dates ({exc})")
            week_days = {}
    out = {}
    for pid in set(sleeper_tags) | set(entries):
        n = weeks_out(entries.get(pid), from_week, week_days, weeks) if week_days else None
        if n is None:
            n = FORCED_OUT.get(sleeper_tags.get(pid, ""), 0)
        if n:
            out[str(pid)] = int(n)
    return out


if __name__ == "__main__":
    from fantasy.config import UPCOMING_YEAR
    rep = report(refresh=True)
    days = sundays(UPCOMING_YEAR)
    today = datetime.now().date()
    week = max([w for w, d in days.items() if d < today], default=0)
    rows = [(weeks_out(e, week, days, 18), pid, e) for pid, e in rep.items()]
    rows = sorted((r for r in rows if r[0]), key=lambda r: -r[0])
    print(f"{len(rep)} players on ESPN's report; {len(rows)} held out from week {week + 1}")
    for n, pid, e in rows[:25]:
        print(f"  {pid:>6} {e['status']:<16} back {e['back']}  ({e['part']}) -> {n} wk")
