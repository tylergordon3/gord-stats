"""
The NFL watch guide (nfl.site.watch): the week's games in the shared engine's
shape (gordstats.watch_page), the reader's Sleeper starters and their
opponent's in each game, and live scores read from ESPN in the browser.

The browser half runs the page in headless Chromium with ESPN's scoreboard
stubbed; skips without Chromium.
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

from gordstats import watch_page
from nfl.site import watch
from browser_util import reap

CHROME = next((p for p in ("/usr/bin/chromium-browser", "/usr/bin/chromium",
                           "/usr/bin/google-chrome") if shutil.which(p)), None)
CDP = 9456


def test_windows_are_eastern_kickoffs():
    at = lambda s: watch.slot(pd.Timestamp(s))
    assert at("2026-10-04T13:30:00Z") == "morning"        # London, 9:30 ET
    assert at("2026-10-04T17:00:00Z") == "early"          # 1:00
    assert at("2026-10-04T20:25:00Z") == "late"           # 4:25
    assert at("2026-10-05T00:20:00Z") == "prime"          # Sunday night
    assert at("2026-10-02T00:15:00Z") == "prime"          # Thursday night


def test_winning_teams_nudge_only_with_games_played():
    assert watch._winning("3-1") and not watch._winning("1-0") and not watch._winning("2-2")
    score, tags, fav = watch.judge({"mq": 80.0, "sp": -2.5, "hw": 0.55, "fw": 0.5,
                                    "hrec": "3-1", "arec": "2-1"})
    assert score == 85.0 and tags == ["Toss-up", "Winning teams"] and fav == "h"
    assert watch.judge({"mq": 80.0, "sp": -2.5, "hrec": "3-1", "arec": "1-2"})[0] == 80.0


def _frame(now):
    kick = pd.Timestamp(now).tz_convert("UTC") + pd.Timedelta(days=2)
    return pd.DataFrame([{
        "game_id": "401", "date": kick, "home": "Commanders", "away": "Cowboys",
        "home_id": "28", "away_id": "6", "home_abbr": "WSH", "away_abbr": "DAL",
        "home_record": "3-1", "away_record": "2-2", "home_score": None, "away_score": None,
        "pred_home": 24.0, "pred_away": 21.0, "pred_margin": 3.0, "home_win_prob": 0.6,
        "book_spread": -2.5, "neutral": False, "venue": "", "tv": "FOX", "state": "pre"}])


def test_games_are_in_the_engines_shape(monkeypatch):
    now = datetime(2026, 10, 1, 12, tzinfo=watch.ET)
    monkeypatch.setattr(watch.predict, "season", lambda: (_frame(now), None, None))
    g = watch.games(now, espn={"401": {"mq": 70.0, "fw": 0.58}})[0]
    assert g["h"]["k"] == "WAS" and g["a"]["k"] == "DAL"     # Sleeper's spelling
    assert "/nfl/500/wsh.png&w=80" in g["h"]["lg"]
    assert g["h"]["rec"] == "3-1" and g["mq"] == 70.0 and g["tags"] == ["Toss-up"]
    assert g["day"] == "2026-10-03"


def test_rosters_name_starters_and_the_opponent(monkeypatch, tmp_path):
    from fantasy import paths as fpaths
    from fantasy.league import matchups as mdata
    pd.DataFrame([{"sleeper_id": "1", "full_name": "Dak Prescott", "position": "QB", "team": "DAL"},
                  {"sleeper_id": "2", "full_name": "Terry McLaurin", "position": "WR", "team": "WAS"}]
                 ).to_parquet(tmp_path / "sleeper.parquet")
    monkeypatch.setattr(fpaths, "PLAYERS_DIR", tmp_path)
    monkeypatch.setattr(mdata, "current_week", lambda year=None: 5)
    monkeypatch.setattr(mdata, "sleeper_matchups", lambda week, league_id=None: [
        {"roster_id": 1, "matchup_id": 3, "starters": ["1"], "players": ["1", "DAL"]},
        {"roster_id": 2, "matchup_id": 3, "starters": ["2"], "players": ["2", "9"]}])
    monkeypatch.setattr(mdata, "teams", lambda league_id=None: {1: {"manager": "Tyler"},
                                                                2: {"manager": "George"}})
    got = watch.rosters()
    assert got["1"] == {"n": "Tyler", "opp": "2",
                        "p": [["Dak Prescott", "QB", "DAL", True], ["DAL D/ST", "DEF", "DAL", False]]}
    assert got["2"]["opp"] == "1" and got["2"]["p"] == [["Terry McLaurin", "WR", "WAS", True]]


# --------------------------------------------------------------------------- #
# In the browser
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def site(tmp_path_factory):
    now = datetime.now(timezone.utc)
    day = now.astimezone(watch.ET).strftime("%Y-%m-%d")

    def game(gid, kick, home, away, hk, ak, score, slot="early"):
        return {"id": gid, "ko": kick.strftime("%Y-%m-%dT%H:%M:%SZ"), "tk": True, "day": day,
                "slot": slot, "tv": "FOX", "n": False, "note": "", "state": "pre",
                "h": {"id": hk, "nm": home, "k": hk, "lg": "", "rec": "2-1", "sc": 0, "pr": 24.0},
                "a": {"id": ak, "nm": away, "k": ak, "lg": "", "rec": "1-2", "sc": 0, "pr": 20.0},
                "hw": 0.6, "fw": 0.6, "sp": -3.0, "mq": score, "score": score, "tags": [], "fav": "h"}
    earlier = now - timedelta(minutes=90)
    data = {"season": 2026, "generated": now.astimezone(watch.ET).isoformat(timespec="minutes"),
            "slots": watch_page.slot_hours(watch.SLOTS),
            "games": [game("1", earlier, "Bills", "Patriots", "BUF", "NE", 80.0),
                      game("2", earlier, "Bears", "Jets", "CHI", "NYJ", 50.0),
                      game("3", earlier, "Texans", "Cowboys", "HOU", "DAL", 60.0)],
            "rosters": {"1": {"n": "Tyler", "opp": "2", "p": [["Dak Prescott", "QB", "DAL", True]]},
                        "2": {"n": "George", "opp": "1", "p": [["Caleb Williams", "QB", "CHI", True]]}}}
    root = tmp_path_factory.mktemp("nflwatch")
    (root / "index.html").write_text("<!doctype html><html><body>" + watch.body(data) + "</body></html>")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a: None
    server = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()


# ESPN's scoreboard, stubbed: Bears 17, Jets 20 with 3:12 left in the fourth -
# the underdog ahead, and close late.
BOOT = """
localStorage.setItem('nflMyTeam', '1');
window.fetch=function(url){
  var board={events:[{id:'2',competitions:[{status:{period:4,type:{state:'in',shortDetail:'4th 3:12'}},
    competitors:[{homeAway:'home',score:'17'},{homeAway:'away',score:'20'}]}]}]};
  window.asked=String(url);
  return Promise.resolve({ok:true,json:function(){ return Promise.resolve(board); }});
};
"""

READ = """JSON.stringify((function(){
  var out={asked:window.asked};
  document.querySelectorAll('#wg-host h3').forEach(function(h){
    out[h.firstChild.textContent.trim()]=Array.prototype.map.call(h.nextElementSibling.querySelectorAll('a.wg-g'),
      function(a){ return {id:a.getAttribute('data-gid'), text:a.textContent}; });
  });
  return out;
})())"""


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
        reap(proc)


@pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")
def test_sunday_with_a_team_picked(site):
    got = json.loads(_run(site, BOOT, READ))
    assert got["asked"].startswith("https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates=")
    on = got["On now"]
    assert [g["id"] for g in on] == ["2"]
    assert "Close late" in on[0]["text"] and "Upset alert" in on[0]["text"]
    # The opponent's quarterback plays in it: named as theirs.
    assert "George’s: Caleb Williams (QB)" in on[0]["text"]
    early = got["Early"]
    # The reader's quarterback lifts Cowboys-Texans (60) over nothing else;
    # Bills-Patriots (80) still leads on its own.
    assert [g["id"] for g in early] == ["1", "3"]
    assert "Your players: Dak Prescott (QB)" in early[1]["text"]
