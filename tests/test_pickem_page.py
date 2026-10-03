"""
/pickem/ in the browser (gordstats.pickem_page, docs/assets/js/gs-pickem.js).

Headless Chromium (CDP port 9663) against a local server on a port the OS
picks, which serves the page built from the real markup (the shared script
inlined, as Jekyll would serve it by URL) and answers /api/pickem* from the
test - no network. What has to hold: the slate draws from the page itself and
nothing moves as the API answers (phone and desktop); signed out it is read
only with a Sign in button; a reader picks by thumb - a tap picks, the select
swaps values, values on locked games are off - and every change is saved as
the whole week; locks follow the server's clock; the leaderboards mark the
model and the reader; past weeks open; names and labels are drawn as text.
"""
import json
import re
import shutil
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from browser_util import launch, reap
from gordstats import how, js_assets, pickem_page

CHROME = next((p for p in ("/usr/bin/chromium-browser", "/usr/bin/chromium",
                           "/usr/bin/google-chrome") if shutil.which(p)), None)
CDP = 9663

CLS = ("<script>window.__cls=0;window.__shifts=[];try{new PerformanceObserver(function(l){"
       "l.getEntries().forEach(function(e){if(!e.hadRecentInput){__cls+=e.value;"
       "__shifts.push(e.value);}});}).observe({type:'layout-shift',buffered:true});}catch(e){}"
       "</script>")


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


NOW = datetime.now(timezone.utc).replace(microsecond=0)


def g(gid, hours, res=None, st="pre", gs=("h", 1, 0.6), home="Home", away="Away", **extra):
    kick = NOW + timedelta(hours=hours)
    out = {"id": gid, "sp": gid[:3], "ko": iso(kick), "tk": True, "lock": iso(kick),
           "tv": "ESPN", "note": "",
           "h": {"id": "1", "nm": home, "ab": home[:3].upper(),
                 "lg": "https://a.espncdn.com/i/teamlogos/nfl/500/buf.png"},
           "a": {"id": "2", "nm": away, "ab": away[:3].upper(),
                 "lg": "https://a.espncdn.com/i/teamlogos/nfl/500/mia.png"},
           "st": st, "det": "", "score": None, "res": res,
           "gs": {"s": gs[0], "c": gs[1], "p": gs[2]} if gs else None}
    out.update(extra)
    return out


def slate(week=5, games=None):
    games = games if games is not None else [
        g("nfl:1", -3, res="h", st="post", gs=("h", 5, 0.8), home="Bills", away="Dolphins",
          score={"h": 24, "a": 17}),
        g("cfb:2", -1, st="in", gs=("a", 4, 0.7), home="Iowa", away="Ohio State"),
        g("nfl:3", 5, gs=("h", 3, 0.66), home="Eagles", away="Rams"),
        g("cfb:4", 26, gs=("a", 2, 0.6), home="Missouri", away="Florida", gotw=True),
        g("nfl:5", 50, gs=("h", 1, 0.55), home="Saints", away="Falcons"),
    ]
    return {"season": 2026, "week": week, "label": f"Week {week}", "sub": "NFL Week 5 · CFB Week 6",
            "start": "", "end": "", "n": len(games), "games": games}


INDEX = {"season": 2026, "current": 5, "weeks": [
    {"w": 4, "label": "Week 4", "sub": "NFL Week 4", "n": 2, "done": True, "g": []},
    {"w": 5, "label": "Week 5", "sub": "NFL Week 5 · CFB Week 6", "n": 5, "done": False, "g": []}]}

WEEKS = [{"w": 4, "label": "Week 4", "sub": "NFL Week 4", "n": 2, "done": True, "players": 3,
          "top": [{"name": "Alpha", "pts": 7}], "gs": 4},
         {"w": 5, "label": "Week 5", "sub": "NFL Week 5 · CFB Week 6", "n": 5, "done": False,
          "players": 2, "top": [], "gs": 5}]


def answer(signed_in=False, me=None, mine=None, week=5, now_ms=None, **extra):
    out = {"ok": True, "configured": True, "signedIn": signed_in, "season": 2026, "current": 5,
           "week": week, "weeks": WEEKS, "slate": slate(week),
           "board": {"week": [{"r": 1, "name": "GordStats", "pts": 5, "right": 1, "of": 1,
                               "max": 15, "gs": True},
                              {"r": 2, "name": "Reader One", "pts": 0, "right": 0, "of": 1,
                               "max": 9}],
                     "season": [{"r": 1, "name": "Alpha", "pts": 7, "right": 2, "of": 2, "wk": 1},
                                {"r": 2, "name": "GordStats", "pts": 9, "right": 2, "of": 3,
                                 "wk": 2, "gs": True}]},
           "now": now_ms if now_ms is not None else int(time.time() * 1000)}
    if signed_in:
        out["me"] = me
        out["mine"] = mine or {}
    out.update(extra)
    return out


def _doc(body: str) -> str:
    body = js_assets.expand(body)
    return ("<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' "
            "content='width=device-width,initial-scale=1'>" + CLS +
            "<style>body{margin:0;font-family:sans-serif}main{padding:0 16px}"
            "[hidden]{display:none!important}</style></head><body><main>"
            "<div id='above' style='height:120px'>above</div>" + body +
            "<div id='below' style='height:1200px'>below</div></main></body></html>")


class Site:
    """The page, /api answers (by method and full path) and a request log."""

    def __init__(self):
        self.pages, self.api, self.log = {}, {}, []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self, method):
                size = int(self.headers.get("content-length") or 0)
                body = self.rfile.read(size).decode() if size else ""
                outer.log.append((method, self.path, body))
                if self.path in outer.pages and method == "GET":
                    return self._send(200, outer.pages[self.path], "text/html; charset=utf-8")
                if self.path.startswith("/how/"):
                    return self._send(404, "", "text/html")
                hit = outer.api.get((method, self.path))
                if hit is None:
                    return self._send(404, '{"ok":false}', "application/json")
                status, data, delay = (list(hit) + [0])[:3]
                if callable(data):
                    data = data(body)
                if delay:
                    time.sleep(delay)
                return self._send(status, json.dumps(data), "application/json")

            def _send(self, status, text, ctype):
                data = text.encode()
                self.send_response(status)
                self.send_header("content-type", ctype)
                self.send_header("content-length", str(len(data)))
                self.send_header("cache-control", "no-store")
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):                                   # noqa: N802
                self._answer("GET")

            def do_POST(self):                                  # noqa: N802
                self._answer("POST")

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.origin = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def posts(self, path):
        return [json.loads(b) for m, p, b in self.log if m == "POST" and p == path]

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class Tab:
    """One persistent DevTools session on the browser's page."""

    def __init__(self):
        from websockets.sync.client import connect

        self.proc = launch(CHROME, CDP)
        for _ in range(60):
            try:
                targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{CDP}/json"))
                url = next(t["webSocketDebuggerUrl"] for t in targets if t.get("type") == "page")
                break
            except Exception:                                   # noqa: BLE001
                time.sleep(0.5)
        else:
            raise RuntimeError("Chromium did not come up")
        self._conn = connect(url, max_size=None, open_timeout=30)
        self.ws = self._conn.__enter__()
        self.n = 0
        self.send("Emulation.setTimezoneOverride", {"timezoneId": "America/New_York"})

    def send(self, method, params=None):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv(timeout=30))
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise AssertionError(msg["error"])
                return msg.get("result", {})

    def ev(self, expression):
        res = self.send("Runtime.evaluate", {"expression": expression, "returnByValue": True,
                                             "awaitPromise": True})
        if res.get("exceptionDetails"):
            d = res["exceptionDetails"]
            raise AssertionError((d.get("exception") or {}).get("description") or d["text"])
        return res["result"].get("value")

    def wait(self, expression, timeout=8.0):
        end = time.time() + timeout
        while time.time() < end:
            if self.ev(expression):
                return
            time.sleep(0.05)
        raise AssertionError(f"timed out waiting for {expression}")

    def open(self, url, width=390, height=844, acct=None):
        """`url` at that size, with favorites.js's account guess (gs:acct)
        set first on the same origin - "in", "out", or none at all."""
        self.send("Emulation.setDeviceMetricsOverride", {
            "width": width, "height": height, "deviceScaleFactor": 1, "mobile": width < 600})
        blank = re.sub(r"/[^/]*$", "/blank.html", url)
        self.send("Page.navigate", {"url": blank})
        self.wait(f"location.href === {json.dumps(blank)} && document.readyState === 'complete'")
        self.ev("(() => { try { %s } catch (e) {} })()" % (
            "localStorage.removeItem('gs:acct');" if acct is None
            else f"localStorage.setItem('gs:acct', {json.dumps(acct)});"))
        self.send("Page.navigate", {"url": url})
        self.wait(f"location.href === {json.dumps(url)} && document.readyState === 'complete'")

    def close(self):
        try:
            self._conn.__exit__(None, None, None)
        finally:
            self.proc.terminate()
            reap(self.proc)


@pytest.fixture(scope="module")
def browser():
    if CHROME is None:
        pytest.skip("no Chromium to run the JS in")
    site = Site()
    site.pages["/pickem.html"] = _doc(pickem_page.body(INDEX, slate()))
    site.pages["/empty.html"] = _doc(pickem_page.body(None, None))
    site.pages["/blank.html"] = "<!doctype html><title>blank</title>"
    tab = Tab()
    try:
        yield tab, site
    finally:
        tab.close()
        site.close()


@pytest.fixture
def page(browser):
    tab, site = browser
    site.api.clear()
    site.log.clear()
    return tab, site


def loaded(tab):
    tab.wait("!!(window.GSPickem && GSPickem.state.known)")


def cards(tab):
    return tab.ev("[...document.querySelectorAll('.pk-g')].map((c) => c.getAttribute('data-id'))")


# --------------------------------------------------------------------------- #
# Markup and the build
# --------------------------------------------------------------------------- #

def test_the_page_reserves_its_room_and_carries_its_week():
    html = pickem_page.body(INDEX, slate())
    assert f'style="min-height:{5 * pickem_page.CARD}px"' in html
    assert pickem_page.CARD == 148, "the card's height + gap in CSS"
    assert ".pk-g{box-sizing:border-box;height:140px;margin:0 0 8px;" in pickem_page.CSS
    assert ".pk-player{box-sizing:border-box;height:112px;overflow:hidden;" in pickem_page.CSS
    assert ".pk-board{min-height:440px}" in pickem_page.CSS
    seed = json.loads(re.search(r'<script type="application/json" id="pk-data">(.*?)</script>',
                                html).group(1))
    assert seed["week"] == 5 and seed["current"] == 5 and len(seed["slate"]["games"]) == 5
    assert [w["w"] for w in seed["weeks"]] == [4, 5]
    assert how.button("pickem") in html and html.count(how.JS_TAG) == 1
    assert "'/assets/js/gs-pickem.js' | fingerprint | relative_url" in html
    assert '"pickem":{"api":"/api/pickem","card":148,' in html
    js = js_assets.source("gs-pickem.js")
    assert "{{" not in js and "{%" not in js and "2026" not in js
    empty = pickem_page.body(None, None)
    assert f'style="min-height:{pickem_page.EMPTY}px"' in empty
    assert "The first slate opens with the NFL season." in empty


def test_the_page_is_written_literal_with_a_description(tmp_path, monkeypatch):
    docs = tmp_path / "pickem"
    (docs / "2026").mkdir(parents=True)
    (docs / "season.json").write_text(json.dumps(INDEX))
    hostile = slate()
    hostile["games"][0]["h"]["nm"] = "{% include evil %}<script>x</script>"
    (docs / "2026" / "week_05.json").write_text(json.dumps(hostile))
    monkeypatch.setattr(pickem_page, "SEASON_FILE", docs / "season.json")
    monkeypatch.setattr(pickem_page, "OUT", docs / "index.html")
    pickem_page.generate()
    doc = (docs / "index.html").read_text()
    assert doc.startswith("---\nlayout: default\ntitle: Pick'em\ndescription: ")
    front, body = doc.split("---\n", 2)[1:]
    assert "pick'em" in front.lower()
    assert body.startswith("{% raw %}<h1>Pick'em</h1>")
    # The seed is JSON inside a script: nothing in a team name can end it.
    assert "<script>x</script>" not in body and "\\u003cscript\\u003e" in body
    assert "page-updated" not in body


def test_home_has_a_small_card_in_season_only():
    from datetime import date

    card = pickem_page.home_card(date(2026, 10, 3))
    assert card.startswith("<section class='home-card pk-home'>") and "href='/pickem/'" in card
    assert "{{" not in card and "{%" not in card and "<script" not in card
    assert pickem_page.home_card(date(2026, 1, 20)) == card
    assert pickem_page.home_card(date(2026, 6, 1)) == ""


def test_home_puts_it_after_the_tweets(tmp_path, monkeypatch):
    from cbb import paths
    from cbb.render import render_home as rh

    monkeypatch.setattr(paths, "WEB_HOME", tmp_path / "index.html")
    monkeypatch.setattr(rh, "_my_teams", lambda today: "")
    rh.render_home()
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    if not pickem_page.home_card():
        pytest.skip("out of season: no card")
    assert html.index('<section class="home-card tw tw-home"') < html.index("pk-home")
    assert html.count("pk-home") == 1


def test_the_daily_run_and_the_live_tick_build_it():
    import inspect

    from cfb import live
    from gordstats import daily

    src = inspect.getsource(daily)
    assert "pickem.generate()" in src
    assert src.index("tweets_page.generate()") < src.index("pickem.generate()") \
        < src.index("profile.generate()")
    assert "pickem.generate()" in inspect.getsource(live)


# --------------------------------------------------------------------------- #
# In the browser
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("width,height", [(390, 844), (1280, 900)])
def test_the_slate_draws_at_once_and_nothing_moves_as_the_api_answers(page, width, height):
    tab, site = page
    for acct, ans in ((None, answer()),
                      ("in", answer(signed_in=True, me={"name": "Reader One"},
                                    mine={"nfl:1": ["h", 5], "nfl:3": ["a", 3]})),
                      ("in", answer(signed_in=True, me=None)),
                      (None, None)):
        site.api[("GET", "/api/pickem")] = (200, ans, 0.7) if ans else (500, {"ok": False}, 0.7)
        tab.open(site.origin + "/pickem.html", width, height, acct=acct)
        measure = ("[document.querySelector('.pk-games').getBoundingClientRect().top, "
                   "document.querySelector('.pk-games').offsetHeight, "
                   "document.querySelector('.pk-player').offsetHeight, "
                   "document.getElementById('below').getBoundingClientRect().top]")
        # Before the API answers, the week is already on the page.
        assert tab.ev("GSPickem.state.known") is False
        assert len(cards(tab)) == 5
        before = tab.ev(measure)
        loaded(tab)
        time.sleep(0.2)
        after = tab.ev(measure)
        assert after == before, (acct, before, after)
        assert tab.ev("window.__cls") < 0.001, (acct, tab.ev("window.__shifts"))
        # Phone first: nothing wider than the screen.
        assert tab.ev("document.scrollingElement.scrollWidth") <= width
    # Sorted by kickoff, earliest first.
    assert cards(tab) == ["nfl:1", "cfb:2", "nfl:3", "cfb:4", "nfl:5"]


def test_signed_out_is_read_only_with_a_sign_in_button(page):
    tab, site = page
    site.api[("GET", "/api/pickem")] = (200, answer())
    tab.open(site.origin + "/pickem.html")
    loaded(tab)
    assert tab.ev("document.querySelector('.pk-player a.pk-btn').getAttribute('href')") == \
        "/api/auth/login?next=%2Fpickem%2F"
    assert tab.ev("[...document.querySelectorAll('.pk-conf')].every((s) => s.disabled)")
    tab.ev("document.querySelector('.pk-g[data-id=\"nfl:3\"] .pk-team[data-side=h]').click()")
    assert "Sign in" in tab.ev("document.querySelector('.pk-msg').textContent")
    assert tab.ev("document.querySelector('.pk-g[data-id=\"nfl:3\"] .pk-team.on')") is None
    time.sleep(0.8)
    assert site.posts("/api/pickem/picks") == []
    # The model's picks and the results show anyway.
    model = tab.ev("document.querySelector('.pk-g[data-id=\"nfl:1\"] .pk-model').textContent")
    assert model == "GordStats: BIL 5 ✓"
    assert "GordStats has 5 this week" in tab.ev("document.querySelector('.pk-player').textContent")
    assert tab.ev("document.querySelector('.pk-g[data-id=\"nfl:1\"] .pk-st').textContent") == "Final"


def test_choosing_a_name_then_playing(page):
    tab, site = page
    site.api[("GET", "/api/pickem")] = (200, answer(signed_in=True, me=None))
    site.api[("POST", "/api/pickem/name")] = (409, {"ok": False, "taken": True,
                                                    "error": "That name is taken - try another."})
    tab.open(site.origin + "/pickem.html", acct="in")
    loaded(tab)
    assert tab.ev("!!document.querySelector('.pk-player form.pk-form .pk-name')")
    # No name yet: a tap asks for one instead of picking.
    tab.ev("document.querySelector('.pk-g[data-id=\"nfl:3\"] .pk-team[data-side=h]').click()")
    assert "Choose a name" in tab.ev("document.querySelector('.pk-msg').textContent")
    tab.ev("document.querySelector('.pk-name').value = 'Roll Tide';"
           "document.querySelector('.pk-form [type=submit]').click()")
    tab.wait("/taken/.test(document.querySelector('.pk-msg').textContent)")
    site.api[("POST", "/api/pickem/name")] = (200, {"ok": True, "saved": True, "name": "Roll Tide 2"})
    tab.ev("document.querySelector('.pk-name').value = 'Roll Tide 2';"
           "document.querySelector('.pk-form [type=submit]').click()")
    tab.wait("/Playing as Roll Tide 2/.test(document.querySelector('.pk-player').textContent)")
    assert site.posts("/api/pickem/name") == [{"name": "Roll Tide"}, {"name": "Roll Tide 2"}]
    assert tab.ev("document.querySelector('.pk-g[data-id=\"nfl:3\"] .pk-conf').disabled") is True
    assert tab.ev("document.querySelector('.pk-g[data-id=\"nfl:3\"] .pk-team').getAttribute("
                  "'aria-disabled')") is None


def test_tapping_picks_and_the_select_swaps_and_every_change_is_saved(page):
    tab, site = page
    mine = {"cfb:2": ["a", 4]}                         # on the game already locked
    site.api[("GET", "/api/pickem")] = (200, answer(signed_in=True, me={"name": "Reader One"},
                                                    mine=mine))
    site.api[("POST", "/api/pickem/picks")] = (
        200, lambda body: {"ok": True, "saved": True, "picks": json.loads(body)["picks"]})
    tab.open(site.origin + "/pickem.html", acct="in")
    loaded(tab)
    card = "document.querySelector('.pk-g[data-id=\"%s\"]')"
    # Locked games take no picks.
    assert tab.ev(f"{card % 'cfb:2'}.querySelector('.pk-team').getAttribute('aria-disabled')") == "true"
    assert tab.ev(f"{card % 'cfb:2'}.querySelector('.pk-conf').disabled") is True
    tab.ev(f"{card % 'cfb:2'}.querySelector('.pk-team[data-side=h]').click()")
    assert "kicked off" in tab.ev("document.querySelector('.pk-msg').textContent")

    # A tap picks with the lowest free value; a second open game gets the next.
    tab.ev(f"{card % 'nfl:3'}.querySelector('.pk-team[data-side=a]').click()")
    tab.ev(f"{card % 'nfl:5'}.querySelector('.pk-team[data-side=h]').click()")
    tab.wait("JSON.stringify(GSPickem.state.mine) === JSON.stringify("
             "{'cfb:2':['a',4],'nfl:3':['a',1],'nfl:5':['h',2]})")
    tab.wait("document.querySelector('.pk-msg').textContent === 'Saved'")
    saved = site.posts("/api/pickem/picks")
    assert saved[-1] == {"season": 2026, "week": 5,
                         "picks": {"cfb:2": ["a", 4], "nfl:3": ["a", 1], "nfl:5": ["h", 2]}}
    assert len(saved) == 1, "two quick taps, one save"

    # The select: 4 sits on a locked game (disabled); 2 sits on an open one (swap).
    opts = tab.ev(f"[...{card % 'nfl:3'}.querySelectorAll('option')].map((o) => "
                  "[o.value, o.textContent, o.disabled, o.selected])")
    assert opts[0][0] == "5" and len(opts) == 5
    by = {o[0]: o for o in opts}
    assert by["4"][1] == "4 · locked" and by["4"][2] is True
    assert by["2"][1] == "2 · swap with FAL at SAI" and by["2"][2] is False
    assert by["1"][3] is True and by["1"][1] == "1"
    tab.ev(f"const s = {card % 'nfl:3'}.querySelector('.pk-conf'); s.value = '2';"
           "s.dispatchEvent(new Event('change', { bubbles: true }));")
    tab.wait("GSPickem.state.mine['nfl:3'][1] === 2 && GSPickem.state.mine['nfl:5'][1] === 1")
    tab.wait("document.querySelector('.pk-msg').textContent === 'Saved'")
    assert site.posts("/api/pickem/picks")[-1]["picks"] == {
        "cfb:2": ["a", 4], "nfl:3": ["a", 2], "nfl:5": ["h", 1]}
    # A value held by a locked game cannot be taken, even by script.
    tab.ev("GSPickem.setConf('nfl:3', 4)")
    assert tab.ev("GSPickem.state.mine['nfl:3'][1]") == 2
    # Tapping the picked team again takes the pick back.
    tab.ev(f"{card % 'nfl:5'}.querySelector('.pk-team[data-side=h]').click()")
    tab.wait("!GSPickem.state.mine['nfl:5']")
    tab.wait("document.querySelector('.pk-msg').textContent === 'Saved'")
    assert site.posts("/api/pickem/picks")[-1]["picks"] == {"cfb:2": ["a", 4], "nfl:3": ["a", 2]}


def test_a_refused_save_shows_the_servers_picks(page):
    tab, site = page
    site.api[("GET", "/api/pickem")] = (200, answer(signed_in=True, me={"name": "Reader One"},
                                                    mine={"nfl:3": ["h", 3]}))
    site.api[("POST", "/api/pickem/picks")] = (409, {
        "ok": False, "error": "A game has kicked off since - its pick is locked and was not changed.",
        "picks": {"nfl:3": ["h", 3], "cfb:4": ["a", 1]}})
    tab.open(site.origin + "/pickem.html", acct="in")
    loaded(tab)
    tab.ev("document.querySelector('.pk-g[data-id=\"nfl:5\"] .pk-team[data-side=a]').click()")
    tab.wait("/kicked off/.test(document.querySelector('.pk-msg').textContent)")
    assert tab.ev("GSPickem.state.mine") == {"nfl:3": ["h", 3], "cfb:4": ["a", 1]}
    assert tab.ev("!!document.querySelector('.pk-g[data-id=\"cfb:4\"] .pk-team.on[data-side=a]')")


def test_locks_follow_the_servers_clock(page):
    tab, site = page
    # The server says it is two days later than this browser thinks.
    later = int(time.time() * 1000) + 60 * 3600 * 1000
    site.api[("GET", "/api/pickem")] = (200, answer(signed_in=True, me={"name": "Reader One"},
                                                    now_ms=later))
    tab.open(site.origin + "/pickem.html", acct="in")
    loaded(tab)
    assert tab.ev("[...document.querySelectorAll('.pk-g')].every((c) => "
                  "c.querySelector('.pk-team').getAttribute('aria-disabled') === 'true')")
    tab.ev("document.querySelector('.pk-g[data-id=\"nfl:5\"] .pk-team').click()")
    time.sleep(0.8)
    assert site.posts("/api/pickem/picks") == []


def test_the_leaderboards_mark_the_model_and_the_reader(page):
    tab, site = page
    site.api[("GET", "/api/pickem")] = (200, answer(signed_in=True, me={"name": "Reader One"}))
    tab.open(site.origin + "/pickem.html", acct="in")
    loaded(tab)
    tab.ev("document.getElementById('pk-t-board').click()")
    assert tab.ev("[document.getElementById('pk-p-board').hidden, "
                  "document.getElementById('pk-p-picks').hidden]") == [False, True]
    rows = tab.ev("[...document.querySelectorAll('.pk-tbl tbody tr')].map((r) => "
                  "[r.className, r.querySelector('.nm').textContent, "
                  "r.cells[2].textContent, r.cells[3].textContent, r.cells[4].textContent])")
    assert rows == [["gs", "GordStatsModel", "5", "1/1", "15"],
                    ["me", "Reader OneYou", "0", "0/1", "9"]]
    tab.ev("document.querySelector('.pk-which [data-b=season]').click()")
    rows = tab.ev("[...document.querySelectorAll('.pk-tbl tbody tr')].map((r) => "
                  "[r.className, r.querySelector('.nm').textContent, r.cells[4].textContent])")
    assert rows == [["", "Alpha", "1"], ["gs", "GordStatsModel", "2"]]


def test_past_weeks_open_in_place(page):
    tab, site = page
    site.api[("GET", "/api/pickem")] = (200, answer())
    old = answer(week=4)
    old["slate"] = slate(4, [g("nfl:11", -200, res="a", st="post", gs=("h", 2, 0.6),
                               home="Jets", away="Bears", score={"h": 10, "a": 20}),
                             g("nfl:12", -199, res="v", st="post", gs=("a", 1, 0.5))])
    site.api[("GET", "/api/pickem?week=4")] = (200, old)
    site.api[("GET", "/api/pickem?week=5")] = (200, answer())
    tab.open(site.origin + "/pickem.html")
    loaded(tab)
    tab.ev("document.getElementById('pk-t-past').click()")
    items = tab.ev("[...document.querySelectorAll('.pk-past button')].map((b) => b.textContent)")
    assert items == ["Week 4 NFL Week 4Winner: Alpha 7 · GordStats 4 · 3 players"]
    tab.ev("document.querySelector('.pk-past button').click()")
    tab.wait("GSPickem.state.week === 4")
    assert tab.ev("document.getElementById('pk-p-picks').hidden") is False
    assert cards(tab) == ["nfl:11", "nfl:12"]
    assert tab.ev("document.querySelector('.pk-wk-t').textContent") == "Week 4"
    assert tab.ev("[document.querySelector('.pk-prev').disabled, "
                  "document.querySelector('.pk-next').disabled]") == [True, False]
    assert tab.ev("document.querySelector('.pk-g[data-id=\"nfl:12\"] .pk-st').textContent") == \
        "No contest"
    assert tab.ev("document.querySelector('.pk-g[data-id=\"nfl:11\"] .pk-model').textContent") == \
        "GordStats: JET 2 ✗"
    tab.ev("document.querySelector('.pk-next').click()")
    tab.wait("GSPickem.state.week === 5")


def test_names_and_labels_are_drawn_as_text(page):
    tab, site = page
    evil = answer(signed_in=True, me={"name": "<img src=x onerror=window.__xss=1>"})
    evil["slate"]["games"][2]["h"]["nm"] = '<img src=x onerror="window.__xss=2">'
    evil["slate"]["games"][2]["h"]["lg"] = "javascript:alert(1)"
    evil["slate"]["games"][2]["tv"] = "</span><script>window.__xss=3</script>"
    evil["board"]["week"][1]["name"] = "<b onmouseover=x>bold</b>"
    evil["slate"]["games"].append({"id": "nfl:9 onclick=x", "ko": "x"})
    site.api[("GET", "/api/pickem")] = (200, evil)
    tab.open(site.origin + "/pickem.html", acct="in")
    loaded(tab)
    tab.ev("document.getElementById('pk-t-board').click()")
    assert tab.ev("window.__xss || null") is None
    assert tab.ev("document.querySelectorAll('.pk img[src=x], .pk script, .pk b[onmouseover]')"
                  ".length") == 0
    assert tab.ev("document.querySelector('.pk-g[data-id=\"nfl:3\"] .pk-team[data-side=h] img')"
                  ".getAttribute('src')") is None
    assert len(cards(tab)) == 5, "a game with a bad id is dropped"
    assert "<img src=x" in tab.ev("document.querySelector('.pk-player b').textContent")


def test_an_empty_season_says_so(page):
    tab, site = page
    site.api[("GET", "/api/pickem")] = (200, {"ok": True, "configured": True, "season": None,
                                              "current": None, "week": None, "weeks": [],
                                              "slate": None, "board": {"week": [], "season": []},
                                              "now": int(time.time() * 1000), "signedIn": False})
    tab.open(site.origin + "/empty.html")
    loaded(tab)
    assert "first slate" in tab.ev("document.querySelector('.pk-games').textContent")
    assert tab.ev("document.querySelector('.pk-games').offsetHeight") == pickem_page.EMPTY
