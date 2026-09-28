"""Opponent-adjusted efficiency and the correction it makes to CFB margins.

Walk-forward on 2020-2025 the ratings alone missed margins by 16.18 points
(RMSE) and with the correction 16.07, better in each of the six seasons; see
cfb.efficiency. These pin the machinery that number rests on: the adjustment
sees only games before its date and finds the teams it was given, the
correction's arithmetic, and the fall-back to the ratings when it cannot run.
"""
import numpy as np
import pandas as pd
import pytest

from cfb import efficiency as E


def _obs(strength: dict, days: int = 60, seed: int = 0) -> pd.DataFrame:
    """Round-robin team-games in which each metric is offence + defence
    allowed + noise, strengths planted per team."""
    rng = np.random.default_rng(seed)
    teams = list(strength)
    start = pd.Timestamp("2025-09-01", tz="UTC")
    rows = []
    for day in range(days):
        rng.shuffle(teams)
        for i in range(0, len(teams) - 1, 2):
            a, b = teams[i], teams[i + 1]
            for off, dfn in ((a, b), (b, a)):
                row = {"game_id": f"{day}-{i}", "off": off, "dfn": dfn,
                       "date": start + pd.Timedelta(days=day), "home": 0.0}
                for m in E.METRICS:
                    row[m] = strength[off] - 0.5 * strength[dfn] + rng.normal(0, 0.05)
                rows.append(row)
    return pd.DataFrame(rows)


def test_the_adjustment_finds_the_teams_it_was_given():
    strength = {str(i): v for i, v in enumerate(np.linspace(-1, 1, 12))}
    obs = _obs(strength)
    fitted = E.fit(obs, pd.Timestamp("2026-01-01", tz="UTC"), fbs=set(strength))
    mu, off, dfn = fitted["ppa"]
    got = np.array([off[t] for t in strength])
    assert np.corrcoef(got, list(strength.values()))[0, 1] > 0.99
    allowed = np.array([dfn[t] for t in strength])
    assert np.corrcoef(allowed, list(strength.values()))[0, 1] < -0.99, \
        "a strong side allows less"


def test_the_adjustment_never_sees_its_own_week():
    strength = {str(i): 0.0 for i in range(12)}
    obs = _obs(strength, days=40)
    asof = obs["date"].min() + pd.Timedelta(days=30)
    late = obs["date"] >= asof
    obs.loc[late & (obs["off"] == "3"), E.METRICS] = 50.0      # a result from the future
    fitted = E.fit(obs, asof, fbs=set(strength))
    assert abs(fitted["ppa"][1]["3"]) < 0.1


def test_the_correction_is_one_line_and_splits_by_team():
    class Base:
        teams = ["h", "a"]
        hfa = 2.0

        def rating(self, t):
            return {"h": 10.0, "a": 4.0}[t]

        def predict(self, frame):
            margin = np.array([8.0])
            total = np.array([50.0])
            return pd.DataFrame({"pred_margin": margin, "pred_total": total,
                                 "pred_home": (total + margin) / 2, "pred_away": (total - margin) / 2})

    model = E.Corrected(Base(), intercept=0.5, b=0.8, values={"h": 3.0, "a": -1.0})
    got = model.predict(pd.DataFrame({"home_team": ["h"], "away_team": ["a"]})).iloc[0]
    assert got["pred_margin"] == pytest.approx(0.5 + 0.8 * 8 + (3.0 - -1.0))
    assert got["pred_home"] - got["pred_away"] == pytest.approx(got["pred_margin"])
    assert got["pred_home"] + got["pred_away"] == pytest.approx(50.0), "totals are the ratings'"
    assert model.rating("h") == pytest.approx(0.8 * 10 + 3.0)
    assert model.hfa == 2.0, "everything else is the ratings model's"


def test_without_a_stack_or_an_archive_the_ratings_stand_alone(monkeypatch):
    base = object()
    assert E.corrected(base, pd.DataFrame(), pd.Timestamp.now(tz="UTC"), stack={}) is base

    class Base:
        teams = ["x"]

    def broken(*_a, **_k):
        raise OSError("no archive")
    monkeypatch.setattr(E, "observations", broken)
    model = Base()
    stack = {"intercept": 0.0, "coef": {c: 0.0 for c in E.FEATURES}}
    assert E.corrected(model, pd.DataFrame(), pd.Timestamp.now(tz="UTC"), stack=stack) is model


def test_an_fcs_opponent_is_read_off_the_fbs_sides_defence(monkeypatch):
    adv = pd.DataFrame([{"game_id": "1", "team": "Big U", "opponent": "Small C",
                         **{f"offense_{m}": 1.0 for m in E.METRICS},
                         **{f"defense_{m}": -1.0 for m in E.METRICS}}])
    games = pd.DataFrame([{"game_id": "1", "date": pd.Timestamp("2025-09-01", tz="UTC"),
                           "home_id": "10", "neutral": False}])
    monkeypatch.setattr(E, "teams", lambda: ({"Big U": "10", "Small C": "99"}, {"10"}))
    obs = E.observations(games, adv).set_index("off")
    assert obs.loc["10", "ppa"] == 1.0 and obs.loc["10", "home"] == 1.0
    assert obs.loc["99", "ppa"] == -1.0 and obs.loc["99", "dfn"] == "10"
    assert obs.loc["99", "home"] == -1.0
