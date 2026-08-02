"""
Regenerate all migrated site pages.

    python -m src.site.build                 # all seasons + global pages
    python -m src.site.build --seasons 2526  # just these seasons' archived data

Every page is now global - schedule, draft-vs-ADP and the draft report each hold
every season behind on-page season buttons. --seasons only narrows the per-season
data archived for the homepage.

NOTE: the weekly Best Ball / Median pages were retired. src.site.bestball and
src.site.median survive as calculation libraries (compute()) with no HTML
rendering; wiring either back into the site means writing a new page for it.
"""
import argparse

from src.config import LEAGUE_IDS
from src.site import adp, draft, draft_report, homepage, schedule

# Season codes we have data for, newest first.
SEASONS = list(LEAGUE_IDS)


def build_all(seasons=None):
    """Generate per-season pages, then the global pages."""
    seasons = seasons or SEASONS
    for season_str in seasons:
        draft.save_games_missed(season_str)   # injury data for the homepage (draft page retired)

    # Every remaining page carries all seasons at once (season buttons on-page).
    schedule.generate()
    adp.generate()
    draft_report.generate()   # all-time + per-year manager draft report
    homepage.generate()


def _parse_args():
    p = argparse.ArgumentParser(description="Regenerate site pages.")
    p.add_argument("--seasons", nargs="+", help="Season codes to build (default: all).")
    return p.parse_args()


if __name__ == "__main__":
    build_all(_parse_args().seasons)
