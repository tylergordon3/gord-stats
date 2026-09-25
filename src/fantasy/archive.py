"""
Per-season statistics archive (data/historical.json).

A simple keyed JSON store: {formal_season: {stat_name: value}}. Used to persist
computed per-season stats (e.g. the draft page's missing_df) that other pages
aggregate later (e.g. the homepage injury section).
"""
import json

from fantasy.config import DATA_DIR, FORMAL_SEASON

ARCHIVE_PATH = DATA_DIR / "historical.json"


def open_archive() -> dict:
    with open(ARCHIVE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(data: dict):
    with open(ARCHIVE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def has_statistic(season_str: str, *stats: str) -> bool:
    """True when every named statistic is already stored for this season.

    Lets a caller skip recomputing a season that has finished: the inputs to
    these figures - a final draft, final rosters, a played-out schedule - stop
    changing when the season does.
    """
    if not ARCHIVE_PATH.exists():
        return False
    try:
        stored = open_archive().get(FORMAL_SEASON[season_str], {})
    except (json.JSONDecodeError, OSError, KeyError):
        return False
    return all(stored.get(stat) is not None for stat in stats)


def save_statistic(season_str: str, stat: str, value):
    """Store `value` under archive[formal_season][stat]."""
    archive = open_archive() if ARCHIVE_PATH.exists() else {}
    key = FORMAL_SEASON[season_str]
    archive.setdefault(key, {})[stat] = value
    _save(archive)
