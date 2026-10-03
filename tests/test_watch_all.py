"""
The all-sports watch guide (gordstats.watch_all) and Home's Tonight card.

The page merges the CFB and NFL guides' games in the browser, so it is run in
headless Chromium over two stubbed games.json files: one window for an 8:00
college kickoff and an 8:25 NFL one, keys that cannot collide across sports
(both files use the id "7"), stars and fantasy players from both leagues, and
each sport's live fetcher asked only for its own games, by its own ids.
"""
import asyncio
import functools
import http.server
import json
import shutil
import socketserver
import subprocess
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest

from gordstats import watch_all, watch_page
from gordstats.js_assets import expand
from browser_util import launch, reap

CHROME = next((p for p in ("/usr/bin/chromium-browser", "/usr/bin/chromium",
                           "/usr/bin/google-chrome") if shutil.which(p)), None)
pytestmark = pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")
CDP = 9485


def _game(gid, ko, score, tv, home, away, hk, ak, day=None):
    ko = ko.astimezone(timezone.utc)
    return {"id": gid, "wk": 5, "st": 2, "ko": ko.strftime("%Y-%m-%dT%H:%M:%SZ"), "tk": True,
            "day": day or watch_page.game_day(ko), "slot": "x",
            "tv": tv, "note": "", "n": False, "state": "pre", "score": score, "tags": [],
            "fav": "h", "hw": 0.6, "sp": -3.0,
            "h": {"id": hk, "k": hk, "nm": home, "sc": 0},
            "a": {"id": ak, "k": ak, "nm": away, "sc": 0}}


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    """Today: one college and one NFL game under way. Tomorrow evening: two
    college games and an NFL one, at 8:00, 8:25 and 9:30 Eastern."""
    root = tmp_path_factory.mktemp("watchall")
    now = datetime.now(watch_page.ET)
    # The guide's day, which runs to 4 AM Eastern (watch_page.NIGHT_ENDS) - at
    # 12:53 AM it is still last night, and so is "today" here.
    today = watch_page.game_day(now)
    tomorrow = (datetime.strptime(today, "%Y-%m-%d").replace(tzinfo=watch_page.ET)
                + timedelta(days=1))

    def at(h, m=0):
        return tomorrow.replace(hour=h, minute=m).astimezone(timezone.utc)
    gen = now.isoformat(timespec="minutes")
    cfb = {"season": 2026, "generated": gen, "games": [
        _game("1", now - timedelta(minutes=40), 30, "ESPN2", "Akron", "Kent St", "1", "2", today),
        _game("7", at(20), 40, "ESPN", "Tulsa", "North Texas", "202", "249"),
        _game("8", at(21, 30), 25, "CBSSN", "New Mexico St", "Western KY", "166", "98")],
        "rosters": {"t.1": {"n": "Puntaholics", "p": [["Tulsa Back", "RB", "202", True]]}}}
    nfl = {"season": 2026, "generated": gen, "games": [
        _game("1", now - timedelta(minutes=20), 35, "CBS", "Bills", "Jets", "BUF", "NYJ", today),
        _game("7", at(20, 25), 37, "Prime Video", "Browns", "Steelers", "CLE", "PIT")],
        "rosters": {"2": {"n": "DRINK MAYE", "p": [["Steelers WR", "WR", "PIT", True]],
                          "opp": "5"},
                    "5": {"n": "Rival", "p": [["Browns TE", "TE", "CLE", True]]}}}
    for sport, data in (("cfb", cfb), ("nfl", nfl)):
        (root / sport / "watch").mkdir(parents=True)
        (root / sport / "watch" / "games.json").write_text(json.dumps(data))
    (root / "watch").mkdir()
    (root / "watch" / "index.html").write_text(
        "<!doctype html><html><body>" + expand(watch_all.body()) + "</body></html>")
    (root / "index.html").write_text(
        "<!doctype html><html><body>" + watch_all.teaser() + "</body></html>")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a: None
    server = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()


# Before the page's scripts: stars, both fantasy teams, and the two sports'
# live fetchers stubbed - each records the ids it was asked for and answers
# for its own game "1", under that raw id.
BOOT = """
localStorage.setItem('gs:favorites', JSON.stringify(%s));
localStorage.setItem('cfbMyTeam', 't.1');
localStorage.setItem('nflMyTeam', '2');
window.__asked = {};
// Read-only, so the page's own GSWatchLive.cfb = ... cannot replace them.
var stub = {};
Object.defineProperty(stub, 'cfb', {writable:false, value:function(g){
  __asked.cfb = g.map(function(x){ return x.id; });
  return Promise.resolve({'1': {state:'in', detail:'Q2', period:2, home:14, away:7}}); }});
Object.defineProperty(stub, 'nfl', {writable:false, value:function(g){
  __asked.nfl = g.map(function(x){ return x.id; });
  return Promise.resolve({'1': {state:'in', detail:'Q1', period:1, home:0, away:3}}); }});
Object.defineProperty(window, 'GSWatchLive', {configurable:true,
  get:function(){ return stub; }, set:function(){}});
"""

READ = """(function(){
  var out={sections:{}, asked:window.__asked};
  document.querySelectorAll('#wg-host h3').forEach(function(h){
    var list=h.nextElementSibling;
    out.sections[h.firstChild.textContent.trim()]=Array.prototype.map.call(
      list.querySelectorAll('a.wg-g'), function(a){
        return {id:a.getAttribute('data-gid'), text:a.innerText}; });
  });
  return out;
})()"""

TOMORROW = ("(function(){var b=document.querySelectorAll('.wg-days button');"
            "b[b.length-1].click(); return true;})()")


def _run(url, boot, steps, wait=2.5):
    """Navigate; for each JS step evaluate it, wait a beat, and keep the last value."""
    import websockets
    subprocess.run(["fuser", "-k", f"{CDP}/tcp"], capture_output=True)
    proc = launch(CHROME, CDP)
    try:
        for _ in range(60):
            try:
                ws_url = next(t["webSocketDebuggerUrl"] for t in json.load(
                    urllib.request.urlopen(f"http://127.0.0.1:{CDP}/json")) if t["type"] == "page")
                break
            except Exception:                               # noqa: BLE001
                time.sleep(0.5)

        async def go():
            async with websockets.connect(ws_url, max_size=None) as ws:
                n = 0

                async def send(method, params=None):
                    nonlocal n
                    n += 1
                    me = n
                    await ws.send(json.dumps({"id": me, "method": method, "params": params or {}}))
                    while True:
                        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
                        if msg.get("id") == me:
                            return msg.get("result", {})
                await send("Page.enable")
                await send("Page.addScriptToEvaluateOnNewDocument", {"source": boot})
                await send("Page.navigate", {"url": url})
                await asyncio.sleep(wait)
                value = None
                for js in steps:
                    r = await send("Runtime.evaluate", {"expression": js, "returnByValue": True})
                    value = r["result"].get("value")
                    await asyncio.sleep(0.4)
                return value
        return asyncio.run(go())
    finally:
        proc.terminate()
        reap(proc)
        subprocess.run(["fuser", "-k", f"{CDP}/tcp"], capture_output=True)


def test_games_on_now_from_both_sports_with_each_sports_live_scores(site):
    got = _run(site + "watch/", BOOT % "[]", [READ])
    on = got["sections"]["On now"]
    assert {g["id"] for g in on} == {"cfb:1", "nfl:1"}
    # Each fetcher was asked for its own game, by its own raw id.
    assert got["asked"] == {"cfb": ["1"], "nfl": ["1"]}
    cfb = next(g for g in on if g["id"] == "cfb:1")
    assert "14" in cfb["text"] and "Q2" in cfb["text"] and "CFB" in cfb["text"]


def test_one_window_for_both_sports_and_keys_kept_apart(site):
    got = _run(site + "watch/", BOOT % "[]", [TOMORROW, READ])
    prime = got["sections"]["Prime time"]
    # The same raw id "7" in both files stays two games; the 8:25 NFL game
    # shares the 8:00 and 9:30 college games' window.
    assert {g["id"] for g in prime} == {"cfb:7", "cfb:8", "nfl:7"}
    nfl = next(g for g in prime if g["id"] == "nfl:7")
    assert "NFL" in nfl["text"] and "Your players: Steelers WR (WR)" in nfl["text"]
    assert "Your opponent’s: Browns TE (TE)" in nfl["text"]
    cfb = next(g for g in prime if g["id"] == "cfb:7")
    assert "Your players: Tulsa Back (RB)" in cfb["text"]


def test_stars_from_both_rankings_go_first(site):
    got = _run(site + "watch/", BOOT % '["cfb:166", "nfl:CLE"]', [TOMORROW, READ])
    prime = got["sections"]["Prime time"]
    assert {prime[0]["id"], prime[1]["id"]} == {"cfb:8", "nfl:7"}
    assert all("Your team" in g["text"] for g in prime[:2])


def test_the_tonight_card_lists_both_sports_in_kickoff_order(site):
    got = _run(site, "", ["(function(){var b=document.getElementById('gs-tonight');"
                          "return [b.hidden, b.innerText];})()"])
    assert got[0] is False
    assert "All 2 games" in got[1]
    assert got[1].index("Kent St") < got[1].index("Jets")


def test_the_tonight_card_stays_hidden_on_a_one_sport_day(tmp_path):
    (tmp_path / "cfb" / "watch").mkdir(parents=True)
    now = datetime.now(watch_page.ET)
    (tmp_path / "cfb" / "watch" / "games.json").write_text(json.dumps({"games": [
        _game("1", now.astimezone(timezone.utc), 30, "ESPN", "A", "B", "1", "2",
              watch_page.game_day(now))]}))
    (tmp_path / "index.html").write_text("<!doctype html><html><body>" + watch_all.teaser()
                                         + "</body></html>")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path))
    handler.log_message = lambda *a: None
    server = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        got = _run(f"http://127.0.0.1:{server.server_address[1]}/", "",
                   ["document.getElementById('gs-tonight').hidden"])
    finally:
        server.shutdown()
    assert got is True
