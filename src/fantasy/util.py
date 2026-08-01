"""
Date / NFL-week helpers and small JSON I/O utilities (ported from py/utilities).
"""
import math
from datetime import date, timedelta

import pandas as pd


def current_season_years():
    """Current season as [start_year, end_year] (offseason returns prior season)."""
    today = date.today()
    if today.month > 9:
        return [today.year, today.year + 1]
    return [today.year - 1, today.year]


def year_str() -> str:
    """Two-part season string, e.g. 2025/2026 -> '2526'."""
    start, end = current_season_years()
    return str(start)[2:] + str(end)[2:]


def _first_thursday(sept_year: int) -> date:
    d = date(sept_year, 9, 1)
    while d.weekday() != 3:  # Thursday
        d += timedelta(days=1)
    return d


def get_week() -> int:
    """NFL week (Fri-Thu; next week starts at TNF's conclusion)."""
    first = _first_thursday(current_season_years()[0])
    return math.ceil((date.today() - first).days / 7)


def get_last_completed_week() -> int:
    """Last completed NFL week."""
    first = _first_thursday(current_season_years()[0])
    approx = (date.today() - first).days / 7
    today = date.today()
    return math.ceil(approx) if 0 < today.weekday() < 4 else math.floor(approx)


def in_fantasy_season() -> bool:
    """True during the NFL season window (weeks 1-18); False in the offseason."""
    return 1 <= get_week() <= 18


def load_df_from_json(filename):
    """Load a DataFrame from JSON, or None if missing/invalid."""
    try:
        return pd.read_json(filename)
    except (FileNotFoundError, ValueError):
        return None
