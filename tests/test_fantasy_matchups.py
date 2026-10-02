"""
The NFL league's weekly matchups page: the feeds behind it, the weekly
projection tilt and the lineup logic.
"""
from datetime import datetime, timezone

import pandas as pd

from fantasy.league import matchups as data_mod
from fantasy.site import matchups as page

SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX", "K", "DEF",
         "BN", "BN", "BN", "BN", "BN"]


def _scoreboard():
    def comp(abbr, side, score):
        return {"homeAway": side, "team": {"abbreviation": abbr}, "score": score}
    return {"events": [
        {"id": "1", "date": "2026-09-10T00:20Z",
         "status": {"type": {"state": "pre", "shortDetail": "9/9 - 8:20 PM EDT"}},
         "competitions": [{"competitors": [comp("SEA", "home", "0"), comp("NE", "away", "0")],
                           "odds": [{"details": "SEA -3.5", "overUnder": 44.5, "spread": -3.5}],
                           "broadcasts": [{"names": ["NBC"]}]}]},
        {"id": "2", "date": "2026-09-13T17:00Z",
         "status": {"type": {"state": "in", "shortDetail": "3rd"}},
         "competitions": [{"competitors": [comp("WSH", "home", "14"), comp("NYG", "away", "7")],
                           "odds": []}]},
    ]}


def test_scoreboard_parse_reads_implied_totals_and_sleeper_team_codes():
    games = data_mod.parse_scoreboard(_scoreboard())
    sea = games[0]
    # A 3.5-point home favourite in a 44.5 game: 24 for the home side, 20.5 away.
    assert sea["home"] == "SEA" and sea["home_implied"] == 24.0 and sea["away_implied"] == 20.5
    assert sea["tv"] == "NBC"
    # ESPN's WSH is Sleeper's WAS, and no odds means no implied total.
    assert games[1]["home"] == "WAS" and games[1]["home_implied"] is None
    by_team = data_mod.team_games(games)
    assert by_team["NYG"]["score_for"] == 7 and by_team["NYG"]["score_against"] == 14
    assert not by_team["NYG"]["home"]


def test_the_game_clock_comes_off_the_status_not_its_type():
    """ESPN puts period and displayClock beside status.type. Read off the
    type they were None, and every game in play read as half over."""
    data = {"events": [{"id": "9", "date": "2026-09-27T20:25Z",
                        "status": {"period": 4, "displayClock": "2:50",
                                   "type": {"state": "in", "shortDetail": "2:50 - 4th"}},
                        "competitions": [{"competitors": [
                            {"homeAway": "home", "score": "29", "team": {"abbreviation": "SF"}},
                            {"homeAway": "away", "score": "27", "team": {"abbreviation": "ARI"}}],
                            "odds": []}]}]}
    game = data_mod.parse_scoreboard(data)[0]
    assert (game["period"], game["clock"]) == (4, "2:50")
    assert abs(data_mod.elapsed(game) - (57 + 10 / 60) / 60) < 1e-9


def test_active_sees_a_game_in_progress_or_about_to_kick():
    games = data_mod.parse_scoreboard(_scoreboard())
    assert data_mod.active(games)
    pre = [g for g in games if g["state"] == "pre"]
    kick = datetime(2026, 9, 10, 0, 20, tzinfo=timezone.utc)
    assert data_mod.active(pre, now=kick.replace(hour=0, minute=0))
    assert not data_mod.active(pre, now=kick.replace(day=9, hour=12))


def test_week_final_needs_every_game_over_and_every_side_scored():
    sides = [{"points": 101.2}, {"points": 88.0}]
    done = {"games": [{"state": "post"}], "matchups": [{"sides": sides}]}
    assert data_mod.week_final(done)
    assert not data_mod.week_final({**done, "games": [{"state": "post"}, {"state": "in"}]})
    assert not data_mod.week_final({**done, "matchups": [{"sides": [{"points": 0}, sides[1]]}]})
    assert not data_mod.week_final({"games": [], "matchups": [{"sides": sides}]})


def test_week_projection_tilts_by_implied_total_and_zeroes_a_bye():
    games = data_mod.parse_scoreboard(_scoreboard())
    board = pd.DataFrame({
        "sleeper_id": ["1", "2", "3", "4"], "pos": ["QB", "QB", "DEF", "RB"],
        "team": ["SEA", "NE", "NE", "DET"], "mu": [20.0, 20.0, 8.0, 15.0],
    })
    wk = data_mod.week_projections(board, games)
    # SEA implied 24 against a 22.25 average lifts; NE at 20.5 lowers.
    assert wk.loc["1", "proj_week"] > 20.0 > wk.loc["2", "proj_week"]
    # A defense facing the 24-point side is tilted down.
    assert wk.loc["3", "proj_week"] < 8.0
    # Detroit has no game this week.
    assert wk.loc["4", "proj_week"] == 0.0 and wk.loc["4", "n_games"] == 0


def test_roster_rows_follow_sleeper_slot_order_then_bench_then_ir():
    side = {"starters": ["q", "r1", "r2", "w1", "w2", "t", "f1", "0", "k", "SEA"],
            "players": ["q", "r1", "r2", "w1", "w2", "t", "f1", "k", "SEA", "b1", "ir1"]}
    rows = page.roster_rows(side, reserve=["ir1"], roster_positions=SLOTS)
    assert [r["slot"] for r in rows] == ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX",
                                         "K", "DEF", "BN", "IR"]
    assert rows[7]["pid"] == "0" and rows[-1]["pid"] == "ir1"


def test_best_lineup_promotes_a_bench_back_over_a_weak_flex():
    side = {"starters": ["q", "r1", "r2", "w1", "w2", "t", "f1", "f2", "k", "SEA"],
            "players": ["q", "r1", "r2", "w1", "w2", "t", "f1", "f2", "k", "SEA", "b1", "ir1"]}
    rows = page.roster_rows(side, reserve=["ir1"], roster_positions=SLOTS)
    pos = {"q": "QB", "r1": "RB", "r2": "RB", "w1": "WR", "w2": "WR", "t": "TE",
           "f1": "RB", "f2": "WR", "k": "K", "SEA": "DEF", "b1": "RB", "ir1": "WR"}
    cards = {p: {"pos": v} for p, v in pos.items()}
    proj = {p: 10.0 for p in pos}
    proj.update({"f1": 4.0, "b1": 12.0, "ir1": 40.0})
    best = page.best_lineup(rows, cards, proj, SLOTS)
    assert "b1" in best and "f1" not in best and "ir1" not in best and len(best) == 10


def test_stat_line_by_position():
    assert page.stat_line({"rush_att": 18, "rush_yd": 169, "rush_td": 2, "rec": 1,
                           "rec_tgt": 1, "rec_yd": 13, "fum_lost": 1}, "RB") == \
        "18 car, 169 rush yds, 2 TD, 1 rec (1 tgt), 13 rec yds, 1 fum lost"
    assert page.stat_line({"fgm": 2, "fga": 3, "xpm": 4, "xpa": 4}, "K") == "2/3 FG, 4/4 XP"
    assert page.stat_line({"pts_allow": 17, "sack": 3, "int": 1}, "DEF") == "17 PA, 3 sk, 1 INT"


def test_game_cell_from_the_players_side():
    games = data_mod.parse_scoreboard(_scoreboard())
    by_team = data_mod.team_games(games)
    assert "vs NE · Wed 8:20p" in page.game_cell(by_team["SEA"])
    assert "Live 7–14" in page.game_cell(by_team["NYG"]) and "at WAS" in page.game_cell(by_team["NYG"])
    assert "Bye" in page.game_cell(None)


def _week_data():
    return {
        "week": 1, "games": [], "roster_positions": SLOTS,
        "teams": {"1": {"name": "A"}, "2": {"name": "B"}},
        "matchups": [{"matchup_id": 1, "sides": [
            {"roster_id": 1, "points": 0, "starters": ["q", "0"], "players": ["q", "b1"],
             "players_points": {}},
            {"roster_id": 2, "points": 0, "starters": ["q2"], "players": ["q2"],
             "players_points": {}}]}],
        "projections": {"q": {"pts": 20.0}, "b1": {"pts": 8.0}, "q2": {"pts": None}},
        "external": {"espn": {"q": 22.0, "q2": 15.0}, "fp": {"q": 21.0}},
    }


def test_outside_sources_keep_a_fixed_order_and_skip_empty_ones():
    src = page.outside_sources(_week_data())
    assert list(src) == ["sleeper", "espn", "fp"]
    assert src["sleeper"] == {"q": 20.0, "b1": 8.0}      # a None projection is not one
    assert list(page.outside_sources({"projections": {}, "external": {"fp": {}}})) == ["sleeper"]


def test_disagreements_rank_by_the_gap_to_the_nearest_source():
    data = _week_data()
    data["external"]["espn"]["b1"] = 8.0          # b1 now has two sources, q2 still one
    wk = pd.DataFrame({"proj_week": [30.0, 8.0, 10.0]}, index=["q", "b1", "q2"])
    ctx = {"wk": wk, "board": {"q": {"player": "Quarterback", "pos": "QB", "team": "KC"},
                                "b1": {"player": "Bench", "pos": "RB", "team": "DET"},
                                "q2": {"player": "Other", "pos": "QB", "team": "SF"}},
           "registry": {}}
    rows = page.disagreements(data, ctx)
    # q: ours 30 against 20/22/21 - nearest source 8 away, consensus gap +9.
    # b1: 8 against 8/8 - no disagreement. q2 has one source and is not judged.
    assert [r["pid"] for r in rows] == ["q", "b1"]
    assert rows[0]["nearest"] == 8.0 and rows[0]["gap"] == 9.0
    assert rows[0]["owner"] == "A" and rows[0]["slot"] == "QB" and rows[1]["slot"] == "BN"
    # One site seeing it our way takes a player off the top, however far the
    # average sits: with ESPN at 29 the consensus gap is still +6.7 but the
    # nearest source is a point away.
    data["external"]["espn"]["q"] = 29.0
    rows = page.disagreements(data, ctx)
    assert rows[0]["pid"] == "q" and rows[0]["nearest"] == 1.0 and round(rows[0]["gap"], 1) == 6.7


def test_week_projection_zeroes_a_player_sleeper_rules_out():
    from fantasy.league import matchups as data_mod
    board = pd.DataFrame({"sleeper_id": ["a", "b", "c"], "team": ["KC", "KC", "KC"],
                          "pos": ["RB", "RB", "RB"], "mu": [12.0, 12.0, 12.0]})
    games = [{"game_id": "1", "date": "2026-09-13T17:00Z", "home": "KC", "away": "SF",
              "home_score": None, "away_score": None, "home_implied": 24.0,
              "away_implied": 24.0, "state": "pre", "detail": ""}]
    wk = data_mod.week_projections(board, games, injuries={"a": "Out", "b": "Doubtful"})
    assert wk.loc["a", "proj_week"] == 0.0
    # Doubtful: 1% of them played, 2016-2025.
    assert abs(wk.loc["b", "proj_week"] - 0.12) < 1e-9 and wk.loc["c", "proj_week"] == 12.0