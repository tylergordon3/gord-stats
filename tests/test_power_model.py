"""
Properties the power simulation must not silently lose.

These are the three things the 2026-08 rework fixed. Each was invisible in the
output — the page looked fine throughout — and each moved rosters against each
other, so each gets a test that fails loudly if it comes back.
"""
import numpy as np
import pandas as pd
import pytest

from fantasy.league import power


def _players(n=4, avail=1.0, mu=10.0, sd=6.0):
    return pd.DataFrame({"avail": [avail] * n, "bye": [0] * n, "mu": [mu] * n,
                         "sd": [sd] * n, "mu_se": [0.0] * n,
                         "pos": ["RB"] * n})


def test_scores_keep_the_mean_and_sd_they_were_given():
    """A normal clipped at zero quietly adds points; a gamma does not."""
    rng = np.random.default_rng(2)
    scores, _ = power._weekly_scores(_players(), 17, 8000, rng)
    assert scores.mean() == pytest.approx(10.0, abs=0.1)
    assert scores.std() == pytest.approx(6.0, abs=0.1)


def test_scores_are_never_negative_and_lean_right():
    rng = np.random.default_rng(3)
    scores, _ = power._weekly_scores(_players(), 17, 4000, rng)
    assert scores.min() >= 0.0
    assert np.median(scores) < scores.mean()      # right-skewed, like real weeks


def test_availability_matches_the_rate_it_was_given():
    rng = np.random.default_rng(1)
    players = pd.DataFrame({"avail": [0.95, 0.70, 0.50], "bye": [0, 0, 0]})
    available = power._availability(players, 17, 8000, rng)
    for i, rate in enumerate(players["avail"]):
        assert available[:, :, i].mean() == pytest.approx(rate, abs=0.02)


def test_absences_clump_instead_of_scattering():
    """The risk that decides a season is a starter gone for a month."""
    rng = np.random.default_rng(1)
    players = pd.DataFrame({"avail": [0.70], "bye": [0]})
    out = ~power._availability(players, 17, 2000, rng)[:, :, 0]

    spells = []
    for season in out:
        run = 0
        for week in season:
            if week:
                run += 1
            elif run:
                spells.append(run); run = 0
        if run:
            spells.append(run)
    # A weekly coin flip would average ~1/0.3 = 1.4 weeks; spells must be longer.
    assert np.mean(spells) > 2.0


def test_byes_are_always_missed():
    rng = np.random.default_rng(4)
    players = pd.DataFrame({"avail": [1.0], "bye": [5]})
    available = power._availability(players, 14, 500, rng)
    assert not available[:, 4, 0].any()           # week 5 is index 4
    assert available[:, 5, 0].all()


def test_lineups_are_set_on_projection_not_on_hindsight():
    """The whole point: the manager picks before the week, not after."""
    frame = pd.DataFrame({"mu": [20.0, 1.0], "sd": [1.0, 1.0], "pos": ["QB", "QB"],
                          "avail": [1.0, 1.0], "bye": [0, 0]})
    roster = power.Roster(1, frame, 0)
    # The bench QB outscores the starter this week. Hindsight would take 99.
    scores = np.array([[[5.0, 99.0]]])
    available = np.ones((1, 1, 2), dtype=bool)
    assert power._lineup_points(scores, available, roster)[0, 0] == 5.0


def test_an_unavailable_starter_is_benched_for_whoever_is_left():
    frame = pd.DataFrame({"mu": [20.0, 1.0], "sd": [1.0, 1.0], "pos": ["QB", "QB"],
                          "avail": [1.0, 1.0], "bye": [0, 0]})
    roster = power.Roster(1, frame, 0)
    scores = np.array([[[0.0, 7.0]]])
    available = np.array([[[False, True]]])
    assert power._lineup_points(scores, available, roster)[0, 0] == 7.0


def test_a_position_with_nobody_left_scores_zero_not_an_error():
    frame = pd.DataFrame({"mu": [20.0], "sd": [1.0], "pos": ["QB"],
                          "avail": [1.0], "bye": [0]})
    roster = power.Roster(1, frame, 0)
    scores = np.array([[[12.0]]])
    available = np.ones((1, 1, 1), dtype=bool)
    # One QB, no RB/WR/TE/K/DEF: the empty slots contribute nothing.
    assert power._lineup_points(scores, available, roster)[0, 0] == 12.0


def test_a_player_on_reserve_is_held_out_then_returns_at_the_usual_rate():
    """IR is four games by rule: those weeks are missed in every simulation,
    from the week being played next, and the chain resumes from out."""
    rng = np.random.default_rng(3)
    players = pd.DataFrame({"avail": [0.9, 0.9], "bye": [0, 0], "out_weeks": [4, 0]})
    available = power._availability(players, 12, 4000, rng, from_week=2)
    assert available[:, 2:6, 0].sum() == 0                      # held out weeks 3-6
    assert available[:, :2, 0].mean() == pytest.approx(0.9, abs=0.03)   # already-played weeks untouched
    back = available[:, 6, 0].mean()                             # first eligible week
    assert 1 / power.MEAN_ABSENCE_WEEKS - 0.05 < back < 0.9      # a return rate, not a full recovery
    assert available[:, :, 1].mean() == pytest.approx(0.9, abs=0.02)
