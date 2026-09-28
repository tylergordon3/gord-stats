"""In season, backs, receivers and tight ends are priced halfway to Sleeper.

Replayed on 2023-2025, predicting each player's next four weeks: ours 5.14
RMSE, Sleeper's 5.17, half of each 5.05, better in every season; for
quarterbacks worse, so they keep ours (fantasy.projections.with_sleeper).
"""
import pandas as pd

from fantasy import projections as P


def _board():
    return pd.DataFrame({"sleeper_id": ["1", "2", "3", "4"], "pos": ["QB", "RB", "WR", "TE"],
                         "mu": [20.0, 10.0, 10.0, 8.0], "basis": ["x"] * 4})


def test_half_way_to_sleepers_recent_mean_but_not_for_quarterbacks(monkeypatch):
    weeks = {3: {"1": 30.0, "2": 14.0, "3": 0.0}, 4: {"1": 30.0, "2": 18.0},
             5: {"1": 30.0, "2": 16.0, "4": 12.0}}
    monkeypatch.setattr(P, "_sleeper_week", lambda year, week: weeks.get(week, {}))
    got = P.with_sleeper(_board(), 2026, through_week=4).set_index("sleeper_id")
    assert got.loc["1", "mu"] == 20.0, "a quarterback keeps ours"
    assert got.loc["2", "mu"] == 0.5 * 10 + 0.5 * 16.0, "mean of weeks 3-5"
    assert got.loc["3", "mu"] == 10.0, "a zero says nothing about the rate"
    assert got.loc["4", "mu"] == 10.0 and got.loc["4", "basis"].endswith("+ Sleeper")


def test_before_kickoff_or_without_sleeper_the_board_stands(monkeypatch):
    board = _board()
    assert P.with_sleeper(board, 2026, through_week=0) is board

    def down(year, week):
        raise OSError("sleeper down")
    monkeypatch.setattr(P, "_sleeper_week", down)
    assert P.with_sleeper(board, 2026, through_week=3)["mu"].tolist() == board["mu"].tolist()
