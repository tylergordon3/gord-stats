"""
Regenerate the fantasy site pages, non-interactively.

    python -m fantasy.site.build                 # every page, cached ADP board
    python -m fantasy.site.build --refresh-adp   # refetch the live ADP board first
    python -m fantasy.site.build --seasons 2526  # narrow the games-missed re-archive

This is `fantasy.rebuild` without the menu. It used to keep its own list of
pages, which drifted: after the draft pages were merged it was still calling
three modules that no longer wrote anything. There is one list now,
rebuild.PAGES, and adding a page there is the whole job.

NOTE: the weekly Best Ball / Median pages were retired. fantasy.site.bestball and
fantasy.site.median survive as calculation libraries (compute()) with no HTML
rendering; wiring either back into the site means writing a new page for it.
"""
import argparse

from fantasy import rebuild


def build_all(seasons=None, refresh_adp: bool = False):
    """Every page, with the ADP board refetched first if asked."""
    plan = rebuild.plan_from_preset("predraft" if refresh_adp else "pages")
    if seasons:
        plan.seasons = list(seasons)
    if rebuild.run(plan):
        raise RuntimeError("one or more pages failed to build")


def _parse_args():
    p = argparse.ArgumentParser(description="Regenerate site pages.")
    p.add_argument("--seasons", nargs="+", help="Season codes to re-archive (default: all).")
    p.add_argument("--refresh-adp", action="store_true",
                   help="Refetch the live ADP board instead of using the cache.")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    build_all(args.seasons, refresh_adp=args.refresh_adp)
