"""
Regenerate all migrated site pages.

    python -m src.site.build                 # all seasons + global pages
    python -m src.site.build --seasons 2526  # just these seasons

Per-season pages: schedule, draft-vs-ADP. Global pages: draft report, homepage.

NOTE: the weekly pages (src.site.bestball, src.site.median) are intentionally
not wired in - removed from the site for now (not operational). To bring one
back, import it and call its generate() for the current season below (they were
previously gated on util.in_fantasy_season()).
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
        schedule.generate(season_str)
        draft.save_games_missed(season_str)   # injury data for the homepage (draft page retired)
        adp.generate(season_str)

    draft_report.generate()   # all-time + per-year manager draft report
    homepage.generate()


def _parse_args():
    p = argparse.ArgumentParser(description="Regenerate site pages.")
    p.add_argument("--seasons", nargs="+", help="Season codes to build (default: all).")
    return p.parse_args()


if __name__ == "__main__":
    build_all(_parse_args().seasons)
