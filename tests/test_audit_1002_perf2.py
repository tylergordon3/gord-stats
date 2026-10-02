"""The matchups pages carry one week, and the median tracker folds on a phone
(2026-10-02 audit, performance).

Both matchups pages carried every week of the season inline, all but one
hidden: 1.4 MB and 27,000 elements by week 5, on course for ~5 MB and 90,000
by the fantasy playoffs - on a phone, to show one week. Now only the week the
page opens on is in it; the rest are fragments beside it
(gordstats.matchup_page.week_switch(src=...) / write_weeks), fetched when a
tab is tapped or a #wk-N / #wkN-mM address is opened, and given what the page
does to the inline week on load: phone folds, the median tracker.

The Median Tracker was 1,900-2,300px of a phone before the first matchup
while a week was on, three quarters of it each team's need line and players.
Those now fold behind the team's name on a phone, and a team the reader opened
stays open through the live poll's redraws.

The browser tests run the real scripts in headless Chromium (DevTools port
9494) against pages served from a temporary directory.
"""
import asyncio
import functools
import http.server
import json
import shutil
import socketserver
import threading
import time
import urllib.request

import pytest

from browser_util import launch, reap
from gordstats import matchup_page as ui

CHROME = next((p for p in ("/usr/bin/chromium-browser", "/usr/bin/chromium",
                           "/usr/bin/google-chrome") if shutil.which(p)), None)
CDP = 9494
SRC = "/m/week-%s"


# --------------------------------------------------------------------------- #
# A season to page through
# --------------------------------------------------------------------------- #

def _tracker(week: int, live: bool) -> str:
    teams = [{"k": f"k{i}", "name": f"Team {i}", "logo": "", "pts": 10.0 * i if live else 0.0,
              "exp": 100.0 + i,
              "left": [{"n": f"P{i}a", "r": 12.0, "live": live, "pos": "RB", "p": 0},
                       {"n": f"P{i}b", "r": 8.0, "live": False, "pos": "WR", "p": 0}]}
             for i in range(1, 11)]
    return ui.median_tracker(teams, week, live, False,
                             {"max": {"RB": 50, "WR": 50}, "min": {"RB": 0, "WR": 0}})


def _view(week: int, live: bool = False) -> str:
    """A week's view as the pages draw one: its line, tracker and five matchups."""
    secs = "".join(
        f'<details class="section" id="wk{week}-m{i}" open><summary>Matchup {i}</summary>'
        f'<div class="mu-head"><b data-num="k{i}a" data-mu="wk{week}-m{i}">{week}.{i}</b>'
        f'<b data-num="k{i}b" data-mu="wk{week}-m{i}">0</b></div>'
        f'<p style="height:600px">week {week} matchup {i}</p></details>'
        for i in range(1, 6))
    return f"<p><strong>Week {week}</strong></p>" + _tracker(week, live) + secs


def _page(weeks, current) -> str:
    views = {w: _view(w, live=w == current) for w in weeks}
    return ("<!doctype html><html><head><meta charset='utf-8'>"
            "<meta name=viewport content='width=device-width'></head><body>"
            + ui.CSS + ui.week_switch(weeks, current, views, src=SRC)
            + ui.MEDIAN_TRACKER_JS + "</body></html>"), views


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    root = tmp_path_factory.mktemp("perf2")
    html, views = _page([1, 2, 3, 4, 5], 5)
    (root / "m").mkdir()
    (root / "m" / "index.html").write_text(html, encoding="utf-8")
    ui.write_weeks(root / "m", views, 5)
    # A page with every week inline (the NFL schedule and predictions), which
    # wraps show_wk the way the schedule's live poll does.
    (root / "p").mkdir()
    (root / "p" / "index.html").write_text(
        "<!doctype html><html><body>"
        + ui.week_switch([1, 2, 3], 3, {w: f"<p>plain week {w}</p>" for w in (1, 2, 3)})
        + "<script>var show=window.show_wk;window.POLLS=0;"
        "window.show_wk=function(w){show(w);POLLS++;};</script></body></html>", encoding="utf-8")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a: None
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield {"root": root, "url": f"http://127.0.0.1:{server.server_address[1]}/m/"}
    server.shutdown()


class Tab:
    """One Chromium page on DevTools port CDP, kept open across calls."""

    def __init__(self):
        self.proc = launch(CHROME, CDP)
        self.ws_url = None
        for _ in range(100):
            try:
                self.ws_url = next(t["webSocketDebuggerUrl"] for t in json.load(
                    urllib.request.urlopen(f"http://127.0.0.1:{CDP}/json"))
                    if t.get("type") == "page")
                break
            except Exception:                                   # noqa: BLE001
                time.sleep(0.1)
        if not self.ws_url:
            self.close()
            raise RuntimeError("Chromium did not come up")
        self.loop = asyncio.new_event_loop()
        import websockets
        self.ws = self.loop.run_until_complete(websockets.connect(self.ws_url, max_size=None))
        self.n = 0
        self.send("Page.enable")

    def send(self, method, **params):
        self.n += 1
        me = self.n

        async def go():
            await self.ws.send(json.dumps({"id": me, "method": method, "params": params}))
            while True:
                msg = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=30))
                if msg.get("id") == me:
                    return msg.get("result", {})
        return self.loop.run_until_complete(go())

    def goto(self, url, width=1200, before=""):
        self.send("Emulation.setDeviceMetricsOverride", width=width, height=900,
                  deviceScaleFactor=1, mobile=width < 700)
        if before:
            self.send("Page.addScriptToEvaluateOnNewDocument", source=before)
        self.send("Page.navigate", url="about:blank")
        self.send("Page.navigate", url=url)
        ready = f"location.href==={json.dumps(url)}&&document.readyState==='complete'"
        for _ in range(100):
            if self.ev(ready):
                break
            time.sleep(0.05)
        time.sleep(0.3)

    def ev(self, expression):
        r = self.send("Runtime.evaluate", expression=expression, returnByValue=True,
                      awaitPromise=True)
        assert "exceptionDetails" not in r, r["exceptionDetails"]
        return r["result"].get("value")

    def close(self):
        try:
            self.loop.run_until_complete(self.ws.close())
        except Exception:                                       # noqa: BLE001
            pass
        self.proc.terminate()
        reap(self.proc)


@pytest.fixture
def tab():
    if CHROME is None:
        pytest.skip("no Chromium to run the JS in")
    t = Tab()
    try:
        yield t
    finally:
        t.close()


def _week(tab, w):
    return tab.ev(
        "(function(){var v=document.getElementById('wk-view-" + str(w) + "');return {"
        "shown:v.style.display!=='none',src:v.getAttribute('data-src'),"
        "heads:v.querySelectorAll('.mu-head').length,rows:v.querySelectorAll('.mu-medt-row').length,"
        "open:[].filter.call(v.querySelectorAll('details.section[id]'),function(d){return d.open;})"
        ".map(function(d){return d.id;}),tab:(document.querySelector('.wk-btn.active')||{}).id,"
        "hash:location.hash};})()")


# --------------------------------------------------------------------------- #
# The page and its fragments
# --------------------------------------------------------------------------- #

def test_only_the_current_week_is_in_the_page(tmp_path):
    html, views = _page([1, 2, 3], 3)
    assert "week 3 matchup 1" in html
    assert "week 1 matchup 1" not in html and "week 2 matchup 1" not in html
    assert "<div id=\"wk-view-1\" class=\"wk-view\" style='display:none' data-src='/m/week-1'></div>" in html
    # Without JavaScript the other weeks are links to their fragments.
    assert '<noscript><p class="mu-note">Other weeks: <a href="/m/week-1">Week 1</a>' in html
    assert ui.write_weeks(tmp_path, views, 3) == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == ["week-1.html", "week-2.html"]
    assert (tmp_path / "week-1.html").read_text() == views[1], "a bare fragment, no front matter"
    assert ui.write_weeks(tmp_path, views, 3) == 0, "an unchanged week is not rewritten"
    views[2] += "<p>later</p>"
    assert ui.write_weeks(tmp_path, views, 3) == 1


def test_without_a_source_every_week_is_inline_as_before():
    """NFL schedule and predictions share week_switch and keep every week."""
    html = ui.week_switch([1, 2], 2, {1: "<p>one</p>", 2: "<p>two</p>"})
    assert ("<div id=\"wk-view-1\" class=\"wk-view\" style='display:none'><p>one</p></div>"
            '<div id="wk-view-2" class="wk-view"><p>two</p></div>') in html
    assert "data-src" not in html.split("<script>")[0] and "<noscript>" not in html


def test_both_pages_write_the_other_weeks_beside_themselves(tmp_path, monkeypatch):
    from cfb.site import matchups as cfb
    from fantasy import paths
    from fantasy.site import matchups as nfl
    views = {1: "<p>one</p>", 2: "<p>two</p>", 3: "<p>three</p>"}
    assert cfb.WEEK_URL == "/cfb/matchups/week-%s"
    assert nfl.WEEK_URL == "/fantasy/matchups/week-%s"

    monkeypatch.setattr(cfb, "build", lambda: ("<p>page</p>", views))
    monkeypatch.setattr(cfb, "OUTPUT", tmp_path / "cfb" / "index.html")
    monkeypatch.setattr(cfb, "write_page", lambda *a, **k: None)
    monkeypatch.setattr(cfb, "_CARDS", {"current": 3})
    cfb.generate()
    assert sorted(p.name for p in (tmp_path / "cfb").iterdir()) == ["week-1.html", "week-2.html"]

    monkeypatch.setattr(nfl, "build", lambda: ("<p>page</p>", views))
    monkeypatch.setattr(paths, "WEB_MATCHUPS", tmp_path / "nfl" / "index.html")
    monkeypatch.setattr(nfl, "_CARDS", {"current": 2})
    nfl.generate()
    assert sorted(p.name for p in (tmp_path / "nfl").iterdir()) == [
        "index.html", "week-1.html", "week-3.html"]
    assert (tmp_path / "nfl" / "week-3.html").read_text() == "<p>three</p>"


def test_only_the_week_the_page_opens_on_polls():
    """A fetched fragment's scripts never run; the college page's other
    unfinished weeks no longer carry a live script into their fragments."""
    import inspect
    from cfb.site import matchups as cfb
    src = inspect.getsource(cfb.week_view)
    assert 'live = ("" if final or not poll else' in src
    assert "poll=w == current" in inspect.getsource(cfb.build)


# --------------------------------------------------------------------------- #
# In the browser
# --------------------------------------------------------------------------- #

def test_a_tab_fetches_its_week_and_draws_its_tracker(tab, site):
    tab.goto(site["url"])
    assert _week(tab, 5)["heads"] == 5 and _week(tab, 1)["src"] == "/m/week-1"
    assert tab.ev("document.querySelectorAll('.mu-head').length") == 5, "one week in the page"
    tab.ev("show_wk('1').then(function(){return 1;})")
    w1 = _week(tab, 1)
    assert w1["shown"] and w1["src"] is None and w1["heads"] == 5
    assert w1["rows"] == 10, "the fetched week's median tracker is drawn"
    assert (w1["tab"], w1["hash"]) == ("wk-tab-1", "#wk-1")
    assert not _week(tab, 5)["shown"]
    # Back to the week being played: nothing fetched again.
    tab.ev("show_wk('5').then(function(){return 1;})")
    assert _week(tab, 5)["shown"] and not _week(tab, 1)["shown"]
    assert _week(tab, 1)["heads"] == 5


def test_an_address_opens_its_week_and_its_matchup(tab, site):
    tab.goto(site["url"] + "#wk-2")
    w2 = _week(tab, 2)
    assert w2["shown"] and w2["heads"] == 5 and w2["hash"] == "#wk-2"
    tab.goto(site["url"] + "#wk3-m4")
    for _ in range(40):
        if _week(tab, 3)["heads"]:
            break
        time.sleep(0.05)
    w3 = _week(tab, 3)
    assert w3["shown"] and w3["hash"] == "#wk3-m4", "a matchup's address is kept"
    assert "wk3-m4" in w3["open"]
    top = tab.ev("document.getElementById('wk3-m4').getBoundingClientRect().top")
    assert 0 <= top < 100, "and scrolled to"
    # A link to another week's matchup from the page.
    tab.ev("location.hash='#wk1-m2';1")
    time.sleep(0.5)
    w1 = _week(tab, 1)
    assert w1["shown"] and "wk1-m2" in w1["open"]


def test_a_fetched_week_folds_on_a_phone_like_the_inline_one(tab, site):
    tab.goto(site["url"], width=390)
    assert _week(tab, 5)["open"] == ["wk5-m1"], "the inline week: the first matchup"
    tab.ev("show_wk('2').then(function(){return 1;})")
    assert _week(tab, 2)["open"] == ["wk2-m1"], "a fetched week folds the same way"
    tab.goto(site["url"], width=390, before="localStorage.setItem('nflMyTeam','k3b');")
    tab.ev("show_wk('4').then(function(){return 1;})")
    assert _week(tab, 4)["open"] == ["wk4-m3"], "the reader's own matchup"
    assert _week(tab, 5)["open"] == ["wk5-m3"]


def test_a_week_that_will_not_load_says_so_and_can_be_tried_again(tab, site):
    frag = site["root"] / "m" / "week-2.html"
    kept = frag.read_text()
    frag.unlink()
    try:
        tab.goto(site["url"])
        tab.ev("show_wk('2').then(function(){return 1;})")
        assert "could not be loaded" in tab.ev("document.getElementById('wk-view-2').textContent")
        assert _week(tab, 2)["src"] == "/m/week-2"
    finally:
        frag.write_text(kept)
    tab.ev("show_wk('2').then(function(){return 1;})")
    assert _week(tab, 2)["heads"] == 5


def test_three_fetched_weeks_are_kept_and_an_evicted_one_comes_back(tab, site):
    tab.goto(site["url"])
    tab.ev("show_wk('1').then(function(){return show_wk('2');}).then(function(){return show_wk('3');})"
           ".then(function(){return show_wk('4');}).then(function(){return 1;})")
    assert _week(tab, 1)["src"] == "/m/week-1", "the oldest fetched week is dropped"
    assert all(_week(tab, w)["heads"] == 5 for w in (2, 3, 4, 5))
    tab.ev("show_wk('1').then(function(){return 1;})")
    assert _week(tab, 1)["heads"] == 5 and _week(tab, 1)["shown"]


FOLDS = ("(function(){var v=document.getElementById('wk-view-5');"
         "return [].map.call(v.querySelectorAll('.mu-medt-more'),function(d){return d.open?1:0;}).join('');})()")


def test_the_tracker_folds_each_team_on_a_phone(tab, site):
    tab.goto(site["url"], width=390)
    assert tab.ev("document.querySelector('#wk-view-5 .mu-medt-sec').open"), \
        "the tracker itself opens while the week is on"
    assert tab.ev(FOLDS) == "0" * 10
    assert tab.ev("document.querySelector('#wk-view-5 .mu-medt-ps').checkVisibility()") is False
    h = tab.ev("document.querySelector('#wk-view-5 .mu-medt').getBoundingClientRect().height")
    # Opened by its name, and kept open through a live redraw.
    tab.ev("document.querySelectorAll('#wk-view-5 .mu-medt-more>summary')[2].click();1")
    time.sleep(0.2)
    assert tab.ev(FOLDS) == "0010000000"
    tab.ev("muMedTrack.update(5,{teams:{k1:{points:90,left:[{n:'P1a',r:3,live:true,pos:'RB',p:20}]}}},"
           "document.getElementById('wk-view-5'));1")
    time.sleep(0.2)
    assert tab.ev(FOLDS).count("1") == 1
    opened = tab.ev("document.querySelector('#wk-view-5 .mu-medt-more[open]').getAttribute('data-mt')")
    assert opened.endswith("|5|k8"), "the same team, wherever the update moved it"
    assert tab.ev("JSON.parse(document.querySelector('#wk-view-5 [data-medt]')"
                  ".getAttribute('data-medt')).teams[0].pts") == 90, "the update was drawn"
    assert h < 900


def test_the_tracker_reads_as_before_on_a_wider_screen(tab, site):
    tab.goto(site["url"])
    assert tab.ev(FOLDS) == "1" * 10
    assert tab.ev("getComputedStyle(document.querySelector('#wk-view-5 .mu-medt-more>summary'))"
                  ".pointerEvents") == "none"
    text = tab.ev("document.querySelector('#wk-view-5 .mu-medt').innerText")
    assert "Needs" in text and "hypothetical max" in text and "P1a 12.0" in text


def test_init_draws_only_inside_the_root_it_is_given(tab, site):
    tab.goto(site["url"])
    tab.ev("show_wk('3').then(function(){return 1;})")
    got = tab.ev("(function(){var a=document.querySelector('#wk-view-5 .mu-medt'),"
                 "b=document.querySelector('#wk-view-3 .mu-medt');a.innerHTML='';b.innerHTML='';"
                 "muMedTrack.init(document.getElementById('wk-view-3'));"
                 "return [a.children.length,b.children.length];})()")
    assert got == [0, 12]


def test_a_page_with_every_week_inline_switches_as_before(tab, site):
    url = site["url"].replace("/m/", "/p/")
    tab.goto(url + "#wk-2")
    assert tab.ev("[1,2,3].map(function(w){return document.getElementById('wk-view-'+w).style.display;})"
                  ".join(',')") == "none,,none"
    got = tab.ev("show_wk('1');[document.getElementById('wk-view-1').style.display,"
                 "document.getElementById('wk-view-2').style.display,POLLS,location.hash,"
                 "document.querySelector('.wk-btn.active').id].join(',')")
    assert got == ",none,1,#wk-1,wk-tab-1", "shown at once, the page's own wrapper still runs"
