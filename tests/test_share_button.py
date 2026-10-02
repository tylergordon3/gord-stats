"""
The Share button (gordstats.share_button, docs/assets/js/share.js): the share
sheet with the page's address and line where a phone has one, a copied link
where it does not, and the address it shares absolute and the one asked for.

The browser half runs share.js in headless Chromium on a page served over
http (a share needs a real origin to make an address from); skips without
Chromium.
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
from gordstats import share_button
from browser_util import reap

CHROME = next((p for p in ("/usr/bin/chromium-browser", "/usr/bin/chromium",
                           "/usr/bin/google-chrome") if shutil.which(p)), None)
CDP = 9451


def test_the_button_carries_its_address_and_line_escaped():
    html = share_button.row("/fantasy/recap/week-3/", "Week 3: Team \"C's\" <b>won</b> & more")
    assert "class='gs-share-row'" in html and "class='gs-share'" in html
    assert "data-url='/fantasy/recap/week-3/'" in html
    assert "data-text='Week 3: Team &quot;C&#x27;s&quot; &lt;b&gt;won&lt;/b&gt; &amp; more'" in html
    assert "<b>" not in html
    assert "data-text" not in share_button.button("/x/")      # no line, no attribute


def test_the_script_is_on_every_page():
    layout = (ROOT / "docs" / "_layouts" / "default.html").read_text()
    assert "/assets/js/share.js" in layout


PAGE = """<!doctype html><html><head><title>NFL Week 3 Recap</title></head><body>
<p>filler</p>__BUTTON__<script>__JS__</script></body></html>"""


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    root = tmp_path_factory.mktemp("share")
    page = PAGE.replace("__BUTTON__", share_button.row("/fantasy/recap/week-3/", "Week 3: A won"))
    page = page.replace("__JS__", (ROOT / "docs" / "assets" / "js" / "share.js").read_text())
    (root / "index.html").write_text(page)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a: None
    server = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()


def _run(url: str, expression: str):
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
                await send("Page.navigate", {"url": url})
                await asyncio.sleep(1.5)
                r = await send("Runtime.evaluate", {"expression": expression,
                                                    "returnByValue": True, "awaitPromise": True})
                return r["result"].get("value")
        return asyncio.run(go())
    finally:
        proc.terminate()
        reap(proc)


@pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")
def test_a_tap_opens_the_share_sheet_or_copies_the_link(site):
    got = _run(site, """(async function(){
      var sheet=null;
      navigator.share=function(d){ sheet=d; return Promise.resolve(); };
      document.querySelector('.gs-share').click();
      await new Promise(function(r){ setTimeout(r,50); });
      // No share sheet (a desktop browser): the line and the address are copied.
      Object.defineProperty(navigator,'share',{value:undefined,configurable:true});
      var copied=null;
      Object.defineProperty(navigator,'clipboard',{configurable:true,
        value:{writeText:function(t){ copied=t; return Promise.resolve(); }}});
      var b=document.querySelector('.gs-share');
      b.click();
      await new Promise(function(r){ setTimeout(r,80); });
      return {sheet:sheet, copied:copied, label:b.textContent, done:b.classList.contains('done')};
    })()""")
    base = site.rstrip("/")
    assert got["sheet"] == {"title": "NFL Week 3 Recap", "text": "Week 3: A won",
                            "url": f"{base}/fantasy/recap/week-3/"}
    assert got["copied"] == f"Week 3: A won {base}/fantasy/recap/week-3/"
    assert got["label"] == "Link copied" and got["done"] is True
