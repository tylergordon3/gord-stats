"""The in-season CFB board: frozen at the draft, blended with the season.

Weekly projections and waivers used to read Yahoo's in-season rank order,
which swung a projection with every week, and league power added the season
on top of a board that already held it. Now one board: the draft-day
projection pulled toward real points (box scores first, Yahoo's archive for
what they cannot name), plus players the draft board never had at Yahoo's
current price.
"""
import pandas as pd
import pytest


def _board(**extra):
    rows = [{"yahoo_id": "1", "player": "A", "school": "X", "proj": 100.0, "floor": 80.0,
             "ceiling": 120.0, "games": 10, "replacement": 40.0, "vorp": 60.0},
            {"yahoo_id": "2", "player": "B", "school": "Y", "proj": 50.0, "floor": 40.0,
             "ceiling": 60.0, "games": 10, "replacement": 40.0, "vorp": 10.0}]
    return pd.DataFrame(rows).assign(**extra)


def test_a_projection_is_pulled_toward_the_season_so_far(monkeypatch):
    from cfb import in_season

    monkeypatch.setattr(in_season, "box_score_season", lambda board, league=None, **k:
                        pd.DataFrame({"points": [100.0], "played": [5.0]}, index=[0]))
    monkeypatch.setattr(in_season, "yahoo_season", lambda *a: pd.DataFrame(columns=["points", "played"]))
    got = in_season.blend(_board(), league={})
    # 10 a game before, 20 a game over five: (10 x 5 + 100) / (5 + 5) = 15 a game.
    assert got.loc[0, "proj"] == pytest.approx(150.0)
    assert got.loc[0, "vorp"] == pytest.approx(110.0)
    assert got.loc[1, "proj"] == pytest.approx(50.0), "no games, no change"


def test_yahoos_archive_covers_what_box_scores_cannot_name(monkeypatch):
    from cfb import in_season

    monkeypatch.setattr(in_season, "box_score_season", lambda board, league=None, **k:
                        pd.DataFrame(columns=["points", "played"]))
    monkeypatch.setattr(in_season, "yahoo_season", lambda *a: pd.DataFrame(
        {"points": [0.0], "played": [5.0]}, index=["2"]))
    got = in_season.blend(_board(), league={})
    assert got.loc[1, "proj"] == pytest.approx(25.0)      # (5 x 5 + 0) / 10 a game
    assert got.loc[1, "played"] == 5.0


def test_a_player_the_draft_board_never_had_joins_at_yahoos_price(monkeypatch):
    from cfb import in_season, projections

    frozen = _board()
    current = pd.concat([_board(), _board().iloc[[0]].assign(
        yahoo_id="9", player="Freshman", proj=180.0)], ignore_index=True)
    monkeypatch.setattr(projections, "value_board",
                        lambda refresh=False, frame=None, frozen=False: (
                            _board() if frozen else current))
    monkeypatch.setattr(in_season, "blend", lambda board, league=None, **k: board.assign(played=1.0))
    got = in_season.board()
    assert list(got["yahoo_id"]) == ["1", "2", "9"]
    late = got.set_index("yahoo_id").loc["9"]
    assert late["proj"] == 180.0 and late["played"] == 0.0, "not blended a second time"
