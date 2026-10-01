"""
A league shared by link (gordstats.share_button, docs/assets/js/share.js,
gordstats.my_league): the Share button on a reader's page sends the address
with ?league=<id>; whoever opens it sees that league for the visit, without
their own saved league being touched unless they choose to keep it.

The browser half serves a page carrying the fantasy pages' head script, the
league bar, a reader-view Share button and a built one, with fetch stubbed so
nothing reaches Sleeper or ESPN. Headless Chromium over CDP (port 9475, the
page on 8815); skips where there is none (the Pi).
"""
import asyncio
import functools
import http.server
import json
import re
import shutil
import socketserver
import subprocess
import threading
import time
import urllib.request

import pytest

from conftest import ROOT
from gordstats import share_button

CHROME = next((p for p in ("/usr/bin/chromium-browser", "/usr/bin/chromium",
                           "/usr/bin/google-chrome") if shutil.which(p)), None)
CDP, HTTP = 9475, 8815
RAW = re.compile(r"\{%-?\s*(?:end)?raw\s*-?%\}")
browser_only = pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")

MINE, FRIEND = "1180208989471400011", "1180208989471400022"


def _site_id():
    from fantasy.config import LEAGUE_IDS
    return sorted(str(v) for v in LEAGUE_IDS.values())[0]


def test_a_league_button_says_so_and_a_reader_row_starts_hidden():
    assert "data-league='1'" in share_button.button("/x/", league=True)
    assert "data-league" not in share_button.button("/x/")
    row = share_button.league_row("/fantasy/power/", "{league} power rankings")
    assert "<div class='gs-share-row' hidden>" in row
    assert ".gs-share-row[hidden]{display:none}" in row, "custom.css's display:flex beats hidden"
    assert "data-text='{league} power rankings'" in row and "data-league='1'" in row
    # Shown before paint, by the rule every reader page uses.
    assert "h&&h.id&&!h.site" in row and "{% raw %}" in row


def _page():
    from fantasy.site import layout
    from gordstats import my_league
    # The site's stylesheet, for the rule that would show a hidden row.
    css = (ROOT / "docs" / "assets" / "css" / "custom.css").read_text()
    css = css[css.index(".gs-share-row {"):]
    css = css[:css.index("}") + 1]
    body = (layout.HEAD + my_league.bar()
            + share_button.league_row("/fantasy/matchups/", "{league}: week 5 matchups")
            + "<div id='built'>" + share_button.row("/fantasy/power/", "Power", league=True)
            + "</div><div id='recap'>" + share_button.row("/fantasy/recap/#week-3", "{league}",
                                                           league=True)
            + "</div>" + my_league.JS)
    share = (ROOT / "docs" / "assets" / "js" / "share.js").read_text()
    return ("<!doctype html><html><head><meta charset='utf-8'><title>Matchups</title>"
            "<style>" + css + "</style></head>"
            "<body>" + RAW.sub("", body) + "<script>" + share + "</script></body></html>")


def _league(name):
    return {"name": name, "season": "2026", "roster_positions": ["QB", "BN"],
            "scoring_settings": {"rec": 1}, "settings": {}}


FX = {}
for lid, name in ((MINE, "Mine League"), (FRIEND, "Friends League")):
    FX[f"/league/{lid}"] = _league(name)
    FX[f"/league/{lid}/rosters"] = [{"roster_id": 1, "owner_id": "u1", "players": []}]
    FX[f"/league/{lid}/users"] = [{"user_id": "u1", "display_name": "x",
                                   "metadata": {"team_name": "X"}}]

# Runs before the page's own scripts: `reset` starts the visit over, `own`
# is the league the recipient already has saved, and fetch is stubbed.
BOOT = r"""
(function(){
  var FX=__FX__, q=location.search;
  if(/[?&]reset=1/.test(q)){
    try{ localStorage.clear(); sessionStorage.clear(); }catch(e){}
    var own=(/[?&]own=([^&]+)/.exec(q)||[])[1];
    if(own) localStorage.setItem('gsSleeperLeague', JSON.stringify({id:own, name:'Mine League'}));
  }
  window.fetch=function(url){
    url=String(url);
    function reply(body, status){
      status=status||200;
      return Promise.resolve({ok:status===200, status:status,
        json:function(){ return Promise.resolve(JSON.parse(JSON.stringify(body))); }});
    }
    if(url.indexOf('/api/leagues')===0) return reply({signedIn:false});
    if(url.indexOf('/fantasy/')===0) return reply({});
    var s=/^https:\/\/api\.sleeper\.app\/v1(\/.*)$/.exec(url);
    if(s && FX[s[1]]!==undefined) return reply(FX[s[1]]);
    return reply(null, 404);
  };
  // The share sheet, kept to be read.
  navigator.share=function(d){ window.__shared=d; return Promise.resolve(); };
})();
""".replace("__FX__", json.dumps(FX))


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    root = tmp_path_factory.mktemp("share-league")
    (root / "index.html").write_text(_page(), encoding="utf-8")
    (root / "other.html").write_text(_page(), encoding="utf-8")

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    socketserver.TCPServer.allow_reuse_address = True
    subprocess.run(["fuser", "-k", f"{HTTP}/tcp"], capture_output=True)
    server = socketserver.TCPServer(("127.0.0.1", HTTP),
                                    functools.partial(Quiet, directory=str(root)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{HTTP}/"
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="module")
def chrome():
    subprocess.run(["fuser", "-k", f"{CDP}/tcp"], capture_output=True)
    proc = subprocess.Popen([CHROME, "--headless=new", "--no-sandbox", "--disable-gpu",
                             f"--remote-debugging-port={CDP}", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ws_url = None
    for _ in range(60):
        try:
            ws_url = next(t["webSocketDebuggerUrl"] for t in json.load(
                urllib.request.urlopen(f"http://127.0.0.1:{CDP}/json")) if t["type"] == "page")
            break
        except Exception:                                   # noqa: BLE001
            time.sleep(0.5)
    if ws_url is None:
        proc.terminate()
        raise RuntimeError("Chromium did not come up")
    yield ws_url
    proc.terminate()
    proc.wait(timeout=10)


def drive(ws_url, steps, timeout=15):
    """("go", url) navigates, ("wait", expr) polls until truthy, ("do", expr)
    runs, ("eval", expr) collects. Returns the values and any uncaught error."""
    import websockets

    async def go():
        async with websockets.connect(ws_url, max_size=None) as ws:
            n, errors = 0, []

            async def send(method, params=None):
                nonlocal n
                n += 1
                me = n
                await ws.send(json.dumps({"id": me, "method": method, "params": params or {}}))
                while True:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
                    if msg.get("method") == "Runtime.exceptionThrown":
                        d = msg["params"]["exceptionDetails"]
                        errors.append((d.get("exception") or {}).get("description") or d.get("text"))
                    if msg.get("id") == me:
                        return msg

            async def evaluate(expr, strict=True):
                r = await send("Runtime.evaluate", {"expression": expr, "returnByValue": True,
                                                    "awaitPromise": True})
                res = r.get("result") or {}
                if "error" in r or res.get("exceptionDetails"):
                    if strict:
                        raise AssertionError(json.dumps(r)[:1500])
                    return None
                return (res.get("result") or {}).get("value")

            added = await send("Page.addScriptToEvaluateOnNewDocument", {"source": BOOT})
            await send("Page.enable")
            await send("Runtime.enable")
            out = []
            for kind, expr in steps:
                if kind == "go":
                    await send("Page.navigate", {"url": expr})
                    await asyncio.sleep(0.3)
                elif kind == "wait":
                    deadline = time.time() + timeout
                    while not await evaluate(expr, strict=False):
                        if time.time() > deadline:
                            dump = await evaluate(
                                "location.href+' '+(document.getElementById('ml-bar')||{})"
                                ".outerHTML+' '+sessionStorage.getItem('gsVisitLeague')",
                                strict=False)
                            raise AssertionError(f"timed out waiting for {expr}\n{dump}\n{errors}")
                        await asyncio.sleep(0.1)
                elif kind == "do":
                    await evaluate(expr)
                else:
                    out.append(await evaluate(expr))
            await send("Page.removeScriptToEvaluateOnNewDocument",
                       {"identifier": added["result"]["identifier"]})
            return out, errors
    return asyncio.run(go())


STATE = r"""(function(){
  var saved=JSON.parse(localStorage.getItem('gsSleeperLeague')||'null');
  var row=document.querySelector('.gs-share-row[hidden], .gs-share-row');
  var reader=document.querySelector('#built')?document.querySelectorAll('.gs-share-row')[0]:null;
  return {saved:saved&&saved.id, name:saved&&saved.name,
          own:window.GSVisit?(GSVisit.own()||{}).id:null,
          visit:JSON.parse(sessionStorage.getItem('gsVisitLeague')||'null'),
          search:location.search, bar:document.getElementById('ml-bar').textContent,
          readerShown:reader?getComputedStyle(reader).display!=='none':null};
})()"""


def _share(selector):
    return ("(async function(){ window.__shared=null; document.querySelector("
            + json.dumps(selector) + ").click(); await new Promise(function(r){"
            " setTimeout(r, 50); }); return window.__shared; })()")


@browser_only
def test_a_shared_league_shows_for_the_visit_and_leaves_theirs_alone(chrome, site):
    named = "document.querySelector('#ml-bar .ml-who') && " \
            "document.querySelector('#ml-bar .ml-who').textContent==='Friends League'"
    (first, shared, week, later), errors = drive(chrome, [
        ("go", f"{site}?league={FRIEND}&reset=1&own={MINE}"), ("wait", named),
        ("eval", STATE), ("eval", _share(".gs-share-row:not([hidden]) .gs-share")),
        ("eval", _share("#recap .gs-share")),
        ("go", f"{site}other.html"), ("wait", named), ("eval", STATE)])
    assert not errors, errors
    # Every read of the saved league is the shared one; theirs is untouched,
    # though the bar has read and named the shared league since.
    assert first["saved"] == FRIEND and first["name"] == "Friends League"
    assert first["own"] == MINE and first["visit"]["id"] == FRIEND
    assert "Use this league" in first["bar"] and "Back to yours" in first["bar"]
    assert first["readerShown"] is True
    # Sharing it on sends the same league.
    assert shared["url"] == f"{site}fantasy/matchups/?league={FRIEND}"
    assert shared["text"] == "Friends League: week 5 matchups"
    # A recap's week is in the address's hash, which stays last.
    assert week["url"] == f"{site}fantasy/recap/?league={FRIEND}#week-3"
    assert week["text"] == "Friends League"
    # The rest of the visit, on another page with nothing in its address.
    assert later["saved"] == FRIEND and later["own"] == MINE and later["search"] == ""


@browser_only
def test_use_this_league_keeps_it_and_back_goes_home(chrome, site):
    named = "!!document.getElementById('ml-keep')"
    (kept, back), errors = drive(chrome, [
        ("go", f"{site}?reset=1&own={MINE}"), ("wait", "!!window.GSLeague"),
        ("go", f"{site}?league={FRIEND}&x=1"), ("wait", named),
        ("do", "document.getElementById('ml-keep').click()"),
        ("wait", "!document.getElementById('ml-keep')"), ("eval", STATE),
        ("go", f"{site}?reset=1&own={MINE}"), ("wait", "!!window.GSLeague"),
        ("go", f"{site}other.html?league={FRIEND}"), ("wait", named),
        ("do", "document.getElementById('ml-back').click()"),
        ("wait", "document.readyState==='complete' && !location.search"
                 " && document.querySelector('#ml-bar .ml-who')"
                 " && document.querySelector('#ml-bar .ml-who').textContent==='Mine League'"),
        ("eval", STATE)])
    assert not errors, errors
    # Kept: now the browser's own saved league, the visit over, and the
    # address no longer carrying it (the rest of it stays).
    assert kept["saved"] == FRIEND and kept["own"] == FRIEND and kept["visit"] is None
    assert kept["search"] == "?x=1"
    assert "Showing Friends League" in kept["bar"]
    # Back: their own league, never overwritten, and the address plain again.
    assert back["saved"] == MINE and back["visit"] is None


@browser_only
def test_a_link_to_their_own_or_this_sites_league_is_no_visit(chrome, site):
    (own, ours, junk, espn, shared), errors = drive(chrome, [
        ("go", f"{site}?league={MINE}&reset=1&own={MINE}"), ("wait", "!!window.GSLeague"),
        ("eval", STATE),
        ("go", f"{site}?league={_site_id()}&reset=1&own={_site_id()}"),
        ("wait", "!!window.GSLeague"), ("eval", STATE),
        ("go", f"{site}?league=sleeper&reset=1"), ("wait", "!!window.GSLeague"), ("eval", STATE),
        ("go", f"{site}?league=espn:2026:48153&reset=1"), ("wait", "!!window.GSLeague"),
        ("eval", STATE), ("eval", _share(".gs-share-row:not([hidden]) .gs-share"))])
    assert not errors, errors
    assert own["saved"] == MINE and own["visit"] is None
    # This site's league: the built button, and nothing added to its address.
    assert ours["visit"] is None and ours["readerShown"] is False
    assert junk["saved"] is None and junk["visit"] is None, "only a league id is a league"
    # An ESPN league shares as one, its colons left readable; with nothing of
    # their own saved, the way back is this site's league.
    assert espn["visit"]["provider"] == "espn" and "This site’s league" in espn["bar"]
    assert shared["url"] == f"{site}fantasy/matchups/?league=espn:2026:48153"


@browser_only
def test_this_sites_league_shares_without_a_league(chrome, site):
    (got,), errors = drive(chrome, [
        ("go", f"{site}?reset=1&own={_site_id()}"), ("wait", "!!window.GSLeague"),
        ("eval", _share("#built .gs-share"))])
    assert not errors, errors
    assert got["url"] == f"{site}fantasy/power/" and got["text"] == "Power"
