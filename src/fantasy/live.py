"""
Publish the fantasy section the moment something happens, not hours later.

The daily job runs four times a day and rebuilds everything. Two events in
this section deserve a response inside ten minutes instead:

  * the draft finishing - the power rankings exist from that moment, and the
    live board has been showing a complete draft to anyone watching;
  * a week of the season finishing - Monday night's game settles the week's
    records, and Tuesday morning is when people look.

This is the gate for the Pi's ten-minute live tick (deploy/pi-live.sh), next
to the WNBA scoreboard check. It decides whether either has happened since it
last published, rebuilds just the power page if so, and leaves the Jekyll
build and the Cloudflare upload to the tick. Only the power page: the homepage
takes minutes on the Pi and shows nothing that changes at these moments.

What "last published" means lives in .fantasy_live_state.json at the repo
root, beside .last_live_commit - per machine, not per checkout, so it is not
committed.

    python -m fantasy.live              # rebuild if there is a reason to
    python -m fantasy.live --dry-run    # say whether there is, change nothing
    python -m fantasy.live --force      # rebuild regardless

Exit codes:
    0 = rebuilt
    3 = nothing to do
"""
import argparse
import json
import sys
from datetime import datetime

import requests

from fantasy import paths, projections
from fantasy.config import (
    FANTASY_REG_WEEKS, LEAGUE_TZ, UPCOMING_DRAFT_ID, UPCOMING_LEAGUE_ID, UPCOMING_YEAR,
)
from fantasy.league import weekly_points

STATE_PATH = paths.ROOT / ".fantasy_live_state.json"
SLEEPER_API = "https://api.sleeper.app/v1"
_TIMEOUT = 20

# Pages rebuilt when the gate opens, by their rebuild.PAGES slug.
PAGES = ["power"]


def _get(url):
    r = requests.get(url, timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json()


def _load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {}


def _save_state(state: dict):
    STATE_PATH.write_text(json.dumps(state, indent=1), encoding="utf-8")


# --------------------------------------------------------------------------- #
# The two things worth waking up for
# --------------------------------------------------------------------------- #

def draft_complete(draft_id: str = UPCOMING_DRAFT_ID) -> bool:
    """Sleeper's word on whether the draft has finished."""
    return (_get(f"{SLEEPER_API}/draft/{draft_id}") or {}).get("status") == "complete"


def week_scored(week: int, league_id: str = UPCOMING_LEAGUE_ID) -> bool:
    """True once every team has a score for `week` - Sleeper shows Thursday's
    points on a week that is otherwise still to be played."""
    rows = [r for r in (_get(f"{SLEEPER_API}/league/{league_id}/matchups/{week}") or [])
            if r.get("matchup_id") is not None]
    return bool(rows) and all(float(r.get("points") or 0) > 0 for r in rows)


def latest_scored_week(after: int, league_id: str = UPCOMING_LEAGUE_ID) -> int:
    """The highest fully scored regular-season week past `after` (or `after`).

    One request per week checked, and only the weeks beyond the last one
    published, so in-season ticks cost a single call most of the time.
    """
    week = after
    while week < FANTASY_REG_WEEKS and week_scored(week + 1, league_id):
        week += 1
    return week


def nflverse_has(week: int, year: int = UPCOMING_YEAR) -> bool:
    """Whether nflverse has published stats through `week`.

    The power page locks in a week only when both Sleeper and nflverse have it
    (see projections.completed_weeks), so publishing on Sleeper's word alone
    would put out a page that still treats the week as unplayed. Refreshes the
    weekly cache as a side effect, which is what the rebuild reads anyway.
    """
    try:
        weekly_points.build(year, refresh=True)
    except Exception as exc:                      # 404 before kickoff, or offline
        print(f"  nflverse: {exc}")
        return False
    return projections.completed_weeks(year) >= week


def pending(state: dict, draft_id: str = UPCOMING_DRAFT_ID,
            league_id: str = UPCOMING_LEAGUE_ID, year: int = UPCOMING_YEAR) -> dict:
    """{trigger: value} for everything that has happened since the last publish.

    The ids are parameters rather than read from config inside, so a finished
    season can be pointed at it to prove it fires.
    """
    due = {}
    if state.get("draft") != draft_id and draft_complete(draft_id):
        due["draft"] = draft_id
    published = int(state.get("week", 0))
    week = latest_scored_week(published, league_id)
    if week > published and nflverse_has(week, year):
        due["week"] = week
    return due


# --------------------------------------------------------------------------- #
# Rebuild
# --------------------------------------------------------------------------- #

def rebuild_pages():
    from fantasy import rebuild

    plan = rebuild.Plan()
    plan.pages = [page for page in rebuild.PAGES if page[0] in PAGES]
    if rebuild.run(plan):
        raise RuntimeError("fantasy live rebuild had failing steps")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild the fantasy power page when the draft or a week completes.")
    parser.add_argument("--force", action="store_true", help="Rebuild regardless.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what is pending and change nothing.")
    args = parser.parse_args(argv)

    now = datetime.now(LEAGUE_TZ)
    state = _load_state()
    due = pending(state)
    if args.dry_run:
        print(f"{now:%F %T} - pending: {due or 'nothing'} (state: {state or 'none'})")
        return 0 if due else 3
    if not due and not args.force:
        print(f"{now:%F %T} - nothing new in the fantasy section, skipping.")
        return 3

    what = ", ".join(f"{k} {v}" if k == "week" else k for k, v in due.items()) or "forced"
    print(f"{now:%F %T} - {what}: rebuilding {', '.join(PAGES)}.")
    rebuild_pages()
    state.update(due)
    state["published"] = now.isoformat(timespec="seconds")
    _save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
