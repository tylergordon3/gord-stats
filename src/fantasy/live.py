"""
Publish the fantasy section the moment something happens, not hours later.

The daily job runs four times a day and rebuilds everything. One event in
this section deserves a response inside ten minutes instead: a week of the
season finishing - Monday night's game settles the week's records, and
Tuesday morning is when people look. (The draft finishing used to be the
other; that gate and the live draft board it served were retired after the
2026 draft.)

This is the gate for the Pi's ten-minute live tick (deploy/pi-live.sh), next
to the WNBA scoreboard check. It decides whether that has happened since it
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
import time
from datetime import datetime

import requests

from fantasy import paths, projections
from fantasy.config import FANTASY_REG_WEEKS, LEAGUE_TZ, UPCOMING_LEAGUE_ID, UPCOMING_YEAR
from fantasy.league import weekly_points

STATE_PATH = paths.ROOT / ".fantasy_live_state.json"
SLEEPER_API = "https://api.sleeper.app/v1"
_TIMEOUT = 20
_ATTEMPTS = 3

# Pages rebuilt when the gate opens, by their rebuild.PAGES slug and trigger:
# a finished week re-ranks the power page and closes the week on the matchups
# page; a game in progress refreshes only the matchups page (live points).
PAGES = {"week": ["power", "matchups", "roster", "usage"], "live": ["matchups"]}


def _get(url, attempts=_ATTEMPTS):
    """GET, retrying a couple of times before giving up.

    Sleeper hands out the occasional spurious 404 on a URL that answered a
    minute earlier and answers again a minute later, so one bad response is
    not news.
    """
    for attempt in range(1, attempts + 1):
        try:
            r = requests.get(url, timeout=_TIMEOUT)
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            if attempt == attempts:
                raise
            time.sleep(2 * attempt)


def _load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {}


def _save_state(state: dict):
    STATE_PATH.write_text(json.dumps(state, indent=1), encoding="utf-8")


# --------------------------------------------------------------------------- #
# The thing worth waking up for
# --------------------------------------------------------------------------- #

def week_scored(week: int, league_id: str = UPCOMING_LEAGUE_ID) -> bool:
    """True once every team has a score for `week` - Sleeper shows Thursday's
    points on a week that is otherwise still to be played.

    A Sleeper that will not answer is "not yet", not a failure. On 2026-08-26
    a single 404 here took the whole live tick down and mailed an alert, and
    the next tick ten minutes later got a 200 from the same URL. A week that
    really has finished is published by the next tick, or by the daily job.
    """
    try:
        rows = _get(f"{SLEEPER_API}/league/{league_id}/matchups/{week}") or []
    except requests.RequestException as exc:  # Sleeper down, or offline
        print(f"  sleeper: {exc}")
        return False
    rows = [r for r in rows if r.get("matchup_id") is not None]
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


def pending(state: dict, league_id: str = UPCOMING_LEAGUE_ID,
            year: int = UPCOMING_YEAR) -> dict:
    """{trigger: value} for everything that has happened since the last publish.

    The ids are parameters rather than read from config inside, so a finished
    season can be pointed at it to prove it fires.
    """
    due = {}
    published = int(state.get("week", 0))
    week = latest_scored_week(published, league_id)
    if week > published and nflverse_has(week, year):
        due["week"] = week
    if games_live(year):
        due["live"] = datetime.now(LEAGUE_TZ).isoformat(timespec="minutes")
    return due


def games_live(year: int = UPCOMING_YEAR) -> bool:
    """An NFL game in progress or about to kick off: one ESPN scoreboard call.
    Refreshes the current week's matchup archive as a side effect, which is
    what the page rebuild reads. Unreachable means "no"."""
    from fantasy.league import matchups

    try:
        week = matchups.current_week(year)
        games = matchups.espn_games(week, year)
    except Exception as exc:                           # noqa: BLE001
        print(f"  espn: {exc}")
        return False
    if not matchups.active(games):
        return False
    try:
        matchups.week_matchups(week, year, refresh=True)
    except Exception as exc:                           # noqa: BLE001
        print(f"  sleeper matchups: {exc}")
    return True


# --------------------------------------------------------------------------- #
# Rebuild
# --------------------------------------------------------------------------- #

def pages_for(due: dict) -> list[str]:
    wanted = []
    for trigger in due:
        for slug in PAGES.get(trigger, []):
            if slug not in wanted:
                wanted.append(slug)
    return wanted or [slug for slugs in PAGES.values() for slug in slugs]


def rebuild_pages(slugs: list[str]):
    from fantasy import rebuild

    plan = rebuild.Plan()
    plan.pages = [page for page in rebuild.PAGES if page[0] in slugs]
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

    what = ", ".join(f"{k} {v}" for k, v in due.items()) or "forced"
    slugs = pages_for(due)
    print(f"{now:%F %T} - {what}: rebuilding {', '.join(slugs)}.")
    rebuild_pages(slugs)
    # "live" is not a high-water mark: every tick with a game on is due again.
    state.update({k: v for k, v in due.items() if k != "live"})
    state["published"] = now.isoformat(timespec="seconds")
    _save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
