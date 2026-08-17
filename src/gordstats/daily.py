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


def _fantasy() -> None:
    """Refresh the fantasy football data and rebuild its pages.

    Reuses the same plan `python -m fantasy.rebuild` runs interactively, so
    there is one description of what a rebuild does rather than a scheduled
    copy that drifts from the manual one. FANTASY_PRESET overrides it from
    the secrets file; "predraft" refreshes the live ADP board first, which is
    what matters until the draft.
    """
    from fantasy import rebuild

    preset = os.environ.get("FANTASY_PRESET", "predraft")
    if rebuild.run(rebuild.plan_from_preset(preset)):
        raise RuntimeError(f"fantasy rebuild preset '{preset}' had failing steps")


TASKS = {
    "wnba": _wnba,
    "cbb": _cbb,
    "fantasy": _fantasy,
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

    if failed:
        print(f"FAILED: {', '.join(failed)}", file=sys.stderr)
        return 1
    print(f"{len(names)}/{len(names)} section(s) ok", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
