"""
wnba_live.py
------------
Lightweight WNBA live refresher for frequent cron runs.

Checks the ESPN scoreboard; if any WNBA game is in progress (or tips off
within the next 30 minutes) it refetches fantasy data and regenerates the
home-page include. Otherwise it exits immediately so the cron run is nearly
free. The BallDontLie schedule is rate-limited, so it refreshes at most
once an hour during live windows.

Usage:
    python -m wnba.wnba_live            # update only if games are active
    python -m wnba.wnba_live --force    # update regardless

Exit codes:
    0 = updated
    3 = skipped (no active games)
"""

import argparse
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from wnba import wnba_defense, wnba_fantasy, wnba_remaining, wnba_schedule

ET = ZoneInfo("America/New_York")
PREGAME_BUFFER_MIN = 30
SCHEDULE_MAX_AGE_MIN = 60


def games_active(buffer_min: int = PREGAME_BUFFER_MIN) -> bool:
    """True if any WNBA game is live now or tips off within buffer_min."""
    now = datetime.now(ET)
    r = requests.get(
        wnba_defense.SCOREBOARD_URL,
        params={"dates": now.strftime("%Y%m%d")},
        headers=wnba_defense.HEADERS,
        timeout=20,
    )
    r.raise_for_status()

    for e in r.json().get("events", []):
        state = e.get("status", {}).get("type", {}).get("state")
        if state == "in":
            return True
        if state == "pre":
            try:
                tip = datetime.fromisoformat(e["date"].replace("Z", "+00:00")).astimezone(ET)
            except (KeyError, ValueError):
                continue
            if 0 <= (tip - now).total_seconds() <= buffer_min * 60:
                return True
    return False


def maybe_refresh_schedule(max_age_min: int = SCHEDULE_MAX_AGE_MIN) -> None:
    """Refresh the BDL schedule at most hourly (their API is rate-limited)."""
    p = wnba_schedule.SCHEDULE_FILE
    if not p.exists() or (time.time() - p.stat().st_mtime) > max_age_min * 60:
        try:
            wnba_schedule.fetch_and_save_schedule()
        except Exception as e:
            print(f"⚠ Schedule refresh failed, using cached: {e}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Refresh WNBA fantasy page when games are being played."
    )
    parser.add_argument("--force", action="store_true",
                        help="Update even if no games are active")
    args = parser.parse_args(argv)

    if not args.force and not games_active():
        print(f"{datetime.now(ET):%F %T} — no active WNBA games, skipping.")
        return 3

    print(f"{datetime.now(ET):%F %T} — games active, running live update.")
    maybe_refresh_schedule()
    wnba_fantasy.fetch_and_save()
    try:
        wnba_defense.update_cache()
    except Exception as e:
        print(f"⚠ Defense cache update failed: {e}")
    wnba_remaining.main([])
    return 0


if __name__ == "__main__":
    sys.exit(main())
