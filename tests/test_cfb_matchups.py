"""
The weekly matchups page: Yahoo's per-week roster feed, the weekly projection
and the lineup logic on top of it.
"""
import pandas as pd
import pytest

from cfb import weekly, yahoo
from cfb.site import matchups


LEAGUE = {"roster": [{"position": "QB", "count": 2}, {"position": "RB", "count": 2},
                     {"position": "WR", "count": 3}, {"position": "TE", "count": 1},
                     {"position": "W/R/T", "count": 2}, {"position": "DEF", "count": 1},
                     {"position": "BN", "count": 6}, {"position": "IL", "count": 2}]}


def _player(pid, pos, slot, name=None):
    return {"yahoo_id": pid, "player": name or f"P{pid}", "pos": pos, "slot": slot,
            "team": "X", "team_full": "X", "points": 0.0, "stats": {}, "status": ""}


# --------------------------------------------------------------------------- #
# Yahoo's roster payload
# --------------------------------------------------------------------------- #

def _roster_payload():
    """A team/<key>/roster;week=1/players/stats payload, in Yahoo's shape."""
    def player(pid, name, pos, slot, pts, stats):
        return {"player": [
            [{"player_key": f"474.p.{pid}"}, {"player_id": pid},
             {"name": {"full": name}}, {"editorial_team_abbr": "RUTG"},
             {"editorial_team_full_name": "Rutgers Scarlet Knights"},
             {"bye_weeks": {"week": "6"}}, {"display_position": pos}, []],
            {"selected_position": [{"coverage_type": "week", "week": "1"},
                                   {"position": slot}, {"is_flex": 0}]},
            {"player_stats": {"0": {"coverage_type": "week"},
                              "stats": [{"stat": {"stat_id": k, "value": v}}
                                        for k, v in stats.items()]},
             "player_points": {"0": {"coverage_type": "week"}, "total": pts}}]}
    return {"fantasy_content": {"team": [
        [{"team_key": "474.l.21318.t.9"}, {"name": "Benjamin Brahman"}],
        {"roster": {"coverage_type": "week", "week": "1", "0": {"players": {
            "0": player("463126", "Antwan Raymond", "RB", "RB", "5.50",
                        {"8": "13", "9": "37", "11": "2", "12": "8", "13": 0}),
            "1": player("900001", "Rutgers", "DEF", "BN", "0.00", {"31": 0}),
            "count": 2}}}}]}}


def test_roster_parse_reads_slot_points_and_nonzero_stats():
    rows = yahoo._parse_team_roster(_roster_payload())
    assert [r["player"] for r in rows] == ["Antwan Raymond", "Rutgers"]
    rb = rows[0]
    assert rb["slot"] == "RB" and rb["points"] == 5.5 and rb["bye"] == 6
    # Zero-valued stats are the noise Yahoo pads every line with.
    assert rb["stats"] == {"8": 13, "9": 37, "11": 2, "12": 8}
    assert rows[1]["slot"] == "BN" and rows[1]["stats"] == {}


def test_week_final_needs_every_matchup_finished():
    assert not yahoo.week_final({"matchups": []})
    assert not yahoo.week_final({"matchups": [{"status": "postevent"}, {"status": "midevent"}]})
    assert yahoo.week_final({"matchups": [{"status": "postevent"}, {"status": "postevent"}]})


# --------------------------------------------------------------------------- #
# The week's games
# --------------------------------------------------------------------------- #

def test_week_window_excludes_the_week_zero_slate():
    """ESPN's week 1 starts on the Week 0 Saturday; Yahoo's starts the
    following Thursday. A game on Aug 29 must not score in Yahoo's week 1."""
    frame = pd.DataFrame({
        "date": pd.to_datetime(["2026-08-29T16:00Z", "2026-09-03T22:00Z",
                                "2026-09-05T19:30Z", "2026-09-08T00:30Z"]),
        "game_id": ["a", "b", "c", "d"],
        "home": ["TCU", "Rutgers", "Utah", "Late"], "away": ["UNC", "UMass", "Idaho", "Team"],
        "home_id": ["2628", "164", "254", "1"], "away_id": ["153", "113", "70", "2"],
        "pred_home": [30.0, 45.0, 40.0, 20.0], "pred_away": [24.0, 10.0, 14.0, 20.0],
        "state": ["post", "in", "pre", "pre"],
    })
    games = weekly.games_between(frame, "2026-09-03", "2026-09-07")
    # Sept 8 00:30 UTC is Sept 7 evening in the league's zone - still the week.
    assert list(games["game_id"]) == ["b", "c", "d"]
    by_team = weekly.team_games(games)
    assert by_team["164"][0]["home"] and by_team["164"][0]["opp"] == "UMass"
    assert by_team["113"][0]["pred_for"] == 10.0 and by_team["113"][0]["pred_against"] == 45.0


# --------------------------------------------------------------------------- #
# Lineup order and the best lineup
# --------------------------------------------------------------------------- #

def test_roster_orders_by_slot_with_bench_last():
    players = [_player("1", "RB", "BN"), _player("2", "DEF", "DEF"), _player("3", "QB", "QB"),
               _player("4", "WR", "W/R/T"), _player("5", "TE", "IL"), _player("6", "RB", "RB")]
    order = [p["slot"] for p in matchups.order_roster(players, LEAGUE)]
    assert order == ["QB", "RB", "W/R/T", "DEF", "BN", "IL"]


def test_best_lineup_promotes_the_bench_player_who_projects_higher():
    players = [_player("q1", "QB", "QB"), _player("q2", "QB", "QB"),
               _player("r1", "RB", "RB"), _player("r2", "RB", "RB"),
               _player("w1", "WR", "WR"), _player("w2", "WR", "WR"), _player("w3", "WR", "WR"),
               _player("t1", "TE", "TE"), _player("f1", "RB", "W/R/T"), _player("f2", "WR", "W/R/T"),
               _player("d1", "DEF", "DEF"),
               _player("b1", "RB", "BN"), _player("b2", "WR", "BN"), _player("il", "WR", "IL")]
    proj = {p["yahoo_id"]: 10.0 for p in players}
    proj["f1"] = 4.0          # a flex starter on a bad week
    proj["b1"] = 12.0         # the bench back who should replace him
    proj["il"] = 50.0         # can't be started from the injured list
    best = matchups.best_lineup(players, LEAGUE, proj)
    assert "b1" in best and "f1" not in best and "il" not in best
    assert len(best) == 11


def test_best_lineup_treats_a_missing_projection_as_zero():
    players = [_player("q1", "QB", "QB"), _player("q2", "QB", "QB"), _player("q3", "QB", "BN")]
    best = matchups.best_lineup(players, LEAGUE, {"q1": None, "q2": 3.0, "q3": 5.0})
    assert best == {"q2", "q3"}


# --------------------------------------------------------------------------- #
# Cells
# --------------------------------------------------------------------------- #

def test_stat_line_groups_by_phase_and_skips_zeros():
    line = matchups.stat_line({"8": 13, "9": 37, "11": 2, "12": 8, "13": 0}, "RB")
    assert line == "13 car, 37 rush yds, 2 rec, 8 rec yds"
    assert matchups.stat_line({"4": 245, "5": 2, "6": 1}, "QB") == "245 pass yds, 2 TD, 1 INT"
    assert matchups.stat_line({"31": 17, "32": 3, "33": 1}, "DEF") == "17 PA, 3 sk, 1 INT"
    # An offensive id on a defense line, or vice versa, is not shown.
    assert matchups.stat_line({"4": 245}, "DEF") == ""


@pytest.mark.parametrize("state,score,expect", [
    ("pre", (None, None), "vs Idaho · Sat 3:30p"),
    ("in", (14.0, 7.0), "Live 14–7"),
    ("post", (40.0, 14.0), "W 40–14"),
    ("post", (10.0, 14.0), "L 10–14"),
])
def test_game_cell_reads_from_the_players_side(state, score, expect):
    g = pd.Series({"opp": "Idaho", "home": True, "state": state, "opp_rank": None,
                   "kickoff": pd.Timestamp("2026-09-05T19:30Z"),
                   "score_for": score[0], "score_against": score[1]})
    assert expect in matchups.game_cell(g)


def test_game_cell_says_bye_without_a_game():
    assert "Bye" in matchups.game_cell(None)
    assert "Bye" in matchups.game_cell(pd.Series({"opp": None, "proj_week": 0.0}))
