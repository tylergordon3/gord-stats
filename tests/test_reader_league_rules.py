"""
Readers' leagues before the fantasy playoffs (2026-10-03): three places where
the browser's season simulation (gordstats.my_power, gs-power-sim.js) played a
reader's league by rules it does not have.

  * **A hold from the lagging week.** The published board (fantasy.site.
    season_board) counts each injured player's weeks out from the last week
    it has absorbed, which runs a day or two behind the games. A player hurt
    in Sunday's game was held out of that game too - the game he got hurt in.
    The board now says when each hold starts (`out_from`, from Sleeper's
    stat feed for the week), and the browser places a hold on the NFL weeks
    it is about (`holdWeek`, the board's week) rather than wherever a
    reader's league has got to.
  * **Two-week playoff rounds.** Sleeper's playoff_round_type (1: a two-week
    final, 2: two weeks every round) and ESPN's two-week matchup periods. A
    round is won on both weeks' points together; the simulation played every
    round as one week, so it read the wrong weeks for every round after the
    first and decided the first on half its points.
  * **ESPN reseeding.** ESPN's scheduleSettings.playoffReseed was not mapped,
    so every ESPN bracket was played fixed.

The real-league numbers below are public 2025 ESPN leagues' playoffs (team ids
only), read 2026-10-03: the two-week totals and the reseeded pairing are what
ESPN actually decided. Python parts run anywhere; the JS runs in headless
Chromium and skips where there is none.
"""
import asyncio
import json
import re
import shutil
import subprocess
import time
import urllib.request
from datetime import date, timedelta

import pandas as pd
import pytest

from fantasy.site import season_board

CHROME = next((p for p in ("/usr/bin/chromium-browser", "/usr/bin/chromium",
                           "/usr/bin/google-chrome") if shutil.which(p)), None)
needs_chrome = pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")
PORT = 9683

# Each NFL week's Sunday, 2026: week 4 is Oct 4, week 7 Oct 25.
DAYS = {w: date(2026, 9, 13) + timedelta(days=7 * (w - 1)) for w in range(1, 19)}
# Week 3 absorbed, week 4 under way. "hurt" played in week 4 and was hurt in
# the game; "ir" went on IR before it. Both are due back for week 7.
ENTRIES = {"hurt": {"status": "Out", "back": "2026-10-25"},
           "ir": {"status": "Injured Reserve", "back": "2026-10-25"}}


# --------------------------------------------------------------------------- #
# 1. The board says which week a hold starts
# --------------------------------------------------------------------------- #

def test_a_player_seen_in_the_unabsorbed_week_is_held_from_the_week_after():
    held, held_from = season_board.holds({}, 3, 2026, seen={"hurt"},
                                         entries=ENTRIES, week_days=DAYS)
    # He played week 4: out for weeks 5 and 6, starting a week after the
    # board's week. The player hurt before it misses 4, 5 and 6.
    assert held == {"hurt": 2, "ir": 3}
    assert held_from == {"hurt": 1}


def test_nobody_seen_is_the_old_count():
    held, held_from = season_board.holds({}, 3, 2026, seen=set(),
                                         entries=ENTRIES, week_days=DAYS)
    assert held == {"hurt": 3, "ir": 3} and held_from == {}


def test_a_tag_without_a_return_date_starts_late_too():
    """No ESPN date: Sleeper's tag prices the hold (power.FORCED_OUT), and a
    player seen in the week still starts it the week after."""
    held, held_from = season_board.holds({"tagged": "Out"}, 3, 2026, seen={"tagged"},
                                         entries={}, week_days=DAYS)
    assert held == {"tagged": 1} and held_from == {"tagged": 1}


def test_seen_in_week_reads_every_player_off_sleepers_feed(monkeypatch):
    from fantasy.league import matchups
    asked = []

    def stats(week, year, only=None):
        asked.append((week, year))
        return {"a": {"gp": 1}, "c": {"pts_ppr": 4.2}, "d": {"rec_tgt": 0}}

    monkeypatch.setattr(matchups, "sleeper_stats", stats)
    assert season_board.seen_in_week(2026, 4) == {"a", "c"}
    assert asked == [(4, 2026)]
    assert season_board.seen_in_week(2026, 0) == set()

    def down(week, year, only=None):
        raise RuntimeError("Sleeper is busy")

    monkeypatch.setattr(matchups, "sleeper_stats", down)
    assert season_board.seen_in_week(2026, 4) == set(), "no feed: holds start with the week"


def test_the_published_row_carries_when_the_hold_starts(monkeypatch):
    """`out_from` goes on the end of each row: the browser reads rows by
    position, so the eight fields an older page knows stay where they were."""
    from fantasy import projections
    from fantasy.league import injury_report, opportunity, return_dip

    frame = pd.DataFrame([
        {"sleeper_id": pid, "pos": "WR", "bye": 9, "mu": 14.0, "sd": 7.0,
         "mu_se": 2.0, "avail": 0.9} for pid in ("hurt", "ir", "fine")])
    monkeypatch.setattr(projections, "load", lambda *a, **k: frame.copy())
    monkeypatch.setattr(projections, "current_form", lambda board, *a, **k: board)
    monkeypatch.setattr(projections, "with_sleeper", lambda board, *a, **k: board)
    monkeypatch.setattr(season_board, "absorbed_weeks", lambda year=None: 3)
    monkeypatch.setattr(season_board, "receptions_per_week", lambda year=None: ({}, {}))
    monkeypatch.setattr(season_board, "injury_status", lambda: {"hurt": "Out", "ir": "IR"})
    monkeypatch.setattr(season_board, "depth_charts", lambda: None)
    weeks_asked = []
    monkeypatch.setattr(season_board, "seen_in_week",
                        lambda year, week: weeks_asked.append(week) or {"hurt", "fine"})
    monkeypatch.setattr(injury_report, "report", lambda refresh=False: ENTRIES)
    monkeypatch.setattr(injury_report, "sundays", lambda year: DAYS)
    monkeypatch.setattr(opportunity, "for_board", lambda *a, **k: {})
    monkeypatch.setattr(opportunity, "apply", lambda board, result: board)
    monkeypatch.setattr(return_dip, "for_board", lambda *a, **k: {})
    monkeypatch.setattr(return_dip, "apply", lambda board, result: board)

    payload = season_board.build(2026)
    assert weeks_asked == [4], "the week after the board's"
    assert payload["fields"] == season_board.FIELDS
    assert season_board.FIELDS[:8] == ["pos", "bye", "mu", "sd", "mu_se", "avail", "rec",
                                       "out"], "fields are appended, never moved"
    out, late = season_board.FIELDS.index("out"), season_board.FIELDS.index("out_from")
    rows = payload["board"]
    assert all(len(r) == len(season_board.FIELDS) for r in rows.values())
    assert (rows["hurt"][out], rows["hurt"][late]) == (2, 1)
    assert (rows["ir"][out], rows["ir"][late]) == (3, 0)
    assert (rows["fine"][out], rows["fine"][late]) == (0, 0), "seen, but not hurt"


# --------------------------------------------------------------------------- #
# The browser
# --------------------------------------------------------------------------- #

def _js(block: str) -> str:
    block = block.replace("{% raw %}", "").replace("{% endraw %}", "")
    return re.sub(r"</?script[^>]*>", "", block)


class Browser:
    """Just enough DevTools to evaluate an expression and await a promise."""

    def __init__(self):
        from browser_util import launch
        subprocess.run(["fuser", "-k", f"{PORT}/tcp"], capture_output=True)
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

    def json(self, expression):
        return json.loads(self.evaluate("JSON.stringify(" + expression + ")"))


@pytest.fixture(scope="module")
def browser():
    if CHROME is None:
        pytest.skip("no Chromium to run the JS in")
    b = Browser()
    yield b
    b.close()


def _load(browser):
    """The real GSAPI (for its ESPN translation), GSL, the simulation and the
    league reader, fresh - nothing reaches a network: every league read is
    stubbed per test, and so is fetch."""
    from gordstats import league_api, my_league_data, my_power
    browser.evaluate("document.body.innerHTML='';"
                     "delete window.GSAPI; delete window.GSL; delete window.GSPower;"
                     "delete window.GSPowerLeague;"
                     "window.fetch=function(){ return Promise.reject(new Error('offline')); };"
                     "true")
    for block in (league_api.JS, my_power.SIM_JS, my_league_data.JS, my_power.LEAGUE_JS):
        browser.evaluate(_js(block) + ";true")


# ----- 1. the hold lands on the weeks it is about -------------------------- #

def _hold_spec(row, actual_weeks, **extra):
    """Two one-slot teams over six regular weeks: A's player scores 20 a week
    (sd at the floor, no uncertainty, never hurt by the chain) and has a bye
    in week `row[1]`; B's scores 10 with no bye. A's points over the weeks
    still to play say exactly which weeks he missed."""
    board = {"a": row, "b": [0, 0, 10.0, 0.5, 0.0, 1.0, 0.0, 0]}
    spec = {"board": board, "posNames": ["QB", "RB", "WR", "TE", "K", "DEF"],
            "rosters": [{"roster_id": 1, "players": ["a"]}, {"roster_id": 2, "players": ["b"]}],
            "slots": ["QB"], "basis": 0, "weeks": 6, "playoffTeams": 2, "median": False,
            "actual": [[100.0, 100.0]] * actual_weeks, "sims": 300, "seed": 4}
    spec.update(extra)
    return spec


def _rest_of_a(browser, spec, played):
    got = browser.json("GSPower.run(" + json.dumps(spec) + ").teams")
    team = next(t for t in got if t["roster_id"] == 1)
    return team["projPoints"] - 100.0 * played


@needs_chrome
def test_a_hold_marked_late_starts_the_week_after(browser):
    """Board week 3; out one week; bye in week 5. Held from week 4 he misses
    4 and 5 (one game left, week 6); seen in week 4 and held from week 5 -
    his bye - he misses only the bye."""
    _load(browser)
    now = _rest_of_a(browser, _hold_spec([0, 5, 20.0, 0.5, 0.0, 1.0, 0.0, 1, 0], 3,
                                         holdWeek=3), 3)
    late = _rest_of_a(browser, _hold_spec([0, 5, 20.0, 0.5, 0.0, 1.0, 0.0, 1, 1], 3,
                                          holdWeek=3), 3)
    assert abs(now - 20.0) < 1.0, now
    assert abs(late - 40.0) < 1.0, late


@needs_chrome
def test_an_older_board_without_the_field_holds_from_the_week(browser):
    _load(browser)
    old = _rest_of_a(browser, _hold_spec([0, 5, 20.0, 0.5, 0.0, 1.0, 0.0, 1], 3,
                                         holdWeek=3), 3)
    assert abs(old - 20.0) < 1.0, old


@needs_chrome
def test_a_hold_sits_on_the_boards_weeks_not_the_leagues(browser):
    """The league has one week in (a team that scored nothing stops the count;
    Sleeper scoring late does too) while the board is at week 3. Out one week
    from week 4 - his bye - he plays weeks 2, 3, 5 and 6. Anchored at the
    league's week, the hold took week 2 instead, and the bye another."""
    _load(browser)
    row = [0, 4, 20.0, 0.5, 0.0, 1.0, 0.0, 1, 0]
    board_weeks = _rest_of_a(browser, _hold_spec(row, 1, holdWeek=3), 1)
    league_weeks = _rest_of_a(browser, _hold_spec(row, 1), 1)
    assert abs(board_weeks - 80.0) < 1.5, board_weeks
    assert abs(league_weeks - 60.0) < 1.5, league_weeks


@needs_chrome
def test_setup_hands_the_simulation_the_boards_week(browser):
    _load(browser)
    league = _sleeper_league({"playoff_week_start": 15, "playoff_teams": 4})
    spec = _setup(browser, league, board_week=3)
    assert spec["holdWeek"] == 3


# ----- 2. two-week rounds --------------------------------------------------- #

# A 2025 ESPN league, four in the playoffs, two weeks a round (periods 14 =
# weeks 14-15, 15 = weeks 16-17): seeds 1-4 are teams 8, 2, 7 and 5. Team 5
# won week 14 by nothing and both rounds on the two weeks together.
TWO_WEEK_GAMES = [
    (14, (8, {"14": 128.0, "15": 74.0}), (5, {"14": 94.0, "15": 137.0}), "AWAY"),
    (14, (2, {"14": 124.0, "15": 122.0}), (7, {"14": 62.0, "15": 116.0}), "HOME"),
    (15, (2, {"16": 106.0, "17": 112.0}), (5, {"16": 100.0, "17": 172.0}), "AWAY"),
]
TWO_WEEK_TEAMS = [8, 2, 7, 5, 3, 1, 4, 6, 10, 11]     # best first; ESPN skips id 9


def _espn_two_week():
    """That league in ESPN's shapes: its real playoff games, and a regular
    season (13 weeks) made up so the standings come out 8, 2, 7, 5 - every
    team scores the same each week, stronger first; nine weeks of a circle,
    then four of best against worst so nobody ties."""
    teams = TWO_WEEK_TEAMS
    score = {t: 150.0 - 5 * i for i, t in enumerate(teams)}
    games = []

    def game(period, a, b, pa=None, pb=None, tier="NONE", winner=None):
        pa = pa if pa is not None else {str(period): score[a]}
        pb = pb if pb is not None else {str(period): score[b]}
        ta, tb = sum(pa.values()), sum(pb.values())
        games.append({"matchupPeriodId": period, "playoffTierType": tier,
                      "home": {"teamId": a, "totalPoints": ta, "pointsByScoringPeriod": pa},
                      "away": {"teamId": b, "totalPoints": tb, "pointsByScoringPeriod": pb},
                      "winner": winner or ("HOME" if ta > tb else "AWAY")})

    fixed, rot = teams[0], teams[1:]
    for week in range(1, 10):
        game(week, fixed, rot[0])
        for i in range(1, 5):
            game(week, rot[i], rot[-i])
        rot = rot[1:] + rot[:1]
    for week in range(10, 14):
        for i in range(5):
            game(week, teams[i], teams[-1 - i])
    for period, (a, pa), (b, pb), winner in TWO_WEEK_GAMES:
        game(period, a, b, pa, pb, "WINNERS_BRACKET", winner)
    periods = {str(w): [w] for w in range(1, 14)}
    periods.update({"14": [14, 15], "15": [16, 17]})
    return {"settings": {"name": "Two-week league",
                         "scheduleSettings": {"matchupPeriodCount": 13,
                                              "matchupPeriods": periods,
                                              "playoffTeamCount": 4,
                                              "playoffMatchupPeriodLength": 2,
                                              "playoffReseed": False}},
            "status": {"latestScoringPeriod": 19, "finalScoringPeriod": 17,
                       "previousSeasons": []},
            "teams": [{"id": t, "name": f"Team {t}"} for t in sorted(teams)],
            "schedule": games}


def _stub_espn(browser, d, league_id, bracket=False):
    """GSAPI.get answering from `d` through GSAPI's own ESPN translation."""
    browser.evaluate(f"""
      window.__D = {json.dumps(d)};
      window.__ID = {json.dumps(league_id)};
      GSAPI.get = function(path){{
        path = decodeURIComponent(path);
        var base = '/league/' + __ID, E = GSAPI._espn;
        if(path === base) return Promise.resolve(E.leagueOf(__D, __ID));
        if(path === base + '/users') return Promise.resolve([]);
        if(path === base + '/rosters') return Promise.resolve(__D.teams.map(function(t){{
          return {{roster_id:t.id, owner_id:'o'+t.id, players:['p'+t.id], settings:{{}}}}; }}));
        var m = /\\/matchups\\/(\\d+)$/.exec(path);
        if(m) return Promise.resolve(E.matchupsOf(__D, __D.schedule, +m[1], {{}}));
        if(/winners_bracket$/.test(path))
          return Promise.resolve({json.dumps(bool(bracket))} ? E.bracketOf(__D, __D.schedule) : []);
        return Promise.resolve(null);
      }};
      true""")


def _board(week, players):
    return {"year": 2025, "week": week, "fields": season_board.FIELDS,
            "pos": ["QB", "RB", "WR", "TE", "K", "DEF"],
            "board": {p: [0, 0, 15.0, 5.0, 1.0, 0.9, 0.0, 0, 0] for p in players}}


def _setup(browser, league_or_none, board_week, league_id=None, year=None, players=()):
    """GSPowerLeague.setup's spec. A Sleeper-shaped `league` is served as it
    is; otherwise GSAPI is already stubbed (_stub_espn)."""
    if league_or_none is not None:
        league_id = league_or_none["info"]["league_id"]
        players = [p for r in league_or_none["rosters"] for p in r["players"]]
        browser.evaluate(f"""
          window.__S = {json.dumps(league_or_none)};
          GSAPI.get = function(path){{
            path = decodeURIComponent(path);
            if(/\\/rosters$/.test(path)) return Promise.resolve(__S.rosters);
            if(/\\/users$/.test(path)) return Promise.resolve([]);
            if(/\\/matchups\\/\\d+$/.test(path)) return Promise.resolve([]);
            if(/winners_bracket$/.test(path)) return Promise.resolve([]);
            return Promise.resolve(__S.info);
          }};
          true""")
    board = _board(board_week, players)
    browser.evaluate(f"""
      window.__B = {json.dumps(board)};
      window.fetch = function(url){{
        return /season-board/.test(url)
          ? Promise.resolve({{ok:true, json:function(){{ return Promise.resolve(__B); }}}})
          : Promise.reject(new Error('offline'));
      }};
      true""")
    year_arg = json.dumps(year) if year else "undefined"
    browser.evaluate(f"GSPowerLeague.setup({json.dumps(league_id)}, {year_arg})"
                     ".then(function(s){ window.__SETUP = s; return true; })")
    return browser.json("__SETUP.spec")


def _sleeper_league(settings, season="2025"):
    rosters = [{"roster_id": r, "owner_id": f"u{r}", "players": [f"s{r}"]} for r in (1, 2, 3, 4)]
    info = {"league_id": "777", "season": season, "roster_positions": ["QB", "BN"],
            "scoring_settings": {"rec": 1}, "settings": settings}
    return {"info": info, "rosters": rosters}


@needs_chrome
def test_two_week_rounds_are_won_on_both_weeks_together(browser):
    """ESPN's real 2025 bracket for that league, end to end: GSAPI maps the
    two-week periods, setup reads all four playoff weeks, and the simulation
    sends through the team ESPN did - team 5, beaten in week 14 and in week
    16, champion on the totals. Played one week a round (the old reading),
    the title went to team 2."""
    _load(browser)
    d = _espn_two_week()
    league_id = "espn:2025:4242"
    _stub_espn(browser, d, league_id)
    spec = _setup(browser, None, 17, league_id=league_id, year=2025,
                  players=[f"p{t}" for t in TWO_WEEK_TEAMS])
    assert spec["roundWeeks"] == [2, 2]
    assert spec["reseed"] is False
    assert len(spec["actual"]) == 13 and len(spec["playoffActual"]) == 4
    assert spec["decided"] is None, "an undecided bracket: the points have to decide"

    spec["sims"] = 200
    got = browser.json("GSPower.run(" + json.dumps(spec) + ")")
    title = {t["roster_id"]: t["titleOdds"] for t in got["teams"]}
    assert title[5] == 1.0, title
    assert got["playoffWeeks"] == 4 and got["playoffRounds"] == 2

    old = dict(spec, roundWeeks=None)
    got = browser.json("GSPower.run(" + json.dumps(old) + ")")
    assert {t["roster_id"]: t["titleOdds"] for t in got["teams"]}[2] == 1.0


@needs_chrome
def test_the_decided_two_week_bracket_agrees(browser):
    _load(browser)
    league_id = "espn:2025:4242"
    _stub_espn(browser, _espn_two_week(), league_id, bracket=True)
    spec = _setup(browser, None, 17, league_id=league_id, year=2025,
                  players=[f"p{t}" for t in TWO_WEEK_TEAMS])
    index = sorted(TWO_WEEK_TEAMS)
    assert spec["decided"] == [[index.index(8), index.index(7)], [index.index(2)]]
    spec["sims"] = 100
    got = browser.json("GSPower.run(" + json.dumps(spec) + ")")
    assert {t["roster_id"]: t["titleOdds"] for t in got["teams"]}[5] == 1.0


@needs_chrome
def test_the_round_lengths_follow_the_leagues_settings(browser):
    """Sleeper's playoff_round_type, read against real leagues' brackets:
    0 one week a round, 1 a two-week final, 2 two weeks every round (2020
    called that last one 1). ESPN's periods win where GSAPI gives them."""
    _load(browser)
    got = browser.json("""[
      GSPowerLeague.roundLengths({season:'2026', settings:{playoff_round_type:0}}, 3),
      GSPowerLeague.roundLengths({season:'2026', settings:{playoff_round_type:1}}, 3),
      GSPowerLeague.roundLengths({season:'2026', settings:{playoff_round_type:2}}, 2),
      GSPowerLeague.roundLengths({season:'2020', settings:{playoff_round_type:1}}, 2),
      GSPowerLeague.roundLengths({season:'2026', settings:{}}, 3),
      GSPowerLeague.roundLengths(null, 2),
      GSPowerLeague.roundLengths({season:'2025', settings:{playoff_round_type:1,
        round_weeks:{'1':[15], '2':[16], '3':[17, 18]}}}, 3)]""")
    assert got == [[1, 1, 1], [1, 1, 2], [2, 2], [2, 2], [1, 1, 1], [1, 1], [1, 1, 2]]


@needs_chrome
def test_a_sleeper_two_week_final_reaches_the_simulation(browser):
    _load(browser)
    league = _sleeper_league({"playoff_week_start": 15, "playoff_teams": 4,
                              "playoff_round_type": 1, "playoff_seed_type": 0})
    spec = _setup(browser, league, 3)
    assert spec["roundWeeks"] == [1, 2] and spec["reseed"] is False
    spec["sims"] = 50
    got = browser.json("GSPower.run(" + json.dumps(spec) + ")")
    assert got["playoffWeeks"] == 3 and got["roundWeeks"] == [1, 2]


@needs_chrome
def test_a_two_week_round_sums_its_weeks(browser):
    """Sleeper's real 2024 bracket from a league that plays two weeks a round
    (playoff_round_type 2, weeks 14-15 then 16-17), rosters 9 v 6 and 7 v 12
    in the first round. Roster 9 won week 14 and lost the round; roster 7 won
    week 17 and lost the final - Sleeper's winners bracket has 6 the champion."""
    _load(browser)
    ids = [6, 7, 9, 12]
    weeks = {14: {9: 143.28, 6: 130.46, 7: 95.28, 12: 81.16},
             15: {9: 103.84, 6: 155.82, 7: 111.24, 12: 102.1},
             16: {6: 124.74, 7: 91.72, 9: 103.3, 12: 109.48},
             17: {6: 141.08, 7: 154.54, 9: 83.86, 12: 90.62}}
    points = [[weeks[w][r] for r in ids] for w in (14, 15, 16, 17)]
    seeds = [ids.index(r) for r in (9, 7, 12, 6)]
    got = browser.json(f"""[
      GSPower.runBracket({points}, {seeds}, 0, false, null, [2, 2]),
      GSPower.runBracket({points}, {seeds}, 0, true, null, [2, 2]),
      GSPower.runBracket({points}, {seeds}, 0, false, null)]""")
    assert [ids[i] for i in got[:2]] == [6, 6]
    assert ids[got[2]] == 7, "one week a round reads week 14, then week 15 as the final"


# ----- 3. ESPN reseeding ----------------------------------------------------- #

# A 2025 ESPN league with playoffReseed on: six teams, weeks 16-18, seeds 1-6
# teams 6, 12, 4, 9, 1, 2. The 6 seed (team 2) won its first game, so ESPN
# drew 1 v 6 and 2 v 4 - a fixed bracket would have drawn 1 v 4 and 2 v 6.
RESEED_SEEDS = [6, 12, 4, 9, 1, 2]
RESEED_WEEKS = {6: [148.0, 121.5, 90.0], 12: [133.0, 95.0, 104.0], 4: [122.0, 104.0, 92.5],
                9: [72.5, 87.5, 75.0], 1: [67.0, 109.0, 97.0], 2: [163.5, 117.0, 96.5]}


@needs_chrome
def test_espns_reseed_setting_is_mapped(browser):
    _load(browser)
    got = browser.json("""[true, false, undefined].map(function(r){
      var s = {matchupPeriodCount:14, playoffTeamCount:6};
      if(r !== undefined) s.playoffReseed = r;
      return GSAPI._espn.leagueOf({settings:{scheduleSettings:s}, status:{}, teams:[]},
                                  'espn:2026:9').settings.playoff_seed_type;
    })""")
    assert got == [1, 0, 0]


@needs_chrome
def test_a_reseeding_espn_league_plays_the_bracket_espn_drew(browser):
    """Reseeded, the bracket crowns team 12, as ESPN's did; fixed, team 2,
    a team ESPN knocked out in round two."""
    _load(browser)
    ids = sorted(RESEED_WEEKS)
    points = [[RESEED_WEEKS[t][w] for t in ids] for w in range(3)]
    seeds = [ids.index(t) for t in RESEED_SEEDS]
    got = browser.json(f"""[GSPower.runBracket({points}, {seeds}, 0, true, null),
                            GSPower.runBracket({points}, {seeds}, 0, false, null)]""")
    assert [ids[i] for i in got] == [12, 2]


@needs_chrome
def test_an_espn_league_that_reseeds_reaches_the_simulation(browser):
    _load(browser)
    d = _espn_two_week()
    d["settings"]["scheduleSettings"]["playoffReseed"] = True
    league_id = "espn:2025:4243"
    _stub_espn(browser, d, league_id)
    spec = _setup(browser, None, 17, league_id=league_id, year=2025,
                  players=[f"p{t}" for t in TWO_WEEK_TEAMS])
    assert spec["reseed"] is True
