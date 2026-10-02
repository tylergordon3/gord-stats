"""
The 2026-10-02 audit's browser-side findings, each run in headless Chromium
against the real script with every request stubbed in the page (no network).

One Chromium for the module (CDP port 9553) and one local HTTP server on a port
the OS picks, so pages have a real origin and localStorage works - an
about:blank page's storage throws, which is itself one of the findings (the
conference dropdown never attached when storage was blocked).
"""
import asyncio
import functools
import http.server
import json
import re
import shutil
import socketserver
import subprocess
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from conftest import DOCS
from browser_util import reap

CHROME = next((p for p in ("/usr/bin/chromium-browser", "/usr/bin/chromium",
                           "/usr/bin/google-chrome") if shutil.which(p)), None)
pytestmark = pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")

CDP_PORT = 9553
SLEEPER = "https://api.sleeper.app/v1"


def _js(src: str) -> str:
    """A module's script, without the Jekyll and <script> wrappers."""
    return re.sub(r"\{% (end)?raw %\}|</?script>", "", src)


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class Page:
    """Chromium plus a local server: open a fresh page, run JS in it."""

    def __init__(self):
        self.dir = Path(tempfile.mkdtemp(prefix="gs-audit-js-"))
        (self.dir / "blank.html").write_text(
            "<!doctype html><meta charset=utf-8><title>t</title><body></body>")
        for name in ("live.js", "conf-toggle.js", "rank-toggle.js"):
            shutil.copy(DOCS / "assets" / "js" / name, self.dir / name)
        handler = functools.partial(_Quiet, directory=str(self.dir))
        self.httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        subprocess.run(["fuser", "-k", f"{CDP_PORT}/tcp"], capture_output=True)
        self.profile = tempfile.mkdtemp(prefix="gs-audit-js-chrome-")
        self.proc = subprocess.Popen(
            [CHROME, "--headless=new", "--no-sandbox", "--disable-gpu",
             f"--remote-debugging-port={CDP_PORT}", f"--user-data-dir={self.profile}",
             "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            try:
                targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json"))
                self.ws_url = next(t["webSocketDebuggerUrl"] for t in targets
                                   if t.get("type") == "page")
                break
            except Exception:                                   # noqa: BLE001
                time.sleep(0.5)
        else:
            raise RuntimeError("Chromium did not come up")

    def close(self):
        self.proc.terminate()
        reap(self.proc)
        self.httpd.shutdown()
        shutil.rmtree(self.dir, ignore_errors=True)
        shutil.rmtree(self.profile, ignore_errors=True)

    def _send(self, method, params):
        import websockets

        async def run():
            async with websockets.connect(self.ws_url, max_size=None) as ws:
                await ws.send(json.dumps({"id": 1, "method": method, "params": params}))
                while True:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
                    if msg.get("id") == 1:
                        return msg
        return asyncio.run(run())

    def ev(self, expression):
        """The value of an expression (a promise is awaited)."""
        msg = self._send("Runtime.evaluate", {"expression": expression, "returnByValue": True,
                                              "awaitPromise": True})
        result = msg.get("result", {})
        if result.get("exceptionDetails"):
            d = result["exceptionDetails"]
            raise AssertionError((d.get("exception") or {}).get("description") or d["text"])
        return result["result"].get("value")

    def open(self, storage=None):
        """A fresh page on the local origin, storage cleared (then `storage`
        set), console errors and timers recorded."""
        self._send("Page.navigate", {"url": f"http://127.0.0.1:{self.port}/blank.html"})
        for _ in range(100):
            try:
                if self.ev("document.readyState") == "complete" and \
                        self.ev("location.pathname") == "/blank.html":
                    break
            except AssertionError:
                pass
            time.sleep(0.05)
        self.ev("localStorage.clear(); sessionStorage.clear(); true")
        for k, v in (storage or {}).items():
            self.ev(f"localStorage.setItem({json.dumps(k)}, {json.dumps(v)}); true")
        self.ev("""
          window.__errs=[]; window.__timers=[];
          (function(){ var ce=console.error;
            console.error=function(){ __errs.push([].map.call(arguments,function(a){
              return a&&a.stack?String(a.stack):String(a); }).join(' ')); };
            var st=window.setTimeout;
            window.setTimeout=function(fn, ms){ __timers.push(ms||0); return st.apply(window, arguments); };
          })(); true""")

    def stub_fetch(self, routes: dict, missing_status: int = 404):
        """fetch answered from `routes` {url: body | {"__status": n} }, in order
        of the longest matching key; everything else is `missing_status`."""
        self.ev("""
          window.__routes=%s; window.__asked=[];
          window.fetch=function(u){ u=String(u); __asked.push(u);
            var keys=Object.keys(__routes).filter(function(k){ return u===k; });
            if(!keys.length) return Promise.resolve({ok:false, status:%d,
              json:function(){ return Promise.resolve(null); }});
            var v=__routes[keys[0]], st=(v&&v.__status)||200;
            var wait=(v&&v.__delay)||0;
            return new Promise(function(res){ setTimeout(function(){
              res({ok:st===200, status:st, json:function(){
                return Promise.resolve(v&&v.__body!==undefined?v.__body:v); }});
            }, wait); });
          }; true""" % (json.dumps(routes), missing_status))

    def run(self, js: str):
        self.ev(js + "\n;true")

    def html(self, sel):
        return self.ev(f"(document.querySelector({json.dumps(sel)})||{{}}).innerHTML||''")


@pytest.fixture(scope="module")
def page():
    p = Page()
    yield p
    p.close()


def settle(seconds=0.6):
    time.sleep(seconds)


# --------------------------------------------------------------------------- #
# A reader's league: Sleeper stubbed, the site's week files stubbed
# --------------------------------------------------------------------------- #

LID = "1234567890123456789"
PLAYERS = {"p1": ["Ann QB", "QB", "KC"], "p2": ["Bo RB", "RB", "BUF"], "p3": ["Cy WR", "WR", "SF"],
           "p4": ["Di QB", "QB", "NYJ"], "p5": ["Ed RB", "RB", "MIA"], "p6": ["Fa WR", "WR", "DAL"],
           "p7": ["Gi QB", "QB", "KC"], "p8": ["Ho RB", "RB", "BUF"], "p9": ["Ix WR", "WR", "SF"],
           "p10": ["Jo QB", "QB", "NYJ"], "p11": ["Ka RB", "RB", "MIA"], "p12": ["Lu WR", "WR", "DAL"]}
WEEKPROJ = {"week": 4, "year": 2026, "kick": {},
            "proj": {pid: [12.0, 11.0, 10.0, meta[2], ""] for pid, meta in PLAYERS.items()}}


def _league(season="2026", league_id=LID):
    rosters = [{"roster_id": r, "owner_id": f"u{r}", "players": [f"p{3*r-2}", f"p{3*r-1}", f"p{3*r}"],
                "starters": [f"p{3*r-2}", f"p{3*r-1}", f"p{3*r}"],
                "settings": {"wins": 1, "losses": 2}} for r in (1, 2, 3, 4)]
    users = [{"user_id": f"u{r}", "display_name": f"m{r}",
              "metadata": {"team_name": f"Team {r}"}} for r in (1, 2, 3, 4)]
    rows = [{"roster_id": r, "matchup_id": (r + 1) // 2, "points": 0,
             "starters": [f"p{3*r-2}", f"p{3*r-1}", f"p{3*r}"],
             "players": [f"p{3*r-2}", f"p{3*r-1}", f"p{3*r}"], "players_points": {}}
            for r in (1, 2, 3, 4)]
    base = f"{SLEEPER}/league/{league_id}"
    return {base: {"league_id": league_id, "name": "Test League", "season": season,
                   "roster_positions": ["QB", "RB", "WR", "BN"],
                   "settings": {"league_average_match": 1, "playoff_week_start": 15},
                   "scoring_settings": {"rec": 1}},
            base + "/rosters": rosters, base + "/users": users, base + "/matchups/4": rows,
            "/fantasy/players-index.json": PLAYERS, "/fantasy/week-projections.json": WEEKPROJ}


def _matchups_page(page, routes, espn=""):
    from gordstats import league_api, my_league_data, my_matchups, my_week
    page.open({"gsSleeperLeague": json.dumps({"id": LID, "name": "Test League"})})
    page.stub_fetch(routes)
    attrs = f" data-espn='{espn}'" if espn else ""
    page.run("document.body.innerHTML=\"<div id='mm-bar'></div><div id='mm-built'></div>"
             f"<div id='mm-host' data-week='4' data-year='2026'{attrs}></div>\"")
    page.run(_js(league_api.JS) + _js(my_league_data.JS) + _js(my_week.JS) + _js(my_matchups.JS))
    settle(1.0)
    return page.html("#mm-host")


def _medt(html):
    m = re.search(r'data-medt="([^"]*)"', html)
    return json.loads(m.group(1).replace("&quot;", '"').replace("&amp;", "&")) if m else None


def test_reader_matchups_without_week_context_are_not_all_byes(page):
    """Finding 1: week-context.json missing - every player was a bye worth 0,
    the median read final, and the live poll never started."""
    html = _matchups_page(page, _league())
    assert 'class="bye"' not in html, "no schedule is not a bye"
    assert ">bye<" not in html
    blob = _medt(html)
    assert blob and blob["final"] is False, "nothing has been played"
    assert all(t["exp"] > 0 for t in blob["teams"]), "projections stand without a schedule"
    assert 300000 in page.ev("__timers"), "the live poll is scheduled"
    assert page.ev("__errs") == []


def test_reader_matchups_with_last_weeks_context_are_not_all_byes(page):
    routes = _league()
    routes["/fantasy/week-context.json"] = {
        "week": 3, "teams": {"KC": {"opp": "LV", "home": True, "state": "post", "el": 1}},
        "gs": {}, "wx": {}, "dvp": {}}
    html = _matchups_page(page, routes)
    assert 'class="bye"' not in html
    assert _medt(html)["final"] is False


def test_reader_matchups_take_the_schedule_from_espn_without_context(page):
    """With no context the scoreboard is the week: on it is a game, off it a bye."""
    routes = _league()
    sb = {"events": [{"id": "g1", "date": "2026-10-04T17:00Z", "competitions": [{
        "status": {"period": 2, "displayClock": "7:30", "type": {"state": "in"}},
        "competitors": [{"homeAway": "home", "score": "14", "team": {"abbreviation": "KC"}},
                        {"homeAway": "away", "score": "7", "team": {"abbreviation": "LV"}}]}]}]}
    routes["/espn/sb"] = sb
    html = _matchups_page(page, routes, espn="/espn/sb")
    rows = dict(re.findall(r'data-pid="(p\d+)" data-team="[A-Z]+"><td class="mu-pts">(.*?)</td>',
                           html))
    assert "live" in rows["p1"], "KC is playing"
    assert "bye" in rows["p2"], "BUF is not on the week's scoreboard"


def test_a_league_from_another_season_is_not_drawn_as_this_week(page):
    """Finding 6: last season's saved league says so instead of drawing."""
    html = _matchups_page(page, _league(season="2025"))
    assert "This is your <b>2025</b> league" in html
    assert "mu-roster" not in html, "no week drawn from it"


def test_a_private_espn_league_says_so_in_espns_words(page):
    """Finding 14: not "Could not read that league from Sleeper"."""
    from gordstats import league_api, my_league_data, my_matchups, my_week
    page.open({"gsSleeperLeague": json.dumps({"id": "espn:2026:1", "name": "E"})})
    page.stub_fetch({}, missing_status=401)
    page.run("document.body.innerHTML=\"<div id='mm-bar'></div>"
             "<div id='mm-host' data-week='4' data-year='2026'></div>\"")
    page.run(_js(league_api.JS) + _js(my_league_data.JS) + _js(my_week.JS) + _js(my_matchups.JS))
    settle(1.0)
    html = page.html("#mm-host")
    assert "ESPN keeps that league private" in html
    assert "Sleeper" not in html
    assert page.ev("GSAPI.problem('1234567890123456789')").startswith(
        "Could not read that league from Sleeper")
    assert page.ev("GSAPI.problem('espn:2025:7')").startswith("Could not read that league from ESPN")


def test_one_bad_draw_does_not_end_the_live_updates(page):
    """Finding 15: the poll had no catch - one render error stopped it for good."""
    _matchups_page(page, _league())
    page.run("window.__timers=[]; GSL.myRoster=function(){ throw new Error('boom'); };"
             "document.dispatchEvent(new Event('visibilitychange'))")
    settle(0.6)
    assert any("boom" in e for e in page.ev("__errs")), "the error is logged"
    assert 300000 in page.ev("__timers"), "and the next poll is still scheduled"


def test_my_team_without_week_context_recommends_on_projections(page):
    """Finding 1 on My Team: "5 changes worth 0.0" with every player a bye."""
    from gordstats import league_api, my_league_data, my_team, my_week
    page.open({"gsSleeperLeague": json.dumps({"id": LID, "name": "Test League"})})
    page.stub_fetch(_league())
    page.run("document.body.innerHTML=\"<div id='mt-bar'></div><div id='mt-host'></div>\"")
    page.run(_js(league_api.JS) + _js(my_league_data.JS) + _js(my_week.JS)
             + _js(my_team.PLANNER_JS) + _js(my_team.VIEW_JS))
    settle(1.0)
    html = page.html("#mt-host")
    assert "worth <b>0.0</b>" not in html
    assert 'class="bye"' not in html
    assert "<td><b>12.0</b></td>" in html, "the projection, not a bye's zero"


# --------------------------------------------------------------------------- #
# Watch guides
# --------------------------------------------------------------------------- #

# 00:30 ET on Sunday 2026-10-04 (04:30 UTC): Saturday's late game is on.
SUNDAY_0030 = 1791088200000
SATURDAY_2000 = 1791072000000          # 8 PM ET Saturday 2026-10-03


def _watch(page, games, now_ms=SUNDAY_0030, generated="2026-10-03T12:00:00Z", cfg="{}"):
    from gordstats import watch_page
    page.open()
    page.run(f"Date.now=function(){{ return {now_ms}; }};"
             "document.body.innerHTML=\"<div id='wg-host'></div>\"")
    page.run(_js(watch_page.ENGINE_JS))
    data = {"generated": generated, "slots": [["prime", "Prime time", "7:30"], ["late", "Late", "10:30"]],
            "games": games, "rosters": {}}
    page.run(f"window.W=GSWatch({json.dumps(data)}, {cfg})")
    settle(0.3)


def _game(gid, day, slot="late", state="pre", ko="2026-10-04T02:30:00Z"):
    return {"id": gid, "day": day, "slot": slot, "state": state, "ko": ko, "tk": True,
            "tv": "ESPN", "score": 50, "tags": [],
            "h": {"id": "h" + gid, "nm": "Home " + gid}, "a": {"id": "a" + gid, "nm": "Away " + gid}}


def test_saturdays_late_game_stays_on_the_guide_after_midnight(page):
    """Finding 2: at 00:30 ET Sunday the Saturday tab vanished mid-game."""
    _watch(page, [_game("1", "2026-10-03", state="in"), _game("2", "2026-10-04", ko="2026-10-04T17:00:00Z")])
    days = page.ev("[].map.call(document.querySelectorAll('[data-day]'),function(b){"
                   "return [b.dataset.day, b.textContent, b.getAttribute('aria-pressed')]; })")
    assert days[0][0] == "2026-10-03" and days[0][1].startswith("Today"), days
    assert days[0][2] == "true", "and it is the day on screen"


def test_saturdays_tab_stays_after_midnight_before_any_live_read(page):
    _watch(page, [_game("1", "2026-10-03", state="pre"), _game("2", "2026-10-04", ko="2026-10-04T17:00:00Z")])
    assert page.ev("!!document.querySelector('[data-day=\"2026-10-03\"]')")


def test_tonight_card_counts_the_night_until_four(page):
    from gordstats import watch_all
    page.open()
    games = {"games": [dict(_game("1", "2026-10-03", state="in"), ko="2026-10-04T02:30:00Z")]}
    page.stub_fetch({"/cfb/watch/games.json": games, "/nfl/watch/games.json": games})
    page.run(f"Date.now=function(){{ return {SUNDAY_0030}; }}")
    body = re.sub(r"(?s)^.*?</style>", "", watch_all.teaser())
    page.run("document.body.innerHTML=" + json.dumps(re.sub(r"(?s)<script>.*", "", body)))
    page.run(_js(re.search(r"(?s)<script>.*</script>", body).group(0)))
    settle(0.4)
    assert page.ev("document.getElementById('gs-tonight').hidden") is False


def test_a_redraw_keeps_open_sections_open(page):
    """Finding 10: every live poll closed "N more" and "Final"."""
    games = [_game(str(i), "2026-10-03", slot="late", state="pre", ko="2026-10-04T05:30:00Z")
             for i in range(8)]
    games += [_game("f1", "2026-10-03", state="post"), _game("f2", "2026-10-03", state="post")]
    _watch(page, games, now_ms=SATURDAY_2000)
    assert page.ev("document.querySelectorAll('details.wg-more').length") == 2
    page.run("document.querySelectorAll('details.wg-more').forEach(function(d){ d.open=true; })")
    page.run("W.redraw()")
    assert page.ev("[].every.call(document.querySelectorAll('details.wg-more'),"
                   "function(d){ return d.open; })")


def test_a_stale_guide_keeps_saying_so(page):
    _watch(page, [_game("1", "2026-10-03")], generated="2026-09-20T12:00:00Z")
    assert "not been rebuilt" in page.html("#wg-host")
    page.run("document.dispatchEvent(new Event('gs:favorites')); W.redraw()")
    assert "not been rebuilt" in page.html("#wg-host"), "a later redraw keeps the notice"


def test_a_failing_live_read_is_logged_and_the_poll_goes_on(page):
    _watch(page, [_game("1", "2026-10-03", state="in")],
           cfg="{every:5000, live:function(){ return null.boom; }}")
    settle(0.3)
    assert any("TypeError" in e for e in page.ev("__errs"))
    assert 5000 in page.ev("__timers")


# --------------------------------------------------------------------------- #
# The built matchups page's live updater
# --------------------------------------------------------------------------- #

def test_live_payload_without_points_leaves_cells_alone(page):
    """Finding 3: game states with no points drew "0.0 final" everywhere."""
    from gordstats import matchup_page
    page.open()
    page.run("document.body.innerHTML=\"<div data-roster='1'><table><tr class='starter' "
             "data-pid='p1'><td class='mu-pts'>PROJ</td><td class='mu-g'></td></tr></table></div>\";"
             "window.__payload={teams:{'1':{players:{p1:{state:'post'}}}}};"
             "window.MU_LIVE={fetch:function(){ return Promise.resolve(__payload); }, delay:1, interval:100}")
    page.run(_js(matchup_page.LIVE_JS))
    settle(0.4)
    assert page.html(".mu-pts") == "PROJ"
    page.run("__payload={teams:{'1':{points:12,players:{p1:{state:'post',points:12}}}}}")
    settle(0.4)
    assert "12.0" in page.html(".mu-pts") and "final" in page.html(".mu-pts")


def test_median_tracker_update_skips_teams_without_points(page):
    from gordstats import matchup_page
    page.open()
    blob = {"started": True, "final": False, "ext": {},
            "teams": [{"k": k, "name": k, "pts": 50.0 + i, "exp": 90, "left": []}
                      for i, k in enumerate("abc")]}
    page.run("document.body.innerHTML='<div data-medt-week=\"4\" id=\"m\"></div>';"
             f"document.getElementById('m').setAttribute('data-medt', {json.dumps(json.dumps(blob))})")
    page.run(_js(re.search(r"(?s)<script>\s*window\.muMedTrack.*?</script>",
                           matchup_page.MEDIAN_TRACKER_JS).group(0)))
    page.run("muMedTrack.update(4, {teams:{a:{left:[]}, b:{left:[], points:null}}})")
    pts = page.ev("JSON.parse(document.getElementById('m').getAttribute('data-medt'))"
                  ".teams.map(function(t){ return t.pts; })")
    assert pts == [50.0, 51.0, 52.0]


# --------------------------------------------------------------------------- #
# Trades & Pickups
# --------------------------------------------------------------------------- #

TRADE_ADAPTER = """
window.__evals=0; window.__picks=0;
var T={a:{playoffs:.5,title:.10,ppw:100,wins:7,losses:7},b:{playoffs:.5,title:.10,ppw:100,wins:7,losses:7},
       c:{playoffs:.5,title:.10,ppw:100,wins:7,losses:7}};
window.__after={a:{playoffs:.45,title:.08,ppw:99,wins:6.8,losses:7.2},
                b:{playoffs:.40,title:.05,ppw:98,wins:6.5,losses:7.5}};
window.GSTradeAdapter={
  load:function(){ return Promise.resolve({teams:[{id:'a',name:'A'},{id:'b',name:'B'},{id:'c',name:'C'}],
    mine:'a', players:{x1:{name:'X1',pos:'RB',ppw:10},x2:{name:'X2',pos:'WR',ppw:9},
      y1:{name:'Y1',pos:'RB',ppw:8},z1:{name:'Z1',pos:'QB',ppw:20},f1:{name:'F1',pos:'TE',ppw:3}},
    rosters:{a:['x1','x2'],b:['y1'],c:['z1']}, before:T}); },
  evaluate:function(){ __evals++; return Promise.resolve({after:{a:__after.a,b:__after.b,c:T.c}}); },
  candidates:function(){ return ['f1']; },
  pickup:function(){ __picks++; return new Promise(function(r){ setTimeout(function(){
    r({before:T.a, after:T.a, drop:null}); }, 50); }); }
};
"""


def _trade(page, hash_="", saved=None):
    from gordstats import trade_page
    page.open({"gsSleeperLeague": json.dumps(saved)} if saved else None)
    page.run(f"history.replaceState(null,'','/blank.html{hash_}');"
             "document.body.innerHTML=\"<div class='tr' id='tr-host'></div>\"")
    if saved is not None:
        page.run("window.GSL={saved:function(){ try{ return JSON.parse("
                 "localStorage.getItem('gsSleeperLeague')||'null'); }catch(e){ return null; } }}")
    page.run(TRADE_ADAPTER + _js(trade_page.JS) + ";GSTrade(document.getElementById('tr-host'), GSTradeAdapter)")
    settle(0.3)


def test_a_tap_then_pick_up_does_not_evaluate_a_trade_into_the_pickup_view(page):
    """Finding 4a: the 450 ms timer fired into Pick up and cancelled its run."""
    _trade(page)
    page.run("document.querySelector('.tr-p[data-side=a]').click();"
             "document.querySelector('[data-mode=pickup]').click()")
    settle(0.9)
    assert page.ev("__evals") == 0
    assert page.ev("!!document.querySelector('.tr-pk')")
    assert "Playing each pickup out" not in page.html(".tr-out"), "the pickups finished"


def test_changing_your_team_in_pick_up_clears_the_trade(page):
    """Finding 4b: a phantom deal came back on Trade and rode in the link."""
    _trade(page)
    page.run("document.querySelector('.tr-p[data-side=a]').click()")
    settle(0.7)
    page.run("document.querySelector('[data-mode=pickup]').click()")
    page.run("var s=document.querySelector('.tr-a'); s.value='c'; s.dispatchEvent(new Event('change'))")
    settle(0.3)
    page.run("document.querySelector('[data-mode=trade]').click()")
    settle(0.3)
    assert page.ev("document.querySelectorAll('.tr-p[aria-pressed=true]').length") == 0
    assert "x1" not in page.ev("location.hash")


def test_changing_trading_with_plays_the_trade_once(page):
    _trade(page)
    page.run("document.querySelector('.tr-p[data-side=a]').click()")
    settle(0.7)
    page.run("__evals=0; var s=document.querySelector('.tr-b'); s.value='c';"
             "s.dispatchEvent(new Event('change'))")
    settle(0.3)
    assert page.ev("__evals") == 1


def test_a_mangled_trade_link_still_opens_the_analyzer(page):
    _trade(page, "#trade=%E2%8")
    assert "Could not read" not in page.html("#tr-host")
    assert page.ev("!!document.querySelector('.tr-p')")


def test_a_trade_that_costs_you_title_odds_is_never_better_for_you(page):
    """Finding 4: both lose title odds, they more - "Hurts you both"."""
    _trade(page, "#trade=" + "a~b~x1~y1")
    settle(0.3)
    verdict = page.html(".tr-verdict")
    assert "Hurts you both" in verdict and "Better for you" not in verdict


def test_a_trade_link_carries_its_league(page):
    """Finding 4: a deal from another league is not laid over this one."""
    _trade(page, "#trade=a~b~x1~y1~site", saved={"id": LID, "name": "Mine"})
    assert page.ev("document.querySelectorAll('.tr-p[aria-pressed=true]').length") == 0
    assert "made in this site" in page.html(".tr-out")
    _trade(page, "#trade=a~b~x1~y1", saved={"id": LID, "name": "Mine"})
    assert page.ev("document.querySelectorAll('.tr-p[aria-pressed=true]').length") == 2, \
        "an old link (no league in it) still opens"
    page.run("document.querySelector('.tr-p[data-side=b]').click()")
    settle(0.7)
    assert page.ev("decodeURIComponent(location.hash)").endswith("~" + LID)


# --------------------------------------------------------------------------- #
# The league bar
# --------------------------------------------------------------------------- #

def test_an_old_seasons_saved_league_moves_to_its_current_season(page):
    """Finding 5: the account's league was saved while the page showed the
    browser's, with no reload; now matched by lineage and drawn again."""
    from gordstats import my_league
    old, new = "1111111111111111111", "2222222222222222222"
    page.open({"gsSleeperLeague": json.dumps({"id": old, "name": "Old"})})
    routes = {}
    for lid in (old, new):
        lg = _league(league_id=lid)
        routes.update({k: v for k, v in lg.items() if k.startswith(SLEEPER)})
    routes["/api/leagues"] = {"signedIn": True, "leagues": [
        {"provider": "sleeper", "league_id": new, "name": "L", "season": "2026", "lineage_id": old},
        {"provider": "sleeper", "league_id": old, "name": "L", "season": "2025", "lineage_id": old},
        {"provider": "sleeper", "league_id": "3333333333333333333", "name": "Other",
         "season": "2026", "lineage_id": "3333333333333333333"}]}
    page.stub_fetch(routes)
    page.run("window.__marker=1; document.body.innerHTML=\"<div id='ml-bar'></div>\"")
    page.run(_js(my_league.JS))
    settle(1.5)
    assert page.ev("JSON.parse(localStorage.getItem('gsSleeperLeague')).id") == new
    assert page.ev("typeof window.__marker") == "undefined", "the page was drawn again"


def test_a_late_answer_for_the_old_league_does_not_overwrite_the_new(page):
    from gordstats import my_league
    old, new = "1111111111111111111", "2222222222222222222"
    page.open({"gsSleeperLeague": json.dumps({"id": old, "name": "Old"})})
    routes = {}
    for lid, delay in ((old, 800), (new, 0)):
        for k, v in _league(league_id=lid).items():
            if k.startswith(SLEEPER):
                routes[k] = {"__body": v, "__delay": delay}
    routes["/api/leagues"] = {"signedIn": True, "leagues": [
        {"provider": "sleeper", "league_id": new, "name": "New", "season": "2026", "lineage_id": new}]}
    page.stub_fetch(routes)
    # A usage page owns its table, so nothing reloads: what is saved last is
    # what the late answer would have overwritten.
    page.run("document.body.innerHTML=\"<div id='ml-bar'></div><select id='us-own'></select>"
             "<table class='us'><tbody><tr data-pid='p1'><td class='us-own'></td></tr></tbody></table>\"")
    page.run(_js(my_league.JS))
    settle(1.6)
    assert page.ev("JSON.parse(localStorage.getItem('gsSleeperLeague')).id") == new


def test_other_season_note_offers_espns_current_season(page):
    from gordstats import league_api
    page.open()
    page.run(_js(league_api.JS))
    assert page.ev("GSAPI.otherSeason({season:'2026', league_id:'x'}, 2026, 'c')") is None
    note = page.ev("GSAPI.otherSeason({season:'2025', league_id:'espn:2025:42', name:'E'}, 2026, 'c')")
    assert 'data-gs-season="espn:2026:42"' in note and "2025" in note


# --------------------------------------------------------------------------- #
# Home cards
# --------------------------------------------------------------------------- #

def test_my_teams_wakes_at_the_next_kickoff_and_survives_a_bad_star_list(page):
    """Findings 7 and 12."""
    from gordstats import my_teams_today
    for bad in ("{}", '"cfb:1"'):
        page.open({"gs:favorites": bad})
        page.stub_fetch({})
        page.run("document.body.innerHTML=\"<section><div id='mt-host' data-cfb='1' data-cbb='0'>"
                 "</div></section>\"")
        page.run(_js(my_teams_today.JS))
        settle(0.3)
        assert "Star teams" in page.html("#mt-host"), bad
        assert page.ev("__errs") == []
    kick = int(time.time() * 1000) + 120000
    week = {"season": 2026, "generated": "2099-01-01T00:00:00Z", "teams": {"1": "Home U"},
            "games": [{"id": "g1", "week": 5, "seasontype": 2, "state": "pre", "time_known": True,
                       "kickoff": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(kick / 1000)),
                       "home": {"id": "1", "name": "Home U"}, "away": {"id": "2", "name": "Away"}}]}
    page.open({"gs:favorites": json.dumps(["cfb:1"])})
    page.stub_fetch({"/cfb/week-games.json": week})
    page.run("document.body.innerHTML=\"<section><div id='mt-host' data-cfb='1' data-cbb='0'>"
             "</div></section>\"")
    page.run(_js(my_teams_today.JS))
    settle(0.3)
    waits = page.ev("__timers")
    assert any(120000 < w <= 152000 for w in waits), waits


def test_week_strip_wakes_at_kickoff_and_retries_a_failed_read(page):
    """Finding 7: polled only if something was live at first draw, and a
    failed fetch was never asked again."""
    from gordstats import league_api, week_strip
    page.open()
    kick = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 600))
    wk = {"week": 4, "kick": {"KC": kick}, "proj": {"p1": [10, 10, 10, "KC", ""], "p4": [10, 10, 10, "KC", ""]}}
    lg = _league()
    routes = {f"{SLEEPER}/state/nfl": {"season": "2026", "display_week": 4}}
    routes.update({k: v for k, v in lg.items() if k.startswith(SLEEPER)})
    def run(routes):
        page.open()
        page.stub_fetch(routes)
        page.run("document.body.innerHTML=\"<div id='ws-host'></div>\";"
                 "var WK=" + json.dumps(wk) + ";"
                 "window.GSL={saved:function(){return {id:'" + LID + "'};},"
                 "week:function(){return Promise.resolve(WK);},basis:function(){return {index:0};},"
                 "points:function(w,i){var o={};for(var k in w.proj)o[k]=w.proj[k][i];return o;},"
                 "myRoster:function(){return null;}}")
        page.run(_js(league_api.JS) + _js(week_strip.JS))
        settle(0.5)
        return page.ev("__timers")
    waits = run(routes)
    assert any(600000 < w <= 640000 for w in waits), waits
    # The matchups read fails: asked again, not abandoned.
    del routes[f"{SLEEPER}/league/{LID}/matchups/4"]
    assert 60000 in run(routes)


def test_profile_follows_the_list_when_sign_in_brings_teams(page):
    """Finding 11."""
    from gordstats import profile_page
    page.open()
    page.stub_fetch({"/assets/favourite-teams.json": {"cfb": {"333": "Alabama"}},
                     "/api/me": {"configured": True, "signedIn": True, "email": "x@y"}})
    page.run("document.body.innerHTML=\"<div id='pf-who'></div><div id='pf-favs'></div>\"")
    page.run(_js(profile_page.JS))
    settle(0.3)
    assert "No teams followed" in page.html("#pf-favs")
    page.run("window.GSFavorites={list:function(){ return ['cfb:333']; }};"
             "document.dispatchEvent(new CustomEvent('gs:favorites'))")
    assert "Alabama" in page.html("#pf-favs")


# --------------------------------------------------------------------------- #
# CBB scoreboard and the conference/rank dropdowns
# --------------------------------------------------------------------------- #

def _live_js(page):
    page.open()
    page.stub_fetch({})
    page.run("var s=document.createElement('script'); s.src='/live.js'; document.head.appendChild(s)")
    settle(0.5)


def test_cbb_overtime_and_seconds_only_clocks(page):
    """Finding 8: 'OT' was NaN (first half, never close late), a clock with no
    colon was Infinity."""
    _live_js(page)
    got = page.ev("""(function(){
      function g(p, c, h, a, ot){ return enrichGame({status:'in_progress', period:p, clock:c,
        home_score:h, away_score:a, overtime:!!ot}); }
      return {ot: g('OT','3:10',70,68).isCloseLate, ot2: g('2OT','4:00',80,79).isCloseLate,
        secs: g('2nd','45.3',60,58).isCloseLate, early: g('2nd','12:00',60,58).isCloseLate,
        order: [gamePriority({status:'in_progress',period:'OT',clock:'1:00'}) >
                gamePriority({status:'in_progress',period:'2nd',clock:'0:30'}),
                gamePriority({status:'in_progress',period:'2nd',clock:'45.3'}) >
                gamePriority({status:'in_progress',period:'2nd',clock:'1:30'})],
        finite: isFinite(gamePriority({status:'in_progress',period:'2nd',clock:'bogus'}))};
    })()""")
    assert got["ot"] and got["ot2"] and got["secs"], got
    assert not got["early"]
    assert got["order"] == [True, True] and got["finite"]


def _conf_page(page, saved, block=False):
    page.open({"conference": saved} if saved else None)
    if block:
        page.run("Storage.prototype.getItem=Storage.prototype.setItem=function(){"
                 "throw new DOMException('blocked','SecurityError'); }")
    page.run("document.body.innerHTML=\"<select id='conference-select'><option value='ALL'>All</option>"
             "</select><div class='table-container'><table class='rank-table' data-conference='SEC'>"
             "</table></div><div class='table-container'><table class='rank-table' data-conference='ACC'>"
             "</table></div>\";"
             "var s=document.createElement('script'); s.src='/conf-toggle.js'; document.body.appendChild(s)")
    settle(0.4)
    return page.ev("[].map.call(document.querySelectorAll('.conference-block'),"
                   "function(b){ return b.style.display; })")


def test_a_saved_conference_that_is_gone_shows_every_conference(page):
    """Finding 9: '0 of 31 blocks'."""
    assert _conf_page(page, "Pac-12") == ["", ""]
    assert _conf_page(page, "SEC") == ["", "none"]


def test_blocked_storage_still_wires_the_conference_dropdown(page):
    assert _conf_page(page, None, block=True) == ["", ""]
    page.run("var s=document.getElementById('conference-select'); s.value='ACC';"
             "s.dispatchEvent(new Event('change'))")
    assert page.ev("[].map.call(document.querySelectorAll('.conference-block'),"
                   "function(b){ return b.style.display; })") == ["none", ""]
    assert page.ev("__errs") == []


def test_rank_period_survives_blocked_storage_and_a_stale_choice(page):
    for block in (False, True):
        page.open({"rankPeriod": "3y"})
        if block:
            page.run("Storage.prototype.getItem=Storage.prototype.setItem=function(){"
                     "throw new DOMException('blocked','SecurityError'); }")
        page.run("window.addEventListener('error', function(e){ __errs.push(String(e.message)); });"
                 "document.body.innerHTML=\"<select id='period-select'><option value='7d'>7d</option>"
                 "<option value='1d'>1d</option></select><table class='rank-table'><thead><tr><th>Team</th>"
                 "<th>\\u0394 1d</th><th>\\u0394 7d</th></tr></thead><tbody><tr><td>A</td><td>1</td><td>2</td>"
                 "</tr></tbody></table>\";"
                 "var s=document.createElement('script'); s.src='/rank-toggle.js'; document.body.appendChild(s)")
        settle(0.3)
        page.run("document.dispatchEvent(new Event('DOMContentLoaded'))")
        assert page.ev("document.getElementById('period-select').value") == "7d"
        assert page.ev("[].map.call(document.querySelectorAll('thead th'),"
                       "function(t){ return t.className; })") == ["", "hidden-col", ""]
        assert page.ev("__errs") == [], block


# --------------------------------------------------------------------------- #
# League history: playoff rounds of more than one week
# --------------------------------------------------------------------------- #

def _history_log(page, settings, weeks, bracket, season="2025"):
    from gordstats import my_history
    page.open()
    data = {f"/league/H/matchups/{w}": rows for w, rows in weeks.items()}
    data["/state/nfl"] = {"season": "2026", "display_week": 5}
    page.run("window.GSAPI={get:function(p){ return Promise.resolve(" + json.dumps(data)
             + "[p]||null); }}")
    page.run(_js(my_history.JS))
    lg = {"league_id": "H", "season": season, "settings": settings}
    return page.ev("""(function(){
      var lg=%s, bracket=%s;
      var stub={'/league/H/rosters':[{roster_id:1,owner_id:'o1',settings:{}},{roster_id:2,owner_id:'o2',settings:{}}],
                '/league/H/users':[], '/league/H/winners_bracket':bracket};
      var get=GSAPI.get;
      GSAPI.get=function(p){ return p in stub ? Promise.resolve(stub[p]) : get(p); };
      return GSHist.loadState().then(function(){ return GSHist.season(lg); })
        .then(function(s){ return GSHist.gameLog([s]); })
        .then(function(log){ return log.filter(function(g){ return g.kind==='playoff'; }); });
    })()""" % (json.dumps(lg), json.dumps(bracket)))


def _two_week_final():
    rows = lambda a, b: [{"roster_id": 1, "matchup_id": 1, "points": a},  # noqa: E731
                         {"roster_id": 2, "matchup_id": 1, "points": b}]
    return {15: rows(100, 90), 16: rows(110, 100), 17: rows(80, 130)}


def test_a_two_week_final_is_scored_on_both_weeks(page):
    """Finding 13: Sleeper's playoff_round_type 1 (two-week championship)."""
    bracket = [{"r": 1, "m": 1, "t1": 1, "t2": 2, "w": 1, "l": 2},
               {"r": 2, "m": 2, "t1": 1, "t2": 2, "w": 2, "l": 1, "p": 1}]
    log = _history_log(page, {"playoff_week_start": 15, "playoff_round_type": 1},
                       _two_week_final(), bracket)
    got = sorted((g["week"], g["ap"], g["bp"]) for g in log)
    assert got == [(15, 100, 90), (17, 190, 230)], got


def test_two_weeks_a_round(page):
    bracket = [{"r": 1, "m": 1, "t1": 1, "t2": 2, "w": 1, "l": 2, "p": 1}]
    weeks = _two_week_final()
    log = _history_log(page, {"playoff_week_start": 15, "playoff_round_type": 2}, weeks, bracket)
    assert [(g["week"], g["ap"], g["bp"]) for g in log] == [(16, 210, 190)]


def test_espn_two_week_periods_become_round_weeks(page):
    from gordstats import league_api
    page.open()
    page.run(_js(league_api.JS))
    lg = page.ev("""GSAPI._espn.leagueOf({settings:{scheduleSettings:{matchupPeriodCount:14,
        matchupPeriods:{'14':[14],'15':[15],'16':[16,17]}, playoffTeamCount:4}}, status:{},
        teams:[]}, 'espn:2025:9').settings""")
    assert lg["playoff_week_start"] == 15
    assert lg["playoff_round_type"] == 1
    assert lg["round_weeks"] == {"1": [15], "2": [16, 17]}
