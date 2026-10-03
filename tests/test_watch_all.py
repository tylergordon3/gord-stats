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
    # Football's two, whatever basketball file this checkout holds.
    (root / "watch" / "index.html").write_text(
        "<!doctype html><html><body>" + expand(watch_all.body(watch_all.SPORTS)) + "</body></html>")
    (root / "index.html").write_text(
        "<!doctype html><html><body>" + watch_all.teaser(watch_all.SPORTS, docs=root)
        + "</body></html>")
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
    (tmp_path / "index.html").write_text("<!doctype html><html><body>"
                                         + watch_all.teaser(watch_all.SPORTS, docs=tmp_path)
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


# --------------------------------------------------------------------------- #
# College basketball (cbb.render.render_watch's games.json)
# --------------------------------------------------------------------------- #

def test_before_the_season_the_pages_are_footballs_alone(tmp_path, monkeypatch):
    """No basketball file, an empty one, or one with only past days: the
    page and the card fetch nothing more and say nothing of basketball."""
    from cbb.render import render_watch
    monkeypatch.setattr(render_watch, "OUT", tmp_path / "cbb" / "watch" / "index.html")
    games = tmp_path / "cbb" / "watch" / "games.json"
    today = watch_page.game_day(datetime.now(watch_page.ET))
    yesterday = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    for content in (None, {"games": []}, {"games": [{"id": "1", "day": yesterday}]}, "{oops"):
        if content is not None:
            games.parent.mkdir(parents=True, exist_ok=True)
            games.write_text(content if isinstance(content, str) else json.dumps(content))
        assert watch_all.sports() == watch_all.SPORTS
        body, card = watch_all.body(), watch_all.teaser()
        for page in (body, card):
            assert "/cbb/watch/games.json" not in page and "GSWatchLive.cbb=" not in page
        assert "College and pro" in watch_all._words(watch_all.sports())["subtitle"]
    games.write_text(json.dumps({"games": [{"id": "1", "day": today}]}))
    assert watch_all.sports() == watch_all.SPORTS + [watch_all.CBB]
    assert "/cbb/watch/games.json" in watch_all.teaser() and "GSWatchLive.cbb=" in watch_all.body()


def _hoop(gid, ko, score, home, away, hk, ak, day=None, league="men", state="pre"):
    g = _game(gid, ko, score, "", home, away, hk, ak, day)
    g.update({"league": league, "badge": "WCBB" if league == "women" else "", "state": state,
              "lt": "", "sp": None})
    return g


@pytest.fixture(scope="module")
def hoops_site(tmp_path_factory):
    """Today: a college football game on now, a basketball game that tipped
    half an hour ago and one six hours ago - both "pre" in a file built this
    morning. Tomorrow evening: basketball at 7:00 (men's, id "7", the same id
    as football's) and 9:00 (women's), college football at 8:00, the NFL at 8:25."""
    root = tmp_path_factory.mktemp("watchhoops")
    now = datetime.now(watch_page.ET)
    today = watch_page.game_day(now)
    tomorrow = (datetime.strptime(today, "%Y-%m-%d").replace(tzinfo=watch_page.ET)
                + timedelta(days=1))

    def at(h, m=0):
        return tomorrow.replace(hour=h, minute=m).astimezone(timezone.utc)
    gen = (now - timedelta(hours=7)).isoformat(timespec="minutes")
    cfb = {"season": 2026, "generated": gen, "games": [
        _game("1", now - timedelta(minutes=40), 30, "ESPN2", "Akron", "Kent St", "1", "2", today),
        _game("7", at(20), 40, "ESPN", "Tulsa", "North Texas", "202", "249")]}
    nfl = {"season": 2026, "generated": gen, "games": [
        _game("7", at(20, 25), 37, "Prime Video", "Browns", "Steelers", "CLE", "PIT")]}
    cbb = {"season": 2027, "generated": gen, "games": [
        _hoop("1", now - timedelta(minutes=30), 55, "Purdue", "Iowa", "cbb-men:purdue",
              "cbb-men:iowa", today),
        _hoop("2", now - timedelta(hours=6), 45, "Gonzaga", "Portland", "cbb-men:gonzaga",
              "cbb-men:portland", today),
        # No tip time yet (theScore's `tba`): the guide's Time TBA, never the card.
        dict(_hoop("3", now - timedelta(hours=1), 99, "Kansas", "Duke", "cbb-men:kansas",
                   "cbb-men:duke", today), tk=False),
        _hoop("7", at(19), 60, "Duke", "North Carolina", "cbb-men:duke",
              "cbb-men:north-carolina"),
        _hoop("9", at(21), 50, "South Carolina", "LSU", "cbb-women:south-carolina",
              "cbb-women:lsu", league="women")]}
    for sport, data in (("cfb", cfb), ("nfl", nfl), ("cbb", cbb)):
        (root / sport / "watch").mkdir(parents=True)
        (root / sport / "watch" / "games.json").write_text(json.dumps(data))
    on = watch_all.SPORTS + [watch_all.CBB]
    (root / "watch").mkdir()
    (root / "watch" / "index.html").write_text(
        "<!doctype html><html><body>" + expand(watch_all.body(on)) + "</body></html>")
    (root / "index.html").write_text(
        "<!doctype html><html><body>" + watch_all.teaser(on, docs=root) + "</body></html>")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a: None
    server = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()


# Basketball's live fetcher answers from "the feed": Purdue-Iowa under way,
# Gonzaga-Portland over - and records every id (with its league) it is asked.
BOOT_HOOPS = BOOT + """
window.__hoops = [];
var FEED = {'1': {state:'in', detail:'2nd 4:10', period:2, home:61, away:58,
                  late:true, ot:false, second:true},
            '2': {state:'post', detail:'', period:2, home:80, away:62}};
Object.defineProperty(stub, 'cbb', {writable:false, value:function(g){
  var out = {};       // as GSWatchLive.cbb does: only the games asked about
  g.forEach(function(x){ __hoops.push(x.league+':'+x.id); if(FEED[x.id]) out[x.id] = FEED[x.id]; });
  return Promise.resolve(out); }});
"""

BOOT_HEIGHT = """
document.addEventListener('DOMContentLoaded', function(){
  var b=document.getElementById('gs-tonight'); window.__h0=b&&!b.hidden?b.offsetHeight:0; });
"""

READ_FINAL = """(function(){
  var d=document.querySelector('#wg-host details[data-k=final]');
  return d?Array.prototype.map.call(d.querySelectorAll('a.wg-g'), function(a){
    return {id:a.getAttribute('data-gid'), text:a.textContent}; }):[];
})()"""


def test_basketball_merges_in_with_its_own_keys_and_badges(hoops_site):
    got = _run(hoops_site + "watch/", BOOT_HOOPS % '["cbb-men:duke"]',
               [TOMORROW, READ])
    prime = got["sections"]["Prime time"]
    ids = [g["id"] for g in prime]
    # The id "7" three times over, three games; the starred Duke game first.
    assert set(ids) == {"cbb:7", "cfb:7", "nfl:7", "cbb:9"} and ids[0] == "cbb:7"
    text = {g["id"]: g["text"] for g in prime}
    assert "Your team" in text["cbb:7"] and "CBB" in text["cbb:7"]
    assert "WCBB" in text["cbb:9"] and "Your team" not in text["cbb:9"]


def test_basketball_live_scores_and_states_come_from_its_feed(hoops_site):
    got = _run(hoops_site + "watch/", BOOT_HOOPS % "[]",
               [READ, "window.__hoops", READ_FINAL], wait=3)
    # The last value is the Final fold: the game six hours old was "pre" in
    # the morning's file and is over by the feed.
    assert [g["id"] for g in got] == ["cbb:2"] and "80" in got[0]["text"]


def test_basketball_on_now_carries_the_feeds_score(hoops_site):
    got = _run(hoops_site + "watch/", BOOT_HOOPS % "[]", [READ], wait=3)
    on = {g["id"]: g["text"] for g in got["sections"]["On now"]}
    assert set(on) == {"cfb:1", "cbb:1"}
    assert "61" in on["cbb:1"] and "Close late" in on["cbb:1"]
    asked = _run(hoops_site + "watch/", BOOT_HOOPS % "[]", ["window.__hoops"], wait=3)
    # By raw id with its league - never "cbb:1", never a football game.
    assert asked and set(asked) <= {"men:1", "men:2", "men:3", "men:7", "women:9"} and "men:1" in asked


def test_the_tonight_card_takes_basketballs_best_beside_football(hoops_site):
    got = _run(hoops_site, "", ["(function(){var b=document.getElementById('gs-tonight');"
                                "return [b.hidden, b.innerText];})()"])
    assert got[0] is False
    # College football's game and basketball's on now; the one that tipped six
    # hours ago is over, whatever the morning's file says.
    assert "Purdue" in got[1] and "Gonzaga" not in got[1] and "Kent St" in got[1]
    assert "Kansas" not in got[1], "a game with no time yet is not tonight's for sure"
    assert "All 2 games, football and basketball" in got[1]


# The real fetcher (render_watch.LIVE_JS), on a stubbed Worker: football's
# fetchers stubbed as above, basketball's left to the page.
BOOT_FEED = """
localStorage.setItem('gs:favorites', '[]');
window.__feedCalls = 0;
var stub = {};
Object.defineProperty(stub, 'cfb', {writable:false, value:function(){ return Promise.resolve({}); }});
Object.defineProperty(stub, 'nfl', {writable:false, value:function(){ return Promise.resolve({}); }});
Object.defineProperty(window, 'GSWatchLive', {configurable:true,
  get:function(){ return stub; }, set:function(){}});
var realFetch = window.fetch;
window.fetch = function(url){
  if(!/workers\\.dev/.test(String(url))) return realFetch.apply(this, arguments);
  __feedCalls++;
  var body = {generated:'x', leagues:{men:{
    '1': {status:'in_progress', period:'2nd', clock:'3:00', home_score:61, away_score:58},
    '2': {status:'final', period:'2nd', clock:'0:00', home_score:80, away_score:62}}, women:{}}};
  return new Promise(function(ok){ setTimeout(function(){
    ok({ok:true, json:function(){ return Promise.resolve(body); }}); }, 300); });
};
"""


def test_the_worker_is_read_once_for_the_states_and_the_scores(hoops_site):
    got = _run(hoops_site + "watch/", BOOT_FEED,
               [READ, READ_FINAL, "window.__feedCalls"], wait=3)
    # One request answers both the refresh and the engine's first poll.
    assert got == 1
    page = _run(hoops_site + "watch/", BOOT_FEED, [READ], wait=3)
    on = {g["id"]: g["text"] for g in page["sections"]["On now"]}
    assert "61" in on["cbb:1"] and "2nd 3:00" in on["cbb:1"]
    final = _run(hoops_site + "watch/", BOOT_FEED, [READ_FINAL], wait=3)
    assert [g["id"] for g in final] == ["cbb:2"]


def test_the_tonight_card_comes_with_the_page_and_stays_put(hoops_site):
    """Drawn by the build on a night two sports play, so Home does not jump
    when the script runs - in basketball season that is most nights."""
    got = _run(hoops_site, BOOT_HEIGHT, ["[window.__h0, document.getElementById('gs-tonight')"
                                         ".offsetHeight, document.getElementById('gs-tonight').hidden]"])
    assert got[0] > 0 and got[0] == got[1] and got[2] is False


def test_tonight_is_drawn_from_the_files_with_names_kept_from_liquid(tmp_path):
    now = datetime.now(watch_page.ET)
    today = watch_page.game_day(now)
    for sport, games in (("cfb", [_game("1", now + timedelta(hours=1), 30, "ESPN", "{{x}}",
                                        "B", "1", "2", today)]),
                         ("nfl", [_game("2", now + timedelta(hours=2), 30, "NBC", "C", "D",
                                        "C", "D", today)])):
        (tmp_path / sport / "watch").mkdir(parents=True)
        (tmp_path / sport / "watch" / "games.json").write_text(json.dumps({"games": games}))
    card = watch_all.tonight(watch_all.SPORTS, now, tmp_path)
    assert "All 2 games, college and pro" in card and card.index("B at") < card.index("D at C")
    assert "{{" not in card and "&#123;&#123;x&#125;&#125;" in card
    page = watch_all.teaser(watch_all.SPORTS, now, tmp_path)
    assert 'id="gs-tonight">' in page                                   # not hidden
    (tmp_path / "nfl" / "watch" / "games.json").write_text(json.dumps({"games": []}))
    assert watch_all.tonight(watch_all.SPORTS, now, tmp_path) == ""
    assert 'id="gs-tonight" hidden>' in watch_all.teaser(watch_all.SPORTS, now, tmp_path)
