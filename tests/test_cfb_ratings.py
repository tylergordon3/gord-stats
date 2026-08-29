"""
The college football prediction baseline.

The tests that matter here are not "does it run" but the three ways a ratings
model silently lies: training on the future, losing track of who a team is, and
reporting an accuracy that came from data it had already seen.
"""
import numpy as np
import pandas as pd
import pytest

from cfb import backtest, games, ratings


def _synthetic(strengths, hfa=3.0, seasons=(2020,), noise=0.0, seed=0):
    """A season where every team plays every other, home and away, by known ratings."""
    rng = np.random.default_rng(seed)
    rows, teams = [], list(strengths)
    for season in seasons:
        day = pd.Timestamp(f"{season}-09-01", tz="UTC")
        for home in teams:
            for away in teams:
                if home == away:
                    continue
                margin = strengths[home] - strengths[away] + hfa
                if noise:
                    margin += rng.normal(0, noise)
                rows.append({"season": season, "week": 1, "date": day,
                             "home_team": home, "away_team": away,
                             "home": home, "away": away,
                             "margin": margin, "total": 50.0, "neutral": False})
                day += pd.Timedelta(days=1)
    return pd.DataFrame(rows)


def test_it_recovers_ratings_and_home_field_it_was_given():
    """The whole model in one test: known strengths in, same strengths out."""
    truth = {"A": 10.0, "B": 0.0, "C": -10.0}
    frame = _synthetic(truth, hfa=3.0)
    model = ratings.fit(frame, alpha=1e-6, half_life=1e6)

    assert model.hfa == pytest.approx(3.0, abs=0.2)
    spread = model.rating("A") - model.rating("C")
    assert spread == pytest.approx(20.0, abs=0.5)


def test_home_field_is_not_shrunk_by_the_penalty():
    """It is a constant to measure, not a team effect to pull toward zero."""
    frame = _synthetic({"A": 8.0, "B": 0.0, "C": -8.0}, hfa=4.0)
    heavy = ratings.fit(frame, alpha=500.0, half_life=1e6)
    assert heavy.hfa == pytest.approx(4.0, abs=0.3)
    # ...while the ratings themselves are pulled almost flat by that penalty.
    assert abs(heavy.rating("A") - heavy.rating("C")) < 8.0


def test_more_penalty_means_less_spread():
    frame = _synthetic({"A": 10.0, "B": 0.0, "C": -10.0}, noise=6.0)
    light = ratings.fit(frame, alpha=0.1, half_life=1e6)
    heavy = ratings.fit(frame, alpha=50.0, half_life=1e6)
    assert (light.rating("A") - light.rating("C")) > (heavy.rating("A") - heavy.rating("C"))


def test_recent_games_outweigh_old_ones():
    old = _synthetic({"A": 20.0, "B": 0.0}, seasons=(2015,))
    new = _synthetic({"A": -20.0, "B": 0.0}, seasons=(2024,))
    frame = pd.concat([old, new], ignore_index=True)
    model = ratings.fit(frame, alpha=0.01, half_life=180.0,
                        asof=pd.Timestamp("2024-12-01", tz="UTC"))
    assert model.rating("A") < model.rating("B")      # the recent collapse wins


def test_scores_invert_the_margin_and_total_exactly():
    frame = _synthetic({"A": 5.0, "B": -5.0})
    model = ratings.fit(frame, alpha=1.0)
    out = model.predict(frame)
    assert np.allclose(out["pred_home"] - out["pred_away"], out["pred_margin"])
    assert np.allclose(out["pred_home"] + out["pred_away"], out["pred_total"])


def test_neutral_sites_get_no_home_field():
    frame = _synthetic({"A": 0.0, "B": 0.0}, hfa=6.0)
    model = ratings.fit(frame, alpha=1.0)
    site = pd.DataFrame({"home_team": ["A", "A"], "away_team": ["B", "B"],
                         "neutral": [False, True]})
    out = model.predict(site)
    assert out["pred_margin"].iloc[0] - out["pred_margin"].iloc[1] == pytest.approx(model.hfa)


def test_an_unknown_team_rates_as_an_fcs_opponent():
    """A team the model has never seen must not silently rate as average."""
    frame = _synthetic({"A": 10.0, "B": 0.0})
    frame.loc[frame.index[:6], "away_team"] = games.FCS
    model = ratings.fit(frame, alpha=1.0)
    assert model.rating("Nobody State") == model.rating(games.FCS)


def test_the_backtest_never_trains_on_the_game_it_predicts(monkeypatch):
    """The one bug that would make every number on the page a lie."""
    monkeypatch.setattr(backtest, "MIN_TRAIN_GAMES", 1)
    seen = []
    real_fit = ratings.fit

    def spy(train, asof=None, **kw):
        seen.append((train["date"].max(), asof))
        return real_fit(train, asof=asof, **kw)

    frame = _synthetic({"A": 6.0, "B": 0.0, "C": -6.0}, seasons=(2020, 2021))
    frame["week"] = (frame.groupby("season").cumcount() // 2) + 1
    ratings.fit = spy
    try:
        backtest.walk_forward(frame, 2021, 2021)
    finally:
        ratings.fit = real_fit

    assert seen, "the backtest fitted nothing"
    for latest_train, asof in seen:
        assert latest_train < asof


def test_zero_zero_games_are_treated_as_never_played(tmp_path, monkeypatch):
    """ESPN files cancelled games as 0-0 'post'; they are not scoreless ties."""
    frame = pd.DataFrame({
        "season": [2020, 2020], "week": [1, 2],
        "date_utc": ["2020-09-05T16:00Z", "2020-09-12T16:00Z"],
        "home_id": ["1", "1"], "away_id": ["2", "2"],
        "home": ["A", "A"], "away": ["B", "B"],
        "home_score": [0.0, 31.0], "away_score": [0.0, 17.0],
        "state": ["post", "post"], "neutral": [False, False],
    })
    monkeypatch.setattr(games, "season_path", lambda season: tmp_path / f"{season}.parquet")
    frame.to_parquet(tmp_path / "2020.parquet", index=False)

    loaded = games.load(first=2020, last=2020)
    assert len(loaded) == 1
    assert loaded["margin"].iloc[0] == 14.0
