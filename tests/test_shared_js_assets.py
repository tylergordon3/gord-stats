"""
The shared browser libraries are files (gordstats.js_assets): a page loads
each by its content-hashed URL, so a reader downloads it once, rather than
finding the same 20-50 KB inline on every page and fetching it again after
every publish (the 2026-10-02 ops review).

What has to hold: each module's `..._TAG` is a <script src> through
`| fingerprint` and carries none of the code; its inline twin (what the
browser tests run) is the file; nothing the build used to write into the
script (this season's league ids, the night, the Share button) is left in a
file, and the page sets it instead; the pages carry tags, in the order the
inline blocks had; and the simulation still gets its Worker when it is
loaded by src rather than inline.
"""
import asyncio
import functools
import http.server
import json
import re
import shutil
import socketserver
import threading
import time
import urllib.request

import pytest

from browser_util import launch, reap
from conftest import DOCS, ROOT
from gordstats import (js_assets, league_api, my_draft, my_history, my_home, my_league,
                       my_league_data, my_matchups, my_power, my_recap, my_team, my_waivers,
                       my_week, trade_page, watch_page, week_strip)

JS_DIR = DOCS / "assets" / "js"

# (module, attribute, file, a line of the library's own code)
LIBRARIES = [
    (league_api, "JS", "gs-league-api.js", "window.GSAPI = window.GSAPI ||"),
    (my_league_data, "JS", "gs-league-data.js", "window.GSL = (function(){"),
    (my_week, "JS", "gs-week.js", "window.GSWeek = (function(){"),
    (my_team, "PLANNER_JS", "gs-plan.js", "window.GSPlan = function("),
    (my_team, "VIEW_JS", "gs-team.js", "getElementById('mt-host')"),
    (my_recap, "CORE_JS", "gs-recap.js", "window.GSRecap=(function(){"),
    (my_recap, "JS", "gs-recap-view.js", "getElementById('rc-host')"),
    (my_power, "SIM_JS", "gs-power-sim.js", "root.GSPower = {"),
    (my_power, "LEAGUE_JS", "gs-power-league.js", "window.GSPowerLeague = (function(){"),
    (my_power, "JS", "gs-power.js", "getElementById('mp-host')"),
    (my_league, "JS", "gs-league-bar.js", "window.GSLeague = {"),
    (my_history, "JS", "gs-history.js", "window.GSHist={"),
    (my_home, "JS", "gs-home.js", "window.GSHome={"),
    (my_matchups, "JS", "gs-matchups.js", "getElementById('mm-host')"),
    (my_waivers, "JS", "gs-waivers.js", "getElementById('wv-host')"),
    (my_draft, "JS", "gs-draft.js", "getElementById('dr-host')"),
    (week_strip, "JS", "gs-week-strip.js", "getElementById('ws-host')"),
    (trade_page, "JS", "gs-trade.js", "window.GSTrade = function("),
    (watch_page, "ENGINE_JS", "gs-watch.js", "window.GSWatch=function("),
]
IDS = [f"{mod.__name__.split('.')[-1]}.{attr}" for mod, attr, _f, _s in LIBRARIES]
FILES = sorted({name for _m, _a, name, _s in LIBRARIES})

# A tag as the page body carries it, before Jekyll: the file's plain path
# inside a fingerprint filter (the liquid() markers around it vary per run).
TAGGED = re.compile(r'<script([^>]*) src="[^"]*\{\{ \'/assets/js/([\w.-]+)\' '
                    r'\| fingerprint \| relative_url \}\}[^"]*"></script>')


def _config(html: str) -> dict:
    """Every GSCFG value a page body (or tag) sets, merged in order."""
    out = {}
    for blob in re.findall(r"window\.GSCFG=Object\.assign\(window\.GSCFG\|\|\{\},(\{.*?\})\);",
                           html):
        out.update(json.loads(blob))
    return out


def _files(html: str) -> list:
    """The libraries a body loads by tag, in order."""
    return [m.group(2) for m in TAGGED.finditer(html)]


# --------------------------------------------------------------------------- #
# The files, the tags and the inline twins
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("name", FILES)
def test_a_library_file_holds_nothing_the_build_used_to_write_in(name):
    from fantasy.config import LEAGUE_IDS, UPCOMING_LEAGUE_ID

    js = (JS_DIR / name).read_text()
    assert not re.findall(r"__[A-Z][A-Z_]*__", js), "a build-time placeholder is left in"
    assert "{% raw" not in js and "{% endraw" not in js and "{{" not in js
    for league_id in {str(UPCOMING_LEAGUE_ID), *map(str, LEAGUE_IDS.values())}:
        assert league_id not in js, f"this season's league {league_id} is baked into {name}"


@pytest.mark.parametrize("mod, attr, name, code", LIBRARIES, ids=IDS)
def test_the_tag_loads_the_file_by_its_hashed_url(mod, attr, name, code):
    tag = getattr(mod, attr + "_TAG")
    assert _files(tag)[-1] == name
    assert code not in tag, "the library is still inline in its tag"
    # In order with the inline scripts after it, as when it was inline itself.
    assert " defer" not in tag and " async" not in tag
    # A frontmatter.liquid() mark, so add_front_matter lets Jekyll run it.
    assert "' | fingerprint | relative_url }}" in tag


@pytest.mark.parametrize("mod, attr, name, code", LIBRARIES, ids=IDS)
def test_the_inline_twin_is_the_file(mod, attr, name, code):
    """What the browser tests run is what the pages load."""
    source = (JS_DIR / name).read_text()
    assert code in source
    assert source in getattr(mod, attr)
    expanded = js_assets.expand(getattr(mod, attr + "_TAG"))
    assert source in expanded and not _files(expanded)


def test_expand_puts_back_a_tag_and_keeps_its_config():
    tag = week_strip.JS_TAG
    out = js_assets.expand(tag)
    assert _config(out) == _config(tag) and _config(tag)
    assert out.index("window.GSCFG") < out.index("getElementById('ws-host')")
    assert not _files(out)


def test_the_page_says_what_the_build_used_to_write_into_the_scripts():
    from fantasy.config import EXPW_RATIO, LEAGUE_IDS, UPCOMING_LEAGUE_ID
    from gordstats import logos, share_button

    site = str(UPCOMING_LEAGUE_ID)
    assert _config(my_league.JS_TAG)["siteLeagues"] == sorted({str(v) for v in LEAGUE_IDS.values()})
    for mod in (my_history, my_draft, week_strip):
        assert _config(mod.JS_TAG) == {"siteLeague": site}, mod.__name__
    assert _config(my_home.JS_TAG) == {"expwRatio": EXPW_RATIO}
    assert _config(watch_page.ENGINE_JS_TAG) == {"nightEnds": watch_page.NIGHT_ENDS}
    assert _config(my_week.JS_TAG) == {"nflLogo": logos.url("nfl", "{abbr}")}
    assert _config(my_recap.JS_TAG) == {"recapShare": share_button.row("", "", league=True)}
    # And the inline twins carry the same, so a test runs what a page runs.
    for mod, attr in ((my_league, "JS"), (my_history, "JS"), (my_draft, "JS"),
                      (week_strip, "JS"), (my_home, "JS"), (watch_page, "ENGINE_JS"),
                      (my_week, "JS"), (my_recap, "JS")):
        assert _config(getattr(mod, attr)) == _config(getattr(mod, attr + "_TAG")), mod.__name__


def test_espns_codes_in_the_file_are_pythons():
    """ESPN's team and position codes are written into gs-league-api.js -
    they are ESPN's, the same on every page and in every season - so they
    have to stay the ones the Python reads ESPN with."""
    from fantasy.league.ext_projections import ESPN_POSITIONS, ESPN_TEAMS

    js = (JS_DIR / "gs-league-api.js").read_text()
    teams = json.loads(re.search(r"var TEAMS=(\{[^}]*\})", js).group(1))
    pos = json.loads(re.search(r"\bPOS=(\{[^}]*\})", js).group(1))
    assert teams == {str(k): v for k, v in ESPN_TEAMS.items()}
    assert pos == {str(k): v for k, v in ESPN_POSITIONS.items()}


# --------------------------------------------------------------------------- #
# The pages
# --------------------------------------------------------------------------- #

def test_the_league_pages_load_the_libraries_in_their_old_order():
    from fantasy.site import draft_review, history, waivers

    lead = ["gs-league-data.js", "gs-league-api.js", "gs-league-bar.js"]
    for page, own in ((history, "gs-history.js"), (waivers, "gs-waivers.js"),
                      (draft_review, "gs-draft.js")):
        html = page.body()
        assert _files(html) == lead + [own], page.__name__
        for _m, _a, _n, code in LIBRARIES:
            assert code not in html, f"{page.__name__} still inlines {code}"


def test_the_watch_guide_loads_its_engine_before_the_adapter():
    html = watch_page.body(None, "<script>GSWatch(D, {});</script>", "how", "/x/", "x")
    assert _files(html) == ["gs-watch.js"]
    assert "window.GSWatch=function(" not in html
    assert html.index("gs-watch.js") < html.index("GSWatch(D, {})")
    assert html.index("nightEnds") < html.index("gs-watch.js")


# Pages whose body() needs the season's data: read their source instead.
# Every one now loads the shared libraries by tag (usage was the last, 2026-10-02).
INLINE_OK = set()
ATTR = re.compile(r"\b(league_api|my_league|my_league_data|my_week|my_team|my_recap|my_power|"
                  r"my_history|my_home|my_matchups|my_waivers|my_draft|week_strip|trade_page|"
                  r"watch_page)\.(JS|SIM_JS|LEAGUE_JS|PLANNER_JS|VIEW_JS|CORE_JS|ENGINE_JS)\b")


def test_no_page_inlines_a_shared_library():
    owners = {f"src/gordstats/{mod.__name__.split('.')[-1]}.py" for mod, *_ in LIBRARIES}
    found = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        rel = str(path.relative_to(ROOT))
        if rel in owners or rel in INLINE_OK:
            continue
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if ATTR.search(line) and not line.lstrip().startswith("#"):
                found.append(f"{rel}:{n}: {line.strip()}")
    assert not found, "a page carries a library inline; use its _TAG:\n" + "\n".join(found)


# --------------------------------------------------------------------------- #
# In the browser: the tags run, and the simulation finds its Worker
# --------------------------------------------------------------------------- #

CHROME = next((p for p in ("/usr/bin/chromium-browser", "/usr/bin/chromium",
                           "/usr/bin/google-chrome") if shutil.which(p)), None)
needs_chrome = pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")
CDP = 9599


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    """The library files at their plain paths, as Jekyll would serve them
    (the hashed copy is the same bytes), and a page per check."""
    from fantasy.site import history

    root = tmp_path_factory.mktemp("jsassets")
    (root / "assets" / "js").mkdir(parents=True)
    for name in FILES:
        shutil.copy(JS_DIR / name, root / "assets" / "js" / name)
    plain = lambda html: TAGGED.sub(r'<script\1 src="/assets/js/\2"></script>', html)  # noqa: E731
    stub = ("<script>window.fetch=function(){return Promise.resolve("
            "new Response('null',{status:404}));};</script>")
    (root / "history.html").write_text(
        "<!doctype html><html><head><meta charset='utf-8'></head><body>" + stub
        + plain(history.body()) + "</body></html>")
    (root / "sim.html").write_text(
        "<!doctype html><html><head><meta charset='utf-8'></head><body>"
        "<script>window.WORKERS=[];(function(W){window.Worker=function(u){"
        "WORKERS.push(String(u));return new W(u);};})(window.Worker);"
        "window.GSAPI={get:function(){return Promise.resolve(null);}};window.GSL={};</script>"
        + plain(my_power.SIM_JS_TAG + my_power.LEAGUE_JS_TAG) + "</body></html>")
    handler = functools.partial(_Quiet, directory=str(root))
    server = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="module")
def chrome():
    if CHROME is None:
        pytest.skip("no Chromium to run the JS in")
    proc = launch(CHROME, CDP)
    for _ in range(60):
        try:
            targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{CDP}/json"))
            url = next(t["webSocketDebuggerUrl"] for t in targets if t.get("type") == "page")
            break
        except Exception:                                       # noqa: BLE001
            time.sleep(0.5)
    else:
        proc.terminate()
        reap(proc)
        raise RuntimeError("Chromium did not come up")
    yield url
    proc.terminate()
    reap(proc)


def _run(ws_url: str, page: str, expression: str):
    """Open `page`, wait for it to settle, evaluate `expression` (awaiting a
    promise); return its value and any exception the page threw."""
    import websockets

    async def go():
        async with websockets.connect(ws_url, max_size=None) as ws:
            n, errors = 0, []

            async def send(method, **params):
                nonlocal n
                n += 1
                await ws.send(json.dumps({"id": n, "method": method, "params": params}))
                while True:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=60))
                    if msg.get("method") == "Runtime.exceptionThrown":
                        d = msg["params"]["exceptionDetails"]
                        errors.append((d.get("exception") or {}).get("description") or d.get("text"))
                    if msg.get("id") == n:
                        return msg.get("result", {})

            await send("Runtime.enable")
            await send("Page.enable")
            await send("Page.navigate", url=page)
            for _ in range(40):
                state = await send("Runtime.evaluate", expression="document.readyState",
                                   returnByValue=True)
                if state.get("result", {}).get("value") == "complete":
                    break
                await asyncio.sleep(0.25)
            out = await send("Runtime.evaluate", expression=expression, returnByValue=True,
                             awaitPromise=True)
            if out.get("exceptionDetails"):
                errors.append(out["exceptionDetails"].get("text"))
            return out.get("result", {}).get("value"), errors
    return asyncio.run(go())


@needs_chrome
def test_a_page_of_tags_defines_every_library_before_its_page_script_runs(chrome, served):
    value, errors = _run(chrome, served + "/history.html",
                         "JSON.stringify([!!window.GSAPI, !!window.GSL, !!window.GSLeague,"
                         " !!window.GSHist, document.getElementById('ml-bar').innerHTML.length>0])")
    assert not errors, errors
    assert json.loads(value) == [True, True, True, True, True]


@needs_chrome
def test_the_simulation_gets_its_worker_from_its_file(chrome, served):
    """Inline, the Worker was built from the element's text; loaded by src the
    element has none, and the Worker loads the file itself (from the cache)."""
    board, rosters, pid = {}, [], 0
    for t in range(8):
        held = []
        for pos in (0, 1, 1, 2, 2, 3, 4, 5):
            pid += 1
            board[str(pid)] = [pos, 6 + t % 3, 9.0 + (pid % 5), 4.0, 1.0, 0.9, 2.0, 0]
            held.append(str(pid))
        rosters.append({"roster_id": t + 1, "players": held})
    spec = {"board": board, "posNames": ["QB", "RB", "WR", "TE", "K", "DEF"], "rosters": rosters,
            "slots": ["QB", "RB", "RB", "WR", "WR", "TE", "K", "DEF"], "basis": 0,
            "weeks": 14, "playoffTeams": 4, "median": False, "reseed": True,
            "sims": 200, "seed": 3}
    # The main thread's copy refuses while the Worker runs, so a fallback to it
    # (what a Worker that failed to load gets) cannot pass for the Worker.
    value, errors = _run(
        chrome, served + "/sim.html",
        "(function(){ var run=GSPower.run;"
        " GSPower.run=function(){ throw new Error('ran on the main thread'); };"
        " return GSPowerLeague.simulate(" + json.dumps(spec) + ").then(function(r){"
        "  GSPower.run=run;"
        "  return JSON.stringify({worker:r, main:run(" + json.dumps(spec) + "),"
        "   urls:WORKERS, text:document.getElementById('gs-power-sim').textContent.length}); });"
        "})()")
    assert not errors, errors
    got = json.loads(value)
    assert got["text"] == 0, "the element is a src now, with no text to build from"
    assert got["urls"] and all(u.endswith("/assets/js/gs-power-sim.js") for u in got["urls"])
    assert got["worker"] == got["main"], "the Worker's season is not the page's"
