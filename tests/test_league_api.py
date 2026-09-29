"""
An ESPN league answers the reader pages' Sleeper questions in Sleeper's shapes
(gordstats.league_api, `window.GSAPI`).

The league below is invented, but every field is one ESPN's API returned for a
real league (the owner's, read once with their permission and anonymised before
it left the Pi): the same keys, nesting and quirks - team ids with a gap, a
team without an owner, a two-week final, lineup slot ids, D/ST players with
negative ids, lineup-only "ROSTER" transactions mixed in with the moves. The
football-specific numbers (slot ids, the scoring items) are ESPN's own public
league defaults.

Runs in headless Chromium with `fetch` stubbed, so nothing reaches ESPN or
Sleeper; skips where there is no Chromium (the Pi).
"""
import asyncio
import json
import re
import shutil
import subprocess
import time
import urllib.request
from datetime import date

import pytest

from gordstats import league_api

CHROME = next((p for p in ("/usr/bin/chromium-browser", "/usr/bin/chromium",
                           "/usr/bin/google-chrome") if shutil.which(p)), None)
pytestmark = pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")
PORT = 9447

# The season the adapter treats as current (January and February belong to
# the season before, as in GSAPI.resolve).
TODAY = date.today()
SEASON = TODAY.year if TODAY.month >= 3 else TODAY.year - 1
LID = "123"
ID = f"espn:{SEASON}:{LID}"

INDEX = {"19": ["Joe Flacco", "QB", "CLE"], "1408": ["Le'Veon Bell", "RB", ""],
         "7918": ["A.J. Rose", "RB", ""], "2801": ["DeAndrew White", "WR", ""],
         "9487": ["Parker Washington", "WR", "JAX"], "6462": ["Ellis Richardson", "TE", ""],
         "11533": ["Brandon Aubrey", "K", "DAL"], "11522": ["Jerome Kapp", "WR", ""]}
ESPN_IDS = {"11252": "19", "15825": "1408", "4035068": "7918", "2515962": "2801",
            "4432620": "9487", "3926590": "6462", "3953687": "11533"}


def player(pid, name, pos, team):
    return {"id": pid, "fullName": name, "defaultPositionId": pos, "proTeamId": team,
            "stats": [], "eligibleSlots": []}


def entry(pid, slot, name="", pos=1, team=0, pts=0.0):
    return {"playerId": pid, "lineupSlotId": slot,
            "playerPoolEntry": {"id": pid, "appliedStatTotal": pts,
                                "player": player(pid, name, pos, team)}}


# Team 1: a full lineup - including Jerome Kapp, whom ESPN knows by an id the
# map lacks (placed by name), Nobody Special (placed by nothing), the Chiefs'
# D/ST (a negative id) - one on IR, and its FLEX slot left empty.
T1 = [entry(11252, 0, "Joe Flacco", 1, 5, 18.5),
      entry(15825, 2, "Le'Veon Bell", 2, 0, 7.0),
      entry(4035068, 2, "A.J. Rose", 2, 0, 3.0),
      entry(2515962, 4, "DeAndrew White", 3, 0, 9.25),
      entry(99999901, 4, "Jerome Kapp", 3, 0, 11.0),
      entry(3926590, 6, "Ellis Richardson", 4, 0, 4.0),
      entry(-16012, 16, "Chiefs D/ST", 16, 12, 6.0),
      entry(3953687, 17, "Brandon Aubrey", 5, 6, 8.0),
      entry(4432620, 20, "Parker Washington", 3, 30, 12.0),
      entry(99999902, 21, "Nobody Special", 2, 0, 0.0)]


def team(tid, owners, wins, losses, pf, roster=None):
    t = {"id": tid, "abbrev": f"T{tid}", "name": f"Team {tid}", "owners": owners,
         "primaryOwner": owners[0] if owners else None,
         "record": {"overall": {"wins": wins, "losses": losses, "ties": 0,
                                "pointsFor": pf, "pointsAgainst": 200.0}},
         "waiverRank": tid}
    if roster is not None:
        t["roster"] = {"entries": roster}
    return t


M1, M2, M4, M5 = ("{00000001-0000-4000-8000-000000000001}", "{00000002-0000-4000-8000-000000000002}",
                  "{00000004-0000-4000-8000-000000000004}", "{00000005-0000-4000-8000-000000000005}")
TEAMS = [team(1, [M1], 2, 0, 250.5), team(2, [M2], 1, 1, 210.0), team(4, [M4], 1, 1, 190.25),
         team(5, [M5], 0, 2, 150.0), team(6, [], 1, 1, 170.0)]
MEMBERS = [{"id": m, "displayName": f"Manager {i}"} for i, m in ((1, M1), (2, M2), (4, M4), (5, M5))]

SETTINGS = {
    "name": "Test League",
    "rosterSettings": {"lineupSlotCounts": {"0": 1, "2": 2, "4": 2, "6": 1, "23": 1, "16": 1,
                                            "17": 1, "20": 7, "21": 1, "1": 0, "7": 0}},
    "scheduleSettings": {"matchupPeriodCount": 2, "playoffTeamCount": 4,
                         "matchupPeriods": {"1": [1], "2": [2], "3": [3], "4": [4, 5]}},
    "scoringSettings": {"scoringItems": [
        {"statId": 53, "points": 0.5, "pointsOverrides": {}},
        {"statId": 4, "points": 4.0, "pointsOverrides": {}},
        {"statId": 43, "points": 6.0, "pointsOverrides": {}},
        {"statId": 17, "points": 2.0, "pointsOverrides": {}}]},
    "acquisitionSettings": {"isUsingAcquisitionBudget": True, "acquisitionBudget": 100},
    "draftSettings": {"type": "SNAKE", "pickOrder": [4, 1, 2, 5, 6]},
}
STATUS = {"latestScoringPeriod": 3, "finalScoringPeriod": 5, "previousSeasons": [SEASON - 2, SEASON - 1]}
BASE = {"id": int(LID), "seasonId": SEASON, "settings": SETTINGS, "status": STATUS,
        "teams": TEAMS, "members": MEMBERS, "draftDetail": {"drafted": True, "inProgress": False}}


def side(tid, by, total=None, roster=None):
    s = {"teamId": tid, "pointsByScoringPeriod": by,
         "totalPoints": sum(by.values()) if total is None else total}
    if roster is not None:
        s["rosterForCurrentScoringPeriod"] = {
            "appliedStatTotal": sum(e["playerPoolEntry"]["appliedStatTotal"] for e in roster
                                    if e["lineupSlotId"] not in (20, 21)),
            "entries": roster}
    return s


def game(gid, period, tier, home, away, winner):
    g = {"id": gid, "matchupPeriodId": period, "playoffTierType": tier, "home": home,
         "winner": winner}
    if away:
        g["away"] = away
    return g


SCHEDULE = [
    game(1, 1, "NONE", side(1, {"1": 120.0}), side(2, {"1": 100.0}), "HOME"),
    game(2, 1, "NONE", side(4, {"1": 95.0}), side(5, {"1": 80.0}), "HOME"),
    game(3, 1, "NONE", side(6, {"1": 70.0}), None, "UNDECIDED"),          # a bye
    game(4, 2, "NONE", side(1, {"2": 130.5}), side(4, {"2": 95.25}), "HOME"),
    game(5, 2, "NONE", side(2, {"2": 110.0}), side(6, {"2": 100.0}), "HOME"),
    game(6, 2, "NONE", side(5, {"2": 70.0}), None, "UNDECIDED"),
    game(7, 3, "WINNERS_BRACKET", side(1, {"3": 0.0}), side(5, {"3": 0.0}), "UNDECIDED"),
    game(8, 3, "WINNERS_BRACKET", side(2, {"3": 0.0}), side(4, {"3": 0.0}), "UNDECIDED"),
]
FINISHED = SCHEDULE[:6] + [
    game(7, 3, "WINNERS_BRACKET", side(1, {"3": 99.0}), side(5, {"3": 90.0}), "HOME"),
    game(8, 3, "WINNERS_BRACKET", side(2, {"3": 80.0}), side(4, {"3": 85.0}), "AWAY"),
    game(9, 4, "WINNERS_BRACKET", side(1, {"4": 50.0, "5": 60.0}), side(4, {"4": 70.0, "5": 30.0}), "HOME"),
    game(10, 4, "WINNERS_CONSOLATION_LADDER", side(5, {"4": 40.0, "5": 45.0}),
         side(2, {"4": 50.0, "5": 20.0}), "HOME"),
]
# Week 3 with lineups: team 1's lineup above, the others' left empty.
BOX3 = [dict(g, home=side(g["home"]["teamId"], g["home"]["pointsByScoringPeriod"],
                          roster=T1 if g["home"]["teamId"] == 1 else []))
        if g["matchupPeriodId"] == 3 else g for g in SCHEDULE]

TX = [
    {"id": "a", "type": "FREEAGENT", "status": "EXECUTED", "scoringPeriodId": 2, "teamId": 1,
     "proposedDate": 1000, "bidAmount": 0, "memberId": M1,
     "items": [{"type": "ADD", "playerId": 4432620, "fromTeamId": 0, "toTeamId": 1},
               {"type": "DROP", "playerId": 99999902, "fromTeamId": 1, "toTeamId": 0}]},
    {"id": "b", "type": "WAIVER", "status": "FAILED_INVALIDPLAYERSOURCE", "scoringPeriodId": 2,
     "teamId": 2, "proposedDate": 2000, "bidAmount": 7,
     "items": [{"type": "ADD", "playerId": 3953687, "fromTeamId": 0, "toTeamId": 2}]},
    {"id": "c", "type": "ROSTER", "status": "EXECUTED", "scoringPeriodId": 2, "teamId": 1,
     "items": [{"type": "LINEUP", "playerId": 11252, "fromTeamId": 0, "toTeamId": 0}]},
    {"id": "d", "type": "FREEAGENT", "status": "EXECUTED", "scoringPeriodId": 3, "teamId": 4,
     "items": [{"type": "ADD", "playerId": 2515962, "fromTeamId": 0, "toTeamId": 4}]},
]
PICKS = [{"overallPickNumber": 1, "roundId": 1, "roundPickNumber": 1, "teamId": 4,
          "memberId": M4, "playerId": 11252, "keeper": False, "bidAmount": 0},
         {"overallPickNumber": 2, "roundId": 1, "roundPickNumber": 2, "teamId": 1,
          "memberId": M1, "playerId": 99999901, "keeper": True, "bidAmount": 0}]

FIXTURES = {
    "base": BASE,
    "rosters": {"teams": [{"id": t["id"], "roster": {"entries": T1 if t["id"] == 1 else []}}
                          for t in TEAMS]},
    "schedule": {"schedule": SCHEDULE},
    "finished": {"schedule": FINISHED},
    "box3": {"schedule": BOX3},
    "draft": {"draftDetail": {"drafted": True, "picks": PICKS}},
    "tx": {"transactions": TX},
    "index": INDEX, "ids": ESPN_IDS,
}

# fetch, stubbed: ESPN by the views asked for, the two site files, Sleeper.
STUB = r"""
window.__calls=[];
window.fetch=function(url, init){
  __calls.push({url:String(url), credentials:(init||{}).credentials||null});
  var F=window.__FX, body=null, status=200;
  function reply(){ return Promise.resolve({ok:status===200, status:status,
    json:function(){ return Promise.resolve(JSON.parse(JSON.stringify(body))); }}); }
  if(url==='/fantasy/players-index.json'){ body=F.index; return reply(); }
  if(url==='/fantasy/espn-ids.json'){ body=F.ids; return reply(); }
  if(url.indexOf('https://api.sleeper.app/v1')===0){ body={sleeper:url}; return reply(); }
  var m=/seasons\/(\d{4})\/segments\/0\/leagues\/(\d+)\?(.*)$/.exec(url);
  if(!m){ status=404; return reply(); }
  var season=+m[1], league=m[2], q=m[3];
  var d=new Date(), cur=d.getUTCMonth()<2?d.getUTCFullYear()-1:d.getUTCFullYear();
  if(league==='777'){ status=401; return reply(); }
  if(league==='555'){ if(season!==cur-1){ status=404; return reply(); } body=F.base; return reply(); }
  if(league!=='123'){ status=404; return reply(); }
  if(season!==window.__SEASON){ body=window.__OLD||F.base; return reply(); }
  if(q.indexOf('mSettings')>=0) body=F.base;
  else if(q.indexOf('mRoster')>=0) body=F.rosters;
  else if(q.indexOf('mScoreboard')>=0 && q.indexOf('scoringPeriodId=3')>=0) body=F.box3;
  else if(q.indexOf('mMatchupScore')>=0) body=window.__DONE?F.finished:F.schedule;
  else if(q.indexOf('mDraftDetail')>=0) body=F.draft;
  else if(q.indexOf('mTransactions2')>=0) body=F.tx;
  else status=404;
  return reply();
};
"""


def _source() -> str:
    js = league_api.JS.replace("{% raw %}", "").replace("{% endraw %}", "")
    return re.sub(r"</?script>", "", js)


class Browser:
    def __init__(self):
        subprocess.run(["fuser", "-k", f"{PORT}/tcp"], capture_output=True)
        self.proc = subprocess.Popen(
            [CHROME, "--headless=new", "--no-sandbox", "--disable-gpu",
             f"--remote-debugging-port={PORT}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
        self.proc.terminate()
        self.proc.wait(timeout=10)

    def run(self, expression):
        """Evaluate, awaiting a promise, and return the value."""
        import websockets

        async def go():
            async with websockets.connect(self.ws_url, max_size=None) as ws:
                await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                                          "params": {"expression": expression,
                                                     "returnByValue": True,
                                                     "awaitPromise": True}}))
                while True:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
                    if msg.get("id") == 1:
                        result = msg.get("result", {})
                        if result.get("exceptionDetails"):
                            raise AssertionError(json.dumps(result["exceptionDetails"])[:800])
                        return result["result"].get("value")
        return asyncio.run(go())


@pytest.fixture(scope="module")
def browser():
    b = Browser()
    b.run(f"window.__FX={json.dumps(FIXTURES)}; window.__SEASON={SEASON};" + STUB + _source())
    yield b
    b.close()


def get(browser, path):
    return browser.run(f"GSAPI.get({json.dumps(path)})")


def test_the_league_reads_as_sleeper_settings(browser):
    lg = get(browser, f"/league/{ID}")
    assert lg["league_id"] == ID and lg["name"] == "Test League" and lg["season"] == str(SEASON)
    assert lg["roster_positions"] == ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "DEF", "K"] + ["BN"] * 7
    assert lg["settings"]["playoff_week_start"] == 3          # two regular-season weeks
    assert lg["settings"]["playoff_teams"] == 4
    assert lg["settings"]["reserve_slots"] == 1
    assert lg["settings"]["last_scored_leg"] == 2 and lg["settings"]["leg"] == 3
    assert lg["settings"]["waiver_type"] == 2 and lg["settings"]["waiver_budget"] == 100
    assert lg["status"] == "in_season"
    # half a point a catch, and a 300-yard bonus: half-PPR, flagged as custom
    assert lg["scoring_settings"]["rec"] == 0.5 and lg["scoring_settings"]["bonus_espn"] == 1
    # the season before is the same league id a year earlier
    assert lg["previous_league_id"] == f"espn:{SEASON - 1}:{LID}"


def test_rosters_map_players_to_sleeper_ids(browser):
    rosters = {r["roster_id"]: r for r in get(browser, f"/league/{ID}/rosters")}
    assert sorted(rosters) == [1, 2, 4, 5, 6]                  # ESPN's ids, gap and all
    r1 = rosters[1]
    # by the id map; Jerome Kapp by name; Nobody Special kept by ESPN id; D/ST by team
    assert r1["players"] == ["19", "1408", "7918", "2801", "11522", "6462", "KC", "11533",
                             "9487", "e99999902"]
    assert r1["starters"] == ["19", "1408", "7918", "2801", "11522", "6462", "0", "KC", "11533"]
    assert r1["reserve"] == ["e99999902"]
    assert r1["owner_id"] == M1
    assert r1["settings"]["wins"] == 2 and r1["settings"]["fpts"] == 250
    assert r1["settings"]["fpts_decimal"] == 50
    assert rosters[6]["owner_id"] == "team-6"                   # nobody owns it
    # the player nobody could place is named from ESPN's own payload
    named = browser.run("GSAPI.players().then(function(ix){ return ix['e99999902']; })")
    assert named == ["Nobody Special", "RB", ""]


def test_users_carry_team_names(browser):
    users = {u["user_id"]: u for u in get(browser, f"/league/{ID}/users")}
    assert users[M2]["display_name"] == "Manager 2"
    assert users[M2]["metadata"]["team_name"] == "Team 2"
    assert users["team-6"]["metadata"]["team_name"] == "Team 6"


def test_this_weeks_matchups_have_lineups(browser):
    rows = {r["roster_id"]: r for r in get(browser, f"/league/{ID}/matchups/3")}
    assert rows[1]["matchup_id"] == rows[5]["matchup_id"] != rows[2]["matchup_id"]
    assert rows[6]["matchup_id"] is None                        # out of the playoffs
    assert rows[1]["starters"][0] == "19" and rows[1]["starters_points"][0] == 18.5
    assert rows[1]["players_points"]["9487"] == 12.0            # bench points kept
    assert rows[1]["points"] == 66.75                           # starters only


def test_earlier_weeks_come_from_the_schedule(browser):
    rows = {r["roster_id"]: r for r in get(browser, f"/league/{ID}/matchups/1")}
    assert rows[1]["points"] == 120.0 and rows[1]["starters"] == []
    assert rows[1]["matchup_id"] == rows[2]["matchup_id"]
    assert rows[6]["matchup_id"] is None and rows[6]["points"] == 70.0      # a bye
    calls = browser.run("__calls.filter(function(c){ return c.url.indexOf('lm-api-reads')>0; })")
    assert calls and all(c["credentials"] == "omit" for c in calls)   # never their ESPN session


def test_a_finished_season_brackets_and_splits_a_two_week_final(browser):
    browser.run("window.__DONE=true; window.__OLD=null;")
    old = f"espn:{SEASON - 1}:{LID}"
    browser.run(f"window.__OLD=JSON.parse(JSON.stringify(__FX.base));"
                f"__OLD.status.latestScoringPeriod=6;")
    lg = get(browser, f"/league/{old}")
    assert lg["status"] == "complete" and lg["settings"]["last_scored_leg"] == 5
    assert lg["previous_league_id"] == f"espn:{SEASON - 2}:{LID}"
    # the old season's schedule is the finished one
    browser.run("(function(){var f=window.fetch; window.fetch=function(u,i){"
                "if(String(u).indexOf('/seasons/" + str(SEASON - 1) + "/')>0 && "
                "String(u).indexOf('mMatchupScore')>0){ return Promise.resolve({ok:true,status:200,"
                "json:function(){return Promise.resolve(JSON.parse(JSON.stringify(__FX.finished)));}});}"
                "return f(u,i);};})()")
    bracket = get(browser, f"/league/{old}/winners_bracket")
    final = [g for g in bracket if g.get("p") == 1]
    third = [g for g in bracket if g.get("p") == 3]
    assert len(final) == 1 and final[0]["w"] == 1 and final[0]["l"] == 4 and final[0]["r"] == 2
    assert len(third) == 1 and third[0]["w"] == 5
    assert [g["r"] for g in bracket if "p" not in g] == [1, 1]
    week4 = {r["roster_id"]: r for r in get(browser, f"/league/{old}/matchups/4")}
    week5 = {r["roster_id"]: r for r in get(browser, f"/league/{old}/matchups/5")}
    assert week4[1]["points"] == 50.0 and week5[1]["points"] == 60.0
    assert week4[1]["matchup_id"] == week4[4]["matchup_id"]
    # a finished season's rosters are its teams, without a 100 KB-a-team player list
    assert get(browser, f"/league/{old}/rosters")[0]["players"] == []


def test_draft_and_picks(browser):
    get(browser, f"/league/{ID}/rosters")
    drafts = get(browser, f"/league/{ID}/drafts")
    assert drafts[0]["draft_id"] == ID and drafts[0]["type"] == "snake"
    # the base request carries no picks: a round for every roster spot
    assert drafts[0]["status"] == "complete" and drafts[0]["settings"]["rounds"] == 16
    picks = get(browser, f"/draft/{ID}/picks")
    assert picks[0]["player_id"] == "19" and picks[0]["draft_slot"] == 1
    assert picks[0]["metadata"]["first_name"] == "Joe" and picks[0]["metadata"]["last_name"] == "Flacco"
    # an id the map lacks is placed once ESPN has named it anywhere (the rosters)
    assert picks[1]["player_id"] == "11522" and picks[1]["is_keeper"] is True


def test_transactions_keep_moves_not_lineup_changes(browser):
    tx = get(browser, f"/league/{ID}/transactions/2")
    assert [t["transaction_id"] for t in tx] == ["a", "b"]
    a, b = tx
    assert a["type"] == "free_agent" and a["status"] == "complete"
    assert a["adds"] == {"9487": 1} and a["drops"] == {"e99999902": 1}
    assert b["type"] == "waiver" and b["status"] == "failed" and b["settings"]["waiver_bid"] == 7


def test_sleeper_paths_still_go_to_sleeper(browser):
    got = get(browser, "/league/1180208989471412224/rosters")
    assert got == {"sleeper": "https://api.sleeper.app/v1/league/1180208989471412224/rosters"}
    assert get(browser, "/state/nfl") == {"sleeper": "https://api.sleeper.app/v1/state/nfl"}


@pytest.mark.parametrize("text,want", [
    ("https://fantasy.espn.com/football/league?leagueId=48153503&seasonId=2025",
     {"provider": "espn", "league": "48153503", "season": 2025}),
    ("https://fantasy.espn.com/football/team?leagueId=123456", {"provider": "espn", "league": "123456", "season": None}),
    ("123456", {"provider": "espn", "league": "123456", "season": None}),
    ("1180208989471412224", {"provider": "sleeper", "id": "1180208989471412224"}),
    ("https://sleeper.com/leagues/1180208989471412224/team", {"provider": "sleeper", "id": "1180208989471412224"}),
    ("espn:2026:123", {"provider": "espn", "id": "espn:2026:123", "league": "123", "season": 2026}),
    ("tylergordon", None),
])
def test_what_a_reader_pastes(browser, text, want):
    assert browser.run(f"GSAPI.parseRef({json.dumps(text)})") == want


def test_resolving_an_id(browser):
    assert browser.run("GSAPI.resolve('777')") == {"error": "private"}
    assert browser.run("GSAPI.resolve('999')") == {"error": "missing"}
    got = browser.run("GSAPI.resolve('555')")           # not renewed: last season's
    assert got["id"].startswith("espn:") and got["id"].endswith(":555")
    assert got["name"] == "Test League"
