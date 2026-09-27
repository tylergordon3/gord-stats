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


@pytest.mark.parametrize("pred_margin", [14.0, -8.0], ids=["leaned-home", "leaned-away"])
def test_a_game_landing_on_the_spread_is_a_push_whichever_side_we_took(
        tmp_path, monkeypatch, pred_margin):
    """Home -3, home wins by 3. It used to score as a loss when we leaned home
    and a win when we leaned away; a book refunds it either way."""
    _archive([_row("2026-09-04T12:00:00+00:00", margin=pred_margin, market=-3.0)],
             tmp_path, monkeypatch)
    _finals(monkeypatch, margin=3.0)
    frame = results.scored(2026)
    assert np.isnan(frame["beat_the_book"].iloc[0])
    assert results.summary(frame)["ats_games"] == 0


def test_no_archive_is_an_empty_report_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(results, "season_path", lambda season=2026: tmp_path / "none.parquet")
    assert results.scored(2026).empty
    assert results.summary(pd.DataFrame()) == {}


# --- over/under -----------------------------------------------------------
#
# Scored the same way as the spread, and wrong in the same ways if it isn't
# careful: a push is not a loss, a lean too small to be a bet is not a pick,
# and a game with no book total on record cannot be graded at all.

def _ou_row(captured, pred_total=50.0, market_total=45.0, **kw):
    row = _row(captured, **kw)
    row["pred_total"] = pred_total
    row["market_total"] = market_total
    return row


def test_leaning_over_and_the_game_going_over_is_a_win(tmp_path, monkeypatch):
    _archive([_ou_row("2026-09-04T12:00:00+00:00")], tmp_path, monkeypatch)
    _finals(monkeypatch, total=60.0)
    frame = results.scored(2026)
    assert frame["ou_pick"].iloc[0] == "over"
    assert bool(frame["ou_correct"].iloc[0]) is True


def test_leaning_over_and_the_game_going_under_is_a_loss(tmp_path, monkeypatch):
    _archive([_ou_row("2026-09-04T12:00:00+00:00")], tmp_path, monkeypatch)
    _finals(monkeypatch, total=40.0)
    frame = results.scored(2026)
    assert bool(frame["ou_correct"].iloc[0]) is False


def test_a_game_landing_on_the_number_is_a_push_not_a_loss(tmp_path, monkeypatch):
    """A book refunds this bet; scoring it as a loss would understate the model."""
    _archive([_ou_row("2026-09-04T12:00:00+00:00", market_total=45.0)],
             tmp_path, monkeypatch)
    _finals(monkeypatch, total=45.0)
    frame = results.scored(2026)
    assert np.isnan(frame["ou_correct"].iloc[0])
    assert results.summary(frame)["ou_games"] == 0


def test_a_lean_under_three_points_is_not_a_pick(tmp_path, monkeypatch):
    """Same gate as the spread: agreeing with the book is not a bet."""
    _archive([_ou_row("2026-09-04T12:00:00+00:00", pred_total=46.0,
                      market_total=45.0)], tmp_path, monkeypatch)
    _finals(monkeypatch, total=80.0)
    frame = results.scored(2026)
    assert np.isnan(frame["ou_correct"].iloc[0])


def test_a_game_with_no_book_total_cannot_be_graded(tmp_path, monkeypatch):
    """Every game archived before market_total existed looks like this."""
    _archive([_ou_row("2026-09-04T12:00:00+00:00", market_total=np.nan)],
             tmp_path, monkeypatch)
    _finals(monkeypatch, total=60.0)
    frame = results.scored(2026)
    assert np.isnan(frame["ou_correct"].iloc[0])
    stat = results.summary(frame)
    assert stat["ou_games"] == 0
    assert stat["market_total_mae"] is None


def test_an_archive_written_before_market_total_existed_still_loads(tmp_path, monkeypatch):
    """The real archive has no such column; reading it must not raise."""
    row = _row("2026-09-04T12:00:00+00:00")
    assert "market_total" not in row
    _archive([row], tmp_path, monkeypatch)
    _finals(monkeypatch)
    frame = results.scored(2026)
    assert len(frame) == 1
    assert np.isnan(frame["market_total"].iloc[0])


def test_the_book_total_error_is_measured_on_priced_games_only(tmp_path, monkeypatch):
    _archive([_ou_row("2026-09-04T12:00:00+00:00", market_total=48.0)],
             tmp_path, monkeypatch)
    _finals(monkeypatch, total=52.0)
    stat = results.summary(results.scored(2026))
    assert stat["market_total_mae"] == pytest.approx(4.0)
    assert stat["totals_priced"] == 1


def test_the_plain_over_under_record_counts_every_priced_game(tmp_path, monkeypatch):
    """The headline figure has no threshold.

    A one-tenth-of-a-point lean is still a lean, and dropping the games where
    we barely disagreed would quietly flatter the number at the top of the
    page. The three-point gate belongs to `ou_correct`, which is a claim about
    bets worth placing, not about being right.
    """
    _archive([_ou_row("2026-09-04T12:00:00+00:00", pred_total=45.5,
                      market_total=45.0)], tmp_path, monkeypatch)
    _finals(monkeypatch, total=60.0)
    frame = results.scored(2026)
    assert bool(frame["ou_called"].iloc[0]) is True     # counted
    assert np.isnan(frame["ou_correct"].iloc[0])        # too small to be a bet
    stat = results.summary(frame)
    assert (stat["ou_all_games"], stat["ou_all_wins"]) == (1, 1)
    assert stat["ou_games"] == 0


def test_a_push_is_out_of_the_plain_record_too(tmp_path, monkeypatch):
    _archive([_ou_row("2026-09-04T12:00:00+00:00", market_total=45.0)],
             tmp_path, monkeypatch)
    _finals(monkeypatch, total=45.0)
    stat = results.summary(results.scored(2026))
    assert stat["ou_all_games"] == 0


def test_calling_under_and_getting_it_right_counts(tmp_path, monkeypatch):
    """Both directions score; the record is not "did we say over"."""
    _archive([_ou_row("2026-09-04T12:00:00+00:00", pred_total=40.0,
                      market_total=45.0)], tmp_path, monkeypatch)
    _finals(monkeypatch, total=30.0)
    frame = results.scored(2026)
    assert frame["ou_pick"].iloc[0] == "under"
    assert bool(frame["ou_called"].iloc[0]) is True


def test_the_game_log_can_be_added_up_to_the_headline():
    """The log is the working behind the records at the top.

    The top of the page is our recommendations against the book - winner,
    our own spread, and the spread and total against the book gated at three
    points - so the per-game columns, the week chips and the headline all read
    the same gated calls. A dash in a gated column is a game with no bet, not a
    wrong one. The band itself moved to gordstats.scorecard, which renders it
    for the NFL page too.
    """
    from conftest import ROOT
    src = (ROOT / "src" / "cfb" / "site" / "predictions.py").read_text()
    rows = src.split("def _result_rows")[1].split("\ndef ")[0]
    assert '_mark(g["beat_the_book"])' in rows
    assert '_mark(g["ou_correct"])' in rows
    assert '_mark(g["ou_called"])' not in rows

    block = src.split("def _week_block")[1].split("\ndef ")[0]
    assert "stat['ou_wins']" in block and "stat['ats_wins']" in block
    assert "ou_all_games" not in block

    band = (ROOT / "src" / "gordstats" / "scorecard.py").read_text()
    band = band.split("def band")[1]
    assert 'stat["ou_wins"]' in band and 'stat["ats_wins"]' in band
    assert "ou_all" not in band


def test_both_over_under_records_keep_a_place_on_the_page():
    """The gated record (bets worth placing) leads the page beside the winners
    and the spread; the ungated one (every lean) answers a different question
    and should not simply disappear - it lives in the analysis tiles."""
    from conftest import ROOT
    src = (ROOT / "src" / "cfb" / "site" / "predictions.py").read_text()
    band = (ROOT / "src" / "gordstats" / "scorecard.py").read_text().split("def band")[1]
    assert 'stat["ou_wins"], stat["ou_games"]' in band
    assert 'stat["ats_wins"], stat["ats_games"]' in band
    section = src.split("def _results_section")[1].split("\ndef ")[0]
    assert 'stat["ou_all_wins"], stat["ou_all_games"]' in section
    # ...and below the log, not above it.
    assert section.index("+ blocks") < section.index("+ tile_html")


def test_the_books_favourite_is_scored_on_the_same_games(tmp_path, monkeypatch):
    """The winners cell compares us with the book's favourite: a pick'em names
    nobody and stays out of the book's record."""
    rows = [_ou_row("2026-09-04T12:00:00+00:00", pred_total=50.0, market_total=45.0)]
    rows[0] = {**rows[0], "pred_margin": 7.0, "market_spread": -3.0}      # home favoured, we agree
    _archive(rows, tmp_path, monkeypatch)
    _finals(monkeypatch, total=60.0)
    frame = results.scored(2026)
    if "actual_margin" in frame and frame["actual_margin"].notna().all():
        stat = results.summary(frame)
        assert stat["book_games"] == 1
        assert stat["book_correct"] == int((frame["actual_margin"] > 0).iloc[0])
        assert stat["correct_on_book_games"] == stat["correct"]


def test_agreeing_with_the_book_is_not_a_call(tmp_path, monkeypatch):
    """The schedule page shows no recommendation inside half a point, so the
    record must not score a pick the reader was never offered."""
    _archive([_ou_row("2026-09-04T12:00:00+00:00", pred_total=45.3,
                      market_total=45.0)], tmp_path, monkeypatch)
    _finals(monkeypatch, total=60.0)
    frame = results.scored(2026)
    assert np.isnan(frame["ou_called"].iloc[0])
    assert results.summary(frame)["ou_all_games"] == 0


def test_a_game_the_model_never_priced_is_not_a_loss(tmp_path, monkeypatch):
    """NaN compares false, so without an explicit guard this scored as wrong."""
    _archive([_ou_row("2026-09-04T12:00:00+00:00", pred_total=float("nan"),
                      market_total=45.0)], tmp_path, monkeypatch)
    _finals(monkeypatch, total=60.0)
    frame = results.scored(2026)
    assert np.isnan(frame["ou_called"].iloc[0])
    assert results.summary(frame)["ou_all_games"] == 0


# --------------------------------------------------------------------------- #
# Our own number, scored as a spread (the calibration figure on the band)
# --------------------------------------------------------------------------- #

def test_our_own_spread_is_covered_when_the_side_we_picked_beats_our_number(
        tmp_path, monkeypatch):
    """We gave the home side 7; they won by 10, so they beat our number."""
    _archive([_row("2026-09-04T12:00:00+00:00", margin=7.0)], tmp_path, monkeypatch)
    _finals(monkeypatch, margin=10.0)
    frame = results.scored(2026)
    assert bool(frame["our_cover"].iloc[0]) is True
    # We were 3 points short on the side we picked, so the lean is negative:
    # we gave the favourite too few.
    assert frame["fav_margin_error"].iloc[0] == pytest.approx(-3.0)


def test_winning_by_less_than_our_number_is_not_a_cover(tmp_path, monkeypatch):
    """The winner was right and the spread was not: the two are different
    questions, which is the whole reason the tile exists."""
    _archive([_row("2026-09-04T12:00:00+00:00", margin=7.0)], tmp_path, monkeypatch)
    _finals(monkeypatch, margin=3.0)
    frame = results.scored(2026)
    assert bool(frame["correct"].iloc[0]) is True
    assert bool(frame["our_cover"].iloc[0]) is False
    assert frame["fav_margin_error"].iloc[0] == pytest.approx(4.0)


def test_our_spread_works_the_same_way_for_an_away_favourite(tmp_path, monkeypatch):
    """Margins are home-relative, so the sign convention is the easy thing to
    get backwards: we gave the away side 7 and they won by 10."""
    _archive([_row("2026-09-04T12:00:00+00:00", margin=-7.0)], tmp_path, monkeypatch)
    _finals(monkeypatch, margin=-10.0)
    frame = results.scored(2026)
    assert bool(frame["our_cover"].iloc[0]) is True
    assert frame["fav_margin_error"].iloc[0] == pytest.approx(-3.0)


def test_landing_exactly_on_our_number_is_a_push_not_a_loss(tmp_path, monkeypatch):
    _archive([_row("2026-09-04T12:00:00+00:00", margin=7.0)], tmp_path, monkeypatch)
    _finals(monkeypatch, margin=7.0)
    frame = results.scored(2026)
    assert pd.isna(frame["our_cover"].iloc[0])
    assert results.summary(frame)["cover_games"] == 0


def test_an_unbiased_set_of_predictions_covers_about_half(tmp_path, monkeypatch):
    """The point of the tile's framing: 50% is the target, not a failing grade.
    Four games missed by 3 points each way come out even."""
    rows = [_row("2026-09-04T12:00:00+00:00", margin=7.0, game_id=str(i))
            for i in range(4)]
    _archive(rows, tmp_path, monkeypatch)
    finals = pd.DataFrame([
        {"game_id": "0", "actual_margin": 10.0, "actual_total": 52.0},
        {"game_id": "1", "actual_margin": 4.0, "actual_total": 52.0},
        {"game_id": "2", "actual_margin": 13.0, "actual_total": 52.0},
        {"game_id": "3", "actual_margin": 1.0, "actual_total": 52.0},
    ])
    finals["home_score"] = (finals["actual_total"] + finals["actual_margin"]) / 2
    finals["away_score"] = (finals["actual_total"] - finals["actual_margin"]) / 2
    monkeypatch.setattr(results, "_finals", lambda season=2026: finals)
    got = results.summary(results.scored(2026))
    assert got["cover_games"] == 4 and got["cover_wins"] == 2
    assert got["fav_bias"] == pytest.approx(0.0)
