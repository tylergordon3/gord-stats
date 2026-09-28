"""The college season played out: wins on top of the standings, the median
game, and a bracket with byes and reseeding (cfb.league_sim)."""
import numpy as np
import pandas as pd

from cfb import league_sim as sim


def _lg(n=6, field=4, median=True, reseed=True, weeks=(5, 6)):
    return {"current_week": weeks[0], "end_week": weeks[-1] + 2, "playoff_start_week": weeks[-1] + 1,
            "num_playoff_teams": field, "uses_median_score": median,
            "uses_playoff_reseeding": reseed,
            "teams": [{"team_key": f"t{i}", "wins": 0, "losses": 0, "ties": 0,
                       "points_for": 0.0} for i in range(n)]}


def test_the_sixth_seed_can_run_the_table():
    # Seeds 0..5 are teams 0..5; team 5 outscores everyone every round.
    order = np.tile(np.arange(6), (3, 1))
    scores = np.tile(np.array([100, 90, 80, 70, 60, 200], float), (3, 3, 1))
    assert (sim._bracket(order, scores, reseed=True) == 5).all()


def test_byes_and_reseeding():
    """Six teams, eight-team bracket: seeds 1-2 sit out round one, then the best
    seed left meets the worst. Scores by team; higher wins."""
    order = np.array([[0, 1, 2, 3, 4, 5]])
    # Round 1: 3v6 -> 6 wins (team 5), 4v5 -> 4 wins (team 3).
    # Round 2 reseeded: 1 (t0) v 6 (t5), 2 (t1) v 4 (t3). t5 and t1 win.
    # Final: t1 v t5 -> t1.
    r1 = [0, 0, 10, 50, 40, 60]
    r2 = [10, 90, 0, 20, 0, 80]
    r3 = [0, 99, 0, 0, 0, 10]
    scores = np.array([[r1, r2, r3]], float)
    assert sim._bracket(order, scores, reseed=True)[0] == 1


def test_a_week_is_won_head_to_head_and_against_the_median(monkeypatch):
    monkeypatch.setattr(sim.yahoo, "archived_weeks", lambda: [])
    lg = _lg(n=4, field=2, weeks=(5,))
    keys = [t["team_key"] for t in lg["teams"]]
    sched = {5: {"pairs": [("t0", "t1"), ("t2", "t3")]}, 6: {"pairs": []}, 7: {"pairs": []}}
    weeks = [5, 6, 7]
    mean = np.array([[100, 90, 80, 70], [100, 90, 80, 70], [100, 90, 80, 70]], float)
    out = sim.simulate(lg, sched, keys, weeks, mean, np.full_like(mean, 1e-9), sims=10)
    wins = dict(zip(out["team_key"], out["wins"].round(6)))
    # t0: beats t1 and is top-half; t1: loses, top-half; t2: wins, bottom; t3: nothing.
    assert wins == {"t0": 2.0, "t1": 1.0, "t2": 1.0, "t3": 0.0}
    assert dict(zip(out["team_key"], out["playoffs"])) == {"t0": 1.0, "t1": 1.0, "t2": 0.0, "t3": 0.0}
    assert out["title"].sum() == 1.0 and dict(zip(out["team_key"], out["title"]))["t0"] == 1.0


def test_seeds_break_ties_on_points_for(monkeypatch):
    monkeypatch.setattr(sim.yahoo, "archived_weeks", lambda: [])
    lg = _lg(n=4, field=1, median=False, weeks=(5,))
    lg["teams"][3]["points_for"] = 500.0         # same record, more points
    keys = [t["team_key"] for t in lg["teams"]]
    sched = {5: {"pairs": []}, 6: {"pairs": []}, 7: {"pairs": []}}
    mean = np.full((3, 4), 100.0)
    out = sim.simulate(lg, sched, keys, [5, 6, 7], mean, np.full_like(mean, 1e-9), sims=5)
    assert dict(zip(out["team_key"], out["playoffs"]))["t3"] == 1.0


def test_playoff_weeks_run_on_a_week_at_a_time(monkeypatch):
    lg = {"current_week": 10, "end_week": 12, "playoff_start_week": 11}
    board = {"week_start": "2026-11-08", "week_end": "2026-11-14",
             "matchups": [{"teams": [{"team_key": "a"}, {"team_key": "b"}]}]}
    monkeypatch.setattr(sim.yahoo, "archived_weeks", lambda: [])
    monkeypatch.setattr(sim.yahoo, "_get", lambda path: {})
    monkeypatch.setattr(sim.yahoo, "_parse_scoreboard", lambda raw: board)
    got = sim.schedule(lg)
    assert got[10]["pairs"] == [("a", "b")]
    assert (got[11]["start"], got[12]["end"]) == ("2026-11-15", "2026-11-28")
    assert got[11]["pairs"] == []
