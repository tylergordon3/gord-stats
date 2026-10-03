"""
The team stats pages (gordstats.stats_page, cfb.advanced, cfb.site.stats):
where a team ranks shaded the right way round, the table sorting best first,
filtering and renumbering, the tabs, and CFB's numbers read off
CollegeFootballData's trimmed caches.

The browser half runs the table's script in headless Chromium; skips without
Chromium.
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

from gordstats import stats_page
from browser_util import launch, reap

CHROME = next((p for p in ("/usr/bin/chromium-browser", "/usr/bin/chromium",
                           "/usr/bin/google-chrome") if shutil.which(p)), None)
CDP = 9457

COLS = [{"key": "off", "label": "Off EPA", "tip": "offense", "fmt": "epa", "better": "high",
         "views": ("overview", "offense")},
        {"key": "dfn", "label": "Def EPA", "tip": "defence", "fmt": "epa", "better": "low",
         "views": ("overview", "defense")},
        {"key": "pace", "label": "Plays/g", "tip": "tempo", "fmt": "num1", "better": None,
         "views": ("situational",)}]
ROWS = [{"name": "Alabama", "off": 0.21, "dfn": -0.01, "pace": 70.0, "group": "SEC", "tags": ["Power4"]},
        {"name": "Toledo", "off": 0.15, "dfn": 0.10, "pace": 66.0, "group": "MAC"},
        {"name": "Georgia", "off": 0.19, "dfn": 0.02, "pace": None, "group": "SEC", "tags": ["Power4"]}]


def test_shading_is_turned_the_right_way():
    p = stats_page.percentiles(ROWS, COLS)
    assert p[(0, "off")] == 1.0 and p[(1, "off")] == 0.0          # high is good
    assert p[(0, "dfn")] == 1.0 and p[(1, "dfn")] == 0.0          # low is good
    assert not any(k[1] == "pace" for k in p)                      # neither: not shaded


def test_the_table_opens_sorted_best_first_with_filters_and_tabs():
    html = stats_page.table(ROWS, COLS, filters=[("", "All"), ("Power4", "Power 4"), ("SEC", "SEC")],
                            sort_key="dfn")
    names = re.findall(r"<td class='st-team' data-v='([^']*)'>", html)
    assert names == ["Alabama", "Georgia", "Toledo"]              # lowest EPA allowed first
    assert "data-f=' Power4'" not in html and "data-f='SEC Power4'" in html
    assert "aria-sort=descending" in html and "data-b='low'" in html
    assert "<td class='v-situational'>&mdash;</td>" in html        # a missing figure, unshaded
    assert "table.st-t.view-defense td:not(.st-rk):not(.st-team):not(.v-defense)" in html
    assert "data-sticky-head" in html


def test_formats():
    assert stats_page.fmt(0.2093, "epa") == "+0.21" and stats_page.fmt(-0.004, "epa") == "+0.00"
    assert stats_page.fmt(0.4583, "pct") == "45.8%" and stats_page.fmt(None, "pct") == "&mdash;"
    assert stats_page.fmt("3-1", "rec") == "3-1"


def test_leaders_and_glossary():
    html = stats_page.leaders([{"key": "qb", "label": "Quarterbacks", "metric": "EPA", "fmt": "epa",
                                "rows": [{"name": "A <b>", "team": "X", "value": 0.8, "vol": "90 plays"}]}])
    assert "A &lt;b&gt;" in html and "+0.80" in html and "data-lbs" in html
    assert "<dt>Off EPA</dt><dd>offense</dd>" in stats_page.glossary(COLS)


# --------------------------------------------------------------------------- #
# CFB's numbers
# --------------------------------------------------------------------------- #

def _caches(monkeypatch):
    from cfb import advanced
    caches = {
        "wepa": {"Alabama": {"id": "333", "conf": "SEC", "off": 0.2, "off_pass": 0.3, "off_rush": 0.1,
                             "def": -0.05, "def_pass": 0.0, "def_rush": -0.1, "sr": 0.5, "sr_sd": 0.55,
                             "sr_pd": 0.35, "sr_a": 0.38, "sr_sd_a": 0.42, "sr_pd_a": 0.25, "line": 3.1,
                             "line_a": 2.5, "expl": 1.1, "expl_a": 1.0},
                 "Toledo": {"id": "2649", "conf": "MAC", "off": 0.1, "off_pass": None, "off_rush": None,
                            "def": None, "def_pass": None, "def_rush": None, "sr": None, "sr_sd": None,
                            "sr_pd": None, "sr_a": None, "sr_sd_a": None, "sr_pd_a": None, "line": None,
                            "line_a": None, "expl": None, "expl_a": None}},
        "advanced": {"Alabama": {"conf": "SEC", "off": {"plays": 280, "start": 30.5, "stuff": 0.12},
                                 "def": {"havoc": 0.2}}},
        "season_stats": {"Alabama": {"games": 4, "thirdDowns": 48, "thirdDownConversions": 22,
                                     "turnovers": 3, "turnoversOpponent": 8, "possessionTime": 7560}},
        "talent": {"Alabama": 980.0, "Toledo": 600.0},
        "ppa_players": [
            {"name": "QB One", "pos": "QB", "team": "Alabama", "pass": 0.5, "pass_n": 120, "rush": None, "rush_n": 0},
            {"name": "QB Few", "pos": "QB", "team": "Alabama", "pass": 0.9, "pass_n": 20, "rush": None, "rush_n": 0},
            {"name": "QB FCS", "pos": "QB", "team": "Maine", "pass": 0.9, "pass_n": 120, "rush": None, "rush_n": 0}],
    }
    monkeypatch.setattr(advanced, "_load", lambda name: caches[name])
    # Plays a game come from the per-game archive (every snap, garbage time
    # included) since the 2026-10-02 audit; pin it rather than read the disk.
    monkeypatch.setattr(advanced, "_plays_per_game", lambda *a, **k: {"Alabama": 70.0})
    return advanced


def test_cfb_team_rows(monkeypatch):
    advanced = _caches(monkeypatch)
    rows = {r["name"]: r for r in advanced.teams()}
    bama = rows["Alabama"]
    assert bama["adj_net"] == 0.25 and bama["third"] == round(22 / 48, 4)
    assert bama["to_margin"] == 1.25 and bama["top_pg"] == 31.5        # 7560 s over 4 games
    assert bama["plays_pg"] == 70.0 and bama["talent_rank"] == 1 and bama["def_havoc"] == 0.2
    assert rows["Toledo"]["adj_net"] is None and rows["Toledo"]["third"] is None


def test_cfb_leaders_keep_the_minimum_and_fbs(monkeypatch):
    advanced = _caches(monkeypatch)
    got = advanced.players({"Alabama", "Toledo"})
    assert [r["name"] for r in got["QB"]] == ["QB One"]


# --------------------------------------------------------------------------- #
# In the browser
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def site(tmp_path_factory):
    root = tmp_path_factory.mktemp("stats")
    html = stats_page.table(ROWS, COLS, filters=[("", "All"), ("SEC", "SEC")], sort_key="off")
    (root / "index.html").write_text("<!doctype html><html><body>" + html + "</body></html>")
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
                await send("Page.enable")
                await send("Page.navigate", {"url": url})
                await asyncio.sleep(1.5)
                r = await send("Runtime.evaluate", {"expression": expression, "returnByValue": True})
                return r["result"].get("value")
        return asyncio.run(go())
    finally:
        proc.terminate()
        reap(proc)


@pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")
def test_sorting_filtering_and_tabs_in_the_browser(site):
    got = json.loads(_run(site, """JSON.stringify((function(){
      function names(){ return [].map.call(document.querySelectorAll('tbody tr'),function(r){
        return r.hidden?null:r.cells[0].textContent+':'+r.cells[1].textContent; }).filter(Boolean); }
      var out={start:names()};
      var def=document.querySelector('th[data-k=dfn]');
      def.click(); out.def=names();                 // low is good: ascending first
      def.click(); out.defAgain=names();            // and reversed
      var sel=document.querySelector('.st-flt select'); sel.value='SEC';
      sel.dispatchEvent(new Event('change')); out.sec=names();
      document.querySelector('button[data-view=situational]').click();
      var t=document.querySelector('table.st-t');
      out.view=t.className; out.offShown=getComputedStyle(t.querySelector('td.v-offense')).display;
      out.paceShown=getComputedStyle(t.querySelector('td.v-situational')).display;
      return out;
    })())"""))
    assert got["start"] == ["1:Alabama", "2:Georgia", "3:Toledo"]
    assert got["def"] == ["1:Alabama", "2:Georgia", "3:Toledo"]
    assert got["defAgain"] == ["1:Toledo", "2:Georgia", "3:Alabama"]
    assert got["sec"] == ["1:Georgia", "2:Alabama"]            # renumbered after the filter
    assert "view-situational" in got["view"]
    assert got["offShown"] == "none" and got["paceShown"] != "none"


def test_team_pages_rank_each_figure_the_right_way(monkeypatch):
    from cfb import advanced
    from cfb.site import teams
    monkeypatch.setattr(advanced, "teams", lambda: [
        {"id": "1", "adj_off": 0.2, "adj_def": 0.05}, {"id": "2", "adj_off": 0.1, "adj_def": -0.02},
        {"id": "3", "adj_off": None, "adj_def": 0.0}])
    ranks = teams.advanced_ranks()
    assert ranks["1"]["adj_off"] == (0.2, 1, 2) and "adj_off" not in ranks["3"]
    assert ranks["2"]["adj_def"] == (-0.02, 1, 3)          # least allowed is first
    html = teams._advanced_block(ranks["2"])
    assert "1st of 3" in html and "/cfb/stats/" in html
    assert teams._advanced_block({}) == ""


def test_a_record_column_sorts_by_winning_share():
    cols = [{"key": "rec", "label": "Rec", "tip": "", "fmt": "rec", "better": None, "views": ("overview",)}]
    html = stats_page.table([{"name": "A", "rec": "3-1"}, {"name": "B", "rec": "2-1-1"}], cols)
    assert "data-v='0.7500'>3-1<" in html and "data-v='0.6250'>2-1-1<" in html
