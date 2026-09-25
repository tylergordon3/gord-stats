"""
The WNBA season is derived, not typed in five places.

`SEASON = 2026` appeared in wnba_fantasy, wnba_defense and wnba_schedule, and
twice more as a bare literal default inside wnba_remaining. Those two were the
dangerous ones: they look a player's average up by a stat id built from the
year (`002026`), and a year with no such id does not raise - it returns 0.0.
Next May every player would have averaged nothing, the page would have
rendered, and nothing would have said so.
"""
from datetime import date

import pytest

from wnba import season


@pytest.mark.parametrize("today,expected", [
    (date(2026, 5, 1), 2026),      # tip-off month: the new season
    (date(2026, 4, 30), 2025),     # the day before: last season is still the latest
    (date(2026, 9, 25), 2026),
    (date(2026, 12, 31), 2026),    # after the final, the year just played
    (date(2027, 1, 15), 2026),     # a new calendar year is not a new season
    (date(2027, 5, 1), 2027),
])
def test_the_season_follows_the_calendar_the_league_plays(today, expected):
    """The league plays inside one calendar year, unlike the NFL's or college
    basketball's - so the year is the season, from May."""
    assert season.current_season(today) == expected


def test_the_opener_is_looked_up_not_guessed():
    """The defence stats are filtered on this date and ESPN is asked for whole
    months, so a start a week early quietly admits the preseason."""
    assert season.season_start(2026) == "2026-05-08"


def test_an_unlisted_season_falls_back_to_a_safe_lower_bound():
    assert season.season_start(2099) == "2099-05-01"


def test_no_module_still_carries_its_own_season():
    """The point of the change: one place to be wrong instead of five."""
    import inspect

    from wnba import wnba_defense, wnba_fantasy, wnba_remaining, wnba_schedule

    for module in (wnba_defense, wnba_fantasy, wnba_schedule, wnba_remaining):
        source = inspect.getsource(module)
        for year in ("2025", "2026", "2027"):
            assert f"= {year}" not in source, (
                f"{module.__name__} hardcodes a season again")


def test_the_modules_agree_with_the_derived_season():
    from wnba import wnba_defense, wnba_fantasy, wnba_schedule

    now = season.current_season()
    assert wnba_defense.SEASON == now
    assert wnba_fantasy.SEASON == now
    assert wnba_schedule.SEASON == now
    assert wnba_defense.SEASON_START == season.season_start(now)


def test_an_average_is_read_for_the_season_in_play():
    """A stat id for a year ESPN has no line for returns zero, silently - which
    is why the year must never be stale."""
    from wnba import wnba_remaining

    now = season.current_season()
    player = {"stats": [{"id": f"00{now}", "appliedAverage": 17.5,
                         "averageStats": {"40": 31.2}}]}
    assert wnba_remaining.get_avg_points(player) == 17.5
    assert wnba_remaining.get_avg_minutes(player) == 31.2
    # And the failure mode itself, so it is on the record.
    stale = {"stats": [{"id": "001999", "appliedAverage": 17.5}]}
    assert wnba_remaining.get_avg_points(stale) == 0.0
