"""
The trade analyzer (gordstats.trade_page and its two adapters).

A trade is judged by running a league's season twice, so two things have to
hold, and both are checked here in headless Chromium (the machine that builds
the site has no node; without Chromium these skip):

  * the browser's season is the Python one. The college adapter ports
    cfb.league_sim to JS, so its weekly lineup means are compared exactly and
    its odds inside Monte Carlo error; the NFL adapter uses gordstats.
    my_power's simulation, which test_my_power_sim already holds to
    fantasy.league.power.
  * the two runs differ by the trade and nothing else: the same draws for the
    same player (NFL) or team-week (CFB), so a trade of nothing changes
    nothing, and the order a roster lists its players in cannot matter.
"""
import asyncio
import json
import re
import shutil
import subprocess
import time
import urllib.request

import numpy as np
import pandas as pd
import pytest

from cfb import league_sim
from cfb.site import trade as cfb_trade
from fantasy.site import trade as nfl_trade
from gordstats import my_power, trade_page

CHROME = next((p for p in ("/usr/bin/chromium-browser", "/usr/bin/chromium",
                           "/usr/bin/google-chrome") if shutil.which(p)), None)
pytestmark = pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")

PORT = 9481


def _js(block: str) -> str:
    """A <script> block's code, without the Jekyll and <script> wrappers."""
    block = block.replace("{% raw %}", "").replace("{% endraw %}", "")
    return re.sub(r"</?script[^>]*>", "", block)


class Browser:
    """Just enough DevTools to evaluate an expression and await a promise."""

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
    b = Browser()
    yield b
    b.close()


# ----- the college league: a port of cfb.league_sim ------------------------- #

# Eight starters and seven on the bench: the fifteen players each roster
# carries fill it exactly, so a two-for-one has to drop or sign someone.
SLOTS = [("QB", 1), ("RB", 2), ("WR", 2), ("TE", 1), ("W/R/T", 1), ("DEF", 1), ("BN", 7),
         ("IL", 1)]
SHAPE = ["QB", "QB", "RB", "RB", "RB", "RB", "WR", "WR", "WR", "WR", "WR", "TE", "TE",
         "DEF"]
WEEKS = list(range(5, 14))
PLAYOFF_START = 11
TEAMS = 8


def _round_robin(keys, weeks):
    """Pairings for each regular week, a circle rotated one seat a week."""
    fixed, rot = keys[0], keys[1:]
    out = {}
    for w in weeks:
        order = [fixed] + rot
        out[w] = [(order[i], order[-1 - i]) for i in range(len(order) // 2)]
        rot = rot[1:] + rot[:1]
    return out


@pytest.fixture(scope="module")
def college():
    """A league for both implementations: the adapter's data and league_sim's."""
    rng = np.random.default_rng(7)
    keys = [f"t{i}" for i in range(1, TEAMS + 1)]
    players, rosters, pid = {}, {}, 0
    for t, key in enumerate(keys):
        rosters[key] = []
        for slot, pos in enumerate(SHAPE):
            pid += 1
            base = {"QB": 20, "RB": 13, "WR": 12, "TE": 8, "DEF": 7}[pos]
            level = base * (0.5 + rng.random()) * (1 - 0.04 * slot) * (1 + 0.04 * t)
            proj = [round(float(max(level * (0.8 + 0.4 * rng.random()), 0)), 2)
                    for _ in WEEKS]
            proj[int(rng.integers(0, len(WEEKS)))] = 0.0            # a bye
            players[str(pid)] = [f"Player {pid}", pos, "School", proj, ""]
            rosters[key].append(str(pid))
        pid += 1                                     # one rostered, unrated
        players[str(pid)] = [f"Player {pid}", "WR", "School", None, ""]
        rosters[key].append(str(pid))
    free = []
    for pos in ("QB", "RB", "WR", "TE", "DEF"):
        pid += 1
        players[str(pid)] = [f"Free {pid}", pos, "School",
                             [round(9.0 + pid % 5, 2)] * len(WEEKS), ""]
        free.append(str(pid))
    pid += 1                                          # a free agent nobody would start
    players[str(pid)] = ["Free weak", "WR", "School", [0.1] * len(WEEKS), ""]
    free.append(str(pid))
    pairs = _round_robin(keys, [w for w in WEEKS if w < PLAYOFF_START])
    teams = [{"key": k, "name": f"Team {k}", "wins": float(rng.integers(3, 7)), "ties": 0.0,
              "losses": 0.0, "pf": round(float(500 + 60 * rng.random()), 2)} for k in keys]
    for t in teams:
        t["losses"] = 8.0 - t["wins"]
    data = {
        "weeks": WEEKS, "playoff_start": PLAYOFF_START, "end_week": 13, "field": 6,
        "median": True, "reseed": True,
        "slots": [list(s) for s in SLOTS],
        "active": sum(n for p, n in SLOTS if p != "IL"),
        "teams": teams, "rosters": rosters, "reserve": {k: [] for k in keys},
        "pairs": {str(w): [list(p) for p in pairs.get(w, [])] for w in WEEKS},
        # Two teams' week under way: a lineup's points so far plus the rest.
        "live": {"t2": [101.5, 180.0], "t5": [88.25, 240.0]},
        "played": {}, "players": players, "free": free, "mine": "t1",
        "sims": 20000, "seed": 20260928,
    }
    return data


def _python_means(data):
    """league_sim.weekly_means' arithmetic on the adapter's data."""
    lg = {"roster": [{"position": p, "count": n} for p, n in data["slots"]]}
    keys = [t["key"] for t in data["teams"]]
    mean = np.zeros((len(data["weeks"]), len(keys)))
    var = np.zeros_like(mean)
    for i in range(len(data["weeks"])):
        for j, key in enumerate(keys):
            if i == 0 and key in data["live"]:
                mean[i, j], var[i, j] = data["live"][key]
                continue
            ids = [p for p in data["rosters"][key] if data["players"][p][3] is not None]
            frame = pd.DataFrame({"pos": [data["players"][p][1] for p in ids],
                                  "proj_week": [data["players"][p][3][i] for p in ids]},
                                 index=ids)
            start = league_sim._best(frame, lg)
            p = frame.loc[start, "proj_week"].to_numpy(float)
            mean[i, j] = p.sum()
            var[i, j] = (league_sim._sd(p) ** 2).sum()
    return keys, mean, np.sqrt(var)


def _load_college(browser, data):
    blob = json.dumps(data)
    browser.evaluate("document.body.innerHTML='';"
                     "var el=document.createElement('script');el.type='application/json';"
                     f"el.id='tr-data';el.textContent={json.dumps(blob)};"
                     "document.body.appendChild(el);true")
    browser.evaluate(_js(cfb_trade.ADAPTER_JS) + ";true")


def test_college_lineup_means_are_league_sims(browser, college):
    _load_college(browser, college)
    got = browser.evaluate("(function(){var D=JSON.parse(document.getElementById('tr-data')"
                           ".textContent); var m=GSTradeAdapter._means(D.rosters);"
                           "return {M:m.M.map(function(r){return Array.from(r);}),"
                           "S:m.S.map(function(r){return Array.from(r);})};})()")
    keys, mean, sd = _python_means(college)
    assert np.allclose(np.array(got["M"]), mean, atol=1e-6)
    assert np.allclose(np.array(got["S"]), sd, atol=1e-6)


def test_college_odds_match_league_sim(browser, college):
    _load_college(browser, college)
    keys, mean, sd = _python_means(college)
    lg = {"teams": [{"team_key": t["key"], "wins": t["wins"], "ties": t["ties"],
                     "losses": t["losses"], "points_for": t["pf"]} for t in college["teams"]],
          "playoff_start_week": PLAYOFF_START, "end_week": 13, "num_playoff_teams": 6,
          "uses_median_score": True, "uses_playoff_reseeding": True}
    sched = {w: {"pairs": [tuple(p) for p in college["pairs"][str(w)]]} for w in WEEKS}
    py = league_sim.simulate(lg, sched, keys, WEEKS, mean, sd, sims=20000).set_index("team_key")
    js = browser.evaluate("(function(){var D=JSON.parse(document.getElementById('tr-data')"
                          ".textContent); return GSTradeAdapter._simulate(D.rosters, 20000);})()")
    for key in keys:
        assert js[key]["ppw"] == pytest.approx(py.loc[key, "per_week"], abs=1e-6)
        assert js[key]["wins"] == pytest.approx(py.loc[key, "wins"], abs=0.08)
        assert js[key]["losses"] == pytest.approx(py.loc[key, "losses"], abs=0.08)
        for col in ("playoffs", "bye", "title"):
            assert js[key][col] == pytest.approx(py.loc[key, col], abs=0.02), (key, col)


@pytest.mark.parametrize("reseed", [True, False])
def test_college_bracket_is_league_sims(browser, college, reseed):
    _load_college(browser, college)
    rng = np.random.default_rng(11)
    for _ in range(25):
        seeds = [int(x) for x in rng.permutation(TEAMS)[:6]]
        scores = rng.normal(100, 20, size=(3, TEAMS)).round(2)
        py = int(league_sim._bracket(np.array([seeds]), scores[None], reseed)[0])
        js = browser.evaluate(
            f"(function(){{var sc={json.dumps(scores.tolist())};"
            f"return GSTradeAdapter._bracket({json.dumps(seeds)},"
            f"function(r,t){{return sc[r][t];}},3,{json.dumps(reseed)});}})()")
        assert js == py


def _college_trade(browser, give, get, a="t1", b="t3"):
    return browser.evaluate(
        "GSTradeAdapter.load().then(function(d){return GSTradeAdapter.evaluate("
        f"{{a:{json.dumps(a)},b:{json.dumps(b)},give:{json.dumps(give)},"
        f"get:{json.dumps(get)}}}).then(function(r){{return {{before:d.before,"
        "after:r.after,moves:r.moves};});})")


def test_college_nothing_traded_changes_nothing(browser, college):
    _load_college(browser, college)
    got = _college_trade(browser, [], [])
    assert got["after"] == got["before"]


def test_college_a_star_moves_the_odds_both_ways(browser, college):
    _load_college(browser, college)
    # The league's best back, from whoever has him, for another team's worst:
    # his team is weaker for it and the other stronger.
    ppw = lambda p: np.mean(college["players"][p][3][:6])
    backs = {k: [p for p in ids if college["players"][p][1] == "RB"]
             for k, ids in college["rosters"].items()}
    a = max(backs, key=lambda k: max(ppw(p) for p in backs[k]))
    b = next(k for k in backs if k not in (a, "t2", "t5"))
    best, worst = max(backs[a], key=ppw), min(backs[b], key=ppw)
    got = _college_trade(browser, [best], [worst], a=a, b=b)
    assert got["after"][a]["ppw"] < got["before"][a]["ppw"]
    assert got["after"][b]["ppw"] > got["before"][b]["ppw"]
    assert got["after"][a]["playoffs"] <= got["before"][a]["playoffs"]
    assert got["after"][b]["playoffs"] >= got["before"][b]["playoffs"]
    # Six places either way: what the two gain or lose between them, the
    # rest of the league loses or gains.
    for side in ("before", "after"):
        assert sum(t["playoffs"] for t in got[side].values()) == pytest.approx(6)
        assert sum(t["title"] for t in got[side].values()) == pytest.approx(1)


def test_college_rosters_stay_legal(browser, college):
    _load_college(browser, college)
    # A two-for-one on full rosters: the side taking two drops one, the side
    # taking one signs a free agent at the position it gave up.
    wr = [p for p in college["rosters"]["t1"] if college["players"][p][1] == "WR"][:2]
    te = [p for p in college["rosters"]["t3"] if college["players"][p][1] == "TE"][:1]
    got = _college_trade(browser, wr, te)
    assert any(line.startswith("Signs ") and " at WR " in line for line in got["moves"]["t1"])
    assert any(line.startswith("Drops ") for line in got["moves"]["t3"])


def test_college_week_under_way_is_untouched(browser, college):
    """A team whose week is being played keeps it whatever it trades."""
    _load_college(browser, college)
    got = browser.evaluate(
        "(function(){var D=JSON.parse(document.getElementById('tr-data').textContent);"
        "var r=JSON.parse(JSON.stringify(D.rosters)); r.t2=r.t2.slice(0,3);"
        "return [GSTradeAdapter._means(D.rosters).M[0][1], GSTradeAdapter._means(r).M[0][1],"
        "GSTradeAdapter._means(D.rosters).M[1][1], GSTradeAdapter._means(r).M[1][1]];})()")
    assert got[0] == got[1] == 101.5
    assert got[3] < got[2]


# ----- the NFL league: gordstats.my_power's simulation ---------------------- #

NFL_POS = ["QB", "RB", "WR", "TE", "K", "DEF"]
NFL_SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF", "BN", "BN", "BN", "BN",
             "IR"]
NFL_SHAPE = ["QB", "RB", "RB", "WR", "WR", "TE", "K", "DEF", "RB", "WR", "WR", "QB", "TE"]
NFL_TEAMS = 8


@pytest.fixture(scope="module")
def nfl():
    rng = np.random.default_rng(99)
    board, index, rosters, pid = {}, {}, [], 100
    for t in range(NFL_TEAMS):
        held = []
        for slot, pos in enumerate(NFL_SHAPE):
            pid += 1
            base = {"QB": 18, "RB": 12, "WR": 11, "TE": 8, "K": 8, "DEF": 7}[pos]
            mu = round(base * (0.55 + 0.9 * rng.random()) * (1 - 0.04 * slot), 2)
            board[str(pid)] = [NFL_POS.index(pos), int(rng.integers(5, 15)), mu,
                               round(mu * 0.45, 2), round(mu * 0.12, 2), 0.88, 0, 0]
            index[str(pid)] = [f"Player {pid}", pos, "FA"]
            held.append(str(pid))
        rosters.append({"roster_id": t + 1, "players": held, "reserve": [], "taxi": [],
                        "owner_id": f"u{t + 1}"})
    for pos in NFL_POS:                                 # free agents
        for k in range(4):
            pid += 1
            mu = round({"QB": 12, "RB": 7, "WR": 7, "TE": 5, "K": 7, "DEF": 6}[pos] - k, 2)
            board[str(pid)] = [NFL_POS.index(pos), 9, mu, round(mu * 0.45, 2),
                               round(mu * 0.12, 2), 0.88, 0, 0]
            index[str(pid)] = [f"Free {pid}", pos, "FA"]
    users = [{"user_id": f"u{t + 1}", "display_name": f"mgr{t + 1}",
              "metadata": {"team_name": f"Team {t + 1}"}} for t in range(NFL_TEAMS)]
    # Two weeks played, pairings for all fourteen.
    ids = list(range(1, NFL_TEAMS + 1))
    matchups = {}
    for w in range(1, 15):
        fixed, rot = ids[0], ids[1:]
        k = (w - 1) % len(rot)
        order = [fixed] + rot[k:] + rot[:k]
        rows = []
        for i in range(NFL_TEAMS // 2):
            for rid in (order[i], order[-1 - i]):
                rows.append({"roster_id": rid, "matchup_id": i + 1,
                             "points": round(float(90 + 40 * rng.random()), 2) if w <= 2 else 0})
        matchups[w] = rows
    info = {"name": "Test League", "roster_positions": NFL_SLOTS,
            "scoring_settings": {"rec": 1},
            "settings": {"playoff_week_start": 15, "playoff_teams": 4,
                         "league_average_match": 1, "last_scored_leg": 2, "leg": 3,
                         "trade_deadline": 11}}
    return {"board": {"year": 2026, "week": 2, "fields": [], "pos": NFL_POS, "board": board},
            "index": index, "rosters": rosters, "users": users, "matchups": matchups,
            "info": info}


def _load_nfl(browser, nfl):
    """The adapter on stubbed Sleeper answers: GSAPI, the two shipped files."""
    stub = f"""
      window.__L = {json.dumps(nfl)};
      window.GSAPI = {{
        get: function(path){{
          var m = /\\/matchups\\/(\\d+)$/.exec(path);
          if(m) return Promise.resolve(__L.matchups[m[1]] || []);
          if(/\\/rosters$/.test(path)) return Promise.resolve(__L.rosters);
          if(/\\/users$/.test(path)) return Promise.resolve(__L.users);
          return Promise.resolve(__L.info);
        }},
        players: function(){{ return Promise.resolve(__L.index); }}
      }};
      window.fetch = function(url){{
        // This week's projections: none, and no kickoffs - every team on
        // bye, so a free agent counts as available on the board alone.
        var body = /season-board/.test(url) ? __L.board
          : /week-projections/.test(url) ? {{week:3, kick:{{}}, proj:{{}}}} : {{}};
        return Promise.resolve({{ok:true, json:function(){{ return Promise.resolve(body); }}}});
      }};
      true
    """
    browser.evaluate("document.body.innerHTML='';" + stub)
    browser.evaluate(_js(nfl_trade.my_league_data.JS) + ";true")
    # The Worker is built from this element's text, as on the page.
    sim = _js(my_power.SIM_JS)
    browser.evaluate("var s=document.createElement('script');s.id='gs-power-sim';"
                     f"s.type='text/plain';s.textContent={json.dumps(sim)};"
                     "document.body.appendChild(s);true")
    browser.evaluate(sim + ";true")
    browser.evaluate(_js(my_power.LEAGUE_JS) + ";true")
    browser.evaluate(_js(trade_page.JS) + ";true")
    browser.evaluate(_js(nfl_trade.adapter_js()) + ";true")


def _nfl_trade(browser, give, get, a="1", b="3"):
    return browser.evaluate(
        "GSTradeAdapter.load().then(function(d){return GSTradeAdapter.evaluate("
        f"{{a:{json.dumps(a)},b:{json.dumps(b)},give:{json.dumps(give)},"
        f"get:{json.dumps(get)}}}).then(function(r){{return {{before:d.before,"
        "after:r.after,moves:r.moves,note:d.note,teams:d.teams};});})")


def test_nfl_nothing_traded_changes_nothing(browser, nfl):
    _load_nfl(browser, nfl)
    got = _nfl_trade(browser, [], [])
    assert got["after"] == got["before"]
    assert [t["id"] for t in got["teams"]] == [str(i) for i in range(1, NFL_TEAMS + 1)]


def test_nfl_roster_order_cannot_matter(browser, nfl):
    """`stable`: each player draws his own numbers wherever he is listed."""
    _load_nfl(browser, nfl)
    got = browser.evaluate(
        "GSPowerLeague.setup('1').then(function(s){s.spec.sims=1500; s.spec.stable=true;"
        "var a=GSPower.run(s.spec);"
        "var r=JSON.parse(JSON.stringify(s.spec)); r.rosters.forEach(function(x){x.players.reverse();});"
        "var b=GSPower.run(r);"
        "var c=GSPower.run(Object.assign({}, r, {stable:false}));"
        "var key=function(x){return x.teams.map(function(t){return t.titleOdds;}).join();};"
        "return [key(a)===key(b), key(a)===key(c)];})")
    assert got == [True, False]


def test_nfl_a_star_moves_the_odds_both_ways(browser, nfl):
    _load_nfl(browser, nfl)
    board = nfl["board"]["board"]
    qbs = {str(r["roster_id"]): [p for p in r["players"] if board[p][0] == 0]
           for r in nfl["rosters"]}
    # The league's best quarterback, for another team's backup.
    a = max(qbs, key=lambda k: max(board[p][2] for p in qbs[k]))
    b = next(k for k in qbs if k != a)
    best = max(qbs[a], key=lambda p: board[p][2])
    backup = min(qbs[b], key=lambda p: board[p][2])
    got = _nfl_trade(browser, [best], [backup], a=a, b=b)
    assert got["after"][a]["ppw"] < got["before"][a]["ppw"]
    assert got["after"][b]["ppw"] > got["before"][b]["ppw"]
    assert got["after"][a]["title"] <= got["before"][a]["title"]
    assert got["after"][b]["title"] >= got["before"][b]["title"]
    # He starts for his new team, and the quarterback he replaces sits.
    assert any(line.startswith("Starts ") for line in got["moves"][b])
    assert any("To the bench" in line for line in got["moves"][b])


def test_nfl_rosters_stay_legal(browser, nfl):
    _load_nfl(browser, nfl)
    board = nfl["board"]["board"]
    wrs = [p for p in nfl["rosters"][0]["players"] if board[p][0] == 2][:2]
    te = [p for p in nfl["rosters"][2]["players"] if board[p][0] == 3][:1]
    got = _nfl_trade(browser, wrs, te)
    # 13 players on 13 active places: the side taking two must drop one.
    assert any(line.startswith("Drops ") for line in got["moves"]["3"])
    assert any(line.startswith("Signs ") and " at WR " in line for line in got["moves"]["1"])


def test_nfl_page_draws_and_plays_a_trade(browser, nfl):
    """The whole page: pickers, a tap on each side, the two result cards."""
    _load_nfl(browser, nfl)
    section = trade_page.section("/fantasy/trade/", league=True)
    got = browser.evaluate("""
      new Promise(function(done){
        document.body.insertAdjacentHTML('beforeend', """ + json.dumps(section) + """);
        var host = document.getElementById('tr-host');
        window.GSTrade(host, window.GSTradeAdapter);
        var tries = 0;
        (function wait(){
          var a = host.querySelectorAll('.tr-side')[0], b = host.querySelectorAll('.tr-side')[1];
          if(!a){ if(++tries > 200) return done('no lists'); return setTimeout(wait, 50); }
          a.querySelectorAll('.tr-p')[1].click();
          b.querySelectorAll('.tr-p')[1].click();
          (function res(){
            var cards = host.querySelectorAll('.tr-card');
            var btn = host.querySelector('.gs-share');
            if(cards.length === 2) return done({cards: cards.length,
              verdict: host.querySelector('.tr-verdict').textContent,
              hash: location.hash, selects: host.querySelectorAll('select').length,
              share: btn && btn.getAttribute('data-url'), text: btn && btn.getAttribute('data-text'),
              league: btn && btn.hasAttribute('data-league')});
            if(++tries > 400) return done('no result');
            setTimeout(res, 50);
          })();
        })();
      })
    """)
    assert isinstance(got, dict), got
    assert got["cards"] == 2 and got["selects"] == 2
    assert got["verdict"]
    # The Share button sends this deal: the address carries it, and the
    # reader's league rides along (share.js adds ?league= when one is on).
    assert got["share"].startswith("/fantasy/trade/#trade=")
    assert got["text"].startswith("Trade idea: Player ") and got["league"]


def test_college_data_cannot_end_its_script_or_meet_liquid():
    """The college data sits inside the page: a player called </script> must
    not end it, and a {{ in a name must reach the reader as typed."""
    html = cfb_trade.data_script({"n": "</script>{{ x }}"})
    inner = html.split(">", 1)[1].rsplit("</script>", 1)[0]
    assert "</script>" not in inner
    assert html.startswith("{% raw %}") and html.endswith("{% endraw %}")


def test_college_flex_is_left_empty_rather_than_filled_with_a_zero(browser, college):
    """A dedicated slot takes the top of its position whatever he scores; the
    flex only takes somebody who scores at all (league_power.best_lineup)."""
    _load_college(browser, college)
    by_pos = {}
    for pid in college["rosters"]["t1"]:
        by_pos.setdefault(college["players"][pid][1], []).append(pid)
    ids = by_pos["QB"][:1] + by_pos["RB"][:3] + by_pos["WR"][:2] + by_pos["TE"][:1] \
        + by_pos["DEF"][:1]
    value = dict(zip(ids, [10.0, 8.0, 7.0, 0.0, 9.0, 6.0, 0.0, 4.0]))
    got = browser.evaluate(
        f"(function(){{var v={json.dumps(value)};"
        f"return GSTradeAdapter._lineup({json.dumps(ids)}, function(p){{return v[p];}});}})()")
    lg = {"roster": [{"position": p, "count": n} for p, n in college["slots"]]}
    frame = pd.DataFrame({"pos": [college["players"][p][1] for p in ids],
                          "proj_week": [value[p] for p in ids]}, index=ids)
    start = league_sim._best(frame, lg)
    assert sorted(got["starters"]) == sorted(start)
    p = frame.loc[start, "proj_week"].to_numpy(float)
    assert got["mean"] == pytest.approx(p.sum())
    assert got["v"] == pytest.approx((league_sim._sd(p) ** 2).sum())
    # The tight end on a bye still starts; the back on one does not flex.
    assert ids[6] in got["starters"] and ids[3] not in got["starters"]


# ----- pick up: the waiver wire in playoff odds ------------------------------ #

def test_college_pickup_drops_the_worst_bench_player_with_the_same_luck(browser, college):
    _load_college(browser, college)
    weak = college["free"][-1]
    got = browser.evaluate(
        "GSTradeAdapter.load().then(function(d){ var c = GSTradeAdapter.candidates('t1');"
        f" return GSTradeAdapter.pickup('t1', {json.dumps(weak)}).then(function(r){{"
        " return {c:c, r:r, before:d.before.t1}; }); })")
    assert got["c"] == college["free"]
    # t1's roster is full: the unrated player (nothing a week) goes.
    unrated = [p for p in college["rosters"]["t1"] if college["players"][p][3] is None]
    assert got["r"]["drop"] == unrated[0]
    # Neither starts, so the season is the same season, to the last decimal.
    assert got["r"]["before"] == got["before"] and got["r"]["after"] == got["before"]


def test_college_pickup_of_a_real_player_moves_the_odds(browser, college):
    _load_college(browser, college)
    got = browser.evaluate(
        "GSTradeAdapter.load().then(function(){ return Promise.all(GSTradeAdapter.candidates('t8')"
        ".map(function(id){ return GSTradeAdapter.pickup('t8', id).then(function(r){"
        " return [id, r.after.ppw - r.before.ppw]; }); })); })")
    gains = dict(got)
    assert max(gains.values()) > 0          # somebody on the wire beats t8's worst starter
    assert gains[college["free"][-1]] == 0  # and the useless one changes nothing


def test_nfl_pickup_candidates_are_real_free_agents(browser, nfl):
    _load_nfl(browser, nfl)
    got = browser.evaluate(
        "GSTradeAdapter.load().then(function(){ var c = GSTradeAdapter.candidates('1');"
        " return Promise.all([GSTradeAdapter.pickup('1', c[0]), GSTradeAdapter.pickup('1', c[1])])"
        ".then(function(rs){ return {c:c, rs:rs}; }); })")
    held = {p for r in nfl["rosters"] for p in r["players"]}
    board = nfl["board"]["board"]
    assert got["c"] and not set(got["c"]) & held
    assert all(nfl["index"][p][0].startswith("Free") for p in got["c"])
    mus = [board[p][2] for p in got["c"]]
    assert mus == sorted(mus, reverse=True)
    # One baseline for every pickup, and a full roster drops somebody.
    a, b = got["rs"]
    assert a["before"] == b["before"]
    assert a["drop"] in nfl["rosters"][0]["players"]


def test_the_pick_up_view_ranks_the_wire_by_title_odds(browser, nfl):
    _load_nfl(browser, nfl)
    section = trade_page.section("/fantasy/trade/", league=True)
    got = browser.evaluate("""
      new Promise(function(done){
        document.body.insertAdjacentHTML('beforeend', """ + json.dumps(section) + """);
        var host = document.getElementById('tr-host'), tries = 0, tapped = false;
        window.GSTrade(host, window.GSTradeAdapter);
        (function wait(){
          var btn = host.querySelector('.tr-mode [data-mode=pickup]');
          if(btn && !tapped){ tapped = true; btn.click(); }
          if(tapped && host.querySelector('.tr-out .tr-now')){
            var rows = Array.prototype.map.call(host.querySelectorAll('.tr-pk tbody tr'),
              function(tr){ var c = tr.querySelectorAll('td'); return c[c.length - 1].textContent; });
            return done({rows: rows, mode: host.querySelector('.tr-mode [aria-pressed=true]').textContent,
                         n: GSTradeAdapter.candidates('1').length});
          }
          if(++tries > 600) return done('timed out');
          setTimeout(wait, 50);
        })();
      })
    """)
    assert isinstance(got, dict), got
    assert got["mode"] == "Pick up" and len(got["rows"]) == got["n"]
    val = lambda t: 0.0 if t.startswith("\u00b1") else float(t.replace("\u2212", "-"))
    vals = [val(t) for t in got["rows"]]
    assert vals == sorted(vals, reverse=True)
