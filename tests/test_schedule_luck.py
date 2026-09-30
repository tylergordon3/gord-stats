"""
Schedule difficulty (gordstats.schedule_luck): each team's schedule effect in
wins - actual head-to-head wins against all-play - split into its opponents'
strength and their timing, the three summing to zero across a league.
"""
import numpy as np

from gordstats import schedule_luck as sl


def _rows(scores: dict, pairs: dict) -> list:
    """scores {week: {team: pts}}, pairs {week: [(a, b), ...]} -> both sides of every game."""
    out = []
    for week, games in pairs.items():
        for a, b in games:
            out += [(week, a, b, scores[week][a], scores[week][b]),
                    (week, b, a, scores[week][b], scores[week][a])]
    return out


def _round_robin(teams, weeks):
    rot = list(teams[1:])
    out = {}
    for w in range(1, weeks + 1):
        order = [teams[0]] + rot
        out[w] = [(order[i], order[-1 - i]) for i in range(len(order) // 2)]
        rot = rot[1:] + rot[:1]
    return out


def test_the_parts_add_up_and_the_league_sums_to_zero():
    rng = np.random.default_rng(7)
    teams = [f"t{i}" for i in range(10)]
    pairs = _round_robin(teams, 9)
    scores = {w: {t: 120 + 10 * i + rng.normal(0, 18) for i, t in enumerate(teams)}
              for w in pairs}
    got = sl.table(_rows(scores, pairs))
    assert len(got) == 10 and (got["games"] == 9).all()
    for r in got.itertuples():
        assert abs(r.schedule - (r.wins - r.allplay_w)) < 1e-9
        assert abs(r.schedule - (r.strength + r.timing)) < 1e-9
    assert abs(got["schedule"].sum()) < 1e-9
    assert abs(got["strength"].sum()) < 1e-9 and abs(got["timing"].sum()) < 1e-9


def test_opponents_peaking_against_a_team_is_timing_not_strength():
    """Everyone scores 100 every week - except against A, where the opponent
    scores 150. A's opponents are ordinary (strength ~0); their timing cost it."""
    teams = ["A", "B", "C", "D"]
    pairs = _round_robin(teams, 3)
    scores = {}
    for w, games in pairs.items():
        scores[w] = {t: 100.0 + (1 if t == "A" else 0) for t in teams}
        for a, b in games:
            if "A" in (a, b):
                scores[w][b if a == "A" else a] = 150.0
    got = sl.table(_rows(scores, pairs)).set_index("team")
    a = got.loc["A"]
    assert a["wins"] == 0 and a["timing"] < -0.5 and a["timing"] < a["strength"]
    assert a["opp_over"] > 30                              # 150 against a normal near 100
    assert got.index[0] == "A"                             # the hardest schedule first
    assert "opponents' big weeks" in sl.finding(got.reset_index(), {"A": "Team A"})


def test_facing_the_best_team_is_strength():
    """E scores 160 every week, everyone else about 100; F draws E every week
    while G and H play each other. F's losses are to a team that is simply
    better - strength, not timing."""
    rng = np.random.default_rng(1)
    pairs = {w: [("E", "F"), ("G", "H")] for w in range(1, 5)}
    scores = {w: {t: (160.0 if t == "E" else 100 + rng.normal(0, 6)) for t in "EFGH"}
              for w in pairs}
    got = sl.table(_rows(scores, pairs)).set_index("team")
    f = got.loc["F"]
    assert f["strength"] < -0.4 and abs(f["timing"]) < abs(f["strength"])
    assert f["strength"] == got["strength"].min()
    assert "strong opponents" in sl.finding(got.reset_index(), {})


def test_the_table_escapes_names_and_marks_signs():
    rows = _rows({1: {"a": 120.0, "b": 100.0}, 2: {"a": 90.0, "b": 110.0}},
                 {1: [("a", "b")], 2: [("a", "b")]})
    html = sl.html(sl.table(rows), {"a": "<b>A's</b>", "b": "B"})
    assert "&lt;b&gt;A&#x27;s&lt;/b&gt;" in html and "<b>A's</b>" not in html
    assert ">Opp. strength</th>" in html and ">Opp. timing</th>" in html and "<th>Team</th>" in html
    assert sl.html(sl.table([]), {}).startswith("<p")       # nothing played yet
