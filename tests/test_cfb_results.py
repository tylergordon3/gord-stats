"""
Scoring the predictions the site actually published.

The whole value of this is that it cannot flatter itself, so that is what these
test: a prediction only counts if it was on record before kickoff, and a game
only counts if it was played.
"""
import numpy as np
import pandas as pd
import pytest

from cfb import results


KICK = pd.Timestamp("2026-09-05T19:00Z")


def _archive(rows, tmp_path, monkeypatch):
    frame = pd.DataFrame(rows)
    path = tmp_path / "2026.parquet"
    frame.to_parquet(path, index=False)
    monkeypatch.setattr(results, "season_path", lambda season=2026: path)


def _row(captured, margin=7.0, game_id="1", market=-6.5):
    return {"captured": captured, "season": 2026, "week": 1, "game_id": game_id,
            "kickoff": KICK, "home_id": "10", "away_id": "20",
            "home": "Home", "away": "Away", "neutral": False,
            "pred_margin": margin, "pred_total": 50.0,
            "home_win_prob": 0.7, "market_spread": market}


def _finals(monkeypatch, margin=10.0, total=52.0, game_id="1"):
    monkeypatch.setattr(results, "_finals", lambda season=2026: pd.DataFrame([{
        "game_id": game_id, "actual_margin": margin, "actual_total": total,
        "home_score": (total + margin) / 2, "away_score": (total - margin) / 2}]))


def test_a_prediction_made_before_kickoff_is_scored(tmp_path, monkeypatch):
    _archive([_row("2026-09-04T12:00:00+00:00")], tmp_path, monkeypatch)
    _finals(monkeypatch)
    frame = results.scored(2026)
    assert len(frame) == 1
    assert frame["margin_error"].iloc[0] == pytest.approx(7.0 - 10.0)
    assert bool(frame["correct"].iloc[0]) is True


def test_a_prediction_made_after_kickoff_is_not_a_prediction(tmp_path, monkeypatch):
    """The one bug that would make every number on the page meaningless."""
    _archive([_row("2026-09-05T21:30:00+00:00")], tmp_path, monkeypatch)
    _finals(monkeypatch)
    assert results.scored(2026).empty


def test_the_last_word_before_kickoff_is_the_one_scored(tmp_path, monkeypatch):
    _archive([_row("2026-09-01T12:00:00+00:00", margin=3.0),
              _row("2026-09-05T12:00:00+00:00", margin=9.0),
              _row("2026-09-05T20:00:00+00:00", margin=99.0)],   # mid-game: ignored
             tmp_path, monkeypatch)
    _finals(monkeypatch)
    frame = results.scored(2026)
    assert len(frame) == 1
    assert frame["pred_margin"].iloc[0] == 9.0


def test_a_game_that_was_never_played_is_not_scored(monkeypatch):
    """ESPN files a cancelled game as 'post' with a 0-0 score."""
    schedule = pd.DataFrame([{"game_id": "1", "state": "post", "home_score": 0.0,
                              "away_score": 0.0},
                             {"game_id": "2", "state": "post", "home_score": 31.0,
                              "away_score": 17.0}])
    monkeypatch.setattr(results.espn, "schedule", lambda: schedule)
    finals = results._finals(2026)
    assert list(finals["game_id"]) == ["2"]


def test_picking_the_wrong_winner_is_recorded_as_wrong(tmp_path, monkeypatch):
    _archive([_row("2026-09-04T12:00:00+00:00", margin=7.0)], tmp_path, monkeypatch)
    _finals(monkeypatch, margin=-3.0)
    frame = results.scored(2026)
    assert bool(frame["correct"].iloc[0]) is False


def test_the_book_is_scored_on_the_same_games(tmp_path, monkeypatch):
    _archive([_row("2026-09-04T12:00:00+00:00", margin=7.0, market=-6.5)],
             tmp_path, monkeypatch)
    _finals(monkeypatch, margin=10.0)
    frame = results.scored(2026)
    # market_spread -6.5 means the book expected the home side by 6.5
    assert frame["market_error"].iloc[0] == pytest.approx(6.5 - 10.0)


def test_against_the_spread_only_counts_a_real_disagreement(tmp_path, monkeypatch):
    """Agreeing with the book to within a field goal is not a bet."""
    _archive([_row("2026-09-04T12:00:00+00:00", margin=7.0, market=-6.5)],
             tmp_path, monkeypatch)
    _finals(monkeypatch, margin=10.0)
    assert np.isnan(results.scored(2026)["beat_the_book"].iloc[0])


def test_a_real_disagreement_that_lands_is_a_win(tmp_path, monkeypatch):
    _archive([_row("2026-09-04T12:00:00+00:00", margin=14.0, market=-3.0)],
             tmp_path, monkeypatch)
    _finals(monkeypatch, margin=20.0)           # we liked home more, home covered
    assert bool(results.scored(2026)["beat_the_book"].iloc[0]) is True


def test_no_archive_is_an_empty_report_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(results, "season_path", lambda season=2026: tmp_path / "none.parquet")
    assert results.scored(2026).empty
    assert results.summary(pd.DataFrame()) == {}
