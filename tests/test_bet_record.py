"""
The honest bet record (gordstats.bet_record): what the bets would have paid,
how the numbers taken compare with the closing line, and - on the predictions
pages - whether the early-week line moved toward the model's calls.
"""
import json
import re

import pandas as pd
import pytest

from gordstats import bet_record, scorecard


def test_units_at_minus_110():
    assert bet_record.units(11, 10) == pytest.approx(0.0)       # break-even is 52.4%
    assert bet_record.units(5, 3) == pytest.approx(5 * 100 / 110 - 3)


def test_a_parlay_is_one_bet():
    assert bet_record.parlay_units([True, True, True]) == pytest.approx((210 / 110) ** 3 - 1)
    assert bet_record.parlay_units([True, False, ""]) == -1.0      # a lost leg settles it
    assert bet_record.parlay_units([True, "", True]) is None       # still live
    # A pushed leg drops out: a three-leg parlay becomes a two-leg one.
    assert bet_record.parlay_units([True, None, True]) == pytest.approx((210 / 110) ** 2 - 1)
    assert bet_record.parlay_units([None, None]) == 0.0


def test_closing_line_value_is_from_the_picks_side():
    """Laying 17.5 on a game that closed at 18.5 was a point better than the
    market ended; taking +10 on one that closed +10.5 was half a point worse."""
    fav = {"kind": "spread", "line": -17.5}
    dog = {"kind": "spread", "line": 10.0}
    assert bet_record.clv(fav, -18.5) == 1.0
    assert bet_record.clv(dog, 10.5) == -0.5
    assert bet_record.clv({"kind": "total", "side": "Over", "line": 48.5}, 50.0) == 1.5
    assert bet_record.clv({"kind": "total", "side": "Under", "line": 48.5}, 50.0) == -1.5
    assert bet_record.clv(fav, None) is None


def _row(game, day, hour, pred_margin, spread, pred_total=50.0, total=50.0, kick="2026-09-26T20:00Z"):
    return {"captured": f"2026-09-{day:02d}T{hour:02d}:00:00+00:00", "game_id": game,
            "kickoff": kick, "pred_margin": pred_margin, "market_spread": spread,
            "pred_total": pred_total, "market_total": total}


NOW = pd.Timestamp("2026-09-28", tz="UTC")


def test_the_line_moving_toward_the_call_is_value():
    """We make the home side 10-point winners with the book at -6: the line
    closing at -7.5 moved 1.5 our way. The away side's call, the same move
    against it."""
    archive = pd.DataFrame([
        _row("a", 21, 12, 10.0, -6.0), _row("a", 26, 18, 10.0, -7.5),
        _row("b", 21, 12, -2.0, -6.0), _row("b", 26, 18, -2.0, -7.5),
    ])
    got = bet_record.moves(archive, now=NOW).set_index("game_id")
    spread = got[got["kind"] == "spread"]
    assert spread.loc["a", "clv"] == 1.5 and spread.loc["a", "lean"] == 4.0
    assert spread.loc["b", "clv"] == -1.5
    assert bet_record.summary(spread.reset_index()) == {
        "calls": 2, "moved": 2, "our_way": 1, "against": 1, "avg": 0.0}


def test_the_open_is_the_first_look_not_the_first_call():
    """A game that was no call at the open is out, even if the line later
    wandered 3 points from us: counting from there would pick lines that had
    just moved away, which tend to come back."""
    archive = pd.DataFrame([
        _row("a", 21, 12, 7.0, -6.0),        # 1 point apart: no call
        _row("a", 23, 12, 7.0, -3.0),        # now 4 apart
        _row("a", 26, 18, 7.0, -5.0),        # and back
    ])
    assert bet_record.moves(archive, now=NOW).empty


def test_what_does_not_count():
    archive = pd.DataFrame([
        _row("ok", 21, 12, 10.0, -6.0), _row("ok", 26, 18, 10.0, -7.5),
        # 16 days out is not this week's line; inside the week it was seen once.
        _row("early", 10, 12, 10.0, -6.0), _row("early", 26, 18, 10.0, -7.5),
        _row("once", 26, 18, 10.0, -6.0),
        _row("later", 21, 12, 10.0, -6.0, kick="2026-10-03T20:00Z"),     # not kicked off
        _row("later", 26, 18, 10.0, -7.5, kick="2026-10-03T20:00Z"),
        _row("inplay", 21, 12, 10.0, -6.0), _row("inplay", 27, 1, 10.0, -12.0),  # after kickoff
    ])
    got = bet_record.moves(archive, now=NOW)
    assert list(got["game_id"]) == ["ok"]


def test_totals_move_the_same_way():
    archive = pd.DataFrame([
        _row("a", 21, 12, 0.0, 0.0, pred_total=58.0, total=52.5),
        _row("a", 26, 18, 0.0, 0.0, pred_total=58.0, total=54.0),
    ])
    got = bet_record.moves(archive, now=NOW)
    total = got[got["kind"] == "total"].iloc[0]
    assert total["clv"] == 1.5 and total["open"] == 52.5 and total["close"] == 54.0


def _stat(**kw):
    base = {"games": 30, "correct": 25, "book_games": 30, "book_correct": 26,
            "cover_games": 30, "cover_wins": 15, "fav_bias": 0.0,
            "ats_games": 21, "ats_wins": 11, "ou_games": 5, "ou_wins": 3}
    base.update(kw)
    return base


def test_the_band_prints_units_and_the_closing_line():
    html = scorecard.band(_stat(), clv={"calls": 30, "moved": 24, "our_way": 16,
                                        "against": 8, "avg": 0.42})
    assert html.count("class='rec-cell") == 5
    assert "class='rec-cell rec-wide'><div class='rec-label'>Line moved our way" in html
    assert "67%" in html and "16 of 24 calls" in html
    assert "on average it moved 0.4 pts our way" in html
    assert "6 of 30 calls saw no move" in html
    # 11-10: 10 x 100/110 + ... = 0.0 units; 3-2 on the total.
    assert "+0.0 units at &minus;110" in html
    assert f"+{bet_record.units(3, 2):.1f} units" in html
    # No early-week calls yet (or none recorded): no fifth tile.
    assert scorecard.band(_stat(), clv=None).count("class='rec-cell") == 4


def test_the_bets_card_record_counts_units_and_the_close(tmp_path, monkeypatch):
    """Week 3: the single lost, the parlay lost a leg. Week 4: the single
    won, the parlay hit on two legs with the third pushed."""
    from cfb.site import homecards
    single = lambda g, line, home=True: {"kind": "spread", "game_id": g, "team": g, "opponent": "x",
                                         "home": home, "line": line, "model": 0, "market_margin": 0}
    (tmp_path / "2026_wk03.json").write_text(json.dumps(
        {"week": 3, "single": single("s3", -6.0), "parlay": [single("p1", -3.0), single("p2", 7.0, False)]}))
    (tmp_path / "2026_wk04.json").write_text(json.dumps(
        {"week": 4, "single": single("s4", -17.5), "parlay": [
            single("q1", -10.0), single("q2", -21.0),
            {"kind": "total", "game_id": "q3", "team": "a at b", "opponent": "", "side": "Over",
             "line": 48.5, "model": 55}]}))
    monkeypatch.setattr(homecards, "BETS_DIR", tmp_path)
    monkeypatch.setattr(homecards, "SEASON", 2026)
    finals = {"s3": (3.0, 40.0),     # home by 3, laid 6: lost
              "p1": (7.0, 40.0),     # covered
              "p2": (10.0, 40.0),    # away +7, lost by 10: lost
              "s4": (20.0, 40.0),    # covered
              "q1": (14.0, 40.0), "q2": (28.0, 40.0), "q3": (0.0, 48.5)}   # won, won, push
    closes = {"s3": (-6.0, 40.0), "s4": (-18.5, 40.0), "q1": (-9.5, 40.0), "q2": (-20.5, 40.0)}
    got = homecards._season_record(finals, closes)
    assert "<strong>4-2-1</strong>" in got
    paid = -1 - 1 + 100 / 110 + ((210 / 110) ** 2 - 1)
    assert f"+{paid:.1f} units" in got
    # s4 laid 17.5 against an 18.5 close; q1 laid 10 against 9.5; q2 21 against 20.5.
    assert "<strong>1 better</strong>, <strong>2 worse</strong>, 1 the same" in got


def test_a_started_game_shows_where_the_line_closed():
    from cfb.site import homecards
    pick = {"kind": "spread", "game_id": "1", "team": "South Florida", "opponent": "BGSU",
            "home": False, "line": -17.5, "model": 27.3, "market_margin": 17.5}
    html = homecards._leg_html(pick, {}, {"1": (18.5, 48.5)})    # the home side +18.5
    assert "Closed -18.5" in html and "beat it by 1.0" in html
    assert "Closed" not in homecards._leg_html(pick, {}, {})
    worse = homecards._close_html(dict(pick, line=-19.0), {"1": (18.5, 48.5)})
    assert re.search(r"hc-down'>0.5 worse", worse)
