"""The NFL game model: the archive's filters, the backtest's week numbering,
and how a card quotes the book against our favourite."""
import pandas as pd

from nfl import games, results
from nfl.site import predictions as page


def _game(**over):
    base = {"week": 1, "seasontype": 2, "game_id": "1", "date_utc": "2026-09-13T17:00Z",
            "home_id": "1", "away_id": "2", "home": "H", "away": "A", "home_abbr": "H",
            "away_abbr": "A", "home_score": 24.0, "away_score": 17.0, "neutral": False,
            "state": "post", "completed": True, "book_spread": -3.0, "book_total": 44.0,
            "season": 2026}
    return {**base, **over}


def test_played_drops_the_cancelled_zero_zero_and_the_unfinished():
    frame = pd.DataFrame([_game(game_id="ok"),
                          _game(game_id="cancelled", home_score=0.0, away_score=0.0),
                          _game(game_id="live", state="in", completed=False),
                          _game(game_id="shutout", home_score=0.0, away_score=10.0)])
    assert sorted(games.played(frame)["game_id"]) == ["ok", "shutout"]
    derived = games._derive(games.played(frame))
    assert list(derived["margin"]) == [7.0, -10.0]
    assert list(derived["home_team"]) == ["1", "1"]     # the model keys on ESPN's id


def test_playoff_weeks_number_past_the_regular_season():
    from nfl import backtest
    block = pd.DataFrame([_game(week=1, seasontype=3)])
    assert page._week_key(block) == "19" and page._week_label(block) == "Wild Card"
    assert page._week_label(pd.DataFrame([_game(week=5, seasontype=3)])) == "Super Bowl"


def _card_game(margin, book):
    return pd.Series({**_game(book_spread=book), "played": False, "pred_margin": margin,
                      "pred_total": 45.0, "home_win_prob": 0.6 if margin > 0 else 0.4,
                      "home_rating": 1.0, "away_rating": 0.0, "home_record": "1-0",
                      "away_record": "0-1", "place": "Foxborough, MA", "tv": "CBS",
                      "date": pd.Timestamp("2026-09-20 17:00", tz="UTC")})


def test_card_quotes_the_book_in_the_favourites_terms():
    # Home favourite: the book's home line reads as is.
    home = page._card(_card_game(6.0, -2.5), {})
    assert "<b>H -6.0</b> &middot; book -2.5" in home and "lean H" in home
    # Away favourite: ESPN's +3.5 on the home side is the away side's -3.5.
    away = page._card(_card_game(-3.9, 3.5), {})
    assert "<b>A -3.9</b> &middot; book -3.5" in away and "lean" not in away
    # Liking the favourite less than the book does leans the other way.
    less = page._card(_card_game(8.8, -13.5), {})
    assert "lean A" in less


def test_on_record_keeps_only_the_last_pre_kickoff_capture(tmp_path, monkeypatch):
    monkeypatch.setattr(results, "PRED_DIR", tmp_path)
    kick = "2026-09-20T17:00:00+00:00"
    rows = pd.DataFrame([
        {"captured": "2026-09-18T10:00:00+00:00", "game_id": "g", "kickoff": kick, "pred_margin": 1.0},
        {"captured": "2026-09-20T12:00:00+00:00", "game_id": "g", "kickoff": kick, "pred_margin": 2.0},
        {"captured": "2026-09-20T19:00:00+00:00", "game_id": "g", "kickoff": kick, "pred_margin": 9.0}])
    rows.to_parquet(tmp_path / "2026.parquet", index=False)
    got = results.on_record(2026)
    assert len(got) == 1 and got.loc[0, "pred_margin"] == 2.0
