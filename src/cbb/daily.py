"""
Scheduled entry point for the Pi.

`cbb.main` is a working scratchpad — sections get commented in and out and gated
behind flags like `update_mens = 0`. That's fine at a keyboard and wrong for a
scheduled job, where what ran has to be explicit, reviewable in a log, and
changeable without editing code. This module names each section as a task and
takes the selection from the command line:

    python -m cbb.daily --tasks wnba        # what the Pi runs today
    python -m cbb.daily --tasks wnba,cbb    # once the CBB section is automated

Turning the college basketball section on later is two steps: fill in `_cbb()`
with whatever `main.py` does by hand today, then change CBB_TASKS in the Pi's
~/secrets/cbb-model.env. The schedule itself doesn't change.
"""
import argparse
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
    """Refresh the men's and women's college basketball predictions.

    Not automated yet: the pipeline in `cbb.main` still runs behind manual
    flags, and the model deps (scikit-learn, statsmodels, selenium, the KenPom
    wrapper) aren't installed on the Pi. Failing loudly here keeps a typo in
    --tasks from quietly publishing a half-built site.
    """
    raise NotImplementedError(
        "the CBB section isn't automated yet — see cbb/main.py for the manual "
        "steps, and environment_pi.yml for the extra dependencies it needs"
    )


TASKS = {
    "wnba": _wnba,
    "cbb": _cbb,
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

    if failed:
        print(f"FAILED: {', '.join(failed)}", file=sys.stderr)
        return 1
    print(f"{len(names)}/{len(names)} section(s) ok", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
