"""
The weekly recap for a reader's own league (gordstats.my_recap): drawn in the
browser from Sleeper or ESPN, in place of the built one (fantasy.site.recap).

Three things are checked, because each is a way the page could be quietly
wrong:

  * The port. The awards, the headline, the season table and the markup are
    gordstats.recap's, rewritten in JavaScript; over the same weeks both must
    say the same thing, character for character. A tie broken the other way
    names a different team for an award, and nothing else would notice.
  * The best lineup. Run over the committed NFL weeks, the browser's maximum
    for every team is the Python's, and so Sleeper's own "max points"
    (test_recap pins the Python to Sleeper on the same weeks).
  * The page. The recap page's own body, served with fetch stubbed to a small
    Sleeper league and an ESPN one: the reader's league replaces the built
    recap, the awards name the teams worked out by hand below, lineup
    accuracy matches a hand-worked best lineup, the week picker moves between
    weeks from memory, the season columns fill in - and with no league picked,
    or this site's own, the built recap stands.

Headless Chromium over CDP (port 9471); skips where there is none (the Pi).
"""
import asyncio
import functools
import http.server
import json
import random
import re
import shutil
import socketserver
import subprocess
import threading
import time
import urllib.request
from datetime import date

import pytest

from conftest import ROOT
from gordstats import my_recap, recap
from gordstats.recap import Player, Side, Team, Week
from browser_util import launch, reap

CHROME = next((p for p in ("/usr/bin/chromium-browser", "/usr/bin/chromium",
                           "/usr/bin/google-chrome") if shutil.which(p)), None)
CDP = 9471
RAW = re.compile(r"\{%-?\s*(?:end)?raw\s*-?%\}")
browser_only = pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")


# --------------------------------------------------------------------------- #
# The page, as the build writes it
# --------------------------------------------------------------------------- #

def _built_week():
    """This site's league, as the built recap has it: two teams, one game."""
    sides = {"1": Side("1", 90, [Player("s1", "Site QB", "QB", 90, "QB")], [], {"s1"}),
             "2": Side("2", 80, [Player("s2", "Site RB", "RB", 80, "RB")], [], {"s2"})}
    return Week(3, {"1": Team("Site One"), "2": Team("Site Two")}, [("1", "2")], sides)


def _page(pinned=0):
    from fantasy.site import layout
    from fantasy.site import recap as nfl
    w = _built_week()
    body = layout.HEAD + nfl._with_reader(recap.page(w, [w], nfl.BASE), pinned)
    return ("<!doctype html><html><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>NFL Week 3 Recap</title></head><body>"
            "<h1>NFL Week 3 Recap</h1><p class='page-sub'>Site League</p>"
            + RAW.sub("", body) + "</body></html>")


def test_the_page_carries_both_recaps_and_picks_before_paint():
    html = _page()
    mine, built = html.index("id='rc-mine' hidden"), html.index("id='rc-built'")
    assert mine < built < html.index("getElementById('rc-mine')"), \
        "the takeover runs straight after both blocks, before anything paints"
    assert "data-week='0'" in html and "data-week='3'" in _page(3)
    # the planner, the recap and GSAPI all on the page, the recap last
    for part in ("window.GSAPI", "window.GSL", "window.GSPlan", "window.GSRecap"):
        assert html.index(part) < html.rindex("rc-host"), part
    assert "id='ml-bar'" in html, "the league bar, to pick a league with"


def test_the_section_can_bring_the_recap_stylesheet():
    assert ".rc-awards{" in my_recap.section(0) and ".rc-awards{" not in my_recap.section(0, False)
    assert ".rc-me " in my_recap.section(0, False)


# --------------------------------------------------------------------------- #
# A Sleeper league, worked by hand
# --------------------------------------------------------------------------- #
#
# Four teams, three weeks played, a FLEX and a SUPER_FLEX. Week 3:
#
#   Alpha   started 79, best 110: Q Two (30, benched) belonged in the
#           SUPER_FLEX over W Two (5), W Three (14) at WR, W One to the FLEX.
#           Lost to Bravo by 26 - its best lineup would have won.
#   Bravo   105 of 105, a perfect lineup.
#   Charlie 94 of 101: W Seven (18, a pickup, benched) at WR, W Six to the
#           FLEX over R Seven (11, a pickup who started). R Nine is on IR
#           and scored nothing: not on the bench.
#   Delta   31 of 41: Q Eight (12, benched) at QB, Q Seven to the SUPER_FLEX.
#
# Week 2 is where the IR rule shows: R Nine is on injured reserve *now* but
# scored 12 on Charlie's bench then, so he counts - 84 of 90, not 84 of 84.

SLEEPER_ID = "1001"
SLOTS = ["QB", "RB", "WR", "TE", "FLEX", "SUPER_FLEX", "K", "DEF", "BN", "BN", "BN", "BN"]
PLAYERS = {}          # short name -> (sleeper id, full name, position)
for i, (short, name, pos) in enumerate([
        ("q1", "Q One", "QB"), ("r1", "R One", "RB"), ("w1", "W One", "WR"),
        ("t1", "T One", "TE"), ("r2", "R Two", "RB"), ("w2", "W Two", "WR"),
        ("k1", "K One", "K"), ("q2", "Q Two", "QB"), ("w3", "W Three", "WR"),
        ("r3", "R Three", "RB"), ("w9", "W Nine", "WR"), ("w11", "W Eleven", "WR"),
        ("q3", "Q Three", "QB"), ("r4", "R Four", "RB"), ("w4", "W Four", "WR"),
        ("t2", "T Two", "TE"), ("w5", "W Five", "WR"), ("q4", "Q Four", "QB"),
        ("k2", "K Two", "K"), ("r5", "R Five", "RB"), ("t3", "T Three", "TE"),
        ("q5", "Q Five", "QB"), ("r6", "R Six", "RB"), ("w6", "W Six", "WR"),
        ("t4", "T Four", "TE"), ("r7", "R Seven", "RB"), ("r8", "R Eight", "RB"),
        ("q6", "Q Six", "QB"), ("k3", "K Three", "K"), ("r9", "R Nine", "RB"),
        ("w7", "W Seven", "WR"), ("w10", "W Ten", "WR"),
        ("q7", "Q Seven", "QB"), ("r10", "R Ten", "RB"), ("w8", "W Eight", "WR"),
        ("t5", "T Five", "TE"), ("r11", "R Eleven", "RB"), ("k4", "K Four", "K"),
        ("q8", "Q Eight", "QB")]):
    PLAYERS[short] = (str(4000 + i), name, pos)
for team in ("BUF", "DAL", "SEA", "NYJ"):
    PLAYERS[team] = (team, f"{team} D/ST", "DEF")


def _pid(short):
    return PLAYERS[short][0]


def _row(rid, mid, starters, bench):
    """A Sleeper matchup row: starters [(short, pts)] in slot order, then the
    rest of the roster."""
    pts = {_pid(s): p for s, p in starters + bench}
    return {"roster_id": rid, "matchup_id": mid,
            "points": round(sum(p for _, p in starters), 2),
            "starters": [_pid(s) for s, _ in starters],
            "starters_points": [p for _, p in starters],
            "players": [_pid(s) for s, _ in starters + bench],
            "players_points": pts, "custom_points": None}


def _alpha(q1, r1, w1, t1, r2, w2, k1, d, bench):
    return [("q1", q1), ("r1", r1), ("w1", w1), ("t1", t1), ("r2", r2), ("w2", w2),
            ("k1", k1), ("BUF", d)], bench


A_EARLY = _alpha(20, 10, 10, 5, 5, 5, 5, 5, [("q2", 0), ("w3", 0), ("r3", 0), ("w9", 0)])
B_EARLY = ([("q3", 20), ("r4", 10), ("w4", 10), ("t2", 5), ("w5", 5), ("q4", 5), ("k2", 5),
            ("DAL", 5)], [("r5", 0), ("t3", 0)])
C_WEEK1 = ([("q5", 20), ("r6", 20), ("w6", 20), ("t4", 10), ("r8", 10), ("q6", 10), ("k3", 5),
            ("SEA", 5)], [("r9", 0), ("w10", 0)])
C_WEEK2 = ([("q5", 20), ("r6", 10), ("w6", 12), ("t4", 4), ("r8", 6), ("q6", 22), ("k3", 7),
            ("SEA", 3)], [("r9", 12), ("w10", 1)])
D_EARLY = ([("q7", 10), ("r10", 10), ("w8", 10), ("t5", 5), ("w11", 5), ("r11", 5), ("k4", 5),
            ("NYJ", 5)], [("q8", 0)])

SLEEPER_WEEKS = {
    1: [_row(1, 1, *A_EARLY), _row(3, 1, *C_WEEK1), _row(2, 2, *B_EARLY), _row(4, 2, *D_EARLY)],
    2: [_row(1, 1, *A_EARLY), _row(4, 1, *D_EARLY), _row(2, 2, *B_EARLY), _row(3, 2, *C_WEEK2)],
    3: [_row(1, 1, *_alpha(25, 12, 10, 6, 8, 5, 9, 4,
                           [("q2", 30), ("w3", 14), ("r3", 2), ("w11", 0)])),
        _row(2, 1, [("q3", 18), ("r4", 20), ("w4", 13), ("t2", 11), ("w5", 9), ("q4", 16),
                    ("k2", 8), ("DAL", 10)], [("r5", 3), ("t3", 1)]),
        _row(3, 2, [("q5", 20), ("r6", 15), ("w6", 12), ("t4", 4), ("r7", 11), ("q6", 22),
                    ("k3", 7), ("SEA", 3)], [("w7", 18), ("r9", 0)]),
        _row(4, 2, [("q7", 10), ("r10", 5), ("w8", 6), ("t5", 3), ("w9", 4), ("r11", 2),
                    ("k4", 1), ("NYJ", 0)], [("q8", 12)])],
}


def _tx(kind, leg, adds, status="complete"):
    return {"type": kind, "status": status, "leg": leg, "roster_ids": sorted(set(adds.values())),
            "adds": {_pid(s): r for s, r in adds.items()}, "drops": None}


SLEEPER = {
    f"/league/{SLEEPER_ID}": {
        "league_id": SLEEPER_ID, "name": "Fake League", "season": "2026", "status": "in_season",
        "roster_positions": SLOTS, "scoring_settings": {"rec": 1},
        "settings": {"leg": 4, "last_scored_leg": 3, "playoff_week_start": 15,
                     "league_average_match": 1, "start_week": 1}},
    f"/league/{SLEEPER_ID}/users": [
        {"user_id": "u1", "display_name": "al", "metadata": {"team_name": "Alpha"}, "avatar": None},
        {"user_id": "u2", "display_name": "bo", "metadata": {"team_name": "Bravo & Co"},
         "avatar": None},
        {"user_id": "u3", "display_name": "cy", "metadata": {"team_name": "Charlie's"},
         "avatar": None},
        {"user_id": "u4", "display_name": "Delta", "metadata": {}, "avatar": None}],
    f"/league/{SLEEPER_ID}/rosters": [
        {"roster_id": rid, "owner_id": f"u{rid}", "reserve": [_pid("r9")] if rid == 3 else [],
         "taxi": None, "players": SLEEPER_WEEKS[3][rid - 1]["players"],
         "settings": {"wins": 1, "losses": 2}} for rid in (1, 2, 3, 4)],
    # Week 1: Bravo's defence was claimed after the draft. Week 3: Charlie's
    # two waiver adds, Alpha and Delta's trade, and a claim that failed.
    f"/league/{SLEEPER_ID}/transactions/1": [_tx("waiver", 1, {"DAL": 2})],
    f"/league/{SLEEPER_ID}/transactions/2": [],
    f"/league/{SLEEPER_ID}/transactions/3": [
        _tx("waiver", 3, {"r7": 3}), _tx("free_agent", 3, {"w7": 3}),
        _tx("trade", 3, {"w9": 4, "w11": 1}), _tx("waiver", 3, {"q8": 1}, "failed")],
}
for wk, rows in SLEEPER_WEEKS.items():
    SLEEPER[f"/league/{SLEEPER_ID}/matchups/{wk}"] = rows

INDEX = {pid: [name, pos, ""] for pid, name, pos in PLAYERS.values() if pos != "DEF"}


# --------------------------------------------------------------------------- #
# An ESPN league, in ESPN's own shapes (see tests/test_league_api.py)
# --------------------------------------------------------------------------- #
#
# Four teams, two weeks played. Week 1 is older than GSAPI's "this week and
# last", so its lineups exist only because the recap asks for them. Eagles
# Nest, week 1: started 50 (QB 20, RB 10, WR 8, FLEX 5, D/ST 7); the best is
# 70 - the benched QB (30), the benched WR (15) and the WR it started in the
# FLEX (8). Its IR player scored 40 and is still no part of it.

TODAY = date.today()
SEASON = TODAY.year if TODAY.month >= 3 else TODAY.year - 1
ESPN_LEAGUE = "4242"
ESPN_ID = f"espn:{SEASON}:{ESPN_LEAGUE}"
ESPN_POS = {"QB": 1, "RB": 2, "WR": 3, "TE": 4, "K": 5}
ESPN_SLOT = {"QB": 0, "RB": 2, "WR": 4, "FLEX": 23, "DEF": 16, "BN": 20, "IR": 21}
ESPN_IDS, ESPN_INDEX = {}, {}


def _espn_player(espn, sleeper, name, pos):
    ESPN_IDS[str(espn)] = sleeper
    ESPN_INDEX[sleeper] = [name, pos, ""]
    return espn, name, pos


def _entry(player, slot, pts):
    espn, name, pos = player
    return {"playerId": espn, "lineupSlotId": ESPN_SLOT[slot],
            "playerPoolEntry": {"id": espn, "appliedStatTotal": pts,
                                "player": {"id": espn, "fullName": name,
                                           "defaultPositionId": ESPN_POS.get(pos, 16),
                                           "proTeamId": 0, "stats": []}}}


def _dst(team_id, slot, pts):
    return {"playerId": -16000 - team_id, "lineupSlotId": ESPN_SLOT[slot],
            "playerPoolEntry": {"id": -16000 - team_id, "appliedStatTotal": pts,
                                "player": {"id": -16000 - team_id, "fullName": "D/ST",
                                           "defaultPositionId": 16, "proTeamId": team_id,
                                           "stats": []}}}


EA = [_espn_player(11, "5001", "Ea QB", "QB"), _espn_player(12, "5002", "Ea RB", "RB"),
      _espn_player(13, "5003", "Ea WR", "WR"), _espn_player(14, "5004", "Ea RB2", "RB"),
      _espn_player(15, "5005", "Ea WR2", "WR"), _espn_player(16, "5006", "Ea QB2", "QB"),
      _espn_player(17, "5007", "Ea Hurt", "RB")]


def _others(t):
    """Teams 2-4: a perfect lineup, the same every week."""
    ps = [_espn_player(t * 100 + j, str(5000 + t * 100 + j), f"T{t} {pos}", pos)
          for j, pos in enumerate(["QB", "RB", "WR", "RB", "WR"])]
    base = 10 * t
    return [_entry(ps[0], "QB", base), _entry(ps[1], "RB", 8), _entry(ps[2], "WR", 7),
            _entry(ps[3], "FLEX", 5), _dst([0, 0, 1, 2, 3][t], "DEF", 4), _entry(ps[4], "BN", 0)]


ESPN_LINEUPS = {
    1: {1: [_entry(EA[0], "QB", 20), _entry(EA[1], "RB", 10), _entry(EA[2], "WR", 8),
            _entry(EA[3], "FLEX", 5), _dst(12, "DEF", 7), _entry(EA[4], "BN", 15),
            _entry(EA[5], "BN", 30), _entry(EA[6], "IR", 40)],
        2: _others(2), 3: _others(3), 4: _others(4)},
    2: {1: [_entry(EA[5], "QB", 25), _entry(EA[1], "RB", 10), _entry(EA[4], "WR", 12),
            _entry(EA[2], "FLEX", 8), _dst(12, "DEF", 7), _entry(EA[0], "BN", 0),
            _entry(EA[3], "BN", 0), _entry(EA[6], "IR", 0)],
        2: _others(2), 3: _others(3), 4: _others(4)},
}
ESPN_PAIRS = {1: [(1, 2), (3, 4)], 2: [(1, 3), (2, 4)], 3: [(1, 4), (2, 3)]}
ESPN_SETTINGS = {
    "name": "ESPN Test League",
    "rosterSettings": {"lineupSlotCounts": {"0": 1, "2": 1, "4": 1, "23": 1, "16": 1,
                                            "20": 3, "21": 1}},
    "scheduleSettings": {"matchupPeriodCount": 14, "playoffTeamCount": 4,
                         "matchupPeriods": {str(w): [w] for w in range(1, 18)}},
    "scoringSettings": {"scoringItems": [{"statId": 53, "points": 1.0}]},
    "acquisitionSettings": {}, "draftSettings": {"type": "SNAKE"},
}
ESPN_TEAMS = [{"id": 1, "name": "Eagles Nest", "owners": ["m1"], "primaryOwner": "m1"},
              {"id": 2, "location": "Big", "nickname": "Dogs", "owners": ["m2"],
               "primaryOwner": "m2"},
              {"id": 3, "name": "Third Team", "owners": ["m3"], "primaryOwner": "m3"},
              {"id": 4, "name": "Fourth Team", "owners": ["m4"], "primaryOwner": "m4"}]
ESPN_BASE = {"id": int(ESPN_LEAGUE), "seasonId": SEASON, "settings": ESPN_SETTINGS,
             "status": {"latestScoringPeriod": 3, "finalScoringPeriod": 17,
                        "previousSeasons": []},
             "teams": ESPN_TEAMS, "members": [{"id": f"m{i}", "displayName": f"M{i}"}
                                              for i in range(1, 5)],
             "draftDetail": {"drafted": True}}


def _espn_side(tid, week, lineup):
    total = sum(e["playerPoolEntry"]["appliedStatTotal"] for e in lineup or []
                if e["lineupSlotId"] not in (20, 21))
    s = {"teamId": tid, "pointsByScoringPeriod": {str(week): total}, "totalPoints": total}
    if lineup is not None:
        s["rosterForCurrentScoringPeriod"] = {"appliedStatTotal": total, "entries": lineup}
    return s


def _espn_schedule(with_week=None):
    games, gid = [], 0
    for week, pairs in ESPN_PAIRS.items():
        for home, away in pairs:
            gid += 1
            lu = ESPN_LINEUPS.get(week, {}) if week == with_week else {}
            h = _espn_side(home, week, lu.get(home))
            a = _espn_side(away, week, lu.get(away))
            if week != with_week and week in ESPN_LINEUPS:
                # Scores without lineups, as ESPN's light schedule has them.
                for s, t in ((h, home), (a, away)):
                    pts = _espn_side(t, week, ESPN_LINEUPS[week][t])["totalPoints"]
                    s["pointsByScoringPeriod"] = {str(week): pts}
                    s["totalPoints"] = pts
            games.append({"id": gid, "matchupPeriodId": week, "playoffTierType": "NONE",
                          "home": h, "away": a, "winner": "UNDECIDED"})
    return games


ESPN = {
    "base": ESPN_BASE,
    "rosters": {"teams": [{"id": t["id"], "roster": {"entries": []}} for t in ESPN_TEAMS]},
    "weeks": {str(w): dict(ESPN_BASE, schedule=_espn_schedule(w)) for w in (1, 2)},
    "schedule": {"schedule": _espn_schedule()},
    "tx": {"transactions": []},
}


def _site_id():
    from fantasy.config import LEAGUE_IDS
    return sorted(str(v) for v in LEAGUE_IDS.values())[0]


FIXTURES = {"sleeper": SLEEPER, "index": {**INDEX, **ESPN_INDEX}, "espnIds": ESPN_IDS,
            "espn": ESPN, "espnId": ESPN_ID, "site": _site_id()}

# Runs before the page's own scripts: the league the reader picked (from the
# address: ?league=sleeper / espn / site / none) and fetch, stubbed, so nothing
# reaches Sleeper or ESPN.
BOOT = r"""
(function(){
  var FX=__FX__;
  var mode=(/[?&]league=(\w+)/.exec(location.search)||[])[1]||'none';
  try{
    localStorage.clear();
    var pick={sleeper:{id:'1001', name:'Fake League'},
              espn:{id:FX.espnId, name:'ESPN Test League', provider:'espn'},
              site:{id:FX.site, name:'Site'}}[mode];
    if(pick) localStorage.setItem('gsSleeperLeague', JSON.stringify(pick));
    // The reader's own team, picked on My Team.
    localStorage.setItem('gsMyRoster', JSON.stringify({'1001':'3'}));
  }catch(e){}
  window.__calls=[];
  window.fetch=function(url, init){
    url=String(url);
    __calls.push({url:url, credentials:(init||{}).credentials||null});
    function reply(body, status){
      status=status||200;
      return new Promise(function(done){ setTimeout(function(){ done({ok:status===200,
        status:status, json:function(){ return Promise.resolve(JSON.parse(JSON.stringify(body))); }});
      }, 5); });
    }
    if(url.indexOf('/api/leagues')===0) return reply({signedIn:false});
    if(url==='/fantasy/players-index.json') return reply(FX.index);
    if(url==='/fantasy/espn-ids.json') return reply(FX.espnIds);
    var s=/^https:\/\/api\.sleeper\.app\/v1(\/.*)$/.exec(url);
    if(s) return FX.sleeper[s[1]]===undefined?reply(null,404):reply(FX.sleeper[s[1]]);
    var e=/lm-api-reads\.fantasy\.espn\.com\/.*\/leagues\/(\d+)\?(.*)$/.exec(url);
    if(e){
      var q=e[2], wk=(/scoringPeriodId=(\d+)/.exec(q)||[])[1];
      if(q.indexOf('mScoreboard')>=0) return FX.espn.weeks[wk]?reply(FX.espn.weeks[wk]):reply(null,404);
      if(q.indexOf('mRoster')>=0) return reply(FX.espn.rosters);
      if(q.indexOf('mTransactions2')>=0) return reply(FX.espn.tx);
      if(q.indexOf('mSettings')>=0) return reply(FX.espn.base);
      if(q.indexOf('mMatchupScore')>=0) return reply(FX.espn.schedule);
    }
    return reply(null, 404);
  };
})();
""".replace("__FX__", json.dumps(FIXTURES))


# --------------------------------------------------------------------------- #
# The harness
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def site(tmp_path_factory):
    root = tmp_path_factory.mktemp("recap")
    (root / "index.html").write_text(_page(), encoding="utf-8")
    (root / "week-1").mkdir()
    (root / "week-1" / "index.html").write_text(_page(1), encoding="utf-8")
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    handler = functools.partial(Quiet, directory=str(root))
    server = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="module")
def chrome():
    subprocess.run(["fuser", "-k", f"{CDP}/tcp"], capture_output=True)
    proc = launch(CHROME, CDP)
    ws_url = None
    for _ in range(60):
        try:
            ws_url = next(t["webSocketDebuggerUrl"] for t in json.load(
                urllib.request.urlopen(f"http://127.0.0.1:{CDP}/json")) if t["type"] == "page")
            break
        except Exception:                                   # noqa: BLE001
            time.sleep(0.5)
    if ws_url is None:
        proc.terminate()
        raise RuntimeError("Chromium did not come up")
    yield ws_url
    proc.terminate()
    reap(proc)


def drive(ws_url, url, steps, timeout=20):
    """Open `url` with BOOT in place and run `steps`: ("wait", expr) polls
    until expr is truthy, ("eval", expr) collects its value, ("do", expr)
    only runs it. Returns the values and any uncaught exception the page
    threw."""
    import websockets

    async def go():
        async with websockets.connect(ws_url, max_size=None) as ws:
            n, errors = 0, []

            async def send(method, params=None):
                nonlocal n
                n += 1
                me = n
                await ws.send(json.dumps({"id": me, "method": method, "params": params or {}}))
                while True:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
                    if msg.get("method") == "Runtime.exceptionThrown":
                        d = msg["params"]["exceptionDetails"]
                        errors.append((d.get("exception") or {}).get("description") or d.get("text"))
                    if msg.get("id") == me:
                        return msg

            async def evaluate(expr, strict=True):
                r = await send("Runtime.evaluate", {"expression": expr, "returnByValue": True,
                                                    "awaitPromise": True})
                res = r.get("result") or {}
                if "error" in r or res.get("exceptionDetails"):
                    if strict:
                        raise AssertionError(json.dumps(r)[:1500])
                    return None
                return (res.get("result") or {}).get("value")

            added = await send("Page.addScriptToEvaluateOnNewDocument", {"source": BOOT})
            await send("Page.enable")
            await send("Runtime.enable")
            await send("Page.navigate", {"url": url})
            out = []
            for kind, expr in steps:
                if kind == "wait":
                    deadline = time.time() + timeout
                    while not await evaluate(expr, strict=False):
                        if time.time() > deadline:
                            dump = await evaluate("document.body?document.body.innerText"
                                                  ".slice(0,1500):''", strict=False)
                            raise AssertionError(f"timed out waiting for {expr}\n{dump}\n{errors}")
                        await asyncio.sleep(0.1)
                elif kind == "sleep":
                    await asyncio.sleep(float(expr))
                elif kind == "do":
                    await evaluate(expr)
                else:
                    out.append(await evaluate(expr))
            await send("Page.removeScriptToEvaluateOnNewDocument",
                       {"identifier": added["result"]["identifier"]})
            return out, errors
    return asyncio.run(go())


READ = r"""(function(){
  var h=document.getElementById('rc-host');
  function t(e){ return e?e.textContent.trim():null; }
  function all(sel, f){ return [].map.call(h.querySelectorAll(sel), f); }
  return {
    mine:!document.getElementById('rc-mine').hidden,
    built:!document.getElementById('rc-built').hidden,
    h1:t(document.querySelector('h1')), sub:t(document.querySelector('.page-sub')),
    lead:t(h.querySelector('.rc-lead')),
    weeks:all('.rc-weeks a, .rc-weeks span', function(e){ return e.tagName+' '+e.textContent; }),
    awards:all('.rc-award', function(a){
      return {label:t(a.querySelector('.lb')), team:t(a.querySelector('.tm')),
              stat:t(a.querySelector('.st')), detail:t(a.querySelector('.dt')),
              tone:a.className.replace('rc-award','').trim()}; }),
    acc:all('.rc-acc tbody tr', function(r){
      var name=[].filter.call(r.querySelectorAll('.tmw > span'), function(e){
        return !e.className; })[0];
      return [t(name)].concat([].slice.call(r.cells,1).map(t))
        .concat([r.classList.contains('rc-me')?'you':'']); }),
    games:all('.rc-game', t),
    med:all('.rc-med', t),
    waiting:!!h.querySelector('.rc-wait'),
    note:t(h.querySelector('.rc-src'))
  };
})()"""

# Drawn, and nothing more on its way: the season columns and the pickups in.
READY = "document.querySelector('#rc-host[aria-busy=\"false\"] .rc-award')"


def _week_ready(n):
    return READY + f" && document.querySelector('h1').textContent==='NFL Week {n} Recap'"


def _awards(view):
    return {a["label"]: a for a in view["awards"]}


# --------------------------------------------------------------------------- #
# The page: a Sleeper league
# --------------------------------------------------------------------------- #

@browser_only
def test_a_sleeper_league_takes_the_page_over(chrome, site):
    (view, calls), errors = drive(chrome, site + "?league=sleeper", [
        ("wait", _week_ready(3)), ("eval", READ), ("eval", "__calls.map(function(c){return c.url;})")])
    assert not errors, errors
    assert view["mine"] and not view["built"], "the reader's league replaces the built recap"
    assert (view["h1"], view["sub"]) == ("NFL Week 3 Recap", "Fake League")
    assert view["lead"] == ("Week 3: Bravo & Co top-scored with 105, Alpha left 31 on the bench "
                            "and 1 team was beaten by their own bench.")
    assert view["weeks"] == ["A 1", "A 2", "SPAN 3"]
    # Median 86.5: Bravo and Charlie above it.
    assert view["med"] == ["Med L", "Med W", "Med W", "Med L"]
    assert view["games"][0].startswith("Alpha") and "best lineups 110 / 105" in view["games"][0]

    a = _awards(view)
    want = {
        "High score": ("Bravo & Co", "105", "Led by R Four, 20", "good"),
        "Low score": ("Delta", "31", "Left 10 on the bench", "bad"),
        "Blowout": ("Charlie's", "by 63", "Over Delta, 94–31", "good"),
        "Nail-biter": ("Bravo & Co", "by 26", "Over Alpha, 105–79", ""),
        "Luckiest win": ("Charlie's", "94", "1 team scored more — just not Delta", "good"),
        "Toughest loss": ("Alpha", "79", "Would have beaten 1 of the other 3 teams", "bad"),
        # the SUPER_FLEX takes a quarterback: the swap a FLEX-only rule misses
        "Cost them the game": ("Alpha", "lost by 26",
                               "Best lineup: 110. Started W Two (5) over Q Two (30)", "bad"),
        "Best lineup": ("Bravo & Co", "100.0%", "The best possible lineup", "good"),
        "Most left on the bench": ("Alpha", "31", "Started W Two (5) over Q Two (30)", "bad"),
        "Player of the week": ("Alpha", "25", "Q One, QB", "good"),
        "Bench star": ("Alpha", "30", "Q Two, QB, never left the bench", ""),
        # R Seven started; W Seven sat; W Nine and W Eleven came in a trade.
        "Pickup of the week": ("Charlie's", "11", "R Seven, RB, added this week", "good"),
    }
    assert {k: (v["team"], v["stat"], v["detail"] or "", v["tone"]) for k, v in a.items()} == want
    assert list(a) == list(want), "in the built recap's order"

    # Week and season, best season first. Charlie's season: 100+84+94 of
    # 100+90+101; Delta's 55+55+31 of 55+55+41; Alpha's 65+65+79 of 65+65+110.
    assert view["acc"] == [
        ["Bravo & Co", "100.0%", "0", "100.0%", "0", "3", ""],
        ["Charlie's", "93.1%", "7", "95.5%", "13", "1", "you"],
        ["Delta", "75.6%", "10", "93.4%", "10", "2", ""],
        ["Alpha", "71.8%", "31", "87.1%", "31", "2", ""]]
    assert not view["waiting"]
    assert "Missed the projection" in view["note"] and "power risers" in view["note"]

    # The week, then the rest of the season behind it - each asked for once.
    matchups = [c for c in calls if "/matchups/" in c]
    assert sorted(matchups) == [f"https://api.sleeper.app/v1/league/{SLEEPER_ID}/matchups/{w}"
                                for w in (1, 2, 3)]
    assert matchups[0].endswith("/matchups/3"), "the week on screen first"


@browser_only
def test_the_readers_recap_shares_its_own_league_and_week(chrome, site):
    """The built recap's Share button sends this site's week; the reader's
    sends the reader's: its week on the recap page, the league added to the
    address by share.js (data-league), its name leading the line."""
    (got,), errors = drive(chrome, site + "?league=sleeper", [
        ("wait", _week_ready(3)),
        ("eval", "(function(){ var b=document.querySelector('#rc-host .gs-share');"
                 " return b && {url:b.dataset.url, text:b.dataset.text,"
                 " league:b.hasAttribute('data-league')}; })()")])
    assert not errors, errors
    assert got == {"url": "/#week-3", "league": True,
                   "text": "Fake League \u2014 Week 3: Bravo & Co top-scored with 105, Alpha "
                           "left 31 on the bench and 1 team was beaten by their own bench."}


@browser_only
def test_the_week_picker_moves_between_weeks_from_memory(chrome, site):
    (w1, w2, w3, calls), errors = drive(chrome, site + "?league=sleeper", [
        ("wait", _week_ready(3)),
        ("do", "document.querySelector('#rc-host .rc-weeks a[href=\"#week-1\"]').click()"),
        ("wait", _week_ready(1)), ("eval", READ),
        ("do", "document.querySelector('#rc-host .rc-weeks a[href=\"#week-2\"]').click()"),
        ("wait", _week_ready(2)), ("eval", READ),
        ("do", "history.back()"), ("wait", _week_ready(1)),
        ("do", "location.hash='#week-3'"), ("wait", _week_ready(3)), ("eval", READ),
        ("eval", "__calls.map(function(c){return c.url;})")])
    assert not errors, errors
    assert w1["weeks"] == ["SPAN 1", "A 2", "A 3"]
    assert w1["lead"] == "Week 1: Charlie's top-scored with 100."
    # The first week's pickups are the claims since the draft.
    pk = _awards(w1)["Pickup of the week"]
    assert (pk["team"], pk["stat"], pk["detail"]) == ("Bravo & Co", "5",
                                                      "DAL D/ST, added since the draft")
    # Week 1's season is week 1.
    assert all(r[1] == r[3] and r[2] == r[4] for r in w1["acc"])
    # Week 2: R Nine is on IR now but played then - 84 of 90, not a perfect 84.
    charlie = next(r for r in w2["acc"] if r[0] == "Charlie's")
    assert charlie[1:3] == ["93.3%", "6"]
    assert "Pickup of the week" not in _awards(w2), "nobody new in week 2"
    assert w3["acc"] and w3["acc"][0][0] == "Bravo & Co"
    # Moving about read nothing twice.
    for w in (1, 2, 3):
        assert calls.count(f"https://api.sleeper.app/v1/league/{SLEEPER_ID}/matchups/{w}") == 1
        assert calls.count(f"https://api.sleeper.app/v1/league/{SLEEPER_ID}/transactions/{w}") == 1


@browser_only
def test_a_week_page_opens_the_readers_league_on_that_week(chrome, site):
    (view,), errors = drive(chrome, site + "week-1/?league=sleeper",
                            [("wait", _week_ready(1)), ("eval", READ)])
    assert not errors, errors
    assert view["weeks"][0] == "SPAN 1" and view["mine"]


# --------------------------------------------------------------------------- #
# The page: an ESPN league
# --------------------------------------------------------------------------- #

@browser_only
def test_an_espn_league_has_lineups_for_every_week(chrome, site):
    (w2, w1, calls), errors = drive(chrome, site + "?league=espn", [
        ("wait", _week_ready(2)), ("eval", READ),
        ("do", "document.querySelector('#rc-host .rc-weeks a[href=\"#week-1\"]').click()"),
        ("wait", _week_ready(1)), ("eval", READ), ("eval", "__calls")])
    assert not errors, errors
    assert w2["mine"] and (w2["h1"], w2["sub"]) == ("NFL Week 2 Recap", "ESPN Test League")
    assert w2["weeks"] == ["A 1", "SPAN 2"]
    assert {r[0] for r in w2["acc"]} == {"Eagles Nest", "Big Dogs", "Third Team", "Fourth Team"}
    # Week 1 is older than GSAPI's lineups reach, and still judged: 50 of 70,
    # the IR player's 40 no part of it.
    eagles = next(r for r in w1["acc"] if r[0] == "Eagles Nest")
    assert eagles[1:3] == ["71.4%", "20"]
    a = _awards(w1)
    # Two calls cost ten each (the QB, and the WR2 left out of the FLEX); the
    # built rule names the first on the roster, and so does this.
    assert (a["Most left on the bench"]["team"], a["Most left on the bench"]["detail"]) == \
        ("Eagles Nest", "Started Ea RB2 (5) over Ea WR2 (15)")
    assert a["Bench star"]["detail"] == "Ea QB2, QB, never left the bench"
    assert "Sleeper does not say" not in (w1["note"] or ""), "ESPN's lineups say who was on IR"
    espn = [c for c in calls if "lm-api-reads" in c["url"]]
    assert espn and all(c["credentials"] == "omit" for c in espn), "never the reader's ESPN session"
    weeks = [c["url"] for c in espn if "mScoreboard" in c["url"]]
    assert sorted(re.search(r"scoringPeriodId=(\d+)", u).group(1) for u in weeks) == ["1", "2"]
    assert not any("mRoster" in c["url"] for c in espn
                   if "scoringPeriodId" in c["url"]), "the recap never asks for ESPN's rosters"


# --------------------------------------------------------------------------- #
# With no league picked, the built recap stands
# --------------------------------------------------------------------------- #

@browser_only
@pytest.mark.parametrize("mode", ["none", "site"])
def test_with_no_reader_league_the_built_recap_stands(chrome, site, mode):
    (view,), errors = drive(chrome, site + f"?league={mode}", [
        ("wait", "document.readyState==='complete' && window.GSRecap"), ("sleep", "0.6"),
        ("eval", r"""({mine:!document.getElementById('rc-mine').hidden,
          built:!document.getElementById('rc-built').hidden,
          host:document.getElementById('rc-host').innerHTML,
          h1:document.querySelector('h1').textContent,
          builtAwards:document.querySelectorAll('#rc-built .rc-award').length,
          matchups:__calls.filter(function(c){ return c.url.indexOf('/matchups/')>0; }).length})""")])
    assert not errors, errors
    assert view["built"] and not view["mine"]
    assert view["host"] == "" and view["matchups"] == 0
    assert view["h1"] == "NFL Week 3 Recap" and view["builtAwards"] > 0


# --------------------------------------------------------------------------- #
# The port against the Python
# --------------------------------------------------------------------------- #

# Plain weeks in, the JS's own sides out - its started/max/left are its own.
MAKE = r"""
function mk(w){
  var sides={}, order=[];
  w.sides.forEach(function(s){
    function P(p){ return {id:p[0], name:p[1], pos:p[2], pts:p[3], slot:p[4]||''}; }
    var best={};
    s.best.forEach(function(id){ best[id]=1; });
    sides[s.key]=GSRecap.side(s.key, s.points, s.starters.map(P), s.bench.map(P), best);
    order.push(s.key);
  });
  var pk=(w.pickups||[]).map(function(x){
    var s=sides[x.key];
    return {key:x.key, player:s.starters.concat(s.bench).filter(function(p){
      return p.id===x.id; })[0], started:x.started};
  });
  return {number:w.number, teams:w.teams, games:w.games, sides:sides, order:order,
          median:w.median, flex:{FLEX:['RB','WR','TE']}, pickups:pk};
}
"""

NAMES = ["Alpha", "Bravo & Co", "Charlie's", "<Delta>", "Echo \"E\"", "Fox", "Golf", "Hotel",
         "India", "Juliet", "Kilo", "Lima"]
STARTING = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"]


def _pts(rng):
    if rng.random() < 0.3:
        return rng.choice([0.0, 5.0, 10.0, 12.5, 20.0])      # ties, on purpose
    return round(rng.uniform(-3, 38), 2)


def _random_week(rng, number, keys):
    from fantasy.site import matchups as mu
    sides, plain = {}, []
    for k in keys:
        starters = []
        for i, slot in enumerate(STARTING):
            pos = rng.choice(["RB", "WR", "TE"]) if slot == "FLEX" else slot
            name = f"{k}'s {pos} #{i}" if rng.random() < 0.2 else f"P{k}-{i}"
            starters.append((f"{k}s{i}", "PIT D/ST" if pos == "DEF" else name, pos, _pts(rng), slot))
        bench = [(f"{k}b{j}", f"B{k}-{j} & co", rng.choice(["QB", "RB", "WR", "TE", "K", "DEF"]),
                  _pts(rng), "") for j in range(rng.randint(0, 5))]
        rows = ([{"pid": p[0], "slot": p[4]} for p in starters]
                + [{"pid": p[0], "slot": "BN"} for p in bench])
        cards = {p[0]: {"pos": p[2]} for p in starters + bench}
        best = mu.best_lineup(rows, cards, {p[0]: p[3] for p in starters + bench},
                              STARTING + ["BN"])
        points = round(sum(p[3] for p in starters), 2)
        if rng.random() < 0.15:
            points = round(points + rng.choice([-2.5, 1.25, 3.0]), 2)   # a stat correction
        sides[k] = Side(k, points, [Player(*p) for p in starters],
                        [Player(*p[:4]) for p in bench], best)
        plain.append({"key": k, "points": points, "starters": starters,
                      "bench": [list(p[:4]) for p in bench], "best": sorted(best)})
    # Some scores tied across teams, so the tie-breaks are exercised.
    if len(keys) >= 4 and rng.random() < 0.5:
        a, b = rng.sample(keys, 2)
        sides[b].points = sides[a].points
        next(p for p in plain if p["key"] == b)["points"] = sides[a].points
    order = keys[:]
    games = [(order[i], order[i + 1]) for i in range(0, len(order) - 1, 2)]
    pickups = []
    for k in rng.sample(keys, min(3, len(keys))):
        pool = sides[k].starters + sides[k].bench
        p = rng.choice(pool)
        pickups.append(recap.Pickup(k, p, p in sides[k].starters))
    teams = {k: Team(NAMES[int(k) - 1],
                     avatar="https://x.test/a'b.png" if int(k) % 3 == 0 else "") for k in keys}
    week = Week(number, teams, games, sides, median=rng.random() < 0.5,
                flex={"FLEX": ("RB", "WR", "TE")}, pickups=pickups)
    js = {"number": number, "teams": {k: {"name": t.name, "avatar": t.avatar}
                                      for k, t in teams.items()},
          "games": [list(g) for g in games], "sides": plain, "median": week.median,
          "pickups": [{"key": p.key, "id": p.player.id, "started": p.started} for p in pickups]}
    return week, js


def _cases(seed):
    rng = random.Random(seed)
    n = rng.choice([4, 6, 8, 10, 12])
    keys = [str(i) for i in range(1, n + 1)]
    rng.shuffle(keys)
    return [_random_week(rng, w, keys) for w in (1, 2, 3)]


@browser_only
def test_the_port_says_what_the_python_says(chrome, site):
    cases = [_cases(seed) for seed in range(60)]
    payload = [[js for _, js in weeks] for weeks in cases]
    (got,), errors = drive(chrome, site + "?league=none", [
        ("wait", "window.GSRecap"),
        ("eval", MAKE + "(function(all){ return all.map(function(weeks){"
                 "  var ws=weeks.map(mk);"
                 "  return ws.map(function(w, i){"
                 "    var to=GSRecap.season(ws.slice(0, i+1));"
                 "    return {awards:GSRecap.awards(w), headline:GSRecap.headline(w),"
                 "      sides:w.order.map(function(k){ var s=w.sides[k];"
                 "        return [k, s.started, s.max, s.left]; }),"
                 "      season:to.map(function(r){ return [r.key, r.left, r.perfect, r.weeks, r.pct]; }),"
                 "      games:GSRecap.games(w), cards:GSRecap.awardCards(w),"
                 "      table:GSRecap.accuracy(w, to, {})};"
                 "  });"
                 "}); })(" + json.dumps(payload) + ")")])
    assert not errors, errors
    for seed, (weeks, mine) in enumerate(zip(cases, got)):
        py_weeks = [w for w, _ in weeks]
        for i, (w, js) in enumerate(zip(py_weeks, mine)):
            where = f"seed {seed}, week {w.number}"
            assert [[k, s.started, s.max, s.left] for k, s in w.sides.items()] == js["sides"], where
            assert [(a.label, a.key, a.stat, a.detail, a.tone) for a in recap.awards(w)] == \
                [(a["label"], a["key"], a["stat"], a["detail"], a["tone"]) for a in js["awards"]], where
            assert recap.headline(w) == js["headline"], where
            to = recap.season(py_weeks[:i + 1])
            assert [[r["key"], r["left"], r["perfect"], r["weeks"]] for r in to] == \
                [r[:4] for r in js["season"]], where
            assert all(abs(r["pct"] - j[4]) < 1e-12 for r, j in zip(to, js["season"])), where
            assert recap._games(w) == js["games"], where
            assert recap._awards(w) == js["cards"], where
            assert recap._accuracy(w, to) == js["table"], where


@browser_only
def test_python_style_rounding(chrome, site):
    """toFixed rounds an exact binary tie up and Python to even: 13/16 of a
    best lineup is 81.2% on the built page, and must be here too."""
    cases = [81.25, 0.125, 0.375, 2.675, 1.005, -0.125, 99.95, 12.5, 7.0, 100.0]
    (got,), errors = drive(chrome, site + "?league=none", [
        ("wait", "window.GSRecap"),
        ("eval", "[" + ",".join(f"[GSRecap.fixed({x},1), GSRecap.fixed({x},2), GSRecap.num({x})]"
                               for x in cases) + "]")])
    assert got == [[f"{x:.1f}", f"{x:.2f}", recap.num(x)] for x in cases]


# --------------------------------------------------------------------------- #
# The best lineup against Sleeper's own "max points"
# --------------------------------------------------------------------------- #

NFL_SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX", "K", "DEF",
             "BN", "BN", "BN", "BN", "BN"]


def _archive(n):
    return json.loads((ROOT / "data/fantasy/matchups/2026" / f"week_{n:02d}.json").read_text())


@browser_only
def test_the_best_lineup_is_sleepers_max_points(chrome, site):
    """The committed NFL weeks, as Sleeper's matchup rows, through the
    browser's build: every team's best lineup is the Python's, week by week,
    and weeks 1-2 total Sleeper's own potential points (tests/test_recap.py
    reads those numbers off the league and pins the Python to them)."""
    from fantasy.site import matchups as mu
    from fantasy.site import recap as nfl
    import pandas as pd
    weeks = [n for n in (1, 2, 3)
             if (ROOT / "data/fantasy/matchups/2026" / f"week_{n:02d}.json").exists()]
    payload, python = [], {}
    for n in weeks:
        d = _archive(n)
        rows = [{"roster_id": s["roster_id"], "matchup_id": m["matchup_id"],
                 "points": s["points"], "starters": s["starters"], "players": s["players"],
                 "players_points": s["players_points"]}
                for m in d["matchups"] for s in m["sides"]]
        index = {pid: [p.get("name") or "", p.get("pos") or "", p.get("team") or ""]
                 for pid, p in (d.get("projections") or {}).items()}
        reserve = {k: t.get("reserve") or [] for k, t in (d.get("teams") or {}).items()}
        payload.append({"week": n, "rows": rows, "index": index, "reserve": reserve})
        cards = {str(p): mu.player_card(str(p), d, {}, {})
                 for m in d["matchups"] for s in m["sides"] for p in s["players"]}
        w = nfl.build_week(d, NFL_SLOTS, cards, {}, pd.DataFrame(columns=["week", "pid",
                                                                          "roster_id", "kind"]),
                           {}, playoff_start=15)
        python[n] = {k: s.max for k, s in w.sides.items()}
    (got,), errors = drive(chrome, site + "?league=none", [
        ("wait", "window.GSRecap"),
        ("eval", "(" + json.dumps(payload) + ").map(function(p){"
                 "  var w=GSRecap.build(p.week, p.rows, {slots:" + json.dumps(NFL_SLOTS) + ","
                 "    index:p.index, teams:{}, reserve:p.reserve}, null);"
                 "  var out={}; w.order.forEach(function(k){ out[k]=w.sides[k].max; });"
                 "  return out; })")])
    assert not errors, errors
    for n, mine in zip(weeks, got):
        assert mine == python[n], f"week {n}"
    sleeper = {"1": 324.78, "2": 298.14, "3": 298.28, "4": 276.7, "5": 370.64,
               "6": 255.86, "7": 280.74, "8": 265.78, "9": 367.88, "10": 258.74}
    totals = {k: round(got[0][k] + got[1][k], 2) for k in got[0]}
    assert totals == sleeper
