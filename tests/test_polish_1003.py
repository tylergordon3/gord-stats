"""Polish + correctness fixes from the 2026-10-03 review pass."""
import os

from gordstats import stable


# --------------------------------------------------------------------------- #
# CBB T-Rank cache: rewritten only when what the site reads changed
# --------------------------------------------------------------------------- #

_TORVIK = (
    "rank,team,conf,record,adjoe,oe Rank,adjde,de Rank,barthag,rank,proj. W,Proj. L,"
    "Pro Con W,Pro Con L,sos,ncsos,Proj. SOS,Proj. Noncon SOS,FUN,WAB,Fun Rk,adjt\n"
    "2,Arizona,B12,0-0,119.16998584562745,11,91.79633311925635,2,0.9526307280702049,2,"
    "23.008686818801543,6.991313181198461,13.1197137,4.8802862,0,0,0.7396887004013927,"
    "0.5803395187298441,0,0,{fa},73.13101542171262\n"
    "1,Duke,ACC,0-0,120.94104876062653,3,91.00685933815402,1,0.9633934945919819,1,"
    "25.86735104334522,6.132648956654773,14.3731433,3.6268566,0,0,0.7216310706538036,"
    "0.6082772672579372,0,0,{fd},69.2808466635242\n")


def test_trank_cache_is_tidy_and_rewritten_only_when_it_changed(tmp_path, monkeypatch):
    import pandas as pd
    from cbb.render import render_power

    tidy = render_power._tidy(_TORVIK.format(fa=133, fd=63))
    lines = tidy.splitlines()
    assert lines[0] == ("rank,team,conf,record,adjoe,adjde,barthag,adjt,proj. W,Proj. L,"
                        "Pro Con W,Pro Con L,sos,ncsos,Proj. SOS,Proj. Noncon SOS,WAB")
    assert lines[1].startswith("1,Duke,ACC,0-0,120.94,91.01,0.9634,69.28,25.87,"), "rank order"
    assert render_power._tidy(tidy) == tidy, "idempotent"
    # The random "Fun Rk" reshuffle and a 16th-digit wobble are not changes.
    noisy = _TORVIK.format(fa=7, fd=301).replace("120.94104876062653", "120.94104876062699")
    assert render_power._tidy(noisy) == tidy

    cache = tmp_path / "trank_2027.csv"
    monkeypatch.setattr(render_power, "_cache_path", lambda: cache)

    class Reply:
        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            pass

    replies = iter([_TORVIK.format(fa=133, fd=63), noisy,
                    _TORVIK.format(fa=1, fd=2).replace("120.94104876062653", "121.5")])
    monkeypatch.setattr(render_power.requests, "get", lambda *a, **k: Reply(next(replies)))
    first = render_power.trank(refresh=True)
    assert list(first["team"]) == ["Duke", "Arizona"]
    written = cache.read_bytes()
    os.utime(cache, (1, 1))
    render_power.trank(refresh=True)
    assert cache.read_bytes() == written, "unchanged content is not rewritten"
    assert cache.stat().st_mtime > 1, "but the cache still reads as fresh"
    df = render_power.trank(refresh=True)
    assert df.loc[df["team"] == "Duke", "adjoe"].item() == 121.5, "a real move is written"
    # The readers' columns survive the trim.
    assert {"adjoe", "adjde", "adjt", "barthag", "proj. W", "Proj. L", "WAB"} <= set(df.columns)
    assert isinstance(pd.read_csv(cache), pd.DataFrame)


def test_write_text_skips_identical_text(tmp_path):
    path = tmp_path / "a" / "b.csv"
    assert stable.write_text("x,y\n1,2\n", path)
    os.utime(path, (1, 1))
    assert not stable.write_text("x,y\n1,2\n", path)
    assert path.stat().st_mtime > 1
    assert stable.write_text("x,y\n1,3\n", path)
    assert path.read_text() == "x,y\n1,3\n"


# --------------------------------------------------------------------------- #
# Browser helper (CDP port 9625 - no other test file uses it)
# --------------------------------------------------------------------------- #

import asyncio  # noqa: E402
import http.server  # noqa: E402
import json  # noqa: E402
import shutil  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import urllib.request  # noqa: E402

import pytest  # noqa: E402

from browser_util import launch, reap  # noqa: E402
from conftest import DOCS  # noqa: E402

CHROME = next((p for p in ("/usr/bin/chromium-browser", "/usr/bin/chromium",
                           "/usr/bin/google-chrome") if shutil.which(p)), None)
needs_chrome = pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")


class Browser:
    def __init__(self, port):
        self.port = port
        self.proc = launch(CHROME, port)
        for _ in range(60):
            try:
                targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
                self.ws_url = next(t["webSocketDebuggerUrl"] for t in targets
                                   if t.get("type") == "page")
                return
            except Exception:                                   # noqa: BLE001
                time.sleep(0.5)
        raise RuntimeError("Chromium did not come up")

    def close(self):
        self.proc.terminate()
        reap(self.proc)

    def evaluate(self, expression):
        import websockets

        async def run():
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
                            raise AssertionError(result["exceptionDetails"]["text"])
                        return result["result"].get("value")
        return asyncio.run(run())


@pytest.fixture
def served(tmp_path):
    """A blank page over http (localStorage needs an origin) and a browser on it."""
    (tmp_path / "index.html").write_text("<html><body></body></html>")
    handler = lambda *a: http.server.SimpleHTTPRequestHandler(*a, directory=str(tmp_path))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    browser = Browser(9625)
    try:
        browser.evaluate(f"location.href='http://127.0.0.1:{server.server_address[1]}/';true")
        time.sleep(1.0)
        yield browser
    finally:
        browser.close()
        server.shutdown()


# --------------------------------------------------------------------------- #
# favorites.js honors Retry-After
# --------------------------------------------------------------------------- #

FAV_JS = (DOCS / "assets" / "js" / "favorites.js").read_text()


def _fav_boot(browser, status, retry_after=None, stored_retry=None):
    headers = ("{get:function(h){return h.toLowerCase()==='retry-after'?%s:null;}}"
               % json.dumps(retry_after)) if retry_after is not None else "undefined"
    browser.evaluate(
        "localStorage.clear();"
        "localStorage.setItem('gs:favorites', JSON.stringify(['cfb:1','cfb:2']));"
        "localStorage.setItem('gs:favorites:sync', 'r@x.com');"
        "localStorage.setItem('gs:favorites:dirty', '1');"
        + (f"localStorage.setItem('gs:favorites:retry', String(Date.now()+{stored_retry}));"
           if stored_retry is not None else "")
        + "window.PUTS=[];window.T0=Date.now();"
        "window.fetch=function(url,opt){opt=opt||{};"
        "  if(url==='/api/me')return Promise.resolve({json:function(){return {configured:true,signedIn:true,email:'r@x.com'};}});"
        "  if(opt.method==='PUT'){PUTS.push(Date.now());"
        f"    return Promise.resolve({{ok:{str(status < 300).lower()},status:{status},headers:{headers}}});}}"
        "  return Promise.resolve({ok:true,json:function(){return {favorites:['cfb:1']};}});};"
        + FAV_JS + ";true")
    time.sleep(1.5)


def _fav_state(browser):
    return json.loads(browser.evaluate(
        "JSON.stringify({puts:PUTS.length,dirty:localStorage.getItem('gs:favorites:dirty'),"
        "wait:(Number(localStorage.getItem('gs:favorites:retry'))-T0)/1000})"))


@needs_chrome
def test_favorites_save_waits_for_retry_after(served):
    _fav_boot(served, 429, retry_after="120")
    got = _fav_state(served)
    assert got["puts"] == 1 and got["dirty"] == "1"
    assert 118 < got["wait"] < 125, got
    # A star inside the wait does not ask again before the server said to.
    served.evaluate("GSFavorites.remove('cfb:2');true")
    time.sleep(1.2)
    assert _fav_state(served)["puts"] == 1


@needs_chrome
def test_favorites_site_limit_wait_is_capped_at_an_hour(served):
    _fav_boot(served, 503, retry_after="40000")      # the site's day: until midnight
    got = _fav_state(served)
    assert got["puts"] == 1 and 3590 < got["wait"] < 3610, got


@needs_chrome
def test_favorites_unexplained_failures_back_off(served):
    _fav_boot(served, 500)
    got = _fav_state(served)
    assert got["puts"] == 1 and 14 < got["wait"] < 17, got


@needs_chrome
def test_favorites_next_page_honors_a_stored_wait(served):
    """The next page has the same unsaved change: it waits too, not sends."""
    _fav_boot(served, 200, stored_retry=60000)
    got = _fav_state(served)
    assert got["puts"] == 0 and got["dirty"] == "1", got


# --------------------------------------------------------------------------- #
# /nfl/ shows the top 10 ratings and links to /nfl/power/ for all 32
# --------------------------------------------------------------------------- #

def test_nfl_home_ratings_are_a_top_ten_with_a_link():
    import re

    import pandas as pd
    from nfl.site import predictions

    class Model:
        total_base = 44.0

        def table(self):
            return pd.DataFrame({"team": [str(i) for i in range(1, 33)],
                                 "rating": [16 - i for i in range(32)],
                                 "pace": [0.0] * 32})

    names = {str(i): (f"Team {i}", "KC") for i in range(1, 33)}
    schedule = pd.DataFrame({"home_id": ["1"], "home_record": ["3-1"],
                             "away_id": ["2"], "away_record": ["1-3"]})
    html = predictions._ratings_table(Model(), names, schedule)
    assert len(re.findall(r"<tr><td>\d+</td>", html)) == 10
    assert "Team 10<" in html and "Team 11<" not in html
    assert "<a href='/nfl/power/'>All 32 teams &rarr;</a>" in html
    import inspect
    assert "<h2>Ratings {how.button('nfl-rankings')}</h2>" in inspect.getsource(predictions.body)


# --------------------------------------------------------------------------- #
# Recap lineup accuracy: full team names on a phone
# --------------------------------------------------------------------------- #

def _recap_week():
    from gordstats import recap
    names = ["Too B1G Too Strong Too Fast", "Jackson's Brilliant Team",
             "Cameron's Choice Team", "Lotta Cox (Balls Too)", "padgett", "The Standard"]
    teams = {str(i): recap.Team(n) for i, n in enumerate(names)}
    sides = {}
    for i in range(len(names)):
        p = recap.Player(f"p{i}", "P", "WR", 100.0 + i, "WR")
        b = recap.Player(f"b{i}", "B", "WR", 12.5 + i)
        sides[str(i)] = recap.Side(str(i), 100.0 + i, [p], [b], {b.id})
    week = recap.Week(4, teams, [("0", "1"), ("2", "3"), ("4", "5")], sides)
    return week, names


def test_recap_names_wrap_on_phones_instead_of_trailing_off():
    from gordstats import recap
    phone = recap.CSS[recap.CSS.index("@media (max-width:600px){"):]
    phone = phone[:phone.index("\n}")]
    assert ".rc-acc td:first-child{white-space:normal}" in phone
    assert "max-width:118px" not in recap.CSS


def _serve(tmp_path, html):
    (tmp_path / "index.html").write_text(html)
    handler = lambda *a: http.server.SimpleHTTPRequestHandler(*a, directory=str(tmp_path))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@needs_chrome
def test_recap_accuracy_names_are_whole_at_390px(tmp_path):
    from gordstats import recap
    week, names = _recap_week()
    html = ("<!doctype html><meta name=viewport content='width=device-width'>"
            "<body style='margin:0;padding:0 16px;font-family:sans-serif'>" + recap.CSS
            + recap._accuracy(week, recap.season([week])) + "</body>")
    server = _serve(tmp_path, html)
    browser = Browser(9626)
    try:
        browser.evaluate(f"location.href='http://127.0.0.1:{server.server_address[1]}/';true")
        time.sleep(1.0)
        import websockets  # noqa: F401  (Browser.evaluate needs it)

        async def resize():
            async with websockets.connect(browser.ws_url) as ws:
                await ws.send(json.dumps({"id": 1, "method": "Emulation.setDeviceMetricsOverride",
                                          "params": {"width": 390, "height": 844,
                                                     "deviceScaleFactor": 1, "mobile": True}}))
                while json.loads(await ws.recv()).get("id") != 1:
                    pass
        asyncio.run(resize())
        time.sleep(0.5)
        got = json.loads(browser.evaluate(
            "JSON.stringify({w:innerWidth,doc:document.documentElement.scrollWidth,"
            "names:[].map.call(document.querySelectorAll('.rc-acc .tmw > span:not(.rc-av)'),function(s){"
            "var r=s.getBoundingClientRect();return [s.textContent,s.scrollWidth>s.clientWidth+1,"
            "Math.round(r.height/parseFloat(getComputedStyle(s).lineHeight))];})})"))
    finally:
        browser.close()
        server.shutdown()
    assert got["w"] == 390 and got["doc"] <= 390, got
    assert sorted(n for n, _, _ in got["names"]) == sorted(names)
    for name, cut, lines in got["names"]:
        assert not cut, f"{name} is cut off"
        assert lines <= 2, f"{name} takes {lines} lines"


# --------------------------------------------------------------------------- #
# /profile/: what the browser already knows is drawn before the first paint
# --------------------------------------------------------------------------- #

_STUB = """<script>
window.__res={};
window.fetch=function(url){
  var key=String(url).split('?')[0];
  return new Promise(function(res){ (window.__res[key]=window.__res[key]||[]).push(res); });
};
window.answer=function(url, body){
  (window.__res[url]||[]).splice(0).forEach(function(r){
    r({ok:true, status:200, json:function(){ return Promise.resolve(body); }});
  });
};
</script>"""
_ROWS = [{"provider": "sleeper", "league_id": "111", "lineage_id": "111", "name": "Gord League",
          "season": "2026", "team_name": "Tyler's Team", "last_synced_at": "2026-10-02T12:00:00Z"},
         {"provider": "espn", "league_id": "espn:2026:9", "name": "Work League", "season": "2026",
          "team_name": "Desk", "last_synced_at": "2026-10-01T12:00:00Z"}]


@needs_chrome
def test_profile_draws_the_known_account_teams_and_leagues_before_the_answers(tmp_path):
    from gordstats import league_sync, profile_page
    page = (profile_page.body(league_sync.body())
            .replace("{% raw %}", "").replace("{% endraw %}", ""))
    (tmp_path / "blank.html").write_text("<!doctype html><body></body>")
    server = _serve(tmp_path, "<!doctype html><meta charset=utf-8><body>" + _STUB + page + "</body>")
    origin = f"http://127.0.0.1:{server.server_address[1]}"
    browser = Browser(9627)
    seed = ("localStorage.clear();localStorage.setItem('gs:acct','in');"
            "localStorage.setItem('gs:favorites:sync','reader@example.com');"
            "localStorage.setItem('gs:favorites',JSON.stringify(['cfb:333','nfl:12']));"
            f"localStorage.setItem('gs:ls-rows',{json.dumps(json.dumps(_ROWS))});true")
    state = ("JSON.stringify({who:(document.querySelector('#pf-who .pf-who b')||{}).textContent||"
             "document.getElementById('pf-who').textContent,"
             "wait:document.getElementById('pf-favs').classList.contains('pf-wait'),"
             "favs:document.querySelectorAll('#pf-favs li').length,"
             "names:[].map.call(document.querySelectorAll('#pf-favs .pf-name'),function(e){return e.textContent;}),"
             "main:!document.getElementById('ls-main').hidden,"
             "gate:document.getElementById('ls-gate').textContent,"
             "leagues:document.querySelectorAll('#ls-list li').length,"
             "kept:localStorage.getItem('gs:ls-rows'),"
             "tops:[].map.call(document.querySelectorAll('.pf-card'),function(c){return c.offsetTop;})})")
    try:
        browser.evaluate(f"location.href='{origin}/blank.html';true")
        time.sleep(0.8)
        browser.evaluate(seed)
        browser.evaluate(f"location.href='{origin}/';true")
        time.sleep(1.0)
        first = json.loads(browser.evaluate(state))
        assert first["who"] == "reader@example.com"
        assert first["wait"] and first["favs"] == 2
        assert first["main"] and first["leagues"] == 2
        browser.evaluate(
            "answer('/assets/favourite-teams.json',{cfb:{'333':'Alabama'},nfl:{'12':'Kansas City'}});"
            "answer('/api/me',{configured:true,signedIn:true,email:'reader@example.com'});true")
        time.sleep(0.3)
        browser.evaluate(f"answer('/api/leagues',{{ok:true,leagues:{json.dumps(_ROWS)}}});true")
        time.sleep(0.3)
        after = json.loads(browser.evaluate(state))
        assert not after["wait"] and sorted(after["names"]) == ["Alabama", "Kansas City"]
        assert after["leagues"] == 2
        assert after["tops"] == first["tops"], "a card moved once the answers came"

        # The guess was wrong - signed out since: everything is taken back,
        # and the league list is not left for the next reader of this browser.
        browser.evaluate(seed)
        browser.evaluate(f"location.href='{origin}/?x=1';true")
        time.sleep(1.0)
        browser.evaluate("answer('/api/me',{configured:true,signedIn:false});true")
        time.sleep(0.3)
        out = json.loads(browser.evaluate(state))
        assert "Sign in with Google" in out["who"]
        assert not out["main"] and out["gate"].startswith("Sign in")
        assert out["kept"] is None
    finally:
        browser.close()
        server.shutdown()
