"""
This week's stakes: each team's playoff odds with a win and with a loss, and
the game of the week (gordstats.stakes, with the split made inside both
leagues' season simulations).
"""
import re

import numpy as np
import pandas as pd

from cfb import league_sim
from fantasy.league import power
from gordstats import stakes

from test_power_playoffs import _league, _schedule


def test_nfl_odds_split_on_next_weeks_game_add_back_up():
    """The same runs, counted by whether the team won: odds with a win and
    with a loss, weighted by the chance of each, are today's odds exactly."""
    board, rosters = _league()
    weeks = power.FANTASY_REG_WEEKS
    played = weeks - 2
    rng = np.random.default_rng(3)
    actual = 100.0 + rng.normal(0, 15, (played, 10))
    sched = _schedule(weeks)
    got = power.simulate(board, rosters, sims=3000, fixed_schedule=sched, actual_points=actual)
    assert (got["stakes_week"] == played + 1).all()
    ids = sorted(got["roster_id"])
    opp = {rid: ids[j] for rid, j in zip(ids, sched[played])}
    assert dict(zip(got["roster_id"], got["opponent"])) == opp
    for _, r in got.iterrows():
        mixed = r["win_prob"] * r["playoff_if_win"] + (1 - r["win_prob"]) * r["playoff_if_loss"]
        assert abs(mixed - r["playoff_odds"]) < 1e-9, r["manager"]
        assert r["playoff_if_win"] >= r["playoff_if_loss"] - 0.02     # winning never hurts


def test_nfl_has_no_stakes_once_the_regular_season_is_over():
    board, rosters = _league()
    weeks = power.FANTASY_REG_WEEKS
    got = power.simulate(board, rosters, sims=100, fixed_schedule=_schedule(weeks),
                         actual_points=np.full((weeks, 10), 100.0))
    assert "playoff_if_win" not in got


def test_cfb_a_game_for_the_last_spot_swings_it_all(monkeypatch):
    """Two teams level for the last playoff place meet: the winner is in,
    the loser out, and it is a coin flip."""
    monkeypatch.setattr(league_sim.yahoo, "archived_weeks", lambda: [])
    lg = {"current_week": 5, "end_week": 7, "playoff_start_week": 6, "num_playoff_teams": 2,
          "uses_median_score": False, "uses_playoff_reseeding": False,
          "teams": [{"team_key": "t0", "wins": 4, "losses": 0, "ties": 0, "points_for": 500.0},
                    {"team_key": "t1", "wins": 2, "losses": 2, "ties": 0, "points_for": 400.0},
                    {"team_key": "t2", "wins": 2, "losses": 2, "ties": 0, "points_for": 400.0},
                    {"team_key": "t3", "wins": 0, "losses": 4, "ties": 0, "points_for": 100.0}]}
    keys = ["t0", "t1", "t2", "t3"]
    sched = {5: {"pairs": [("t1", "t2"), ("t0", "t3")]}, 6: {"pairs": []}, 7: {"pairs": []}}
    mean = np.full((3, 4), 100.0)
    out = league_sim.simulate(lg, sched, keys, [5, 6, 7], mean, np.full_like(mean, 10.0),
                              sims=4000).set_index("team_key")
    assert out.loc["t1", "opponent"] == "t2" and out.loc["t1", "stakes_week"] == 5
    assert out.loc["t1", "playoff_if_win"] == 1.0 and out.loc["t1", "playoff_if_loss"] == 0.0
    assert abs(out.loc["t1", "win_prob"] - 0.5) < 0.05
    assert out.loc["t0", "playoff_if_win"] == out.loc["t0", "playoff_if_loss"] == 1.0


TEAMS = {  # CFB week 5, 2026, rounded: the lopsided game has the biggest raw swing
    "a": {"name": "Mike Locksley", "opp": "b", "now": .80, "win": .807, "loss": .448, "wp": .976},
    "b": {"name": "I Stand With Diggs", "opp": "a", "now": .43, "win": .717, "loss": .429, "wp": .024},
    "g": {"name": "Puntaholics", "opp": "h", "now": .84, "win": .882, "loss": .678, "wp": .814},
    "h": {"name": "Too B1G", "opp": "g", "now": .03, "win": .091, "loss": .015, "wp": .186},
}


def test_the_game_of_the_week_is_the_one_expected_to_move_the_odds():
    """Not the biggest raw swing: a 98% favourite's game would move almost
    nothing, however big the upset would be."""
    ranked = stakes.games(TEAMS)
    assert [(a, b) for a, b, _ in ranked] == [("g", "h"), ("a", "b")]
    html = stakes.callout(5, TEAMS, names={"g": "Puntaholics FC"}, anchor="wk5-m1")
    assert "Puntaholics FC" in html and "href='#wk5-m1'" in html
    assert "88% with a win, 68% with a loss" in html


def test_the_table_leads_with_the_biggest_swing_and_marks_the_game():
    html = stakes.table(5, TEAMS)
    rows = re.findall(r"<td class='t'>([^<]*)</td>", html[html.index("<tbody>"):])
    # swings 36, 29, 20, 8
    assert rows == ["Mike Locksley", "I Stand With Diggs", "Puntaholics", "Too B1G"]
    assert html.count("class=gw-row") == 2 and ">Swing</th>" in html
    # Swing's meaning is its header's tooltip; the method is the explainer's.
    assert "in percentage points'>Swing</th>" in html
    assert "split on that game" not in html


def test_the_file_the_matchups_page_reads_is_for_its_week_only(tmp_path):
    path = tmp_path / "stakes.json"
    stakes.write(path, 5, TEAMS)
    assert stakes.read(path, 5) == TEAMS
    assert stakes.read(path, 6) == {}                    # another week's stakes
    stakes.write(path, None, {})                         # nothing to show: cleared
    assert not path.exists() and stakes.read(path, 5) == {}


def test_teams_are_read_off_either_leagues_table():
    frame = pd.DataFrame({"roster_id": [1, 2], "manager": ["A", "B"], "opponent": [2, 1],
                          "playoff_odds": [.6, .4], "win_prob": [.55, .45],
                          "playoff_if_win": [.8, .6], "playoff_if_loss": [.36, .24]})
    got = stakes.teams_from(frame, "roster_id", "manager")
    assert got["1"] == {"name": "A", "opp": "2", "now": .6, "win": .8, "loss": .36, "wp": .55}
    assert stakes.teams_from(frame.drop(columns=["playoff_if_win"]), "roster_id", "manager") == {}
