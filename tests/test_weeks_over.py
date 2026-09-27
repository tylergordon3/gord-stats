"""A fantasy week is over when Sleeper's clock has moved past it, not when
every team has points - which is true from Sunday lunchtime. The power page
locked in week 2 at 1:21 PM on the Sunday, and the live gate saved the week as
published, so it was never redone once Monday night finished.
"""
import pytest


def _posted(weeks):
    return {w: [{"roster_id": 1, "points": 90.0}, {"roster_id": 2, "points": 80.0}]
            for w in weeks}


def test_a_week_with_points_everywhere_is_not_over_until_sleeper_moves_on():
    from fantasy.league import power

    posted = _posted([1, 2, 3])              # Sunday of week 3: everyone has points
    assert power.scored_weeks(posted, over=2) == 2
    assert power.scored_weeks(posted, over=3) == 3


def test_without_sleepers_clock_the_points_still_decide():
    from fantasy.league import power

    posted = _posted([1, 2, 3])
    posted[3][1]["points"] = 0.0             # one team yet to play
    assert power.scored_weeks(posted, over=None) == 2


@pytest.mark.parametrize("state, year, expected", [
    ({"season": "2026", "display_week": 3, "season_type": "regular"}, 2026, 2),
    ({"season": "2026", "week": 1, "season_type": "regular"}, 2026, 0),
    ({"season": "2026", "display_week": 1, "season_type": "pre"}, 2026, 0),
    ({"season": "2027", "display_week": 1, "season_type": "pre"}, 2026, 99),
    ({"season": "2026", "display_week": 3, "season_type": "regular"}, 2027, 0),
    ({}, 2026, None),
])
def test_weeks_over_follows_sleepers_display_week(monkeypatch, state, year, expected):
    from fantasy.league import matchups

    monkeypatch.setattr(matchups, "nfl_state", lambda: state)
    assert matchups.weeks_over(year) == expected


def test_sleeper_not_answering_is_unknown_not_a_crash(monkeypatch):
    from fantasy.league import matchups

    def down():
        raise ConnectionError("handshake dropped")

    monkeypatch.setattr(matchups, "nfl_state", down)
    assert matchups.weeks_over(2026) is None


def test_the_live_gate_stops_at_the_week_being_played(monkeypatch):
    from fantasy import live
    from fantasy.league import matchups

    monkeypatch.setattr(matchups, "weeks_over", lambda year: 2)
    monkeypatch.setattr(live, "week_scored", lambda week, league_id: True)
    assert live.latest_scored_week(0) == 2
