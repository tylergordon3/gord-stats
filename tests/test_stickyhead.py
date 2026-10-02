"""
Column names that stay in view (docs/assets/js/stickyhead.js): a long table
in a sideways scroller gets a copy of its header row under the pinned bar once
the real one scrolls away, with the real widths, slid with the scroller, and a
tap on a copied header sorts the real table.

Runs the script in headless Chromium on a page served over http; skips
without Chromium.
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

import pytest

from conftest import ROOT
from browser_util import launch, reap

CHROME = next((p for p in ("/usr/bin/chromium-browser", "/usr/bin/chromium",
                           "/usr/bin/google-chrome") if shutil.which(p)), None)
CDP = 9454

ROWS = "".join(f"<tr><td>Team {i}</td><td>{i}</td><td>{100 - i}</td><td>x</td></tr>" for i in range(60))
PAGE = f"""<!doctype html><html><head><meta name=viewport content="width=device-width">
<style>body{{margin:0;font:16px sans-serif}}
.pin-bar{{position:sticky;top:0;height:50px;background:#fff;z-index:20}}
.power-wrap{{overflow-x:auto}} table{{border-collapse:collapse;width:700px}}
td,th{{padding:8px;border:1px solid #ccc}}
.gs-sticky-head{{position:fixed;z-index:19;overflow:hidden}}</style></head><body>
<div class=pin-bar>controls</div><p style="height:300px">intro</p>
<div class=power-wrap><table class=power><thead><tr><th id=t>Team</th><th>Rank</th><th>Rating</th>
<th>Other</th></tr></thead><tbody>{ROWS}</tbody></table></div>
<div style="height:2000px"></div>
<script>document.getElementById('t').addEventListener('click',function(){{window.sorted=(window.sorted||0)+1;}});</script>
<script>__JS__</script></body></html>"""


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    root = tmp_path_factory.mktemp("sticky")
    js = (ROOT / "docs" / "assets" / "js" / "stickyhead.js").read_text()
    (root / "index.html").write_text(PAGE.replace("__JS__", js))
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a: None
    server = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()


def _run(url: str, expression: str):
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
                await send("Emulation.setDeviceMetricsOverride",
                           {"width": 390, "height": 800, "deviceScaleFactor": 1, "mobile": True})
                await send("Page.enable")
                await send("Page.navigate", {"url": url})
                await asyncio.sleep(1.5)
                r = await send("Runtime.evaluate", {"expression": expression, "returnByValue": True,
                                                    "awaitPromise": True})
                return r["result"].get("value")
        return asyncio.run(go())
    finally:
        proc.terminate()
        reap(proc)


@pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")
def test_the_header_follows_a_long_table(site):
    got = _run(site, """(async function(){
      function wait(){ return new Promise(function(r){ setTimeout(r,120); }); }
      var box=document.querySelector('.gs-sticky-head');
      var before=box&&box.hidden;
      window.scrollTo(0,900); await wait();
      var shown=!box.hidden, top=box.getBoundingClientRect().top;
      var real=document.querySelectorAll('.power-wrap > table thead th'), copy=box.querySelectorAll('th');
      var widths=[].map.call(real,function(t,i){ return Math.round(t.getBoundingClientRect().width)
        ===Math.round(copy[i].getBoundingClientRect().width); });
      document.querySelector('.power-wrap').scrollLeft=120; await wait();
      var slid=box.scrollLeft;
      copy[0].click(); await wait();
      window.scrollTo(0,0); await wait();
      return JSON.stringify({before:before, shown:shown, top:top, widths:widths, slid:slid,
              sorted:window.sorted||0, after:box.hidden});
    })()""")
    got = json.loads(got)
    assert got["before"] is True                   # the real header is in view
    assert got["shown"] and got["top"] == 50       # under the 50px pinned bar
    assert all(got["widths"]) and len(got["widths"]) == 4
    assert got["slid"] == 120                      # scrolled with the table's scroller
    assert got["sorted"] == 1                       # the tap reached the real header
    assert got["after"] is True
