"""
Single entry point to refresh every dataset the site depends on.

    python -m src.data_manager                     # all datasets, all seasons
    python -m src.data_manager --pages             # + regenerate all site pages (update everything)
    python -m src.data_manager --refresh           # force re-fetch of cached data
    python -m src.data_manager --only players       # just the player registry
    python -m src.data_manager --seasons 2526       # limit to one season

Each dataset is an "update job". Two scopes:
  * global jobs  run once            (e.g. the cross-source player registry)
  * season jobs  run once per season (e.g. injuries, league matchup data)

Add a dataset by writing a function and registering it in GLOBAL_JOBS or
SEASON_JOBS - same extensibility idea as sources/.
"""
import argparse

from src import util
from src.config import DATA_DIR, LEAGUE_IDS
from src.identity.history import build_player_seasons
from src.identity.registry import build_registry
from src.league import injuries, season as season_data

# (four-digit season key used by the league helpers, folder/file season string).
SEASONS = [
    ("2025", "2526"),
    ("2024", "2425"),
    ("2023", "2324"),
]
CURRENT_SEASON_STR = util.year_str()


def _end_week(season_str: str) -> int:
    """Last week to pull: live count for the current season, full 14 for past."""
    if season_str == CURRENT_SEASON_STR:
        return util.get_last_completed_week()
    return 14


# --------------------------------------------------------------------------- #
# Update jobs
# --------------------------------------------------------------------------- #

def update_players(refresh: bool = False, **_):
    """Rebuild the canonical cross-source player registry (season-independent)."""
    build_registry(refresh=refresh)


def update_history(seasons=None, refresh: bool = False, **_):
    """Refresh the year-over-year (gsis_id, season) player table for `seasons`."""
    build_player_seasons(seasons or [], refresh=refresh)


def update_injuries(season4: str, season_str: str, refresh: bool = False, **_):
    """Scrape weekly 'Out' injury reports for a season -> data/injuries/<szn>.json."""
    path = DATA_DIR / "injuries" / f"{season_str}.json"
    if path.exists():
        # Past seasons are immutable once saved - never re-scrape (even with
        # --refresh); the nfl.com scrape is slow/flaky. The current season
        # re-scrapes only when forced.
        if season_str != CURRENT_SEASON_STR:
            print(f"[injuries] {season_str} already saved (completed season), skipping.")
            return
        if not refresh:
            print(f"[injuries] {season_str} already saved, skipping (use --refresh).")
            return
    df = injuries.scrape_all(season4, 1, _end_week(season_str))
    df = df.reset_index(drop=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_json(path)
    print(f"[injuries] {season_str} -> {path}")


def update_season(season4: str, season_str: str, refresh: bool = False, **_):
    """Pull league matchup/record data for a season -> data/season/<szn>.json."""
    path = DATA_DIR / "season" / f"{season_str}.json"
    if path.exists() and season_str != CURRENT_SEASON_STR and not refresh:
        print(f"[season] {season_str} already saved, skipping.")
        return
    df = season_data.get_season(_end_week(season_str), LEAGUE_IDS[season_str])
    df = df.reset_index(drop=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_json(path)
    print(f"[season] {season_str} -> {path}")


GLOBAL_JOBS = {"players": update_players, "history": update_history}
SEASON_JOBS = {"injuries": update_injuries, "season": update_season}
ALL_JOBS = list(GLOBAL_JOBS) + list(SEASON_JOBS)


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

def main(seasons=None, only=None, refresh: bool = False, pages: bool = False):
    jobs = only or ALL_JOBS
    wanted = set(seasons) if seasons else None
    season_pairs = [
        (s4, ss) for (s4, ss) in SEASONS
        if wanted is None or s4 in wanted or ss in wanted
    ]

    season_codes = [s4 for s4, _ in season_pairs]
    for name in jobs:
        if name in GLOBAL_JOBS:
            print(f"== {name} ==")
            GLOBAL_JOBS[name](seasons=season_codes, refresh=refresh)

    for season4, season_str in season_pairs:
        for name in jobs:
            if name in SEASON_JOBS:
                print(f"== {name} [{season_str}] ==")
                SEASON_JOBS[name](season4=season4, season_str=season_str, refresh=refresh)

    # After data is current, optionally regenerate the site pages for these seasons.
    if pages:
        from src.site.build import build_all  # lazy: only imports matplotlib/jinja2 when needed
        print("== pages ==")
        build_all([ss for _, ss in season_pairs])


def _parse_args():
    p = argparse.ArgumentParser(description="Refresh all stored fantasy data.")
    p.add_argument("--seasons", nargs="+",
                   help="Season codes to update (e.g. 2526 2425). Default: all.")
    p.add_argument("--only", nargs="+", choices=ALL_JOBS,
                   help="Run only these jobs. Default: all.")
    p.add_argument("--refresh", action="store_true",
                   help="Force re-fetch of cached source pulls / completed seasons.")
    p.add_argument("--pages", action="store_true",
                   help="After updating data, regenerate the site pages for these seasons.")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    main(seasons=args.seasons, only=args.only, refresh=args.refresh, pages=args.pages)
