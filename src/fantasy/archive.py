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


def save_statistic(season_str: str, stat: str, value):
    """Store `value` under archive[formal_season][stat]."""
    archive = open_archive() if ARCHIVE_PATH.exists() else {}
    key = FORMAL_SEASON[season_str]
    archive.setdefault(key, {})[stat] = value
    _save(archive)
