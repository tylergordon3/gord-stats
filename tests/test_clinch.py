"""
The playoff picture (gordstats.clinch): clinched, eliminated, byes, magic
numbers and win-and-in, from standings and games left - and never at odds
with either league's season simulation.
"""
import re

import numpy as np
import pandas as pd

from cfb import league_sim
from fantasy.league import power
from gordstats import clinch

from test_power_playoffs import _league, _schedule


def _t(wins, left, losses=0, pf=0.0, **kw):
    return {"name": kw.pop("name", ""), "wins": wins, "losses": losses, "left": left, "pf": pf,
            **kw}


def _named(teams):
    return {k: {**t, "name": t["name"] or k} for k, t in teams.items()}


def test_clinched_when_fewer_than_n_others_can_reach_its_total():
    teams = _named({"a": _t(10, 2), "b": _t(9, 2), "c": _t(7, 2), "d": _t(4, 2)})
    got = clinch.picture(teams, spots=2)
    # a losing out stays on 10; only b (11) can reach it.
    assert got["a"]["clinched"] and not got["a"]["eliminated"]
    # b on 9: a (12) and c (9, level) can reach it - the tie counts against b.
    assert not got["b"]["clinched"]
    # d at best 6: a and b already have more.
    assert got["d"]["eliminated"] and not got["c"]["eliminated"]


def test_a_tie_on_wins_is_never_counted_in_the_teams_favour():
    """Level on wins, the points-for tiebreak decides, and it can't be known
    ahead: a level finish neither clinches nor eliminates."""
    s = clinch.picture(_named({"a": _t(8, 1), "b": _t(6, 2), "c": _t(3, 2)}), spots=1)
    assert not s["a"]["clinched"] and not s["b"]["eliminated"]    # b can reach a's 8
    s = clinch.picture(_named({"a": _t(9, 1), "b": _t(6, 2), "c": _t(3, 2)}), spots=1)
    assert s["a"]["clinched"] and s["b"]["eliminated"]             # 9 against b's best 8


def test_the_median_game_is_counted_in_the_games_left():
    """Two games a week where the league plays the median: the same record
    with one week left is clinched without it and open with it."""
    week_left = {"a": 10, "b": 8, "c": 5, "d": 2}
    plain = _named({k: _t(w, 1) for k, w in week_left.items()})
    doubled = _named({k: _t(w, 2) for k, w in week_left.items()})
    assert clinch.picture(plain, spots=1)["a"]["clinched"]         # b at most 9
    assert not clinch.picture(doubled, spots=1)["a"]["clinched"]   # b can reach 10


def test_byes_and_the_top_seed():
    teams = _named({"a": _t(12, 2), "b": _t(11, 2), "c": _t(8, 2), "d": _t(7, 2),
                    "e": _t(3, 2), "f": _t(1, 2)})
    got = clinch.picture(teams, spots=4, bye_spots=2)
    assert got["a"]["bye"] and not got["a"]["top"]                 # b can reach 13
    assert got["b"]["bye"]                                         # c, d at most 10, 9
    assert got["c"]["clinched"] and got["c"]["no_bye"]             # a, b already past 10
    assert clinch.label(got["c"]) == ("Clinched", "in", "no bye")
    assert clinch.label(got["a"])[0] == "Clinched bye"
    top = clinch.picture(_named({"a": _t(12, 2), "b": _t(9, 2), "c": _t(1, 2)}), 2, 1)
    assert top["a"]["top"] and clinch.label(top["a"])[0] == "Clinched #1"
    assert clinch.byes(6) == 2 and clinch.byes(4) == 0 and clinch.byes(8) == 0


def test_win_and_in_and_a_loss_is_out():
    """The last week: a and c meet level on 5 for the second place."""
    teams = _named({"b": _t(6, 1, opp="d"), "a": _t(5, 1, opp="c"),
                    "c": _t(5, 1, opp="a"), "d": _t(3, 1, opp="b")})
    got = clinch.picture(teams, spots=2)
    assert got["a"]["win_in"] and got["a"]["must_win"] and got["c"]["win_in"]
    assert clinch.label(got["a"]) == ("Win and in", "go", "a loss: out")
    # Without the week's pairing nothing is claimed for this week.
    bare = clinch.picture(_named({k: {**t, "opp": None} for k, t in teams.items()}), spots=2)
    assert not bare["a"]["win_in"] and bare["a"]["magic"] is None      # needs c to lose too


def test_win_both_is_the_game_and_the_median():
    teams = _named({"a": _t(10, 2, opp="c"), "b": _t(10, 2, opp="d"),
                    "c": _t(9, 2, opp="a"), "d": _t(2, 2, opp="b")})
    got = clinch.picture(teams, spots=2, median=True)
    # Beating c puts a on 11 and holds c to 10: only b (12) can reach it.
    assert got["a"]["win_in"]
    tight = _named({"a": _t(9, 2, opp="d"), "b": _t(11, 2, opp="c"),
                    "c": _t(10, 2, opp="b"), "d": _t(2, 2, opp="a")})
    got = clinch.picture(tight, spots=2, median=True)
    # Even with the median a is on 11, and b (13) and c (12) can both pass it.
    assert not got["a"]["win_in"] and not got["a"]["both_in"]
    three = _named({"a": _t(9, 2, opp="c"), "b": _t(13, 2, opp="d"),
                    "c": _t(9, 2, opp="a"), "d": _t(2, 2, opp="b")})
    got = clinch.picture(three, spots=2, median=True)
    # Beating c holds it to 10, level with a's 10 - not enough; the median
    # as well puts a on 11, past it.
    assert not got["a"]["win_in"] and got["a"]["both_in"]
    assert clinch.label(got["a"])[0] == "Win both and in"


def test_the_magic_number_counts_the_teams_own_wins_against_the_first_team_out():
    """Two places; the others can reach 16, 16, 16: 16 - 8 + 1 = 9 more wins
    clinch whatever else happens. One chaser's loss need not lower that:
    the next team sits on the same 16."""
    teams = _named({"a": _t(8, 12), "b": _t(4, 12), "c": _t(4, 12), "d": _t(4, 12),
                    "e": _t(0, 12)})
    got = clinch.picture(teams, spots=2)
    assert got["a"]["magic"] == 9
    assert got["b"]["magic"] is None           # 16 - 4 + 1 = 13 > 12 left: needs help
    # Half wins (a tied week) still need a whole win to pass.
    half = clinch.picture(_named({"a": _t(8, 4), "b": _t(6.5, 4), "c": _t(0, 4)}), spots=1)
    assert half["a"]["magic"] == 3              # 11 > 10.5


def test_once_the_regular_season_is_over_points_for_decides():
    teams = _named({"a": _t(9, 0, pf=900), "b": _t(8, 0, pf=850), "c": _t(8, 0, pf=870),
                    "d": _t(3, 0, pf=990)})
    got = clinch.picture(teams, spots=2, bye_spots=1)
    assert [k for k in "abcd" if got[k]["clinched"]] == ["a", "c"]
    assert got["b"]["eliminated"] and got["a"]["top"]


def test_a_near_certain_win_is_labelled_as_odds_never_as_in():
    teams = _named({"a": _t(6, 4, opp="b", win=1.0), "b": _t(6, 4, opp="a", win=0.2),
                    "c": _t(5, 4, opp="d"), "d": _t(0, 4, opp="c")})
    got = clinch.picture(teams, spots=2)
    assert not got["a"]["win_in"] and got["a"]["near"] == 1.0
    text = clinch.label(got["a"])[0]
    assert text == "A win: >99%" and "100" not in text


def test_the_section_hides_what_cannot_apply_yet():
    early = _named({k: _t(w, 20, 6 - w, pf=100 * w, odds=0.1 * w)
                    for k, w in zip("abcdefghij", (6, 5, 4, 4, 3, 3, 2, 2, 1, 0))})
    html = clinch.section(early, 6, 2, median=True)
    heads = re.findall(r"<th[^>]*>([^<]*)</th>", html)
    assert heads == ["Team", "W-L", "Magic", "Playoffs"], heads
    assert "Each team has 20 games left - 10 weeks of a head-to-head game and the median" in html
    assert html.count("class='cut'") == 1 and html.count("class='bye'") == 1
    assert "prefers-color-scheme: dark" in html and "Clinched" not in html.split("</style>")[1]
    assert "<b>Magic</b>:" in html and "Every status" not in html     # no chip to explain
    late = _named({k: _t(w, 2, 26 - w, pf=100 * w, odds=min(1.0, 0.1 * w))
                   for k, w in zip("abcdefghij", (23, 20, 17, 16, 14, 13, 13, 8, 6, 3))})
    html = clinch.section(late, 6, 2, median=True)
    heads = re.findall(r"<th[^>]*>([^<]*)</th>", html)
    assert heads[:3] == ["Team", "W-L", "Status"], heads
    assert "cl-chip cl-lock'>Clinched #1" in html and "Eliminated" in html


def test_the_odds_column_never_reads_as_a_status_it_is_not():
    """Every simulated run landing one way is not a proof: 100% is printed
    only beside Clinched, 0% only beside Eliminated."""
    teams = _named({"a": _t(9, 2, pf=3, odds=1.0), "b": _t(8, 2, pf=2, odds=1.0),
                    "c": _t(6, 2, pf=1, odds=0.0), "d": _t(1, 2, odds=0.0)})
    html = clinch.section(teams, 2)
    cells = re.findall(r"<td>([^<]*%)</td>", html)
    assert cells == ["100%", "&gt;99%", "&lt;1%", "0%"], cells


def test_the_nfl_page_reads_its_table(monkeypatch):
    from fantasy.site import power as page

    ids = list(range(1, 11))
    table = pd.DataFrame({"roster_id": ids, "manager": [f"M{i}" for i in ids],
                          "wins": [26 - 2 * i for i in ids], "losses": [2 * i for i in ids],
                          "points_for": [1500.0 - i for i in ids],
                          "playoff_odds": [1.0] * 5 + [0.5] * 2 + [0.0] * 3,
                          "week": power.FANTASY_REG_WEEKS - 1})
    html = page._playoffs_section(table, None, {})
    assert "Each team has 2 games left - 1 week of a head-to-head game and the median" in html
    assert page._playoffs_section(table.assign(week=0), None, {}) == ""


def _nfl_posted(scores: np.ndarray, sched: np.ndarray) -> dict:
    """Sleeper's matchup rows for played weeks, from (weeks, teams) scores."""
    posted = {}
    for w in range(len(scores)):
        rows, seen = [], {}
        for i, j in enumerate(sched[w]):
            mid = seen.setdefault(frozenset((i, int(j))), len(seen) + 1)
            rows.append({"roster_id": i + 1, "matchup_id": mid, "points": float(scores[w, i])})
        posted[w + 1] = rows
    return posted


def test_nfl_statuses_never_contradict_the_simulation():
    """Every status is a claim about every legal finish; the simulation only
    plays legal finishes. Across late-season states: clinched teams make it
    in every run, eliminated ones in none, a win-and-in team is in whenever
    it wins, a must-win team out whenever it loses."""
    board, rosters = _league()
    weeks = power.FANTASY_REG_WEEKS
    sched = _schedule(weeks)
    seen = set()
    for played, seed in ((10, 1), (11, 2), (12, 3), (13, 4), (13, 5), (12, 6)):
        rng = np.random.default_rng(seed)
        scores = np.maximum(70.0 + 6.0 * np.arange(10)[None, :]
                            + rng.normal(0, 18, (played, 10)), 1.0)
        actual = power.actual_results(through_week=played, posted=_nfl_posted(scores, sched))
        got = power.simulate(board, rosters, sims=400, fixed_schedule=sched,
                             actual_points=actual["points"]).set_index("roster_id")
        left = 2 * (weeks - played)
        teams = {}
        for i, rid in enumerate(actual["order"]):
            g = got.loc[rid]
            teams[str(rid)] = {"name": str(rid), "wins": float(actual["wins"][i]),
                               "losses": float(actual["losses"][i]), "left": left,
                               "pf": float(actual["points_for"][i]),
                               "odds": float(g["playoff_odds"]), "opp": str(int(g["opponent"])),
                               "win": float(g["playoff_if_win"])}
        status = clinch.picture(teams, power.PLAYOFF_TEAMS, clinch.byes(6), median=True)
        assert clinch.check(teams, status) == [], (played, seed)
        for k, s in status.items():
            g = got.loc[int(k)]
            if s["must_win"] and not np.isnan(g["playoff_if_loss"]):
                assert g["playoff_if_loss"] == 0.0, (played, seed, k)
            if s["top"]:
                assert g["first_seed_odds"] == 1.0
            seen |= {name for name in ("clinched", "eliminated", "win_in", "must_win")
                     if s[name]}
    assert seen == {"clinched", "eliminated", "win_in", "must_win"}, seen


def test_cfb_statuses_never_contradict_the_simulation(monkeypatch):
    """The same on the Yahoo league's simulation, with its byes, starting from
    standings that already count the median (W + L = 2 a week)."""
    monkeypatch.setattr(league_sim.yahoo, "archived_weeks", lambda: [])
    keys = [f"t{i}" for i in range(8)]
    wins = [15, 13, 12, 10, 9, 8, 5, 2]
    lg = {"current_week": 9, "end_week": 12, "playoff_start_week": 11, "num_playoff_teams": 6,
          "uses_median_score": True, "uses_playoff_reseeding": True,
          "teams": [{"team_key": k, "wins": w, "losses": 16 - w, "ties": 0,
                     "points_for": 1000.0 - 10 * i}
                    for i, (k, w) in enumerate(zip(keys, wins))]}
    sched = {9: {"pairs": [("t0", "t7"), ("t1", "t6"), ("t2", "t5"), ("t3", "t4")]},
             10: {"pairs": [("t0", "t1"), ("t2", "t3"), ("t4", "t5"), ("t6", "t7")]},
             11: {"pairs": []}, 12: {"pairs": []}}
    weeks = [9, 10, 11, 12]
    mean = np.tile(100.0 + 3 * np.arange(8)[::-1], (4, 1))
    out = league_sim.simulate(lg, sched, keys, weeks, mean, np.full_like(mean, 25.0),
                              sims=6000).set_index("team_key")
    assert (out["games_left"] == 4).all()                       # two weeks, each two games
    assert out.loc["t0", "now_wins"] == 15 and out.loc["t0", "now_losses"] == 1
    teams = {k: {"name": k, "wins": out.loc[k, "now_wins"], "losses": out.loc[k, "now_losses"],
                 "left": out.loc[k, "games_left"], "pf": out.loc[k, "now_pf"],
                 "odds": out.loc[k, "playoffs"], "opp": out.loc[k, "opponent"],
                 "win": out.loc[k, "playoff_if_win"]} for k in keys}
    status = clinch.picture(teams, 6, clinch.byes(6), median=True)
    assert clinch.check(teams, status) == []
    # t0 on 15: only t1 (17) and t2 (16) can reach it - in, though not yet
    # sure of a bye. t7 at best 6: six teams have more already.
    assert status["t0"]["clinched"] and status["t7"]["eliminated"]
    for k, s in status.items():
        if s["bye"]:
            assert out.loc[k, "bye"] == 1.0
        if s["no_bye"]:
            assert out.loc[k, "bye"] == 0.0
    assert any(s["bye"] or s["no_bye"] for s in status.values())
