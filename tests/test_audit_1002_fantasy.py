"""
The 2026-10-02 audit's fantasy fixes, each pinned where it was found.

  * The playoff bracket is reseeded, as the league plays it (Sleeper's
    playoff_seed_type 1), and the rounds Sleeper has decided stand - in
    fantasy.league.power and in its browser twin, gordstats.my_power.
  * A tie is half a win: head to head, against the median, in the all-play.
  * Disagreements compare a Doubtful player's expected points, not 1% of
    them blown up; a started player with no pre-game number is not a call.
  * A week rebuilt without a pre-game record does not zero a player seen
    playing; a frozen projection keeps the chance it was priced at.
  * The power page's stakes read a refreshed archive; the injury report's
    fallback copy has an age limit; an injury after a player's game in the
    week the model has not counted yet starts the week after.
  * Readers' leagues: the play chance is spent once a player is seen; an
    unread league is PPR, not standard.
  * The trade page: IR players never start or count against the active
    limit, every rostered player draws in every run, a new deal stops the
    old one's Worker, an undrafted league says so.
  * The matchups page polls one week, the one it opens on, and a failed
    live read is no update rather than a page of zeroes.

Python parts run anywhere; the JS parts run in headless Chromium and skip
where there is none (the build machine has no node).
"""
import asyncio
import json
import os
import re
import shutil
import subprocess
import time
import urllib.request

import numpy as np
import pandas as pd
import pytest

from fantasy.league import injury_report as ir
from fantasy.league import power

CHROME = next((p for p in ("/usr/bin/chromium-browser", "/usr/bin/chromium",
                           "/usr/bin/google-chrome") if shutil.which(p)), None)
needs_chrome = pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")
PORT = 9497

# 2024-25, as Sleeper has it: seeds (roster ids, best first) from the week-14
# standings, the round-one and round-two scores, and the winners bracket.
SEEDS_2425 = [1, 5, 2, 8, 3, 10]
R1_2425 = {3: 151.76, 8: 155.1, 2: 113.96, 10: 129.18}
R2_2425 = {1: 190.52, 10: 185.52, 5: 162.38, 8: 148.08}
BRACKET_2425 = [
    {"m": 1, "r": 1, "l": 3, "w": 8, "t1": 8, "t2": 3},
    {"m": 2, "r": 1, "l": 2, "w": 10, "t1": 10, "t2": 2},
    {"m": 3, "r": 2, "l": 10, "w": 1, "t1": 1, "t2": 10},
    {"m": 4, "r": 2, "l": 8, "w": 5, "t1": 5, "t2": 8},
    {"p": 5, "m": 5, "r": 2, "l": 2, "w": 3, "t1": 2, "t2": 3},
    {"p": 1, "m": 6, "r": 3, "l": 5, "w": 1, "t1": 1, "t2": 5,
     "t2_from": {"w": 4}, "t1_from": {"w": 3}},
    {"p": 3, "m": 7, "r": 3, "l": 8, "w": 10, "t1": 10, "t2": 8,
     "t2_from": {"l": 4}, "t1_from": {"l": 3}}]
ORDER = list(range(1, 11))                  # roster ids, ascending: index = id - 1


def _old_fixed_bracket(points, seeds):
    """The bracket the module hardcoded before the audit, for comparison."""
    rows = np.arange(seeds.shape[0])

    def better(week, left, right):
        return np.where(points[rows, week, left] >= points[rows, week, right], left, right)

    qa = better(0, seeds[:, 2], seeds[:, 5])
    qb = better(0, seeds[:, 3], seeds[:, 4])
    return better(2, better(1, seeds[:, 0], qb), better(1, seeds[:, 1], qa))


# --------------------------------------------------------------------------- #
# 1. The bracket
# --------------------------------------------------------------------------- #

def _finalist_test_points(seeds, r1, r2):
    """One sim of real round-one and round-two scores and a final the worse
    seed of the two finalists wins - so the champion names who got there."""
    pts = np.zeros((1, 3, 10))
    for rid, v in r1.items():
        pts[0, 0, rid - 1] = v
    for rid, v in r2.items():
        pts[0, 1, rid - 1] = v
    for k, rid in enumerate(seeds):
        pts[0, 2, rid - 1] = k + 1
    return pts, np.array([[rid - 1 for rid in seeds]])


def test_the_reseeded_bracket_is_the_one_sleeper_played():
    """2024-25: the 6 seed (roster 10) won its quarter and met the 1 seed, as
    Sleeper drew it; the fixed bracket sent it to the 2 seed instead, and on
    the real scores into the final."""
    pts, seeds = _finalist_test_points(SEEDS_2425, R1_2425, R2_2425)
    reseeded = int(power._bracket(pts, seeds, reseed=True)[0]) + 1
    fixed = int(power._bracket(pts, seeds, reseed=False)[0]) + 1
    assert reseeded == 5, "the real final was 1 v 5"
    assert fixed == 10, "the fixed bracket puts the eliminated 6 seed in the final"


def test_the_fixed_bracket_is_the_one_it_always_was():
    rng = np.random.default_rng(7)
    points = rng.gamma(9, 12, size=(400, 3, 10))
    seeds = np.array([rng.permutation(10)[:6] for _ in range(400)])
    assert (power._bracket(points, seeds) == _old_fixed_bracket(points, seeds)).all()


def test_bracket_losers_are_the_elimination_games_only():
    """The fifth-place and third-place games are in the same bracket; a game
    between two teams already beaten is one of those and is not read."""
    got = power.bracket_losers(ORDER, rows=BRACKET_2425)
    assert got == [[3 - 1, 2 - 1], [10 - 1, 8 - 1], [5 - 1]]
    assert power.bracket_losers(ORDER, rows=[{"r": 1, "t1": 1, "t2": 2, "w": None}]) is None


def test_a_decided_round_stands_whatever_the_seeding_says():
    """Seeds the simulation got wrong (on a tie break, say) still send the
    teams Sleeper sent through: the losers lose every round from theirs."""
    pts, _ = _finalist_test_points(SEEDS_2425, R1_2425, R2_2425)
    pts[0, 2, :] = 100.0
    pts[0, 2, 10 - 1] = 500.0                       # the eliminated 6 seed "scores" most
    wrong = np.array([[1 - 1, 5 - 1, 3 - 1, 8 - 1, 2 - 1, 10 - 1]])   # 2 and 3 swapped
    decided = power.bracket_losers(ORDER, rows=BRACKET_2425)
    assert int(power._bracket(pts, wrong, reseed=True, decided=decided)[0]) == 1 - 1


def _league(teams=10):
    rows, held, pid = [], [], 0
    for team in range(teams):
        for pos in ("QB", "RB", "RB", "WR", "WR", "WR", "TE", "K", "DEF"):
            pid += 1
            rows.append({"sleeper_id": str(pid), "pos": pos, "bye": 7, "mu": 10.0,
                         "sd": 5.0, "mu_se": 1.0, "avail": 0.9})
            held.append({"roster_id": team + 1, "sleeper_id": str(pid)})
    return pd.DataFrame(rows), pd.DataFrame(held)


def _schedule(weeks, teams=10):
    table, rotating = [], list(range(1, teams))
    for _ in range(weeks):
        pairs = [(0, rotating[0])] + [(rotating[i], rotating[-i]) for i in range(1, teams // 2)]
        week = [0] * teams
        for a, b in pairs:
            week[a], week[b] = b, a
        table.append(week)
        rotating = rotating[1:] + rotating[:1]
    return np.array(table)


def test_after_the_semis_only_the_finalists_hold_title_odds():
    """Weeks 15 and 16 played: the simulation takes Sleeper's bracket as it
    stands, so an eliminated team holds nothing and the final is a coin flip
    between the two left."""
    board, rosters = _league()
    weeks = power.FANTASY_REG_WEEKS
    seeds_by_index = [rid - 1 for rid in SEEDS_2425]
    regular = np.full((weeks, 10), 80.0)
    for k, i in enumerate(seeds_by_index):
        regular[:, i] = 140.0 - 5 * k                   # the seeds, in order
    playoff = np.zeros((2, 10))
    for rid, v in R1_2425.items():
        playoff[0, rid - 1] = v
    for rid, v in R2_2425.items():
        playoff[1, rid - 1] = v
    decided = power.bracket_losers(ORDER, rows=[m for m in BRACKET_2425 if m["r"] < 3])
    got = power.simulate(board, rosters, sims=300, fixed_schedule=_schedule(weeks),
                         actual_points=regular, playoff_points=playoff, reseed=True,
                         decided=decided)
    odds = dict(zip(got["roster_id"], got["title_odds"]))
    assert set(k for k, v in odds.items() if v > 0) == {1, 5}, odds
    assert abs(sum(odds.values()) - 1) < 1e-9


def test_league_rules_come_from_sleeper_with_the_leagues_own_as_fallback(monkeypatch):
    monkeypatch.setattr(power, "_get", lambda url: {"settings": {
        "playoff_week_start": 16, "playoff_teams": 8, "playoff_seed_type": 0}})
    assert power.league_rules("x") == {"weeks": 15, "playoff_teams": 8, "reseed": False}

    def down(url):
        raise RuntimeError("sleeper down")
    monkeypatch.setattr(power, "_get", down)
    assert power.league_rules("x") == {"weeks": power.FANTASY_REG_WEEKS,
                                       "playoff_teams": power.PLAYOFF_TEAMS,
                                       "reseed": power.RESEED}


def test_an_eight_team_field_plays_three_rounds_and_everyone_can_win():
    board, rosters = _league(12)
    got = power.simulate(board, rosters, sims=400, playoff_teams=8, reseed=True)
    assert abs(got["playoff_odds"].sum() - 8) < 1e-9
    assert abs(got["title_odds"].sum() - 1) < 1e-9
    assert power.bracket_rounds(8) == 3 and power.bracket_rounds(6) == 3
    assert power.bracket_rounds(4) == 2 and power.bracket_rounds(12) == 4


# --------------------------------------------------------------------------- #
# 5. Ties
# --------------------------------------------------------------------------- #

def _posted(scores, pairs):
    rows = []
    for mid, (a, b) in enumerate(pairs, 1):
        rows += [{"roster_id": a, "matchup_id": mid, "points": scores[a]},
                 {"roster_id": b, "matchup_id": mid, "points": scores[b]}]
    return {1: rows}


def test_a_tie_is_half_a_win_head_to_head_and_against_the_median():
    # 1 and 2 tie their game; 5 and 6 sit level across the median (the mean
    # of the fifth and sixth scores is their score).
    scores = {1: 100.0, 2: 100.0, 3: 130.0, 4: 90.0, 5: 110.0, 6: 110.0,
              7: 150.0, 8: 80.0, 9: 120.0, 10: 115.0}
    posted = _posted(scores, [(1, 2), (3, 4), (5, 7), (6, 8), (9, 10)])
    got = power.actual_results(through_week=1, posted=posted)
    by = {rid: i for i, rid in enumerate(got["order"])}
    assert got["h2h_wins"][by[1]] == 0.5 and got["h2h_wins"][by[2]] == 0.5
    assert got["median_wins"][by[5]] == 0.5 and got["median_wins"][by[6]] == 0.5
    assert got["median_wins"][by[9]] == 1 and got["median_wins"][by[1]] == 0
    assert got["ties"][by[1]] == 1 and got["ties"][by[5]] == 1 and got["ties"][by[3]] == 0
    assert (got["wins"] + got["losses"] == 2).all()
    # All-play: 5 beats the four below it and is level with 6.
    assert got["allplay_pct"][by[5]] == pytest.approx(4.5 / 9)


def test_the_record_column_writes_a_tie_as_sleeper_does():
    from fantasy.site import power as page
    assert page._wlt(7.5, 6.5, 1) == "7-6-1"
    assert page._wlt(8.0, 6.0, 0) == "8-6"
    assert page._wlt(8.0, 6.0, float("nan")) == "8-6"


def test_the_simulation_counts_a_played_tie_the_same_way():
    """A season played out in full: the simulation's wins are the record,
    ties and all - head-to-head ties and teams level across the median."""
    board, rosters = _league()
    weeks = power.FANTASY_REG_WEEKS
    sched = _schedule(weeks)
    rng = np.random.default_rng(4)
    actual = rng.integers(80, 140, size=(weeks, 10)).astype(float)
    for w in range(weeks):
        actual[w, sched[w][0]] = actual[w, 0]            # 0 ties its game every week
        order = np.argsort(-actual[w])
        actual[w, order[5]] = actual[w, order[4]]         # fifth and sixth level
    posted = {w + 1: [{"roster_id": i + 1, "matchup_id": min(i, int(sched[w][i])) + 1,
                       "points": float(actual[w, i])} for i in range(10)] for w in range(weeks)}
    real = power.actual_results(through_week=weeks, posted=posted)
    assert real["ties"].sum() > weeks * 2
    got = power.simulate(board, rosters, sims=20, fixed_schedule=sched, actual_points=actual)
    sim = dict(zip(got["roster_id"], got["proj_wins"]))
    assert [sim[rid] for rid in real["order"]] == pytest.approx(real["wins"].tolist())


# --------------------------------------------------------------------------- #
# 2-4. Matchups: disagreements, weeks without a pre-game record, frozen chances
# --------------------------------------------------------------------------- #

def _dis_data():
    return {"projections": {"d": {"name": "Doubt Ful", "pos": "QB", "team": "CHI", "pts": 0.0},
                            "q": {"name": "Ques Tion", "pos": "WR", "team": "SF", "pts": 16.0},
                            "late": {"name": "Late Week", "pos": "WR", "team": "KC", "pts": 15.0}},
            "external": {"espn": {"d": 0.0, "q": 16.5, "late": 14.0}},
            "teams": {"1": {"name": "A"}},
            "matchups": [{"sides": [{"roster_id": 1, "starters": ["d", "q", "late"],
                                     "players": ["d", "q", "late"]}]}]}


def test_a_doubtful_player_is_compared_on_expected_points():
    """Week 4's row 1 was Caleb Williams, GS 18.6 against ESPN's 0.0: his
    1.2% chance's 0.22 expected points divided back up by the chance."""
    from fantasy.site import matchups as page
    wk = pd.DataFrame({"proj_week": [0.22, 8.0, 3.0], "p_play": [0.012, 0.5, 0.0],
                       "pregame": [True, True, False]}, index=["d", "q", "late"])
    rows = {r["pid"]: r for r in page.disagreements(_dis_data(),
                                                    {"wk": wk, "board": {}, "registry": {}})}
    assert rows["d"]["gs"] == pytest.approx(0.22), "a Doubtful player read 'if he plays'"
    assert rows["q"]["gs"] == 16.0, "a Questionable one is still read as if he plays"
    assert "late" not in rows, "a number rebuilt after the game is not a call"


def _post_week(stats, pts):
    games = [{"game_id": "1", "date": "2026-09-13T17:00Z", "home": "BAL", "away": "CLE",
              "home_score": 30, "away_score": 10, "home_implied": 24.0, "away_implied": 20.0,
              "state": "post", "detail": "Final"}]
    return {"week": 1, "year": 2026, "games": games, "stats": stats,
            "matchups": [{"sides": [{"roster_id": 1, "starters": ["zf", "hurt"],
                                     "players": ["zf", "hurt"], "players_points": pts}]}]}


def test_a_week_with_no_pregame_record_does_not_zero_a_player_who_played(tmp_path, monkeypatch):
    """Zay Flowers, week 1: 26 points, tagged Out after the game he was hurt
    in, and GS 0.0 - the week's tags were read after it."""
    from fantasy import pregame
    from fantasy.site import matchups as page
    monkeypatch.setattr(pregame, "ARCHIVE", tmp_path)
    board = pd.DataFrame({"sleeper_id": ["zf", "hurt"], "team": ["BAL", "BAL"],
                          "pos": ["WR", "WR"], "mu": [14.0, 9.0]})
    data = _post_week({"zf": {"gp": 1, "rec": 7}}, {"zf": 26.0, "hurt": 0.0})
    wk = page.gs_week(data, board, chances={"zf": {"p": 0.0}, "hurt": {"p": 0.0}})
    assert wk.loc["zf", "p_play"] == 1.0 and wk.loc["zf", "proj_week"] == wk.loc["zf", "proj_full"]
    assert wk.loc["zf", "proj_week"] > 0
    assert not wk.loc["zf", "pregame"], "still not an honest pre-game number"
    assert wk.loc["hurt", "proj_week"] == 0.0, "not seen in the game: the tag stands"


def test_a_frozen_projection_keeps_the_chance_it_was_priced_at(tmp_path):
    """RJ Harvey: frozen at 9.0 with no tag, then the official report listed
    him after his game - 9.0 / 0.649 = 13.9 "if he plays"."""
    from gordstats import pregame
    path = tmp_path / "week_04.json"
    pre = pd.DataFrame({"proj_week": [9.0, 12.0], "p_play": [1.0, 0.75], "state": ["pre", "pre"]},
                       index=["rj", "q"])
    pregame.freeze_at(path, pre)
    later = pd.DataFrame({"proj_week": [8.4, 11.0], "p_play": [0.649, 0.75],
                          "state": ["post", "pre"]}, index=["rj", "q"])
    got = pregame.freeze_at(path, later)
    assert got.loc["rj", "proj_week"] == 9.0 and got.loc["rj", "p_play"] == 1.0
    assert got.loc["q", "p_play"] == 0.75
    # The projection file is still {id: points} for everything reading it.
    assert json.loads(path.read_text()) == {"rj": 9.0, "q": 11.0}
    assert json.loads(pregame.chances_path(path).read_text()) == {"rj": 1.0, "q": 0.75}


def test_an_archive_from_before_the_chances_were_kept_still_reads(tmp_path):
    from gordstats import pregame
    path = tmp_path / "week_03.json"
    path.write_text('{"rj": 9.0}')
    got = pregame.freeze_at(path, pd.DataFrame(
        {"proj_week": [8.4], "p_play": [0.649], "state": ["post"]}, index=["rj"]))
    assert got.loc["rj", "proj_week"] == 9.0 and got.loc["rj", "p_play"] == 0.649
    assert not pregame.chances_path(path).exists()
    # The college page's frames carry no chance, and write no chance file.
    cfb = tmp_path / "cfb.json"
    pregame.freeze_at(cfb, pd.DataFrame({"proj_week": [5.0], "state": ["pre"]}, index=["a"]))
    assert not pregame.chances_path(cfb).exists()


def test_the_page_opens_on_and_polls_the_week_under_way(monkeypatch):
    from fantasy.site import matchups as page
    final = {1: True, 2: True, 3: False, 4: False}
    started = {1: True, 2: True, 3: True, 4: True}
    monkeypatch.setattr(page.data_mod, "week_final", lambda d: final[d["w"]])
    monkeypatch.setattr(page.data_mod, "week_started", lambda d: started[d["w"]])
    datas = {w: {"w": w} for w in final}
    assert page.current_view([1, 2, 3, 4], datas) == 4, "a stale week 3 held the page"
    started[4] = False
    assert page.current_view([1, 2, 3, 4], datas) == 3
    final.update({3: True, 4: True})
    assert page.current_view([1, 2, 3, 4], datas) == 4


def test_a_failed_live_read_is_no_update():
    from fantasy.site import matchups as page
    js = page._LIVE_FETCH_JS
    assert "r.ok?r.json():null" in js and "r.ok?r.json():{}" in js
    assert "if(!Array.isArray(both[0])||!both[0].length)return {teams:{}};" in js


# --------------------------------------------------------------------------- #
# 6. Stakes read a refreshed archive
# --------------------------------------------------------------------------- #

def _stakes_table():
    return pd.DataFrame({"roster_id": [1, 2], "manager": ["A", "B"], "opponent": [2, 1],
                         "playoff_odds": [0.5, 0.5], "playoff_if_win": [0.7, 0.7],
                         "playoff_if_loss": [0.3, 0.3], "win_prob": [0.5, 0.5],
                         "stakes_week": [4, 4]})


def test_stakes_ask_the_refreshing_reader_whether_the_week_is_over(monkeypatch):
    from fantasy.site import power as page
    monkeypatch.setattr(page.league_matchups, "weeks_over", lambda year: 3)
    asked = []

    def week_matchups(week, year):
        asked.append(week)
        return {"final": True}
    monkeypatch.setattr(page.league_matchups, "week_matchups", week_matchups)
    monkeypatch.setattr(page.league_matchups, "week_final", lambda d: bool(d.get("final")))
    assert page._stakes(_stakes_table()) == (None, {}) and asked == [4]

    monkeypatch.setattr(page.league_matchups, "week_matchups", lambda w, y: {"final": False})
    week, teams = page._stakes(_stakes_table())
    assert week == 4 and set(teams) == {"1", "2"}


def test_stakes_fall_back_to_the_archive_when_sleeper_is_down(monkeypatch, tmp_path):
    from fantasy.site import power as page
    monkeypatch.setattr(page.league_matchups, "weeks_over", lambda year: 3)

    def down(week, year):
        raise RuntimeError("sleeper down")
    monkeypatch.setattr(page.league_matchups, "week_matchups", down)
    archive = tmp_path / "week_04.json"
    archive.write_text('{"final": true}')
    monkeypatch.setattr(page.league_matchups, "_path", lambda w, y: archive)
    monkeypatch.setattr(page.league_matchups, "week_final", lambda d: bool(d.get("final")))
    assert page._stakes(_stakes_table()) == (None, {})


def test_the_playoff_picture_reads_the_rules_the_table_was_played_under():
    from fantasy.site import power as page
    ids = list(range(1, 11))
    table = pd.DataFrame({"roster_id": ids, "manager": [f"M{i}" for i in ids],
                          "wins": [20 - i for i in ids], "losses": [i for i in ids],
                          "points_for": [1500.0 - i for i in ids],
                          "playoff_odds": [0.6] * 10, "week": 10})
    table.attrs["rules"] = {"weeks": 15, "playoff_teams": 4, "reseed": True}
    page._playoffs_section(table, None, {})
    pic = page._CARD.pop("picture")
    assert pic["spots"] == 4 and pic["teams"]["1"]["left"] == 10


# --------------------------------------------------------------------------- #
# 8. The injury report
# --------------------------------------------------------------------------- #

def test_a_failed_fetch_falls_back_only_to_a_recent_copy(tmp_path, monkeypatch):
    cache = tmp_path / "injury_report.json"
    cache.write_text('{"1": {"status": "Injured Reserve", "back": "2026-12-01"}}')
    monkeypatch.setattr(ir, "CACHE", cache)

    def down(*a, **k):
        raise ir.requests.ConnectionError("espn down")
    monkeypatch.setattr(ir.requests, "get", down)
    day_old = time.time() - 86400
    os.utime(cache, (day_old, day_old))
    assert "1" in ir.report()
    stale = time.time() - (ir.STALE_DAYS + 1) * 86400
    os.utime(cache, (stale, stale))
    assert ir.report() == {}, "last season's IR list held players out"


def test_an_empty_report_is_no_better_than_a_failed_one(tmp_path, monkeypatch, capsys):
    cache = tmp_path / "injury_report.json"
    cache.write_text('{"1": {"status": "Out", "back": "2026-10-11"}}')
    stale = time.time() - 30 * 86400
    os.utime(cache, (stale, stale))
    monkeypatch.setattr(ir, "CACHE", cache)

    class Empty:
        def raise_for_status(self):
            pass

        def json(self):
            return {"injuries": []}
    monkeypatch.setattr(ir.requests, "get", lambda *a, **k: Empty())
    monkeypatch.setattr(ir, "_espn_to_sleeper", lambda: {})
    assert ir.report() == {}
    assert "came back empty" in capsys.readouterr().out


DAYS = {w: pd.Timestamp("2026-09-13").date() + pd.Timedelta(days=7 * (w - 1)) for w in range(1, 19)}


def test_a_player_seen_in_the_uncounted_week_is_held_from_the_week_after():
    """Week 3 counted, week 4 played (not yet on nflverse): hurt in his week-4
    game, back Oct 25 (week 7's Sunday) - he misses weeks 5-6, not 4-6."""
    entries = {"hurt": {"status": "Out", "back": "2026-10-25"},
               "ir": {"status": "Injured Reserve", "back": "2026-10-25"}}
    got = ir.held_out({}, from_week=3, weeks=18, year=2026, entries=entries,
                      week_days=DAYS, seen={"hurt"})
    assert got == {"hurt": 2, "ir": 3}


def test_the_simulation_starts_a_late_hold_a_week_later():
    players = pd.DataFrame({"avail": [1.0, 1.0], "bye": [0, 0], "out_weeks": [2, 2],
                            "out_from": [0, 1]})
    got = power._availability(players, weeks=8, sims=20, rng=np.random.default_rng(1),
                              from_week=3)
    # (After a hold the chain resumes from the out state, so the weeks after
    # it are the chain's; the weeks before are certain at avail 1.)
    assert got[:, 2, 0].all() and not got[:, 3:5, 0].any()
    assert got[:, 3, 1].all() and not got[:, 4:6, 1].any()


def test_seen_playing_reads_the_weeks_archive(tmp_path, monkeypatch):
    week = {"stats": {"a": {"gp": 1}, "b": {}},
            "matchups": [{"sides": [{"players_points": {"c": 4.5, "d": 0.0}}]}]}
    path = tmp_path / "week_04.json"
    path.write_text(json.dumps(week))
    monkeypatch.setattr(power.matchups_mod, "_path", lambda w, y: path)
    assert power.seen_playing(2026, 4) == {"a", "c"}
    assert power.seen_playing(2026, 0) == set()


# --------------------------------------------------------------------------- #
# 9. Readers' leagues: a chance spent once he is seen
# --------------------------------------------------------------------------- #

def test_week_projections_drop_the_chance_of_a_player_seen_in_his_game():
    from fantasy.site import players_index
    proj = {"q1": [10, 9, 8, "SF", "Questionable"], "q2": [10, 9, 8, "SF", "Questionable"],
            "q3": [10, 9, 8, "KC", "Questionable"]}
    kick = {"SF": "2026-10-04T17:00Z", "KC": "2026-10-04T20:25Z"}
    play = {"q1": 0.7, "q2": 0.7, "q3": 0.7}
    now = pd.Timestamp("2026-10-04T18:00Z")
    got = players_index._unspent(play, proj, kick, 4, 2026, now=now,
                                 stats={"q1": {"gp": 1, "pts_ppr": 6.0}})
    assert got == {"q2": 0.7, "q3": 0.7}, "q2 is not in it (inactive?), q3 has not kicked off"
    assert players_index._unspent(play, proj, kick, 4, 2026,
                                  now=pd.Timestamp("2026-10-04T12:00Z"), stats={}) == play


# --------------------------------------------------------------------------- #
# The browser
# --------------------------------------------------------------------------- #

def _js(block: str) -> str:
    block = block.replace("{% raw %}", "").replace("{% endraw %}", "")
    return re.sub(r"</?script[^>]*>", "", block)


class Browser:
    """Just enough DevTools to evaluate an expression and await a promise."""

    def __init__(self):
        subprocess.run(["fuser", "-k", f"{PORT}/tcp"], capture_output=True)
        from browser_util import launch
        self.proc = launch(CHROME, PORT)
        for _ in range(60):
            try:
                targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
                self.ws_url = next(t["webSocketDebuggerUrl"] for t in targets
                                   if t.get("type") == "page")
                return
            except Exception:                                   # noqa: BLE001
                time.sleep(0.5)
        raise RuntimeError("Chromium did not come up")

    def close(self):
        from browser_util import reap
        self.proc.terminate()
        reap(self.proc)
        subprocess.run(["fuser", "-k", f"{PORT}/tcp"], capture_output=True)

    def evaluate(self, expression):
        import websockets

        async def run():
            async with websockets.connect(self.ws_url, max_size=None) as ws:
                await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                                          "params": {"expression": expression,
                                                     "returnByValue": True,
                                                     "awaitPromise": True}}))
                while True:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=180))
                    if msg.get("id") == 1:
                        result = msg.get("result", {})
                        if result.get("exceptionDetails"):
                            raise AssertionError(result["exceptionDetails"]["text"] + " "
                                                 + str(result["exceptionDetails"]
                                                       .get("exception", {})
                                                       .get("description", "")))
                        return result["result"].get("value")
        return asyncio.run(run())


@pytest.fixture(scope="module")
def browser():
    if CHROME is None:
        pytest.skip("no Chromium to run the JS in")
    b = Browser()
    yield b
    b.close()


def _sim(browser):
    from gordstats import my_power
    browser.evaluate("document.body.innerHTML='';true")
    sim = _js(my_power.SIM_JS)
    browser.evaluate("var s=document.createElement('script');s.id='gs-power-sim';"
                     f"s.type='text/plain';s.textContent={json.dumps(sim)};"
                     "document.body.appendChild(s);true")
    browser.evaluate(sim + ";true")


@needs_chrome
@pytest.mark.parametrize("reseed", [False, True])
def test_the_browser_bracket_is_the_python_one(browser, reseed):
    """Every field from two to twelve, random scores, with and without rounds
    already decided: the same champion, sim by sim."""
    _sim(browser)
    rng = np.random.default_rng(11)
    cases = []
    for field in range(2, 13):
        rounds = power.bracket_rounds(field)
        for k in range(12):
            pts = rng.gamma(9, 12, size=(rounds, 14)).round(2)
            pts[:, :] = np.where(rng.random((rounds, 14)) < 0.15, pts.max() / 2, pts)  # some ties
            seeds = rng.permutation(14)[:field]
            decided = None
            if k % 3 == 0 and rounds > 1:
                decided = [[int(t) for t in rng.choice(seeds, size=1)]]
            py = int(power._bracket(pts[None], seeds[None], reseed=reseed, decided=decided)[0])
            cases.append((pts.tolist(), seeds.tolist(), decided, py))
    got = json.loads(browser.evaluate(
        "JSON.stringify(" + json.dumps([c[:3] for c in cases])
        + ".map(function(c){return GSPower.runBracket(c[0], c[1], 0, "
        + json.dumps(reseed) + ", c[2]);}))"))
    assert got == [c[3] for c in cases]


@needs_chrome
def test_the_browser_reads_the_winners_bracket_as_python_does(browser):
    from gordstats import my_power
    _sim(browser)
    browser.evaluate("window.GSAPI={get:function(){return Promise.resolve(null);}};"
                     "window.GSL={};true")
    browser.evaluate(_js(my_power.LEAGUE_JS) + ";true")
    got = json.loads(browser.evaluate(
        f"JSON.stringify(GSPowerLeague.losers({json.dumps(BRACKET_2425)}, {json.dumps(ORDER)}))"))
    assert got == power.bracket_losers(ORDER, rows=BRACKET_2425)


@needs_chrome
def test_the_browser_season_takes_the_played_bracket(browser):
    """After the semis a reader's league (and the trade page's "Now") gives
    the eliminated teams nothing: the playoff weeks played and the rounds
    Sleeper decided are taken, the way the built ranking takes them."""
    _sim(browser)
    positions = ["QB", "RB", "WR", "TE", "K", "DEF"]
    board, rosters, pid = {}, [], 0
    for t in range(10):
        held = []
        for pos in (0, 1, 1, 2, 2, 3, 4, 5):
            pid += 1
            board[str(pid)] = [pos, 7, 10.0, 4.0, 1.0, 0.9, 2.0, 0]
            held.append(str(pid))
        rosters.append({"roster_id": t + 1, "players": held})
    regular = [[140.0 - 5 * SEEDS_2425.index(r) if r in SEEDS_2425 else 80.0
                for r in ORDER] for _ in range(14)]
    playoff = [[R1_2425.get(r, 0.0) for r in ORDER], [R2_2425.get(r, 0.0) for r in ORDER]]
    decided = power.bracket_losers(ORDER, rows=[m for m in BRACKET_2425 if m["r"] < 3])
    spec = {"board": board, "posNames": positions, "rosters": rosters,
            "slots": ["QB", "RB", "RB", "WR", "WR", "TE", "K", "DEF"], "basis": 0,
            "weeks": 14, "playoffTeams": 6, "median": True, "reseed": True,
            "actual": regular, "playoffActual": playoff, "decided": decided,
            "sims": 300, "seed": 5}
    got = json.loads(browser.evaluate("JSON.stringify(GSPower.run(" + json.dumps(spec) + "))"))
    odds = {t["roster_id"]: t["titleOdds"] for t in got["teams"]}
    assert {k for k, v in odds.items() if v > 0} == {1, 5}, odds
    # And before the regular season is in, neither is read.
    spec["actual"] = regular[:10]
    got = json.loads(browser.evaluate("JSON.stringify(GSPower.run(" + json.dumps(spec) + "))"))
    assert sum(1 for t in got["teams"] if t["titleOdds"] > 0) > 2


@needs_chrome
def test_the_browser_counts_a_tie_as_python_does(browser):
    _sim(browser)
    scores = [100.0, 100.0, 130.0, 90.0, 110.0, 110.0, 150.0, 80.0, 120.0, 115.0]
    pairs = [1, 0, 3, 2, 6, 7, 4, 5, 9, 8]
    got = json.loads(browser.evaluate(
        "(function(){var h=[0,0,0,0,0,0,0,0,0,0], m=h.slice();"
        f"GSPower.weekWins({json.dumps(scores)}, {json.dumps(pairs)}, true, h, m);"
        "return JSON.stringify([h, m]);})()"))
    posted = _posted({i + 1: s for i, s in enumerate(scores)},
                     [(1, 2), (3, 4), (5, 7), (6, 8), (9, 10)])
    real = power.actual_results(through_week=1, posted=posted)
    assert got[0] == real["h2h_wins"].tolist() and got[1] == real["median_wins"].tolist()


@needs_chrome
def test_a_player_dropped_from_a_roster_keeps_everyone_elses_draws(browser):
    """With every rostered player in the pool, a deep-bench player who never
    starts can leave a roster without changing a single number; out of the
    pool, he shifted every later player's draws."""
    _sim(browser)
    positions = ["QB", "RB", "WR", "TE", "K", "DEF"]
    board, rosters, pid = {}, [], 100
    for t in range(8):
        held = []
        for pos in (0, 1, 1, 2, 2, 3, 5, 1, 2):
            pid += 1
            board[str(pid)] = [pos, 5 + t, 8.0 + (pid % 7), 4.0, 1.0, 0.85, 2.0, 0]
            held.append(str(pid))
        rosters.append({"roster_id": t + 1, "players": held})
    board["999"] = [4, 9, 6.0, 3.0, 1.0, 0.9, 0.0, 0]        # a kicker: no K slot here
    rosters[0]["players"].append("999")
    everyone = [p for r in rosters for p in r["players"]]
    spec = {"board": board, "posNames": positions, "rosters": rosters,
            "slots": ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "DEF", "BN", "BN"],
            "basis": 0, "weeks": 14, "playoffTeams": 4, "median": True,
            "stable": True, "pool": everyone, "sims": 400, "seed": 9}
    dropped = json.loads(json.dumps(spec))
    dropped["rosters"][0]["players"].remove("999")
    out = json.loads(browser.evaluate(
        "(function(){var a=" + json.dumps(spec) + ", b=" + json.dumps(dropped) + ";"
        "var key=function(x){return JSON.stringify(x.teams.map(function(t){"
        "return [t.roster_id, t.titleOdds, t.playoffOdds, t.projPoints];}));};"
        "var c=JSON.parse(JSON.stringify(b)); c.pool=c.pool.filter(function(p){return p!=='999';});"
        "return JSON.stringify([key(GSPower.run(a))===key(GSPower.run(a)),"
        "key(GSPower.run(a))===key(GSPower.run(b)), key(GSPower.run(a))===key(GSPower.run(c))]);})()"))
    assert out == [True, True, False]


@needs_chrome
def test_unread_league_is_ppr_and_a_seen_player_spends_his_chance(browser):
    from gordstats import my_league_data
    browser.evaluate("document.body.innerHTML='';window.GSAPI={};true")
    browser.evaluate(_js(my_league_data.JS) + ";true")
    got = json.loads(browser.evaluate(
        "JSON.stringify([GSL.basis({}).index, GSL.basis(null).index,"
        "GSL.basis({scoring_settings:{rec:0}}).index, GSL.basis({scoring_settings:{rec:0.5}}).index,"
        "GSL.points({proj:{a:[10,9,8,'SF',''],b:[10,9,8,'SF','']},play:{a:0.5,b:0.5}}, 0),"
        "GSL.points({proj:{a:[10,9,8,'SF',''],b:[10,9,8,'SF','']},play:{a:0.5,b:0.5}}, 0, {a:3.5})])"))
    assert got[:4] == [0, 0, 2, 1]
    assert got[4] == {"a": 5, "b": 5} and got[5] == {"a": 10, "b": 5}


# ----- the trade page ----------------------------------------------------- #

NFL_POS = ["QB", "RB", "WR", "TE", "K", "DEF"]
NFL_SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF", "BN", "BN", "BN", "BN"]
SHAPE = ["QB", "RB", "RB", "WR", "WR", "TE", "K", "DEF", "RB", "WR", "WR", "QB", "TE"]


def _trade_league(empty=False):
    rng = np.random.default_rng(3)
    board, index, rosters, pid = {}, {}, [], 100
    for t in range(4):
        held = []
        for slot, pos in enumerate(SHAPE):
            pid += 1
            mu = round({"QB": 18, "RB": 12, "WR": 11, "TE": 8, "K": 8, "DEF": 7}[pos]
                       * (0.6 + 0.8 * rng.random()) * (1 - 0.04 * slot), 2)
            board[str(pid)] = [NFL_POS.index(pos), 9, mu, round(mu * .45, 2),
                               round(mu * .12, 2), 0.88, 0, 0]
            index[str(pid)] = [f"Player {pid}", pos, "FA"]
            held.append(str(pid))
        rosters.append({"roster_id": t + 1, "players": [] if empty else held,
                        "reserve": [], "taxi": [], "owner_id": f"u{t + 1}"})
    # Team 2's star quarterback is on IR, and team 1's on IR is its best WR.
    star = "200"
    board[star] = [0, 9, 30.0, 8.0, 2.0, 0.88, 0, 4]
    index[star] = ["Hurt Star", "QB", "FA"]
    hurt_wr = "201"
    board[hurt_wr] = [2, 9, 25.0, 8.0, 2.0, 0.88, 0, 4]
    index[hurt_wr] = ["Hurt Receiver", "WR", "FA"]
    if not empty:
        rosters[1]["players"].append(star)
        rosters[1]["reserve"] = [star]
        rosters[0]["players"].append(hurt_wr)
        rosters[0]["reserve"] = [hurt_wr]
    for pos in NFL_POS:
        for k in range(3):
            pid += 1
            board[str(pid)] = [NFL_POS.index(pos), 9, 6.0 - k, 2.7, 0.7, 0.88, 0, 0]
            index[str(pid)] = [f"Free {pid}", pos, "FA"]
    users = [{"user_id": f"u{t + 1}", "display_name": f"m{t + 1}",
              "metadata": {"team_name": f"Team {t + 1}"}} for t in range(4)]
    matchups = {w: [{"roster_id": rid, "matchup_id": (1 if rid in (1, 2) else 2), "points": 0}
                    for rid in (1, 2, 3, 4)] for w in range(1, 15)}
    info = {"name": "Test", "roster_positions": NFL_SLOTS, "scoring_settings": {"rec": 1},
            "settings": {"playoff_week_start": 15, "playoff_teams": 2, "reserve_slots": 2,
                         "league_average_match": 0, "leg": 1}}
    return {"board": {"year": 2026, "week": 0, "fields": [], "pos": NFL_POS, "board": board},
            "index": index, "rosters": rosters, "users": users, "matchups": matchups,
            "info": info}


def _load_trade(browser, league):
    from fantasy.site import trade as nfl_trade
    from gordstats import my_power, trade_page
    stub = f"""
      window.__L = {json.dumps(league)};
      window.GSAPI = {{
        get: function(path){{
          var m = /\\/matchups\\/(\\d+)$/.exec(path);
          if(m) return Promise.resolve(__L.matchups[m[1]] || []);
          if(/\\/rosters$/.test(path)) return Promise.resolve(__L.rosters);
          if(/\\/users$/.test(path)) return Promise.resolve(__L.users);
          if(/winners_bracket$/.test(path)) return Promise.resolve([]);
          return Promise.resolve(__L.info);
        }},
        players: function(){{ return Promise.resolve(__L.index); }}
      }};
      window.fetch = function(url){{
        var body = /season-board/.test(url) ? __L.board
          : /week-projections/.test(url) ? {{week:1, kick:{{}}, proj:{{}}}} : {{}};
        return Promise.resolve({{ok:true, json:function(){{ return Promise.resolve(body); }}}});
      }};
      true
    """
    browser.evaluate("document.body.innerHTML='';" + stub)
    browser.evaluate(_js(my_power.SIM_JS.replace("{% raw %}", "")) + ";true")
    sim = _js(my_power.SIM_JS)
    browser.evaluate("var s=document.createElement('script');s.id='gs-power-sim';"
                     f"s.type='text/plain';s.textContent={json.dumps(sim)};"
                     "document.body.appendChild(s);true")
    browser.evaluate(_js(nfl_trade.my_league_data.JS) + ";true")
    browser.evaluate(_js(my_power.LEAGUE_JS) + ";true")
    browser.evaluate(_js(trade_page.JS) + ";true")
    browser.evaluate(_js(nfl_trade.adapter_js()) + ";true")


@needs_chrome
def test_a_player_off_injured_reserve_stays_there_and_never_starts(browser):
    """Team 1 takes team 2's IR quarterback for a bench receiver: one for
    one, and the hurt player goes to IR - no "Drops X to make room" - and
    team 2's IR star was never in its lineup to lose."""
    league = _trade_league()
    _load_trade(browser, league)
    give = [league["rosters"][0]["players"][9]]           # a bench WR
    got = json.loads(browser.evaluate(
        "GSTradeAdapter.load().then(function(d){return GSTradeAdapter.evaluate("
        f"{{a:'1',b:'2',give:{json.dumps(give)},get:['200']}}).then(function(r){{"
        "return JSON.stringify(r.moves);});})"))
    assert not any(line.startswith("Drops ") for line in got["1"]), got
    assert not any("Hurt Star" in line for line in got["1"] + got["2"]), got
    # Team 1's IR receiver is its best by far; he does not start either.
    assert not any("Hurt Receiver" in line for line in got["1"]), got


@needs_chrome
def test_a_new_deal_stops_the_last_ones_worker(browser):
    league = _trade_league()
    _load_trade(browser, league)
    got = browser.evaluate("""
      GSTradeAdapter.load().then(function(){
        var spec = {rosters:[], sims:1};
        var first = GSPowerLeague.simulate({board:{}, rosters:[{roster_id:1, players:[]}],
                                            sims:200000, weeks:14}, 'x');
        var caught = first.then(function(){ return 'finished'; },
                                function(e){ return e.message; });
        GSPowerLeague.stop('x');
        return caught;
      })""")
    assert got == "superseded"


@needs_chrome
def test_an_undrafted_league_says_so(browser):
    league = _trade_league(empty=True)
    _load_trade(browser, league)
    got = json.loads(browser.evaluate(
        "GSTradeAdapter.load().then(function(d){return JSON.stringify(d);})"))
    assert got["teams"] == [] and "not drafted" in got["empty"]
    err = browser.evaluate(
        "GSPowerLeague.setup('1').then(function(){return 'ranked';},"
        "function(e){return e.message;})")
    assert err == "undrafted"
