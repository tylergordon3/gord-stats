"""
Back from injury (fantasy.league.return_dip): what a player scores in his
first games after one, measured on history and taken off the projections.

The history tests build small seasons whose answer is known - returning
players who score exactly four fifths of their line in their first game back -
and check the measurement gets it back, with the absences told apart the way
the measurement needs (a bye is not a game missed, a trade is not an absence,
an illness is not an injury). The application tests pin the rules a reader
would notice: who is coming back and when, the bye in the way, the weeks
already missed counted in, Sleeper's own discount not taken twice, and the
season average the simulations take. No network: every input is a fixture.
"""
import numpy as np
import pandas as pd
import pytest

from fantasy.league import availability
from fantasy.league import return_dip as rd


# --------------------------------------------------------------------------- #
# The table
# --------------------------------------------------------------------------- #

def test_the_table_only_takes_points_off_and_only_where_measured():
    assert set(rd.TABLE) <= {1, 2}
    for games in rd.TABLE.values():
        assert set(games) <= {1, 2}
        assert all(-0.3 < v < 0 for v in games.values())
    assert rd.dip(1, 1) == rd.TABLE[1][1]
    assert rd.dip(2, 1) == rd.dip(9, 1) == rd.TABLE[2][1]
    assert rd.dip(1, 2) == 0.0                  # not told from nothing: not shipped
    assert rd.dip(3, 3) == 0.0 and rd.dip(0, 1) == 0.0
    assert rd.dip(2, 1) < rd.dip(1, 1)          # longer out, bigger first-game dip


@pytest.mark.parametrize("text, kind", [
    ("Right Hamstring", "hamstring"), ("Knee - ACL", "knee"), ("Shoulder - AC Joint", "shoulder"),
    ("Ankle", "ankle"), ("Toe", "foot"), ("Head", "concussion"), ("Concussion", "concussion"),
    ("Groin", "groin"), ("Calf", "calf"), ("Back", "back"), ("Achilles", "other"),
    ("Wrist", "other"), ("Chest", "other"), ("Quadricep", "other"),
    ("Illness", "not injury"), ("Not injury related - resting player", "not injury"),
    ("Personal", "not injury"), ("Coach's Decision", "not injury"),
    (None, None), ("", None), (float("nan"), None)])
def test_report_text_is_read_as_an_injury_type(text, kind):
    assert rd.injury_type(text) == kind


# --------------------------------------------------------------------------- #
# History
# --------------------------------------------------------------------------- #

def test_player_games_counts_a_snap_without_a_stat_as_a_zero():
    weekly = pd.DataFrame([
        {"season": 2021, "week": 1, "team": "LAR", "gsis_id": "g1", "position": "RB",
         "fantasy_points": 10.0, "fantasy_points_ppr": 12.0},
        {"season": 2020, "week": 17, "team": "KC", "gsis_id": "g3", "position": "WR",
         "fantasy_points": 9.0, "fantasy_points_ppr": 9.0},          # rested-starter finale
        {"season": 2021, "week": 1, "team": "LAR", "gsis_id": "g4", "position": "FB",
         "fantasy_points": 1.0, "fantasy_points_ppr": 1.0}])
    snaps = pd.DataFrame([
        {"season": 2021, "week": 1, "team": "LA", "pfr_player_id": "p1", "position": "RB",
         "offense_snaps": 40, "offense_pct": 0.6, "game_type": "REG"},
        {"season": 2021, "week": 1, "team": "LA", "pfr_player_id": "p2", "position": "WR",
         "offense_snaps": 12, "offense_pct": 0.2, "game_type": "REG"},   # played, no stat row
        {"season": 2021, "week": 1, "team": "LA", "pfr_player_id": "p5", "position": "WR",
         "offense_snaps": 0, "offense_pct": 0.0, "game_type": "REG"},    # dressed only
        {"season": 2021, "week": 19, "team": "LA", "pfr_player_id": "p1", "position": "RB",
         "offense_snaps": 30, "offense_pct": 0.5, "game_type": "WC"}])
    ids = pd.DataFrame({"pfr_id": ["p1", "p2", "p5"], "gsis_id": ["g1", "g2", "g5"]})
    got = rd.player_games(weekly, snaps, ids).set_index("gsis_id")
    assert sorted(got.index) == ["g1", "g2", "g4"]
    assert got.loc["g2", "ppr"] == 0.0 and got.loc["g2", "team"] == "LAR"
    assert got.loc["g1", "half"] == 11.0 and got.loc["g1", "snap"] == 0.6
    assert got.loc["g4", "pos"] == "RB" and np.isnan(got.loc["g4", "snap"])


def _games(season, team, gsis, weeks, pts=12.0, pos="WR", first_back=None):
    """Rows of games for one player; `first_back` = (week, points) overrides one."""
    rows = []
    for w in weeks:
        p = first_back[1] if first_back and w == first_back[0] else pts
        rows.append({"season": season, "week": w, "team": team, "gsis_id": gsis, "pos": pos,
                     "ppr": p, "half": p - 1.0, "snap": 0.8})
    return rows


def test_absences_skip_byes_and_trades_and_name_the_cause():
    weeks = {(2021, "AAA"): [1, 2, 3, 4, 5, 6, 8, 9, 10], (2021, "BBB"): list(range(1, 11))}
    games = pd.DataFrame(
        _games(2021, "AAA", "hurt", [1, 2, 3, 6, 8, 9, 10])          # misses 4-5, bye 7
        + _games(2021, "AAA", "benched", [1, 2, 3, 5, 6])            # misses 4, nobody says why
        + _games(2021, "AAA", "sick", [1, 2, 4, 5])                  # misses 3: illness
        + _games(2021, "AAA", "covid", [1, 2, 4, 5])                 # misses 3: COVID list
        + _games(2021, "AAA", "traded", [1, 2])
        + _games(2021, "BBB", "traded", [5, 6])                      # a trade, not an absence
        + _games(2021, "AAA", "ir", [1, 6, 8]))                      # IR 2-5, no report text
    reports = {(2021, 4, "hurt"): {"status": "Out", "type": "hamstring"},
               (2021, 5, "hurt"): {"status": "Out", "type": "hamstring"},
               (2021, 3, "sick"): {"status": "Out", "type": "not injury"},
               (2021, 3, "covid"): {"status": None, "type": None, "roster": "RES",
                                    "code": "R62"},
               **{(2021, w, "ir"): {"status": None, "type": None, "roster": "RES",
                                    "code": "R01"} for w in (2, 3, 4, 5)}}
    gone = rd.absences(pd.DataFrame(games), weeks, reports).set_index("gsis_id")
    assert "traded" not in gone.index
    hurt = gone.loc["hurt"]
    assert (hurt["missed"], hurt["cause"], hurt["type"]) == (2, "injury", "hamstring")
    assert hurt["games"] == [6, 8, 9]                                # the bye is not a game
    assert gone.loc["benched", "cause"] == "unlisted"
    assert gone.loc["sick", "cause"] == "not injury"
    assert gone.loc["covid", "cause"] == "not injury"
    ir = gone.loc["ir"]
    assert (ir["missed"], ir["cause"], ir["type"], ir["games"]) == (4, "injury", "unknown", [6, 8])


def test_games_back_stop_at_the_next_game_missed():
    weeks = {(2021, "AAA"): list(range(1, 11))}
    games = pd.DataFrame(_games(2021, "AAA", "x", [1, 2, 4, 6, 7]))
    reports = {(2021, 3, "x"): {"status": "Out", "type": "ankle"},
               (2021, 5, "x"): {"status": "Out", "type": "ankle"}}
    gone = rd.absences(games, weeks, reports)
    assert gone["games"].tolist() == [[4], [6, 7]]


def _league(players=40, seasons=(2020, 2021, 2022, 2023), dip=0.8):
    """Every player scores 12 a game every week; in each season after the
    first, the first `players` miss weeks 5-6 hurt (Out, knee) and score
    12 x `dip` in their first game back. Another `players` never miss."""
    rows, reports, weeks = [], {}, {}
    for season in seasons:
        for t in range(players):
            team = f"T{t:02d}"
            weeks[(season, team)] = list(range(1, 15))
            hurt = season != seasons[0]
            rows += _games(season, team, f"h{t}", [w for w in range(1, 15)
                                                   if not (hurt and w in (5, 6))],
                           first_back=(7, 12.0 * dip) if hurt else None)
            rows += _games(season, team, f"c{t}", range(1, 15))
            if hurt:
                reports.update({(season, w, f"h{t}"): {"status": "Out", "type": "knee"}
                                for w in (5, 6)})
    games = pd.DataFrame(rows)
    gone = rd.absences(games, weeks, reports)
    return rd.observations(games, gone, seasons=seasons[1:])


def test_the_measurement_gets_a_known_dip_back():
    obs = _league()
    first = rd.effect(obs, (obs["k"] == 1) & (obs["cause"] == "injury"), draws=200)
    # Not exactly -20%: last season's dipped game is in this season's prior.
    assert first["effect"] == pytest.approx(-0.2, abs=0.01)
    assert first["hi"] < 0 and first["n"] == 120 and first["players"] == 40
    table, cells = rd.fit_table(obs, draws=200)
    assert table[2][1] == pytest.approx(-0.2, abs=0.01)
    assert 1 not in table and cells[(1, 1)]["n"] == 0                 # nobody missed one game
    # Half-PPR on its own form says the same.
    half = rd.effect(obs, (obs["k"] == 1) & (obs["cause"] == "injury"), y="half",
                     base="form_half", draws=200)
    assert half["effect"] < -0.15


def test_a_game_back_is_never_a_control():
    obs = _league()
    assert set(obs.loc[obs["k"] > 0, "gsis_id"].str[0]) == {"h"}
    assert (obs.loc[obs["k"] == 0, "ppr"] == 12.0).all()


def test_injury_type_adds_nothing_when_every_type_dips_alike():
    obs = _league()
    obs.loc[obs["gsis_id"].str[1:].astype(int) % 2 == 0, "type"] = "hamstring"
    rows, q, df, p = rd.heterogeneity(obs, "type", draws=200)
    assert df == 1 and q == pytest.approx(0.0, abs=1e-6)
    assert {r["type"] for r in rows} == {"knee", "hamstring"}


def test_the_backtest_shows_the_gain_on_returners_and_not_on_controls():
    obs = _league()
    got = rd.backtest(obs, train=(2021, 2022), test=(2023,), draws=200)
    assert got["table"][2][1] == pytest.approx(-0.2, abs=0.01)
    assert got["mae"][1] < got["mae"][0] and got["rmse"][1] < got["rmse"][0]
    assert got["mae_change_95"][1] < 0
    # Controls score their line exactly: shading them only costs.
    assert got["placebo"]["mae_change"] > 0 and got["placebo"]["mse_change"] > 0


# --------------------------------------------------------------------------- #
# Today
# --------------------------------------------------------------------------- #

def _played(rows):
    """[(week, id, team)] -> the played frame."""
    return pd.DataFrame(rows, columns=["week", "sleeper_id", "team"])


def _board(*rows):
    return pd.DataFrame(rows, columns=["sleeper_id", "pos", "mu", "bye"])


def _team_rows(team, weeks, mate="mate"):
    return [(w, f"{mate}-{team}", team) for w in weeks]


def test_state_reads_the_most_recent_absence():
    weeks = [1, 2, 3, 4, 5, 6]
    assert rd._state({1: "A", 2: "A"}, weeks, 5) == (2, 0, [3, 4])      # still out
    assert rd._state({1: "A", 2: "A", 4: "A"}, weeks, 5) == (1, 1, [3])  # back last week
    assert rd._state({1: "A", 2: "A", 3: "A", 4: "A"}, weeks, 5) is None
    assert rd._state({3: "A", 4: "A"}, weeks, 5) is None                 # out before his first
    assert rd._state({1: "B", 4: "A"}, weeks, 5) is None                 # traded, not hurt
    listed = lambda w: w == 3                                            # noqa: E731
    assert rd._state({1: "A", 2: "A"}, weeks, 5, listed) == (2, 0, [3, 4])
    assert rd._state({1: "A", 4: "A"}, weeks, 5, lambda w: False) is None


def test_a_held_player_gives_up_his_first_games_back_spread_over_the_season():
    board = _board(("rb", "RB", 15.0, 12))
    played = _played(_team_rows("AAA", [1, 2, 3]) + [(1, "rb", "AAA"), (2, "rb", "AAA")])
    got = rd.dips(board, {"rb": 2}, weeks_left=14, played=played, upcoming=4)["rb"]
    # One missed (week 3) and two to come: two or more, back in two weeks.
    assert got["missed"] == 3
    assert got["games"] == [[1, 2, rd.TABLE[2][1]], [2, 3, rd.TABLE[2][2]]]
    assert got["season"] == pytest.approx((rd.TABLE[2][1] + rd.TABLE[2][2]) / 12, abs=1e-4)
    assert got["week"] == 1.0
    out = rd.apply(board, {"rb": got})
    assert out["mu"].iloc[0] == pytest.approx(15.0 * (1 + got["season"]))


def test_a_bye_inside_the_hold_is_not_a_game_missed_and_one_after_it_waits():
    played = _played(_team_rows("AAA", [1, 2, 3]) + [(w, "wr", "AAA") for w in (1, 2, 3)])
    inside = rd.dips(_board(("wr", "WR", 12.0, 5)), {"wr": 2}, 14, played, upcoming=4)["wr"]
    assert inside["missed"] == 1 and inside["games"] == [[1, 2, rd.TABLE[1][1]]]
    after = rd.dips(_board(("wr", "WR", 12.0, 6)), {"wr": 2}, 14, played, upcoming=4)["wr"]
    assert after["missed"] == 2
    assert [g[:2] for g in after["games"]] == [[1, 3], [2, 4]]         # week 6 is his bye


def test_a_game_past_the_season_is_not_counted():
    played = _played(_team_rows("AAA", [1, 2, 3]) + [(w, "te", "AAA") for w in (1, 2, 3)])
    board = _board(("te", "TE", 10.0, 0))
    assert rd.dips(board, {"te": 5}, weeks_left=5, played=played, upcoming=4) == {}
    last = rd.dips(board, {"te": 4}, weeks_left=5, played=played, upcoming=4)["te"]
    assert [g[0] for g in last["games"]] == [1]


def test_players_out_since_before_the_season_or_not_hurt_or_fringe_are_left_alone():
    played = _played(_team_rows("AAA", [1, 2, 3]) + [(w, "wr", "AAA") for w in (1, 2, 3)]
                     + [(w, "low", "AAA") for w in (1, 2, 3)])
    board = _board(("never", "RB", 14.0, 9), ("wr", "WR", 12.0, 9), ("low", "WR", 3.0, 9),
                   ("k", "K", 8.0, 9))
    held = {"never": 3, "wr": 2, "low": 2, "k": 2}
    got = rd.dips(board, held, 14, played, upcoming=4, skip={"wr"})
    assert got == {}


def test_a_player_due_back_this_week_needs_the_report_to_say_he_was_hurt():
    played = _played(_team_rows("AAA", [1, 2, 3]) + [(w, "qb", "AAA") for w in (1, 2)])
    board = _board(("qb", "QB", 18.0, 10))
    assert rd.dips(board, {}, 14, played, upcoming=4) == {}                        # no reports
    assert rd.dips(board, {}, 14, played, upcoming=4, reports={2: {"qb": {}}}) == {}
    got = rd.dips(board, {}, 14, played, upcoming=4,
                  reports={3: {"qb": {"status": "Out"}}})["qb"]
    assert got["missed"] == 1 and got["games"] == [[1, 0, rd.TABLE[1][1]]]
    assert got["week"] == pytest.approx(1 + rd.TABLE[1][1])
    assert got["season"] == pytest.approx(rd.TABLE[1][1] / 14, abs=1e-4)


def test_the_blended_positions_take_their_dips_too():
    """Sleeper's shaded projections for a game back are in a back's,
    receiver's and tight end's blended rate, and the dip comes off on top:
    replayed on 2019-25 that beat skipping them, and beat leaving his games
    back out of the blend (the module notes, "Sleeper")."""
    played = _played(_team_rows("AAA", [1, 2, 3])
                     + [(w, pid, "AAA") for w in (1,) for pid in ("rb", "qb", "wr")])
    board = _board(("rb", "RB", 14.0, 10), ("qb", "QB", 18.0, 10), ("wr", "WR", 12.0, 10))
    reports = {w: {pid: {"status": "Out"} for pid in ("rb", "qb", "wr")} for w in (2, 3)}
    got = rd.dips(board, {}, 14, played, upcoming=4, reports=reports)
    assert set(got) == {"rb", "qb", "wr"}
    assert got["rb"]["games"][0] == [1, 0, rd.TABLE[2][1]]
    import inspect
    assert "sleeper_weeks" not in inspect.signature(rd.dips).parameters


def test_the_second_game_back_after_two_missed():
    played = _played(_team_rows("AAA", [1, 2, 3, 4]) + [(w, "wr", "AAA") for w in (1, 4)])
    board = _board(("wr", "WR", 12.0, 10))
    got = rd.dips(board, {}, 13, played, upcoming=5,
                  reports={2: {"wr": {"status": "Out"}}})["wr"]
    assert got["games"] == [[2, 0, rd.TABLE[2][2]]]
    assert got["week"] == pytest.approx(1 + rd.TABLE[2][2])
    # One game missed: the second game back was not told from nothing.
    played = _played(_team_rows("AAA", [1, 2, 3, 4]) + [(w, "wr", "AAA") for w in (1, 2, 4)])
    assert rd.dips(board, {}, 13, played, upcoming=5,
                   reports={3: {"wr": {"status": "Out"}}}) == {}


def test_week_factors_are_this_weeks_multipliers_only():
    played = _played(_team_rows("AAA", [1, 2, 3])
                     + [(w, "wr", "AAA") for w in (1,)] + [(w, "rb", "AAA") for w in (1, 2, 3)])
    board = _board(("wr", "WR", 12.0, 10), ("rb", "RB", 14.0, 10))
    reports = {2: {"wr": {"status": "Out"}}, 3: {"wr": {"status": "Out"}}}
    got = rd.week_factors(board, 2026, 4, played=played, reports=reports)
    assert got == {"wr": pytest.approx(1 + rd.TABLE[2][1])}
    # His bye this week: no game back to price.
    assert rd.week_factors(_board(("wr", "WR", 12.0, 4)), 2026, 4, played=played,
                           reports=reports) == {}
    # A suspension is not an injury.
    assert rd.week_factors(board, 2026, 4, played=played, reports=reports,
                           tags={"wr": "Sus"}) == {}


def test_availability_takes_the_dip_off_the_projection_if_he_plays():
    wk = pd.DataFrame({"proj_week": [10.0, 8.0, 6.0]},
                      index=pd.Index(["a", "b", "c"], name="sleeper_id"))
    chances = {"a": {"p": 0.5}}
    out = availability.apply(wk, chances, dips={"a": 0.8, "b": 0.9})
    assert out["dip"].tolist() == [0.8, 0.9, 1.0]
    assert out["proj_full"].tolist() == pytest.approx([8.0, 7.2, 6.0])
    assert out["proj_week"].tolist() == pytest.approx([4.0, 7.2, 6.0])
    plain = availability.apply(wk, chances)
    assert plain["proj_full"].tolist() == [10.0, 8.0, 6.0] and (plain["dip"] == 1.0).all()
