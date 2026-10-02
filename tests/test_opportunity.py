"""
Next man up (fantasy.league.opportunity): an injured player's work measured
onto his teammates on history, and applied to today's board.

The history tests build tiny leagues where the answer is known exactly - a
back who gains 30% of the injured starter's points every week he is out - and
check the fit gets it back, discount and all. The application tests pin the
rules a reader would notice being wrong: who counts as the next man, that a
teammate above the injured player gains nothing, that the board's own form and
Sleeper's projections are not counted twice, and the season average the
simulations take.
"""
import json

import numpy as np
import pandas as pd
import pytest

from fantasy.league import opportunity as op

COEFFS = {"min_mu": 5.0,
          "same": {"RB": [0.3, 0.1, 0.05], "WR": [0.1, 0.08], "TE": [0.2]},
          "qb_out": {"RB": -0.1, "WR": -0.2, "TE": -0.05}}


# --------------------------------------------------------------------------- #
# History
# --------------------------------------------------------------------------- #

def _season(season, team, players, weeks=range(1, 17)):
    """Rows of games: players = {gsis: (pos, points by week or None if out)}."""
    rows = []
    for gsis, (pos, by_week) in players.items():
        for week in weeks:
            pts = by_week(week)
            if pts is not None:
                rows.append({"season": season, "week": week, "team": team,
                             "gsis_id": gsis, "pos": pos, "pts": float(pts)})
    return rows


def _injured_starter_league(share_next=0.3, share_second=0.1, hurt_from=6):
    """2020 sets everyone's prior; in 2021 the 15-point back A is hurt from
    `hurt_from` on and B and C gain their shares of his 15 a week."""
    out = lambda w: w >= hurt_from                           # noqa: E731
    rows = _season(2020, "AAA", {"A": ("RB", lambda w: 15), "B": ("RB", lambda w: 5),
                                 "C": ("RB", lambda w: 2)})
    rows += _season(2021, "AAA", {
        "A": ("RB", lambda w: None if out(w) else 15),
        "B": ("RB", lambda w: 5 + share_next * 15 if out(w) else 5),
        "C": ("RB", lambda w: 2 + share_second * 15 if out(w) else 2)})
    games = pd.DataFrame(rows)
    hurt = {(2021, w, "A") for w in range(hurt_from, 17)}
    return games, hurt


def test_games_frame_counts_a_snap_without_a_stat_as_a_zero():
    weekly = pd.DataFrame([
        {"season": 2021, "week": 1, "team": "LAR", "gsis_id": "g1", "position": "RB",
         "fantasy_points_ppr": 12.0},
        {"season": 2020, "week": 17, "team": "KC", "gsis_id": "g3", "position": "WR",
         "fantasy_points_ppr": 9.0},                         # rested-starter finale
        {"season": 2021, "week": 1, "team": "LAR", "gsis_id": "g4", "position": "FB",
         "fantasy_points_ppr": 1.0}])
    snaps = pd.DataFrame([
        {"season": 2021, "week": 1, "team": "LA", "pfr_player_id": "p1", "position": "RB",
         "offense_snaps": 40, "game_type": "REG"},
        {"season": 2021, "week": 1, "team": "LA", "pfr_player_id": "p2", "position": "WR",
         "offense_snaps": 12, "game_type": "REG"},           # played, no stat row
        {"season": 2021, "week": 1, "team": "LA", "pfr_player_id": "p5", "position": "WR",
         "offense_snaps": 0, "game_type": "REG"},            # dressed, never on the field
        {"season": 2021, "week": 19, "team": "LA", "pfr_player_id": "p1", "position": "RB",
         "offense_snaps": 30, "game_type": "WC"}])
    ids = pd.DataFrame({"pfr_id": ["p1", "p2", "p5"], "gsis_id": ["g1", "g2", "g5"]})
    got = op.games_frame(weekly, snaps, ids).set_index("gsis_id")
    assert sorted(got.index) == ["g1", "g2", "g4"]
    assert got.loc["g2", "pts"] == 0.0 and got.loc["g2", "team"] == "LAR"
    assert got.loc["g1", "pts"] == 12.0 and got.loc["g4", "pos"] == "RB"


def test_hurt_keys_reads_the_report_and_the_reserve_lists():
    injuries = pd.DataFrame({"season": [2021, 2021], "week": [3, 4], "gsis_id": ["a", "b"],
                             "report_status": ["Out", "Questionable"]})
    rosters = pd.DataFrame({"season": [2021, 2021], "week": [5, 5], "gsis_id": ["c", "d"],
                            "status": ["RES", "ACT"]})
    assert op.hurt_keys(injuries, rosters) == {(2021, 3, "a"), (2021, 5, "c")}


def test_the_fit_recovers_known_shares_with_the_form_discount():
    games, hurt = _injured_starter_league(0.3, 0.1)
    obs = op.observations(games, hurt)
    week6 = obs[(obs.season == 2021) & (obs.week == 6)].set_index("gsis_id")
    # B was behind A, so he is one step below him; C two.
    assert [a[3] for a in week6.loc["B", "absent"]] == [1]
    assert [a[3] for a in week6.loc["C", "absent"]] == [2]
    got = op.fit(obs[obs.season == 2021])
    # Exact, because B's form absorbs his gain at exactly the rate the
    # discount (1 - games without A / (games + 5)) takes it back off.
    assert got["same"]["RB"][0] == pytest.approx(0.3, abs=1e-3)
    assert got["same"]["RB"][1] == pytest.approx(0.1, abs=1e-3)


def test_an_absence_that_is_not_an_injury_is_kept_out_of_the_effect():
    games, _ = _injured_starter_league(0.3, 0.1)
    obs = op.observations(games, hurt=set())                 # benched, not hurt
    got = op.fit(obs[obs.season == 2021])
    assert got["same"]["RB"] == [0.0, 0.0, 0.0]


def test_a_player_who_left_for_another_team_is_not_absent():
    games, hurt = _injured_starter_league()
    moved = games[(games.gsis_id == "A") & (games.season == 2021)].copy()
    moved = moved[moved.week <= 5].assign(week=lambda f: f.week + 5, team="BBB")
    games = pd.concat([games, moved], ignore_index=True)
    obs = op.observations(games, hurt)
    later = obs[(obs.season == 2021) & (obs.team == "AAA") & (obs.week >= 7)]
    assert all(not absent for absent in later["absent"])


def test_validation_beats_no_change_out_of_sample():
    rng = np.random.default_rng(4)
    rows, hurt = [], set()
    for season in range(2018, 2024):
        for t in range(12):
            team, a, b = f"T{t}", f"A{t}", f"B{t}"
            star = 12 + t % 6
            first = int(rng.integers(4, 12))
            out = (lambda w, f=first: w >= f) if season > 2018 else (lambda w: False)
            noise = rng.normal(0, 3, size=(2, 17))
            rows += _season(season, team, {
                a: ("RB", lambda w, o=out, s=star, n=noise: None if o(w) else s + n[0, w]),
                b: ("RB", lambda w, o=out, s=star, n=noise:
                    5 + n[1, w] + (0.3 * s if o(w) else 0))})
            hurt |= {(season, w, a) for w in range(first, 17)} if season > 2018 else set()
    obs = op.observations(pd.DataFrame(rows), hurt)
    v = op.validate(obs, train=range(2018, 2022), test=range(2022, 2024), draws=50)
    assert v["injury_weeks"]["n"] > 0
    assert v["injury_weeks"]["rmse_rule"] < v["injury_weeks"]["rmse_none"]
    assert v["moved_a_point"]["mse_gain_95"][0] > 0
    assert v["coefficients"]["same"]["RB"][0] == pytest.approx(0.3, abs=0.08)


def test_the_committed_coefficients_have_the_shape_boosts_reads():
    stored = op.load()
    assert set(stored["same"]) == {"RB", "WR", "TE"}
    for pos, shares in stored["same"].items():
        assert len(shares) == op.DEPTH_CAP[pos]
        assert all(0 < s < 0.5 for s in shares)
    assert stored["same"]["RB"][0] > stored["same"]["RB"][1]
    assert stored["qb_out"]["WR"] < 0 and stored["qb_out"]["RB"] < 0
    held_out = stored["validation"]["moved_a_point"]
    assert held_out["rmse_rule"] < held_out["rmse_none"]
    assert len(json.dumps(stored)) < 8000


# --------------------------------------------------------------------------- #
# Today
# --------------------------------------------------------------------------- #

def _board(rows):
    """rows: (id, pos, team, mu[, mu_se])."""
    return pd.DataFrame([{"sleeper_id": r[0], "pos": r[1], "team": r[2], "mu": r[3],
                          "mu_se": r[4] if len(r) > 4 else 1.0, "basis": "usage"}
                         for r in rows])


BOARD = _board([
    ("rb1", "RB", "MIA", 16.0), ("rb2", "RB", "MIA", 6.0), ("rb3", "RB", "MIA", 3.0),
    ("rb4", "RB", "MIA", 1.0),
    ("qb1", "QB", "MIA", 18.0), ("qb2", "QB", "MIA", 9.0),
    ("wr1", "WR", "MIA", 15.0), ("wr2", "WR", "MIA", 10.0), ("te1", "TE", "MIA", 8.0),
    ("rbx", "RB", "BUF", 14.0), ("rby", "RB", "BUF", 5.0),
])
# Sleeper moves an injured player to the bottom of the chart.
DEPTH = {"MIA": {"RB": ["rb2", "rb3", "rb4", "rb1"], "QB": ["qb1", "qb2"],
                 "WR": ["wr1", "wr2"], "TE": ["te1"]},
         "BUF": {"RB": ["rbx", "rby"]}}


def test_the_next_man_gets_the_biggest_share_for_as_long_as_the_starter_is_out():
    got = op.boosts(BOARD, {"rb1": 6}, weeks_left=12, depth=DEPTH, coeffs=COEFFS)
    assert got["rb2"]["full"] == pytest.approx(0.3 * 16.0)
    assert got["rb3"]["full"] == pytest.approx(0.1 * 16.0)
    assert got["rb4"]["full"] == pytest.approx(0.05 * 16.0)
    assert got["rb2"]["add"] == got["rb2"]["full"]           # nothing absorbed yet
    assert got["rb2"]["weeks"] == 6 and got["rb2"]["because"] == "rb1"
    assert got["rb2"]["season"] == pytest.approx(0.3 * 16.0 * 6 / 12, abs=1e-3)
    assert "rbx" not in got and "wr1" not in got           # other team, other position


def test_a_teammate_above_the_injured_player_gains_nothing():
    got = op.boosts(BOARD, {"rb2": 4}, weeks_left=12, depth=DEPTH, coeffs=COEFFS)
    assert "rb1" not in got
    assert got["rb3"]["full"] == pytest.approx(0.3 * 6.0)   # the next man below rb2


def test_a_backup_below_the_threshold_moves_nobody():
    assert op.boosts(BOARD, {"rb3": 8}, weeks_left=12, depth=DEPTH, coeffs=COEFFS) == {}


def test_a_starting_quarterback_out_takes_a_share_off_each_catcher():
    got = op.boosts(BOARD, {"qb1": 3}, weeks_left=12, depth=DEPTH, coeffs=COEFFS)
    assert got["wr1"]["full"] == pytest.approx(-0.2 * 15.0)
    assert got["rb1"]["full"] == pytest.approx(-0.1 * 16.0)
    assert got["te1"]["full"] == pytest.approx(-0.05 * 8.0)
    assert "qb2" not in got                                 # the backup's line is the board's
    assert op.boosts(BOARD, {"qb2": 3}, weeks_left=12, depth=DEPTH, coeffs=COEFFS) == {}


def test_a_teammate_out_as_long_is_skipped_and_one_out_briefly_waits():
    got = op.boosts(BOARD, {"rb1": 6, "rb2": 6}, weeks_left=12, depth=DEPTH, coeffs=COEFFS)
    assert got["rb3"]["parts"][0][:3] == ["rb1", pytest.approx(4.8), pytest.approx(4.8)]
    got = op.boosts(BOARD, {"rb1": 6, "rb2": 2}, weeks_left=12, depth=DEPTH, coeffs=COEFFS)
    assert got["rb2"]["weeks"] == 4
    # His mu matters only in the ten weeks he plays.
    assert got["rb2"]["season"] == pytest.approx(4.8 * 4 / 10, abs=1e-3)


def test_two_injuries_feeding_one_player_add_up():
    got = op.boosts(BOARD, {"rb1": 6, "qb1": 2}, weeks_left=12, depth=DEPTH, coeffs=COEFFS)
    rb2 = got["rb2"]
    assert rb2["full"] == pytest.approx(0.3 * 16 - 0.1 * 6, abs=0.01)
    assert rb2["because"] == "rb1" and len(rb2["parts"]) == 2
    assert rb2["season"] == pytest.approx((4.8 * 6 - 0.6 * 2) / 12, abs=1e-3)


def test_what_the_board_already_holds_is_not_counted_twice():
    # rb2 has played three games, two of them without rb1; Sleeper projected
    # him all three weeks of its window and had rb1 ruled out for one.
    played = pd.DataFrame({"week": [1, 2, 3, 1],
                           "sleeper_id": ["rb2", "rb2", "rb2", "rb1"],
                           "team": ["MIA"] * 4})
    sleeper = [{"rb2": 6.0, "rb1": 15.0}, {"rb2": 6.5, "rb1": 15.0}, {"rb2": 9.0}]
    got = op.boosts(BOARD, {"rb1": 6}, weeks_left=12, depth=DEPTH, played=played,
                    sleeper_weeks=sleeper, coeffs=COEFFS)
    absorbed = 0.5 * 2 / (3 + 5) + 0.5 * 1 / 3
    assert got["rb2"]["full"] == pytest.approx(4.8)
    assert got["rb2"]["add"] == pytest.approx(4.8 * (1 - absorbed), abs=0.01)


def test_a_player_out_since_before_the_season_is_already_priced():
    played = pd.DataFrame({"week": [1, 2], "sleeper_id": ["rb2", "rb2"], "team": ["MIA"] * 2})
    assert op.boosts(BOARD, {"rb1": 6}, weeks_left=12, depth=DEPTH, played=played,
                     coeffs=COEFFS) == {}


def test_without_a_depth_chart_real_projections_outrank_the_replacement_floor():
    board = _board([("rb1", "RB", "NYJ", 15.0), ("floor", "RB", "NYJ", 9.6, 0.0),
                    ("rb2", "RB", "NYJ", 6.0)])
    got = op.boosts(board, {"rb1": 3}, weeks_left=10, coeffs=COEFFS)
    assert got["rb2"]["full"] == pytest.approx(0.3 * 15.0)
    assert got["floor"]["full"] == pytest.approx(0.1 * 15.0)


def test_apply_moves_mu_by_the_season_average():
    result = {"rb2": {"season": 2.4}, "wr1": {"season": -20.0}}
    out = op.apply(BOARD, result).set_index("sleeper_id")["mu"]
    assert out["rb2"] == pytest.approx(8.4)
    assert out["wr1"] == 0.0                                 # never below zero
    assert out["rb1"] == 16.0


def test_depth_charts_read_sleepers_order():
    raw = {"1": {"team": "MIA", "position": "RB", "depth_chart_order": 2},
           "2": {"team": "MIA", "position": "RB", "depth_chart_order": 1},
           "3": {"team": "MIA", "position": "K", "depth_chart_order": 1},
           "4": {"team": None, "position": "RB", "depth_chart_order": 1},
           "5": {"team": "MIA", "position": "WR", "depth_chart_order": None}}
    assert op.depth_charts(raw) == {"MIA": {"RB": ["2", "1"]}}
