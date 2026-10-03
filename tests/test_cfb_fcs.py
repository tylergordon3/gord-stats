"""
FCS opponents rated as themselves (cfb.fcs + cfb.ratings' hierarchical fit).

Until 2026-10 every FCS side was one pooled "FCS" team, so Montana State and
Mississippi Valley State were priced alike, and the board's FCS games missed
by 3.2 points a game more than the book. These pin the pieces that fix it:
the division gap is not shrunk away, the FCS teams price their own games
without leaking into the FBS ranking, and nothing trains on the future.
"""
import numpy as np
import pandas as pd
import pytest

from cfb import backtest, fcs, games, predict, ratings


def _league(strengths, conference, *, cross=(), day0="2025-09-01", hfa=3.0,
            season=2025, rounds=2):
    """Every team plays every team in its own division `rounds` times (home
    and away), plus the `cross` pairs once - known strengths, no noise."""
    rows, day = [], pd.Timestamp(day0, tz="UTC")
    teams = list(strengths)

    def play(home, away):
        nonlocal day
        rows.append({"season": season, "week": 1, "date": day,
                     "game_id": str(len(rows) + 1), "home_id": home, "away_id": away,
                     "home_team": home, "away_team": away, "home": home, "away": away,
                     "neutral": False,
                     "margin": strengths[home] - strengths[away] + hfa, "total": 50.0})
        day += pd.Timedelta(hours=6)

    for _ in range(rounds):
        for home in teams:
            for away in teams:
                if home != away and conference[home][:3] == conference[away][:3]:
                    play(home, away)
    for home, away in cross:
        play(home, away)
    return pd.DataFrame(rows)


STRENGTH = {"A": 10.0, "B": 0.0, "C": -10.0, "D": -30.0, "E": -35.0, "F": -40.0}
CONF = {"A": "fbs:1", "B": "fbs:1", "C": "fbs:1", "D": "fcs:9", "E": "fcs:9", "F": "fcs:9"}
DIV = {t: c[:3] for t, c in CONF.items()}


def test_the_division_gap_survives_the_penalty():
    """Pooled toward the whole field, the FCS was dragged up toward the FBS;
    pulled toward its own conference it stays where its games put it."""
    frame = _league(STRENGTH, CONF, cross=[("A", "D"), ("B", "E"), ("C", "F")])
    plain = ratings.fit(frame, alpha=2.0, half_life=1e6)
    levels = ratings.fit(frame, alpha=2.0, half_life=1e6, levels=CONF, divisions=DIV)

    def gap(model):
        fbs = np.mean([model.rating(t) for t in "ABC"])
        fcs_mean = np.mean([model.rating(t) for t in "DEF"])
        return fbs - fcs_mean

    assert gap(levels) == pytest.approx(35.0, abs=1.0)
    assert gap(plain) < gap(levels) - 3.0
    assert levels.hfa == pytest.approx(3.0, abs=0.3)


def test_fcs_teams_price_their_games_but_stay_out_of_the_ranking():
    frame = _league(STRENGTH, CONF, cross=[("A", "D"), ("B", "E"), ("C", "F")])
    model = ratings.fit(frame, alpha=0.01, half_life=1e6, levels=CONF, divisions=DIV)

    # `teams` is what rankings and the playoff simulation enumerate.
    assert set(model.teams) == {"A", "B", "C", games.FCS}
    assert set(model.table()["team"]) == {"A", "B", "C", games.FCS}
    # The average FBS team is zero, and the generic FCS opponent is the
    # FCS teams' average.
    assert np.mean([model.rating(t) for t in "ABC"]) == pytest.approx(0.0, abs=1e-6)
    assert model.rating(games.FCS) == pytest.approx(
        np.mean([model.rating(t) for t in "DEF"]))

    # A schedule names an FCS visitor only as FCS; its ESPN id says which.
    board = pd.DataFrame({"home_team": ["A", "A", "A"],
                          "away_team": [games.FCS, games.FCS, games.FCS],
                          "home_id": ["A", "A", "A"], "away_id": ["D", "F", "Nobody"],
                          "neutral": [True, True, True]})
    margin = model.predict(board)["pred_margin"].to_numpy()
    assert margin[0] == pytest.approx(model.rating("A") - model.rating("D"))
    assert margin[1] == pytest.approx(model.rating("A") - model.rating("F"))
    assert margin[1] > margin[0] + 5
    # An id the model has never seen falls back to the generic opponent.
    assert margin[2] == pytest.approx(model.rating("A") - model.rating(games.FCS))


def test_a_model_fitted_without_divisions_is_unchanged():
    """The NFL and every plain caller: no levels, no hidden teams."""
    frame = _league({"A": 5.0, "B": 0.0, "C": -5.0}, {t: "fbs:1" for t in "ABC"})
    model = ratings.fit(frame, alpha=1.0, half_life=1e6)
    assert model.teams == ["A", "B", "C"]
    assert not model.divisions
    out = model.predict(frame.assign(home_id="zzz", away_id="zzz"))
    assert np.allclose(out["pred_margin"],
                       frame["home_team"].map(model.rating) - frame["away_team"].map(model.rating)
                       + model.hfa)


def _fcs_rows(season=2026):
    """An FCS schedule: D, E, F six times each, one D2 visitor (Z), one
    game against an FBS side (A) that the FBS archive also has."""
    rows, day = [], pd.Timestamp(f"{season}-09-01T03:00", tz="UTC")
    pairs = [("D", "E"), ("E", "F"), ("F", "D")] * 4 + [("D", "Z"), ("A", "E")]
    for i, (home, away) in enumerate(pairs):
        rows.append({"season": season, "week": i + 1, "game_id": f"f{i}",
                     "date_utc": (day + pd.Timedelta(hours=6 * i)).isoformat(),
                     "home_id": home, "away_id": away, "home_score": 30.0, "away_score": 20.0,
                     "home_conf_id": "9" if home in "DEF" else "1",
                     "away_conf_id": "9" if away in "DEF" else "",
                     "neutral": False, "state": "post", "detail": "Final"})
    rows[-1]["game_id"] = "shared"
    return pd.DataFrame(rows)


def test_prepare_keys_teams_by_this_season_and_drops_the_shared_game():
    rows = _fcs_rows()
    own = pd.DataFrame({"date": [pd.Timestamp("2026-09-20", tz="UTC")] * 2,
                        "game_id": ["shared", "fbs1"], "home_id": ["A", "A"],
                        "away_id": ["E", "B"], "home_team": ["A", "A"],
                        "away_team": [games.FCS, "B"], "neutral": [False, False],
                        "margin": [10.0, 3.0], "total": [50.0, 50.0]})
    asof = pd.Timestamp("2026-10-01", tz="UTC")
    fit_on, levels, divisions = fcs.prepare(own, asof, {"A": "1", "B": "1"}, 2026, rows=rows)

    assert fit_on["game_id"].tolist().count("shared") == 1
    assert set(fit_on["home_team"]) | set(fit_on["away_team"]) == {"A", "B", "D", "E", "F",
                                                                   fcs.NON_D1}
    assert divisions["D"] == "fcs" and divisions["A"] == "fbs"
    assert divisions[fcs.NON_D1] == "nond1"
    assert levels["D"] == "fcs:9" and levels["A"] == "fbs:1"
    assert (fit_on["date"] < asof).all()


def test_prepare_says_none_without_an_archive():
    own = pd.DataFrame({"date": [pd.Timestamp("2026-09-20", tz="UTC")], "game_id": ["1"],
                        "home_id": ["A"], "away_id": ["B"], "neutral": [False],
                        "margin": [3.0], "total": [50.0]})
    assert fcs.prepare(own, pd.Timestamp("2026-10-01", tz="UTC"), {"A": "1"}, 2026,
                       rows=pd.DataFrame()) is None


def test_predict_fits_plainly_when_the_archive_is_missing(monkeypatch):
    seen = {}

    def spy(games_, asof=None, **kw):
        seen.update(kw)
        return "model"

    monkeypatch.setattr(predict.fcs, "load", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(predict.ratings_mod, "fit", spy)
    frame = _league({"A": 5.0, "B": 0.0}, {"A": "fbs:1", "B": "fbs:1"})
    schedule = frame.assign(home_conf_id="1", away_conf_id="1")
    assert predict.fit(frame, schedule, pd.Timestamp("2026-01-01", tz="UTC")) == "model"
    assert "divisions" not in seen


def test_the_backtest_with_fcs_games_never_trains_on_the_future(monkeypatch):
    monkeypatch.setattr(backtest, "MIN_TRAIN_GAMES", 1)
    seen = []
    real_fit = ratings.fit

    def spy(train, asof=None, **kw):
        seen.append((train["date"].max(), asof, bool(kw.get("divisions"))))
        return real_fit(train, asof=asof, **kw)

    fbs = _league({"A": 6.0, "B": 0.0, "C": -6.0}, {t: "fbs:1" for t in "ABC"},
                  day0="2026-09-01", season=2026)
    fbs["week"] = (fbs.index // 2) + 1
    fbs["home_conf_id"] = "1"
    fbs["away_conf_id"] = "1"
    monkeypatch.setattr(ratings, "fit", spy)
    backtest.walk_forward(fbs, 2026, 2026, fcs_rows=_fcs_rows())

    assert seen and all(divisions for _, _, divisions in seen)
    for latest_train, asof, _ in seen:
        assert latest_train < asof
