"""
Live-window gate for the Pi's 10-minute tick (deploy/pi-live.sh).

Same contract as wnba.wnba_live: one cheap scoreboard call decides whether
anything is happening. If a CFB game is in progress (or kicks off within 30
minutes), today's events are patched into the season schedule parquet and
the pages that show game state regenerate - the scoreboard, the schedule,
and the homepage game clock. The scoreboard page also polls ESPN from the
browser, so this tick is about keeping the *served* snapshot honest (and the
odds/model context fresh) rather than being the only source of liveness.

Usage:
    python -m cfb.live              # regenerate only if games are active
    python -m cfb.live --force      # regenerate regardless

Exit codes:
    0 = updated
    3 = skipped (no active games)
"""
import argparse
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from cfb import espn
from cfb.config import DATA_DIR, SEASON

ET = ZoneInfo("America/New_York")
PREGAME_BUFFER_MIN = 30


def _events_today() -> dict:
    """Today's FBS events by id - plus yesterday's before 5am ET, because a
    late West Coast kickoff is still in the fourth quarter after midnight."""
    now = datetime.now(ET)
    days = [now] + ([now - timedelta(days=1)] if now.hour < 5 else [])
    events = {}
    for day in days:
        data = espn._get({"groups": espn._FBS, "dates": day.strftime("%Y%m%d"),
                          "limit": 500})
        for ev in data.get("events", []):
            if ev.get("competitions"):
                events[str(ev["id"])] = ev
    return events


def _active(events: dict) -> bool:
    now = datetime.now(ET)
    for ev in events.values():
        state = (ev.get("status", {}).get("type") or {}).get("state")
        if state == "in":
            return True
        if state == "pre":
            try:
                kick = (datetime.fromisoformat(ev["date"].replace("Z", "+00:00"))
                        .astimezone(ET))
            except (KeyError, ValueError):
                continue
            if 0 <= (kick - now).total_seconds() <= PREGAME_BUFFER_MIN * 60:
                return True
    return False


def _patch_schedule(events: dict) -> None:
    """Fold today's states/scores into the season parquet, in place."""
    path = DATA_DIR / f"schedule_{SEASON}.parquet"
    df = pd.read_parquet(path)
    weeks = dict(zip(df["game_id"].astype(str), df["week"]))
    rows = [espn._game_row(ev, int(weeks[eid]))
            for eid, ev in events.items() if eid in weeks]
    if not rows:
        return
    upd = pd.DataFrame(rows)
    df.index = df["game_id"].astype(str)
    upd.index = upd["game_id"].astype(str)
    df.update(upd[["state", "detail", "home_score", "away_score", "tv", "date_utc"]])
    df.reset_index(drop=True).to_parquet(path, index=False)


def main(force: bool = False) -> int:
    events = _events_today()
    if not (force or _active(events)):
        return 3
    _patch_schedule(events)
    from cfb.site import countdown, schedule, scoreboard
    scoreboard.generate()
    schedule.generate()
    countdown.generate()
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Regenerate CFB pages if games are live.")
    ap.add_argument("--force", action="store_true",
                    help="regenerate even with no game in the window")
    sys.exit(main(force=ap.parse_args().force))
