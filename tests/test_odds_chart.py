"""
Playoff and title odds over the season (gordstats.odds_chart) on both fantasy
Power pages: one point a week - the last build of it - read back from the
snapshots the pages already keep, the reader's team picked out.

The browser half (docs/assets/js/gs-odds-chart.js) runs in headless Chromium
on CDP port 9496.
"""
import asyncio
import functools
import http.server
import json
import shutil
import socketserver
import subprocess
import tempfile
import threading
import time
import urllib.request
from datetime import datetime, timedelta
from html.parser import HTMLParser

import pandas as pd
import pytest

from gordstats import odds_chart as oc

D = datetime


def _rows(snaps):
    """[(taken, week, {key: (playoff, title)})] -> the long frame by_week reads."""
    return pd.DataFrame([{"taken": t, "week": w, "key": k, "playoff": p, "title": ti}
                         for t, w, odds in snaps for k, (p, ti) in odds.items()])


SNAPS = [
    (D(2026, 9, 8, 23), 0, {"a": (0.60, 0.10), "b": (0.50, 0.08)}),
    (D(2026, 9, 12, 5), 0, {"a": (0.62, 0.11), "b": (0.48, 0.07)}),   # last of week 0
    (D(2026, 9, 14, 5), 1, {"a": (0.70, 0.15), "b": (0.40, 0.05)}),
    (D(2026, 9, 19, 5), 1, {"a": (0.72, 0.16), "b": (0.39, 0.05)}),   # last of week 1
    (D(2026, 9, 22, 5), 2, {"a": (0.90, 0.30)}),                       # b left out
]


# --------------------------------------------------------------------------- #
# One point a week
# --------------------------------------------------------------------------- #

def test_each_week_is_its_last_build():
    data = oc.by_week(_rows(SNAPS))
    assert data["weeks"] == [0, 1, 2]
    assert data["playoff"]["a"] == [0.62, 0.72, 0.90]
    assert data["title"]["a"] == [0.11, 0.16, 0.30]
    assert data["taken"][1] == D(2026, 9, 19, 5)


def test_a_team_a_snapshot_left_out_is_a_gap_not_a_zero():
    assert oc.by_week(_rows(SNAPS))["playoff"]["b"] == [0.48, 0.39, None]


def test_nothing_to_draw():
    assert oc.by_week(pd.DataFrame()) is None
    assert oc.by_week(None) is None
    # Old CFB snapshots carry rank only: no odds, no point.
    old = pd.DataFrame({"taken": [D(2026, 9, 1)], "week": [0], "key": ["a"],
                        "playoff": [float("nan")], "title": [float("nan")]})
    assert oc.by_week(old) is None


def test_a_build_belongs_to_the_last_week_that_had_kicked_off():
    starts = [(1, D(2026, 9, 3, 18)), (2, D(2026, 9, 10, 20)), (3, None)]
    assert oc.week_of(D(2026, 9, 2, 12), starts) == 0          # the draft
    assert oc.week_of(D(2026, 9, 3, 18), starts) == 1          # the first kickoff
    assert oc.week_of(D(2026, 9, 8, 5), starts) == 1           # a window's first day, 5am
    assert oc.week_of(D(2026, 9, 11, 9), starts) == 2


# --------------------------------------------------------------------------- #
# The drawing
# --------------------------------------------------------------------------- #

class _Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def _tags(html, tag=None, cls=None):
    p = _Tags()
    p.feed(html)
    return [a for t, a in p.tags if (tag is None or t == tag)
            and (cls is None or cls in (a.get("class") or "").split())]


NAMES = {"a": "Alice", "b": "Bob"}


def test_the_readers_team_is_drawn_last_with_a_dot_a_week():
    data = oc.by_week(_rows(SNAPS))
    html = oc.section(data, NAMES, mine="b", storage="nflMyTeam", sid="t")
    playoff = html.split('class="oc-fig oc-fp"')[1].split("</figure>")[0]
    lines = _tags(playoff, "polyline", "oc-ln")
    assert [ln["data-k"] for ln in lines] == ["a", "b"]          # b on top
    assert "oc-on" in lines[-1]["class"] and "oc-on" not in lines[0]["class"]
    # b has two of the three weeks: two dots, and its end value.
    assert len(_tags(playoff, "span", "oc-dot")) == 2
    assert ">39%</span>" in playoff
    box = _tags(html, "div", "oc")[0]
    assert box["data-on"] == "b" and box["data-store"] == "nflMyTeam"
    assert 'value="b" selected' in html


def test_an_unknown_team_falls_back_to_the_leader():
    html = oc.section(oc.by_week(_rows(SNAPS)), NAMES, mine="zz")
    assert _tags(html, "div", "oc")[0]["data-on"] == "a"


def test_the_story_is_told_in_words_too():
    html = oc.section(oc.by_week(_rows(SNAPS)), NAMES, mine="a")
    assert "Biggest riser since the preseason: <strong>Alice</strong>, 62%\u00a0\u2192\u00a090%." in html
    # Bob's last point is a gap: his change runs to the last week he has.
    plot = _tags(html, "div", "oc-plot")[0]
    assert "Biggest riser since the preseason: Alice, 62%\u00a0\u2192\u00a090%." in plot["aria-label"]


def test_the_title_chart_is_cut_to_the_leader():
    assert oc.scale([0.31, 0.05]) == (0.4, 0.1)
    assert oc.scale([0.12]) == (0.2, 0.05)
    assert oc.scale([0.99]) == (1.0, 0.25)
    html = oc.section(oc.by_week(_rows(SNAPS)), NAMES, mine="a")
    title = html.split('class="oc-fig oc-ft"')[1]
    assert ">40%</span>" in title and ">100%</span>" not in title


def test_a_week_still_being_played_has_a_hollow_dot_and_says_so():
    html = oc.section(oc.by_week(_rows(SNAPS)), NAMES, mine="a", live=True)
    playoff = html.split('class="oc-fig oc-fp"')[1].split("</figure>")[0]
    dots = _tags(playoff, "span", "oc-dot")
    assert ["oc-live" in d["class"] for d in dots] == [False, False, True]
    assert "Week 2 is still being played" in playoff
    assert "data-live" in html


def test_a_seasons_labels_thin_out_on_a_phone_but_never_the_last():
    snaps = [(D(2026, 9, 1) + timedelta(days=7 * w), w, {"a": (0.5, 0.1)}) for w in range(15)]
    html = oc.section(oc.by_week(_rows(snaps)), {"a": "Alice"}, mine="a")
    labels = _tags(html.split('class="oc-fig oc-fp"')[1].split("</figure>")[0], "span", "oc-x")
    thin = ["oc-x2" in x["class"] for x in labels]
    assert len(labels) == 15 and thin[-1] is False and thin[1] is True and thin[0] is False


def test_names_and_long_shots_are_escaped():
    snaps = [(D(2026, 9, 1), 0, {"a": (0.5, 0.003)}), (D(2026, 9, 8), 1, {"a": (0.999, 0.002)})]
    html = oc.section(oc.by_week(_rows(snaps)), {"a": "<b>{{x}}</b>"}, mine="a")
    assert "<b>{{x}}</b>" not in html and "&lt;b&gt;" in html
    assert "&lt;1%" in html and "&gt;99%" in html
    assert "<1%" not in html.replace("&lt;1%", "")


def test_one_week_is_not_a_chart_yet():
    html = oc.section(oc.by_week(_rows(SNAPS[:2])), NAMES, mine="a")
    assert "oc-plot" not in html and "first week is played" in html


def test_the_page_carries_the_script_by_its_hashed_url():
    assert "gs-odds-chart.js" in oc.JS_TAG and "fingerprint" in oc.JS_TAG
    assert "localStorage" in oc.JS


# --------------------------------------------------------------------------- #
# The two adapters
# --------------------------------------------------------------------------- #

def test_nfl_ends_on_this_builds_table(monkeypatch):
    """The archive skips a build within six hours of the last; the chart's
    end must still agree with the table printed above it."""
    from fantasy.site import power as page
    hist = pd.DataFrame([
        {"taken": D(2026, 9, 13, 11), "week": 0, "roster_id": 1, "manager": "Tyler",
         "playoff_odds": 0.6, "title_odds": 0.1},
        {"taken": D(2026, 9, 13, 11), "week": 0, "roster_id": 2, "manager": "Max",
         "playoff_odds": 0.5, "title_odds": 0.1},
        {"taken": D(2026, 9, 20, 5), "week": 1, "roster_id": 1, "manager": "Tyler",
         "playoff_odds": 0.7, "title_odds": 0.2},
        {"taken": D(2026, 9, 20, 5), "week": 1, "roster_id": 2, "manager": "Max",
         "playoff_odds": 0.4, "title_odds": 0.05},
    ])
    monkeypatch.setattr(page.power, "history", lambda year: hist)
    table = pd.DataFrame({"roster_id": [1, 2], "manager": ["Tyler", "Max"], "week": [1, 1],
                          "playoff_odds": [0.75, 0.35], "title_odds": [0.25, 0.04]})
    html = page._odds_section(table)
    from gordstats import how
    assert (f"<h3>Playoff and title odds {how.button('fantasy-stakes')}</h3>" in html
            and "gs-odds-chart.js" in html)
    box = _tags(html, "div", "oc")[0]
    assert box["data-on"] == "1" and box["data-store"] == "nflMyTeam"   # MY_MANAGER
    assert ">75%</span>" in html and "60%\u00a0\u2192\u00a075%" in html


def _matchups(tmp_path, weeks):
    for w, start, end in weeks:
        (tmp_path / f"week_{w:02d}.json").write_text(
            json.dumps({"week": w, "week_start": start, "week_end": end}))


def test_cfb_weeks_open_at_their_first_kickoff(tmp_path, monkeypatch):
    from cfb.site import league_power as lp
    _matchups(tmp_path, [(1, "2026-09-03", "2026-09-07"), (2, "2026-09-08", "2026-09-12")])
    monkeypatch.setattr(lp.yahoo, "MATCHUPS_DIR", tmp_path)
    games = pd.DataFrame({"date_utc": ["2026-09-03T22:00Z", "2026-09-06T16:00Z",
                                       "2026-08-29T16:00Z"]})   # the last: before week 1
    monkeypatch.setattr(lp.espn, "schedule", lambda **kw: games)
    starts = lp.week_starts()
    assert starts[0] == (1, D(2026, 9, 3, 18), D(2026, 9, 7).date())    # 22:00Z = 18:00 ET
    # No game on record in week 2's window: noon on its first day.
    assert starts[1] == (2, D(2026, 9, 8, 12), D(2026, 9, 12).date())


def test_cfb_points_and_the_week_in_progress(tmp_path, monkeypatch):
    from cfb.site import league_power as lp
    hist_dir = tmp_path / "hist"
    hist_dir.mkdir()
    keys = ["474.l.1.t.1", "474.l.1.t.2"]
    for stamp, odds in (("20260902-120000", (0.80, 0.20)), ("20260908-050000", (0.90, 0.30)),
                        ("20260911-120000", (0.50, 0.10))):
        pd.DataFrame({"key": keys, "rank": [1, 2], "team": ["Puntaholics", "Other"],
                      "playoffs": [odds[0], 1 - odds[0]], "title": [odds[1], 0.05]}
                     ).to_csv(hist_dir / f"{stamp}.csv", index=False)
    monkeypatch.setattr(lp, "HISTORY_DIR", hist_dir)
    monkeypatch.setattr(lp, "week_starts", lambda: [
        (1, D(2026, 9, 3, 18), D(2026, 9, 7).date()),
        (2, D(2026, 9, 10, 20), D(2026, 9, 12).date())])
    rows = [{"key": k, "team": {"name": n}, "sim": {"playoffs": p, "title": t}}
            for k, n, p, t in ((keys[0], "Puntaholics", 0.6, 0.15), (keys[1], "Other", 0.4, 0.1))]
    html = lp._odds_section(rows, True, now=D(2026, 9, 11, 21))
    playoff = html.split('class="oc-fig oc-fp"')[1].split("</figure>")[0]
    on = [ln for ln in _tags(playoff, "polyline", "oc-ln") if "oc-on" in ln["class"]][0]
    assert on["data-k"] == keys[0]                                     # MY_TEAM
    # Pre (Sep 2), after week 1 (Sep 8, before week 2's kickoff), and week 2
    # so far: this build's 60%, not the 50% snapshot it supersedes.
    assert len(on["points"].split()) == 3 and on["data-end"] == "60%"
    assert "Week 2 is still being played" in playoff
    # Once the window has closed the point is final.
    done = lp._odds_section(rows, True, now=D(2026, 9, 13, 3))
    assert "still being played" not in done
    assert lp._odds_section(rows, False) == ""


# --------------------------------------------------------------------------- #
# In the browser
# --------------------------------------------------------------------------- #

CHROME = next((p for p in ("/usr/bin/chromium-browser", "/usr/bin/chromium",
                           "/usr/bin/google-chrome") if shutil.which(p)), None)
CDP_PORT = 9496


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def browser():
    """(send, ev, dir, port): Chromium and a local server for the page - a
    data: URL has no origin, so no localStorage to remember a team in."""
    if CHROME is None:
        pytest.skip("no Chromium to run the JS in")
    import websockets
    from browser_util import launch, reap
    root = tempfile.mkdtemp(prefix="gs-odds-chart-")
    httpd = socketserver.TCPServer(("127.0.0.1", 0),
                                   functools.partial(_Quiet, directory=root))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    subprocess.run(["fuser", "-k", f"{CDP_PORT}/tcp"], capture_output=True)
    proc = launch(CHROME, CDP_PORT)
    for _ in range(60):
        try:
            targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json"))
            ws_url = next(t["webSocketDebuggerUrl"] for t in targets if t.get("type") == "page")
            break
        except Exception:                                   # noqa: BLE001
            time.sleep(0.5)
    else:
        raise RuntimeError("Chromium did not come up")

    def send(method, params):
        async def run():
            async with websockets.connect(ws_url, max_size=None) as ws:
                await ws.send(json.dumps({"id": 1, "method": method, "params": params}))
                while True:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
                    if msg.get("id") == 1:
                        return msg
        return asyncio.run(run())

    def ev(expr):
        res = send("Runtime.evaluate", {"expression": expr, "returnByValue": True})["result"]
        if res.get("exceptionDetails"):
            raise AssertionError(res["exceptionDetails"])
        return res["result"].get("value")
    yield send, ev, root, httpd.server_address[1]
    proc.terminate()
    reap(proc)
    httpd.shutdown()
    httpd.server_close()
    shutil.rmtree(root, ignore_errors=True)


_LOADS = [0]


def _page(browser, stored=None):
    """The chart (site owner's team 'a' picked out) with `stored` as the
    reader's remembered team, the script run after it as on the page."""
    send, ev, root, port = browser
    html = oc.section(oc.by_week(_rows(SNAPS)), {**NAMES, "c": "Cy"}, mine="a",
                      storage="nflMyTeam", sid="t")
    body = ("<script>try{localStorage.clear();"
            + (f"localStorage.setItem('nflMyTeam',{json.dumps(stored)});" if stored else "")
            + "}catch(e){}</script>" + html
            + oc.JS.replace("{% raw %}", "").replace("{% endraw %}", ""))
    _LOADS[0] += 1
    name = f"p{_LOADS[0]}.html"
    with open(f"{root}/{name}", "w", encoding="utf-8") as f:
        f.write("<!doctype html><meta charset=utf-8><body>" + body + "</body>")
    send("Page.navigate", {"url": f"http://127.0.0.1:{port}/{name}"})
    for _ in range(100):
        try:
            if ev("location.pathname") == "/" + name and \
                    ev("document.readyState") == "complete":
                return
        except AssertionError:
            pass
        time.sleep(0.05)
    raise RuntimeError("page did not load")


ON = ("JSON.stringify([...document.querySelectorAll('.oc-fp .oc-ln.oc-on')].map("
      "l=>l.dataset.k).concat([document.querySelector('.oc-fp svg .oc-ln:last-of-type')"
      ".dataset.k, document.querySelector('.oc select').value,"
      " document.querySelectorAll('.oc-fp .oc-dot').length,"
      " document.querySelector('.oc-fp .oc-end').textContent,"
      " document.querySelector('.oc-fp tr.oc-on').dataset.k]))")


def test_the_readers_remembered_team_is_picked_out(browser):
    ev = browser[1]
    _page(browser, stored="b")
    assert json.loads(ev(ON)) == ["b", "b", "b", 2, "39%", "b"]


def test_without_a_remembered_team_the_owners_stays(browser):
    ev = browser[1]
    _page(browser, stored="nobody-here")
    assert json.loads(ev(ON)) == ["a", "a", "a", 3, "90%", "a"]


def test_the_menu_and_a_tap_on_a_line_pick_out_another(browser):
    ev = browser[1]
    _page(browser)
    ev("var s=document.querySelector('.oc select'); s.value='b';"
       "s.dispatchEvent(new Event('change')); true")
    assert json.loads(ev(ON))[:3] == ["b", "b", "b"]
    ev("document.querySelector('.oc-fp .oc-hit[data-k=\"a\"]')"
       ".dispatchEvent(new MouseEvent('click', {bubbles:true})); true")
    assert json.loads(ev(ON))[:3] == ["a", "a", "a"]
    # Both charts follow, and the plot box keeps its size.
    assert ev("document.querySelector('.oc-ft .oc-ln.oc-on').dataset.k") == "a"


def test_the_title_switch_needs_no_script(browser):
    ev = browser[1]
    _page(browser)
    shown = ("[getComputedStyle(document.querySelector('.oc-fp')).display,"
             " getComputedStyle(document.querySelector('.oc-ft')).display].join()")
    assert ev(shown) == "block,none"
    ev("document.querySelector('label.oc-lt').click(); true")
    assert ev(shown) == "none,block"
