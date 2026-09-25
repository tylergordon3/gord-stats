"""
A game that is over has an answer, not a forecast.

The team dashboard's "As set" and "Best lineup" totals summed projections for
every starter, including the ones who had already played. On 2026-09-25 that
made one roster read 129.8 when it had actually scored 144.5: Bijan Robinson
was projected 20.6, scored 35.3, and the total still said 20.6 — on the number
a reader checks on a Sunday afternoon.
"""
import pytest

from fantasy.site.roster import settled


def test_a_finished_game_counts_what_he_scored():
    states = {"bijan": "post"}
    assert settled(states, {"bijan": 35.3}) == {"bijan": 35.3}


def test_a_game_in_progress_keeps_its_projection():
    """Partial points are not a result. A back with one carry in the first
    quarter is on 0.4, and a projection is a better guess at his finish than
    that is."""
    assert settled({"p": "in"}, {"p": 0.4}) == {}


def test_a_game_not_started_keeps_its_projection():
    assert settled({"p": "pre"}, {"p": 0}) == {}


def test_a_finished_player_with_no_score_is_not_invented():
    """Sleeper can be missing a line for somebody who did not dress. Absent is
    not zero, and it must not silently become one."""
    assert settled({"p": "post"}, {}) == {}


def test_a_genuine_zero_is_kept():
    """Distinct from the case above: he played and scored nothing, which is a
    real result and must not fall back to a projection."""
    assert settled({"p": "post"}, {"p": 0.0}) == {"p": 0.0}


def test_only_the_finished_players_come_back():
    states = {"done": "post", "playing": "in", "later": "pre"}
    pts = {"done": 21.0, "playing": 6.2, "later": 0}
    assert settled(states, pts) == {"done": 21.0}


def test_the_totals_use_it():
    """The helper exists to be used; a total that goes back to raw projections
    is the bug returning."""
    import inspect

    from fantasy.site import roster

    body = inspect.getsource(roster.team_view)
    assert "settled(" in body
    assert "effective.get" in body, "the totals must read the blended map"
