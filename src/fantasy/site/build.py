"""
Regenerate all migrated site pages.

    python -m fantasy.site.build                 # all seasons + global pages
    python -m fantasy.site.build --seasons 2526  # just these seasons' archived data
    python -m fantasy.site.build --refresh-adp   # force a fresh pull of the live ADP board

Every page is now global - schedule, draft-vs-ADP and the draft report each hold
every season behind on-page season buttons. --seasons only narrows the per-season
data archived for the homepage.

NOTE: the weekly Best Ball / Median pages were retired. fantasy.site.bestball and
fantasy.site.median survive as calculation libraries (compute()) with no HTML
rendering; wiring either back into the site means writing a new page for it.
"""
import argparse

from fantasy.config import LEAGUE_IDS
from fantasy.league import adp_board
from fantasy.site import (
    adp, draft, draft_dna, draft_live, draft_recap, draft_report, homepage, schedule,
    team_adjusted, transactions,
)

# Season codes we have data for, newest first.
SEASONS = list(LEAGUE_IDS)


def build_all(seasons=None, refresh_adp=False):
    """Generate per-season pages, then the global pages."""
    seasons = seasons or SEASONS
    if refresh_adp:
        adp_board.board(refresh=True)         # live ADP for the homepage draft board
    for season_str in seasons:
        draft.save_games_missed(season_str)   # injury data for the homepage (draft page retired)

    # Every remaining page carries all seasons at once (season buttons on-page).
    schedule.generate()
    transactions.generate()
    adp.generate()
    draft_recap.generate()    # per-season draft boards with tier movement
    draft_report.generate()   # all-time + per-year manager draft report
    draft_dna.generate()      # owner draft habits across every draft
    draft_live.generate()     # live board for the draft being held next
    homepage.generate()


def _parse_args():
    p = argparse.ArgumentParser(description="Regenerate site pages.")
    p.add_argument("--seasons", nargs="+", help="Season codes to build (default: all).")
    p.add_argument("--refresh-adp", action="store_true",
                   help="Refetch the live ADP board instead of using the cache.")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    build_all(args.seasons, refresh_adp=args.refresh_adp)
