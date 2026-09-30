"""
Scheduled entry point for the Pi — every section of gordstats.com.

`cbb.main` is a working scratchpad — sections get commented in and out and gated
behind flags like `update_mens = 0`. That's fine at a keyboard and wrong for a
scheduled job, where what ran has to be explicit, reviewable in a log, and
changeable without editing code. This module names each section as a task and
takes the selection from the command line:

    python -m gordstats.daily --tasks wnba,fantasy   # what the Pi runs today
    python -m gordstats.daily --tasks wnba,cbb       # once CBB is automated

Turning the college basketball section on later is two steps: fill in `_cbb()`
with whatever `main.py` does by hand today, then change TASKS in the Pi's
~/secrets/gord-stats.env. The schedule itself doesn't change.

A failing section is recorded and the run continues, so one broken feed can't
stop the rest of the site from publishing.
"""
import argparse
import os
import sys
import traceback
from contextlib import contextmanager
from datetime import datetime

from cbb.render import render_home as rh
from wnba import wnba_remaining


@contextmanager
def _own_argv():
    """Hide this module's flags from the sections it calls.

    Several of these modules are also standalone scripts and end up calling
    `parser.parse_args()` with no argument, which reads sys.argv directly —
    `wnba_remaining.wnba_update()` does exactly that on its last line. Without
    this, `--tasks wnba` reaches their parser and exits the process.
    """
    saved = sys.argv
    sys.argv = [saved[0]]
    try:
        yield
    finally:
        sys.argv = saved


def _wnba() -> None:
    """Refresh the WNBA remaining-schedule and fantasy data."""
    wnba_remaining.wnba_update()


def _cbb() -> None:
    """Scrape the day's college basketball feeds and rebuild the predictions.

    Mirrors what `cbb.main` does by hand: pull the day's data, run the men's
    and women's models, then re-render the conference pages. The homepage is
    rendered once for every task by main(), so it is not repeated here.

    Refuses to run outside the season. The feeds keep serving last season's
    numbers in the off-season, so without this guard turning `cbb` on in
    September would quietly republish March's bracket as if it were current.

    The model imports are deliberately local: scikit-learn and joblib cost a
    few seconds to load and the wnba-only path should not pay for them.
    """
    from datetime import date

    from cbb import daily_data, predictions
    from cbb.render import render_conferences as rc
    from cbb.render.render_home import CBB_SEASON_END, CBB_TIPOFF

    today = date.today()
    if not CBB_TIPOFF <= today <= CBB_SEASON_END:
        print(f"  outside the {CBB_TIPOFF:%b %-d}-{CBB_SEASON_END:%b %-d} season; nothing to do")
        return

    # The live tick's betting lines into the committed record (cbb.lines),
    # before anything below can fail the task.
    from cbb import lines
    print(f"  cbb: {lines.publish()} games' lines on record")

    # daily_data reports rather than raises, so a partial scrape has to be
    # turned into a failure here: predictions built on half the feeds are
    # worse than no update at all. main() records the task as failed and
    # still renders the homepage, so the rest of the site publishes.
    if not daily_data.main():
        raise RuntimeError("one or more college basketball feeds failed to scrape")

    _, mens = predictions.predict(today)
    _, womens = predictions.predict_womens(today)

    rc.main(mens, "M")
    rc.main(womens, "W")

    # Each day writes a new predict_<date>.html. Fold every one into the JSON
    # archive the history pages read, and keep only the newest as a page —
    # the tool did this by hand at season end, which left the dailies piling up.
    from cbb.tools import archive_predictions
    archive_predictions.archive()


def _cbb_power() -> None:
    """Rebuild the CBB power rankings page (docs/cbb/power/).

    Its own task rather than part of _cbb: that one refuses to run outside
    the basketball season, and this page is most alive before it - Torvik's
    preseason projections move all autumn as rosters settle.

    The watch guide (docs/cbb/watch/) rides along: its games come from the
    live scoreboard in the browser, so the page only has to exist, all year -
    out of season it says when the next game is.
    """
    from cbb.render import render_power, render_watch

    render_power.trank(refresh=True)
    render_power.generate()
    render_watch.generate()


def _fantasy() -> None:
    """Refresh the fantasy football data and rebuild its pages.

    Reuses the same plan `python -m fantasy.rebuild` runs interactively, so
    there is one description of what a rebuild does rather than a scheduled
    copy that drifts from the manual one. FANTASY_PRESET overrides it from
    the secrets file. "pages" rebuilds from cached ADP; "predraft" refreshes
    the live ADP board first, which matters until the draft - set it in the
    secrets file next summer (the board itself is switched on in
    fantasy.site.homepage.LIVE_ADP_BOARD).
    """
    from fantasy import rebuild

    preset = os.environ.get("FANTASY_PRESET", "pages")
    if rebuild.run(rebuild.plan_from_preset(preset)):
        raise RuntimeError(f"fantasy rebuild preset '{preset}' had failing steps")


def _cfb() -> None:
    """Refresh the college football data (Yahoo board + ESPN schedule) and
    rebuild the section's pages. Import deferred like the others: the wnba-only
    path should not pay for pandas parquet readers it never uses."""
    from cfb import build

    failed = build.build_all(refresh=True)
    if failed:
        raise RuntimeError(f"cfb pages failed to build: {', '.join(failed)}")


def _nfl() -> None:
    """Refetch this season's NFL results, archive the predictions, rebuild
    the predictions page."""
    from nfl import build

    failed = build.build_all(refresh=True)
    if failed:
        raise RuntimeError(f"nfl pages failed to build: {', '.join(failed)}")


# Exit status for "some sections failed, but the run finished": the homepage
# rendered and every section that worked has written its pages. pi-deploy.sh
# publishes on this status and reports the failure afterwards. Any other
# non-zero exit — an uncaught error in the runner itself, render_home raising —
# means the tree may be half-built, and the deploy stops before Jekyll.
SECTIONS_FAILED = 4

TASKS = {
    "wnba": _wnba,
    "cbb": _cbb,
    "fantasy": _fantasy,
    "cfb": _cfb,
    "nfl": _nfl,
    "cbb_power": _cbb_power,
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Refresh the selected sections and re-render the homepage."
    )
    parser.add_argument(
        "--tasks",
        default="wnba",
        help=f"comma-separated section names ({', '.join(TASKS)}); default: wnba",
    )
    parser.add_argument(
        "--skip-render",
        action="store_true",
        help="refresh data but don't re-render the homepage",
    )
    args = parser.parse_args(argv)

    names = [t.strip() for t in args.tasks.split(",") if t.strip()]
    unknown = [n for n in names if n not in TASKS]
    if unknown:
        parser.error(
            f"unknown task(s): {', '.join(unknown)} — known: {', '.join(TASKS)}"
        )

    failed = []
    for name in names:
        started = datetime.now()
        print(f"--- {name} ---", flush=True)
        try:
            with _own_argv():
                TASKS[name]()
        # SystemExit is caught deliberately: a stray parse_args() inside a
        # section should fail that section, not kill the whole run.
        except (Exception, SystemExit):
            traceback.print_exc()
            failed.append(name)
        else:
            elapsed = (datetime.now() - started).total_seconds()
            print(f"  {name} ok in {elapsed:.1f}s", flush=True)

    # The homepage reads whatever each section last wrote, so render it even
    # when a section failed — one broken section shouldn't stale the whole site.
    if not args.skip_render:
        print("--- render home ---", flush=True)
        rh.render_home()
        rh.render_cbb_home()
        # Last: the profile page reads the stars every other page has just
        # written, so it cannot be built before them.
        try:
            from fantasy.site import profile
            profile.generate()
        except Exception as exc:                        # noqa: BLE001
            print(f"  ! profile page: {exc}", flush=True)

    if failed:
        print(f"FAILED: {', '.join(failed)}", file=sys.stderr)
        return SECTIONS_FAILED
    print(f"{len(names)}/{len(names)} section(s) ok", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
