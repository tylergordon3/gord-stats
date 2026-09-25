"""
Which season it is, and which week - the two questions every season-keyed file
and page starts from.

Sleeper is asked first, because it is the calendar this league actually runs
on and it is keyless. The date arithmetic below is the fallback for a build
that cannot reach it, and it has to be right on its own: a wrong answer here
does not fail loudly, it writes the wrong season's file.

The anchor is the Thursday after Labor Day - the NFL opener - not the first
Thursday of September. In 2026 those are a week apart (3rd vs 10th), which is
exactly the kind of quiet off-by-one this module is for.
"""
import math
from datetime import date, timedelta


def _labor_day(year: int) -> date:
    d = date(year, 9, 1)
    while d.weekday() != 0:                       # Monday
        d += timedelta(days=1)
    return d


def opening_thursday(year: int) -> date:
    """The NFL season opener: the Thursday after Labor Day."""
    return _labor_day(year) + timedelta(days=3)


_state = None


def _sleeper_state() -> dict:
    """Sleeper's NFL calendar, fetched once per process.

    Cached including the failure: a build that cannot reach Sleeper should not
    retry it for every page, and the fallback is good enough to finish on.
    """
    global _state
    if _state is None:
        try:
            from fantasy.league import matchups            # late: avoids a cycle
            got = matchups.nfl_state() or {}
            _state = {"season": int(got["season"]), "week": int(got.get("week") or 0)}
        except Exception:                                  # noqa: BLE001
            _state = {}
    return _state


def current_season_years():
    """Current season as [start_year, end_year].

    The season turns over at kickoff, not at the new calendar year: in January
    2027 this is still the 2026 season. Before the opener it is the season just
    finished, which is what the draft pages want through the summer.
    """
    state = _sleeper_state()
    if state.get("season"):
        return [state["season"], state["season"] + 1]
    today = date.today()
    if today >= opening_thursday(today.year):
        return [today.year, today.year + 1]
    return [today.year - 1, today.year]


def year_str() -> str:
    """Two-part season string, e.g. 2026/2027 -> '2627'."""
    start, end = current_season_years()
    return str(start)[2:] + str(end)[2:]


def get_week() -> int:
    """NFL week (Fri-Thu; next week starts at TNF's conclusion)."""
    state = _sleeper_state()
    if state.get("week"):
        return state["week"]
    first = opening_thursday(current_season_years()[0])
    return max(1, math.ceil((date.today() - first).days / 7))


def get_last_completed_week() -> int:
    """Last completed NFL week."""
    first = opening_thursday(current_season_years()[0])
    approx = (date.today() - first).days / 7
    today = date.today()
    return math.ceil(approx) if 0 < today.weekday() < 4 else math.floor(approx)
