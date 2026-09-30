"""
The watch guide (cfb.site.watch): the day cut into kickoff windows, each
ranked by a watch score, with the reader's starred teams and fantasy players
and the live state of the games added in the browser.

The browser half runs the page's script in headless Chromium on a page served
over http, with the scoreboard proxy stubbed; skips without Chromium.
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

import pandas as pd
import pytest

from cfb.site import watch

CHROME = next((p for p in ("/usr/bin/chromium-browser", "/usr/bin/chromium",
                           "/usr/bin/google-chrome") if shutil.which(p)), None)
CDP = 9453


def test_windows_are_eastern_kickoffs():
    at = lambda s: watch.slot(pd.Timestamp(s))
    assert at("2026-10-03T16:00:00Z") == "early"          # noon ET
    assert at("2026-10-03T17:59:00Z") == "early"          # 1:59
    assert at("2026-10-03T18:00:00Z") == "afternoon"      # 2:00
    assert at("2026-10-03T22:00:00Z") == "prime"          # 6:00
    assert at("2026-10-04T01:29:00Z") == "prime"          # 9:29
    assert at("2026-10-04T02:30:00Z") == "late"           # 10:30
    assert watch.slot(pd.Timestamp("2026-10-03T16:00:00Z"), time_known=False) == "tba"
    assert [s[2] for s in watch._slot_hours()][:4] == [
        "before 2 ET", "2-6 ET", "6-9:30 ET", "from 9:30 ET"]


def test_the_score_is_espns_nudged_and_the_tags_say_why():
    base = {"mq": 80.0, "sp": -6.0, "hw": 0.62, "fw": 0.70, "hr": None, "ar": None}
    score, tags, fav = watch.judge(base)
    assert (score, tags, fav) == (80.0, ["Upset watch"], "h")     # the model gives the dog 38%
    # Both ranked and both in the playoff race: a quarter of the gap each.
    score, tags, _ = watch.judge({**base, "hr": 5, "ar": 12, "hpo": 40.0, "apo": 15.0})
    assert score == 90.0 and tags == ["Top 25 matchup", "Upset watch", "Playoff stakes"]
    assert watch.judge({**base, "mq": 99.0, "hr": 1, "ar": 2, "hpo": 90, "apo": 80})[0] <= 100
    # A line of a field goal or less is a toss-up rather than an upset watch.
    assert watch.judge({**base, "sp": 2.5})[1] == ["Toss-up"]
    assert watch.judge({**base, "sp": 2.5})[2] == "a"
    # A lopsided game: no tags; the leader's playoff odds alone are not stakes.
    lop = {**base, "sp": -24.5, "hw": 0.95, "fw": 0.93, "hpo": 60.0, "apo": 0.1}
    assert watch.judge(lop)[1] == []
    # No book line: our margin stands in; no ESPN quality either: closeness.
    score, tags, fav = watch.judge({"mq": None, "sp": None, "margin": 7.0, "hw": 0.7})
    assert fav == "h" and score == pytest.approx(50 * (1 - 7 / 28), abs=0.1)


def test_rosters_carry_school_ids_and_who_starts(monkeypatch):
    monkeypatch.setattr(watch.yahoo, "archived_weeks", lambda: [4, 5])
    monkeypatch.setattr(watch.yahoo, "week_matchups", lambda w: {"rosters": {"t.1": [
        {"player": "Josh Hoover", "pos": "QB", "team_full": "Indiana Hoosiers", "slot": "QB"},
        {"player": "Bench Guy", "pos": "WR", "team_full": "Indiana Hoosiers", "slot": "BN"},
        {"player": "A Kicker", "pos": "K", "team_full": "Indiana Hoosiers", "slot": "K"},
        {"player": "Nowhere", "pos": "RB", "team_full": "Unknown U", "slot": "RB"}]}})
    monkeypatch.setattr(watch.yahoo, "league", lambda: {"teams": [{"team_key": "t.1", "name": "CCAM"}]})
    monkeypatch.setattr(watch.schools_mod, "yahoo_school", lambda: {"Indiana Hoosiers": "Indiana"})
    monkeypatch.setattr(watch.schools_mod, "espn_ids", lambda: {"Indiana": 84})
    assert watch.rosters() == {"t.1": {"n": "CCAM", "p": [["Josh Hoover", "QB", "84", True],
                                                         ["Bench Guy", "WR", "84", False]]}}


def test_names_cannot_close_the_data_block():
    html = watch.body({"season": 2026, "generated": "2026-10-03T08:00-04:00", "slots": [],
                       "games": [], "rosters": {"t": {"n": "</script><b>x", "p": []}}})
    blob = html[html.index("id='wg-data'>"):]
    assert "</script><b>" not in blob[:blob.index("</script>")]


# --------------------------------------------------------------------------- #
# In the browser
# --------------------------------------------------------------------------- #

def _game(gid, kick, home, away, score, tags=(), fav="h", slot="early", hid=None, aid=None):
    return {"id": gid, "wk": 5, "st": 2, "ko": kick.strftime("%Y-%m-%dT%H:%M:%SZ"), "tk": True,
            "day": kick.astimezone(watch.ET).strftime("%Y-%m-%d"), "slot": slot, "tv": "ABC",
            "note": "", "n": False,
            "h": {"id": hid or home.lower(), "nm": home, "rk": None, "sc": 0, "pr": 28.0},
            "a": {"id": aid or away.lower(), "nm": away, "rk": None, "sc": 0, "pr": 21.0},
            "state": "pre", "hw": 0.7, "fw": 0.7, "sp": -6.5, "mq": score, "score": score,
            "tags": list(tags), "fav": fav}


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    """Today's games: three in the early window (one of them on now), one in
    prime time. The page's day is today, whatever today is."""
    now = datetime.now(timezone.utc)
    early = now - timedelta(minutes=60)
    later = now + timedelta(hours=3)
    games = [_game("1", early, "Alabama", "Auburn", 90.0, ["Top 25 matchup"]),
             _game("2", early, "Iowa", "Purdue", 60.0),
             _game("3", early, "Kansas", "Baylor", 50.0),
             _game("4", later, "Utah", "BYU", 70.0, slot="prime")]
    for g in games[:3]:
        g["day"] = games[3]["day"] = now.astimezone(watch.ET).strftime("%Y-%m-%d")
    data = {"season": 2026, "generated": now.astimezone(watch.ET).isoformat(timespec="minutes"),
            "slots": watch._slot_hours(), "games": games,
            "rosters": {"t.1": {"n": "CCAM", "p": [["Kansas Back", "RB", "kansas", True],
                                                   ["Utah End", "TE", "utah", False]]}}}
    root = tmp_path_factory.mktemp("watch")
    (root / "index.html").write_text("<!doctype html><html><body>" + watch.body(data) + "</body></html>")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a: None
    server = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()


# The scoreboard proxy, stubbed: Iowa 20-17 Purdue in the 4th, the rest not
# started. Stars and the fantasy team set before the page's script runs.
BOOT = """
localStorage.setItem('gs:favorites', JSON.stringify(%s));
localStorage.setItem('cfbMyTeam', 't.1');
window.fetch=function(url){
  var board={events:[{id:'2',competitions:[{status:{period:4,type:{state:'in',shortDetail:'4th 3:12'}},
    competitors:[{homeAway:'home',score:'20'},{homeAway:'away',score:'17'}]}]}]};
  return Promise.resolve({ok:true,json:function(){ return Promise.resolve(board); }});
};
"""

READ = """(function(){
  var out={};
  document.querySelectorAll('#wg-host h3').forEach(function(h){
    var list=h.nextElementSibling;
    out[h.firstChild.textContent.trim()]=Array.prototype.map.call(list.querySelectorAll('a.wg-g'),
      function(a){ return {id:a.getAttribute('data-gid'), top:a.classList.contains('top'),
        text:a.textContent}; });
  });
  return out;
})()"""


def _run(url: str, boot: str, expression: str):
    import websockets
    subprocess.run(["fuser", "-k", f"{CDP}/tcp"], capture_output=True)
    proc = subprocess.Popen([CHROME, "--headless=new", "--no-sandbox", "--disable-gpu",
                             f"--remote-debugging-port={CDP}", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
                await asyncio.sleep(2)
                r = await send("Runtime.evaluate", {"expression": expression, "returnByValue": True})
                return r["result"].get("value")
        return asyncio.run(go())
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")
def test_the_day_on_a_phone(site):
    """No stars: the game on now leads, marked close late; the early window
    is what is left of it by score; the fantasy team's players are named."""
    got = _run(site, BOOT % "[]", READ)
    assert [g["id"] for g in got["On now"]] == ["2"]
    assert "Close late" in got["On now"][0]["text"] and "Live" in got["On now"][0]["text"]
    early = got["Early"]
    assert [g["id"] for g in early] == ["1", "3"] and early[0]["top"]
    # Kansas's back starts for the reader's team: named, and worth a nudge.
    assert "Your players: Kansas Back (RB)" in early[1]["text"]
    assert "Utah End (TE, bench)" in got["Prime time"][0]["text"]


@pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")
def test_a_starred_team_goes_first_in_its_window(site):
    got = _run(site, BOOT % '["cfb:baylor"]', READ)
    early = got["Early"]
    assert [g["id"] for g in early] == ["3", "1"]
    assert "Your team" in early[0]["text"]
