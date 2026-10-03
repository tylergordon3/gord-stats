"""
The watch guide's quadbox (gordstats.watch_page): four games for one screen
per window, the best with the sound, never two on one broadcast channel, and
- while games are on - boxes that stay put until a game ends, turns into a
blowout or is clearly beaten.

Run on the engine alone in headless Chromium, with a stubbed live feed that
the test moves on between polls.
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

from gordstats import watch_page
from gordstats.js_assets import expand
from browser_util import launch, reap

CHROME = next((p for p in ("/usr/bin/chromium-browser", "/usr/bin/chromium",
                           "/usr/bin/google-chrome") if shutil.which(p)), None)
pytestmark = pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")
CDP = 9483


def _game(gid, kick, score, tv, slot, home=None, away=None):
    return {"id": gid, "ko": kick.strftime("%Y-%m-%dT%H:%M:%SZ"), "tk": True,
            "day": kick.astimezone(watch_page.ET).strftime("%Y-%m-%d"), "slot": slot,
            "tv": tv, "note": "", "n": False, "state": "pre", "score": score, "tags": [],
            "fav": "h", "hw": 0.6, "sp": -3.0,
            "h": {"id": f"h{gid}", "nm": home or f"Home {gid}", "rk": None, "sc": 0},
            "a": {"id": f"a{gid}", "nm": away or f"Away {gid}", "rk": None, "sc": 0}}


@pytest.fixture(scope="module")
def page(tmp_path_factory):
    """Today: six games in a window later on, five on now. The kickoffs are
    placed so both windows are today in Eastern time."""
    now = datetime.now(timezone.utc)
    # Both windows must fall on today's Eastern date: CI failed at 23:59 ET
    # ("Later" was tomorrow) and at 01:07 ET ("On now" was yesterday).
    start = now.astimezone(watch_page.ET).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    if now - start < timedelta(minutes=3) or end - now < timedelta(minutes=3):
        pytest.skip("too close to midnight Eastern for both windows to be today")
    on = max(now - timedelta(minutes=70), start + timedelta(minutes=1))
    later = min(now + timedelta(minutes=50), end - timedelta(minutes=1))
    upcoming = [_game("u1", later, 90, "ABC", "later"), _game("u2", later, 85, "ABC", "later"),
                _game("u3", later, 80, "ESPN", "later"), _game("u4", later, 70, "ESPN+", "later"),
                _game("u5", later, 60, "ESPN+", "later"), _game("u6", later, 50, "FOX", "later")]
    live = [_game(f"n{i}", on, 80 - 5 * i, tv, "now")
            for i, tv in enumerate(["CBS", "ESPN2", "FS1", "BTN", "SECN"], start=1)]
    data = {"generated": now.astimezone(watch_page.ET).isoformat(timespec="minutes"),
            "slots": [["now", "Earlier", "on now"], ["later", "Later", "tonight"]],
            "games": live + upcoming}
    # The feed: phase 1 every game close in the third; phase 2 game n2 is 35-7.
    adapter = """<script>
    window.__phase = 1;
    window.W = GSWatch(JSON.parse(document.getElementById('wg-data').textContent), {
      every: 250, blowout: 21,
      live: function(games){
        var out = {};
        games.forEach(function(g){
          var blow = window.__phase === 2 && g.id === 'n2';
          out[g.id] = {state:'in', detail:'3rd 8:00', period:3,
                       home: blow ? 35 : 14, away: blow ? 7 : 10};
        });
        return Promise.resolve(out);
      }
    });
    </script>"""
    root = tmp_path_factory.mktemp("quad")
    (root / "index.html").write_text(
        "<!doctype html><html><body>"
        "<script>localStorage.setItem('gsWatchView','quad');</script>"
        + expand(watch_page.body(data, adapter, "how", "/x/", "x")) + "</body></html>")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a: None
    server = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()


READ = """(function(){
  var out={};
  document.querySelectorAll('#wg-host h3').forEach(function(h){
    var box=h.nextElementSibling, bench=box&&box.nextElementSibling;
    out[h.firstChild.textContent.trim()]={
      grid: box.classList.contains('wg-quad'),
      tiles: Array.prototype.map.call(box.querySelectorAll('a.wg-q'), function(a){
        return {id:a.getAttribute('data-gid'), sound:!!a.querySelector('.aud'),
                fresh:!!a.querySelector('.new'), ch:a.querySelector('.ch b').textContent};
      }),
      bench: bench&&bench.classList.contains('wg-bench')?bench.textContent:''};
  });
  return out;
})()"""


def _run(url, steps):
    """Navigate, then for each (js-before, wait seconds) read the guide."""
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
                await send("Page.navigate", {"url": url})
                await asyncio.sleep(1.5)
                out = []
                for js, wait in steps:
                    if js:
                        await send("Runtime.evaluate", {"expression": js})
                    await asyncio.sleep(wait)
                    r = await send("Runtime.evaluate", {"expression": READ, "returnByValue": True})
                    out.append(r["result"].get("value"))
                return out
        return asyncio.run(go())
    finally:
        proc.terminate()
        reap(proc)
        subprocess.run(["fuser", "-k", f"{CDP}/tcp"], capture_output=True)


def test_a_window_fills_four_boxes_one_game_per_channel(page):
    got = _run(page, [(None, 0.5)])[0]["Later"]
    assert got["grid"]
    ids = [t["id"] for t in got["tiles"]]
    # u2 is ABC like u1, so it waits; ESPN+ is streaming and can carry two.
    assert ids == ["u1", "u3", "u4", "u5"]
    assert [t["sound"] for t in got["tiles"]] == [True, False, False, False]
    assert "Away u2 at Home u2" in got["bench"] and "Away u6 at Home u6" in got["bench"]


def test_the_live_box_keeps_its_places_and_swaps_out_a_blowout(page):
    first, second = _run(page, [(None, 0.6), ("window.__phase = 2", 1.0)])
    before = [t["id"] for t in first["On now"]["tiles"]]
    after = [t["id"] for t in second["On now"]["tiles"]]
    assert before == ["n1", "n2", "n3", "n4"]
    # n2 is decided: n5 takes its box, and nobody else moves.
    assert after == ["n1", "n5", "n3", "n4"]
    assert [t["fresh"] for t in second["On now"]["tiles"]] == [False, True, False, False]
    # A decided game is nobody's swap-in.
    assert second["On now"]["bench"] == ""


def test_the_list_view_is_one_tap_away(page):
    got = _run(page, [("document.querySelector('button[data-view=list]').click()", 0.3)])[0]
    assert not got["Later"]["grid"]
