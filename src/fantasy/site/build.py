"""
Regenerate all migrated site pages.

    python -m src.site.build            # every season's pages + homepage
    python -m src.site.build 2526 2425  # just these seasons

Per-season pages: schedule, draft. Current-season sections: best ball, median.
Global page: homepage (all-time).
"""
import sys

from src import util
from src.config import LEAGUE_IDS
from src.site import adp, bestball, draft, draft_report, homepage, median, schedule

# Season codes we have data for, newest first.
SEASONS = list(LEAGUE_IDS)


def build_all(seasons=None):
    """Generate per-season pages, the current-season live sections, then homepage."""
    seasons = seasons or SEASONS
    for season_str in seasons:
        schedule.generate(season_str)
        draft.save_games_missed(season_str)   # injury data for the homepage (draft page retired)
        adp.generate(season_str)

    # Best ball / median live in single (current-season) folders.
    current = util.year_str()
    if current in seasons:
        bestball.generate(current)
        median.generate(current)

    draft_report.generate()   # all-time + per-year manager draft report
    homepage.generate()


if __name__ == "__main__":
    build_all(sys.argv[1:] or None)
