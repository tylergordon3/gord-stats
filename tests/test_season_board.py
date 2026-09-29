"""
The projection board the browser ranks a reader's league from.

The board is the one thing a client-side power ranking cannot compute for
itself, so this file guards the payload's shape (the browser indexes it by
position, not by name) and the two fields that exist only because a reader's
league is not this one.
"""
import json

import pytest

from conftest import DOCS
from fantasy.site import season_board

PATH = DOCS / "fantasy" / "season-board.json"

pytestmark = pytest.mark.skipif(not PATH.exists(),
                                reason="the board has not been generated yet")


@pytest.fixture(scope="module")
def payload() -> dict:
    return json.loads(PATH.read_text(encoding="utf-8"))


def test_every_row_matches_the_declared_fields(payload):
    """The browser reads these by index. A field added in the middle without
    the client knowing would shift every number one place along, which no
    other test on either side would notice."""
    assert payload["fields"] == season_board.FIELDS
    assert payload["pos"] == season_board.POSITIONS
    width = len(payload["fields"])
    assert payload["board"]
    for pid, row in payload["board"].items():
        assert len(row) == width, f"{pid} has {len(row)} of {width} fields"


def test_positions_are_indices_into_the_published_list(payload):
    for pid, row in payload["board"].items():
        assert 0 <= row[0] < len(payload["pos"]), pid


def test_the_numbers_are_in_ranges_a_simulation_can_use(payload):
    """A zero standard deviation or a negative mean is a gamma that cannot be
    drawn, and a availability outside 0-1 is a probability that is not one."""
    fields = {name: i for i, name in enumerate(payload["fields"])}
    for pid, row in payload["board"].items():
        assert row[fields["mu"]] >= 0, pid
        assert row[fields["sd"]] > 0, pid
        assert row[fields["mu_se"]] >= 0, pid
        assert 0 < row[fields["avail"]] <= 1, pid
        assert 0 <= row[fields["bye"]] <= 18, pid
        assert row[fields["rec"]] >= 0, pid
        assert row[fields["out"]] >= 0, pid


def test_a_catch_is_never_worth_more_than_the_points_it_came_with(payload):
    """Standard scoring is `mu - rec`. If a player's catch rate exceeded his
    PPR projection, a standard league would price him below zero - which is
    not a worse player, it is a broken number."""
    fields = {name: i for i, name in enumerate(payload["fields"])}
    for pid, row in payload["board"].items():
        assert row[fields["rec"]] <= row[fields["mu"]] + 1e-6, pid


def test_only_pass_catchers_are_given_a_catch_rate(payload):
    """A kicker in a standard league must score what he scores in PPR."""
    fields = {name: i for i, name in enumerate(payload["fields"])}
    for pid, row in payload["board"].items():
        if payload["pos"][row[0]] in ("K", "DEF", "QB"):
            assert row[fields["rec"]] == 0, pid


def test_the_catch_rate_prefers_a_real_number_to_the_median():
    """The first pass gave every unprojected player his position's median,
    which handed a receiver who catches six a week the league-wide 1.8 - and
    the players Sleeper does not project this week are exactly the hurt ones a
    reader is deciding about."""
    projected = {"1": 4.0}
    past = {"2": 6.0}
    median = {"WR": 1.8}
    assert season_board._catch_rate("1", "WR", 12.0, projected, past, median) == 4.0
    assert season_board._catch_rate("2", "WR", 12.0, projected, past, median) == 6.0
    assert season_board._catch_rate("3", "WR", 12.0, projected, past, median) == 1.8


def test_a_catch_cannot_be_worth_more_than_the_projection_it_sits_in():
    """A fringe receiver projected for a point and a half a week, carrying the
    catch rate of the season he played a real role, would be projected below
    zero in a standard league. `mu` is his ceiling, because a catch scores a
    point before it scores any yards."""
    assert season_board._catch_rate("2", "WR", 1.55, {}, {"2": 6.0}, {}) == 1.55


def test_the_board_is_small_enough_to_fetch_on_a_phone():
    """It is downloaded to read a page, so it competes with the page."""
    assert PATH.stat().st_size < 150_000


def test_a_part_played_week_is_not_absorbed(tmp_path, monkeypatch):
    """A Thursday night game is not a week.

    `projections.completed_weeks` answers with the highest week in the weekly
    file, which mid-week is a week with one game in it. Blending that into
    every player's form marks everyone who has not played yet as having had a
    terrible one - and it showed: the reader's ranking and the built page
    disagreed about two teams until this guard went in.
    """
    import pandas as pd
    from fantasy import projections
    from fantasy.league import weekly_points

    path = tmp_path / "weekly.parquet"
    rows = ([{"week": 1}] * 3700 + [{"week": 2}] * 3700 + [{"week": 3}] * 300)
    pd.DataFrame(rows).to_parquet(path)
    monkeypatch.setattr(weekly_points, "path", lambda year: path)
    monkeypatch.setattr(projections, "completed_weeks", lambda year=None: 3)
    assert season_board.absorbed_weeks(2026) == 2

    # A full week is absorbed.
    pd.DataFrame([{"week": 1}] * 3700 + [{"week": 2}] * 3700
                 + [{"week": 3}] * 3600).to_parquet(path)
    assert season_board.absorbed_weeks(2026) == 3


def test_sleepers_calendar_decides_when_it_answers(tmp_path, monkeypatch):
    """A bye week has four to six fewer teams' rows, which the size test read
    as a week part played; Monday afternoon, every team has rows but Monday
    night's game is still to come. Sleeper's display week knows both."""
    import pandas as pd
    from fantasy import projections
    from fantasy.league import matchups, weekly_points

    path = tmp_path / "weekly.parquet"
    # Week 3 is a bye week: 83% of a full week's rows - "part played" by size.
    pd.DataFrame([{"week": 1}] * 3700 + [{"week": 2}] * 3700
                 + [{"week": 3}] * 3080).to_parquet(path)
    monkeypatch.setattr(weekly_points, "path", lambda year: path)
    monkeypatch.setattr(projections, "completed_weeks", lambda year=None: 3)
    monkeypatch.setattr(matchups, "weeks_over", lambda year=None: 3)
    assert season_board.absorbed_weeks(2026) == 3
    monkeypatch.setattr(matchups, "weeks_over", lambda year=None: 2)
    assert season_board.absorbed_weeks(2026) == 2, "Monday: week 3 is not over"
