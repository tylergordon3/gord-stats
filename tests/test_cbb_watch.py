"""
The CBB watch guide (cbb.render.render_watch): the day's games read from the
live scoreboard feed in the browser, cut into tip-off windows and ranked by a
watch score, men's or women's.

The browser half runs the page's script in headless Chromium on a page served
over http, with fetch stubbed to answer as the Worker, star-teams.json and
ESPN's calendar would; skips without Chromium.
"""
import asyncio
import functools
import http.server
import json
import math
import shutil
import socketserver
import subprocess
import threading
import time
import urllib.request
from datetime import datetime, time as dtime, timedelta, timezone

import pytest

from cbb.render import render_watch as watch
from gordstats.watch_page import ET
from browser_util import launch, reap

CHROME = next((p for p in ("/usr/bin/chromium-browser", "/usr/bin/chromium",
                           "/usr/bin/google-chrome") if shutil.which(p)), None)
CDP = 9455


def test_windows_are_eastern_tip_offs():
    cfg = watch.config()
    assert [s[:2] for s in cfg["slots"]] == [["early", "Early"], ["afternoon", "Afternoon"],
                                             ["evening", "Evening"], ["late", "Late"],
                                             ["tba", "Time TBA"]]
    assert [s[2] for s in cfg["slots"]][:4] == ["before 3 ET", "3-6 ET", "6-9 ET", "from 9 ET"]
    # The browser cuts on the same hours the engine labels.
    assert cfg["cuts"] == [["early", 15.0], ["afternoon", 18.0], ["evening", 21.0], ["late", 99.0]]


def test_the_words_carry_the_numbers_the_page_uses():
    how = watch.HOW
    assert "#101 half that" in how and "#201 a quarter" in how
    assert "42%-58%" in how and "35%+" in how and "within 6" in how
    cfg = watch.config()
    assert (cfg["half"], cfg["toss"], cfg["upset"], cfg["close"]) == (100, [0.42, 0.58], 0.35, 6)


def test_the_page_carries_no_games_only_the_adapter():
    html = watch.body()
    assert "id='wg-data'" not in html
    assert "__CONFIG__" not in html and watch.FEED in html
    assert html.index("window.GSWatch=") < html.index("GSWatch(D, cfg)")


def test_generate_writes_the_page(tmp_path, monkeypatch):
    out = tmp_path / "cbb" / "watch" / "index.html"
    monkeypatch.setattr(watch, "OUT", out)
    watch.generate()
    text = out.read_text(encoding="utf-8")
    assert text.startswith("---\nlayout: default\ntitle: Watch Guide\n")
    assert "What to have on, window by window" in text and "wg-host" in text


def test_the_daily_run_builds_it_beside_the_rankings(monkeypatch):
    from cbb.render import render_power
    from gordstats import daily
    calls = []
    monkeypatch.setattr(render_power, "trank", lambda refresh=False: calls.append("trank"))
    monkeypatch.setattr(render_power, "generate", lambda: calls.append("power"))
    monkeypatch.setattr(watch, "generate", lambda: calls.append("watch"))
    from cbb.render import render_previews, render_stats
    monkeypatch.setattr(render_stats, "generate", lambda: calls.append("stats"))
    monkeypatch.setattr(render_previews, "generate", lambda: calls.append("previews"))
    daily._cbb_power()
    assert calls == ["trank", "power", "previews", "watch", "stats"]


def test_a_failed_preview_run_still_builds_the_guide_then_says_so(monkeypatch):
    import pytest
    from cbb.render import render_power, render_previews, render_stats
    from gordstats import daily
    calls = []
    monkeypatch.setattr(render_power, "trank", lambda refresh=False: None)
    monkeypatch.setattr(render_power, "generate", lambda: None)
    monkeypatch.setattr(watch, "generate", lambda: calls.append("watch"))
    monkeypatch.setattr(render_stats, "generate", lambda: calls.append("stats"))

    def boom():
        raise RuntimeError("feed down")
    monkeypatch.setattr(render_previews, "generate", boom)
    with pytest.raises(RuntimeError):
        daily._cbb_power()
    assert calls == ["watch", "stats"]


# --------------------------------------------------------------------------- #
# In the browser
# --------------------------------------------------------------------------- #

def _score(hm, am, p, lifts=0):
    """The module docstring's formula, rounded as the page's chip rounds it."""
    grade = lambda r: 100 * 0.5 ** ((r - 1) / 100)
    a, b = grade(hm), grade(am)
    s = 2 * a * b / (a + b) * (0.5 + 0.5 * (1 - abs(2 * p - 1)))
    s = math.floor((s + (100 - s) * 0.25 * lifts) * 10 + 0.5) / 10
    return math.floor(s + 0.5)


def _at(hour, minute=0, days=0):
    day = datetime.now(ET).date() + timedelta(days=days)
    return datetime.combine(day, dtime(hour, minute), tzinfo=ET)


def _g(home, away, when, hm, am, p, status="pre_game", score=(None, None), period=None,
       clock=None, ranks=(None, None), desc="", gtype="", mm=False):
    return {"date": when.astimezone(ET).strftime("%Y-%m-%d"),
            "start_time_utc": when.astimezone(timezone.utc).isoformat(), "status": status,
            "home_team": home, "away_team": away, "home_score": score[0], "away_score": score[1],
            "home_model": hm, "away_model": am, "home_rank": ranks[0], "away_rank": ranks[1],
            "home_record": "3-0", "away_record": "2-1", "home_win_prob": p,
            "pred_home": 75.0, "pred_away": 70.0, "spread_close": "HOME -5.5",
            "period": period, "clock": clock, "overtime": False, "game_description": desc,
            "game_type": gtype, "is_mm": mm, "is_nit": False, "neutral": False}


def _feed():
    now = datetime.now(ET)
    men = {
        "e1": _g("Illinois", "Iowa St.", _at(12), 100, 110, 0.5,
                 desc="Big Ten Tournament | First Round", gtype="Postseason Tournament"),
        "a1": _g("Gonzaga", "Portland", _at(16), 15, 280, 0.95),
        "v1": _g("Duke", "North Carolina", _at(19), 3, 12, 0.6, ranks=(3, 10)),
        "v2": _g("Kansas", "Baylor", _at(19, 30), 8, 30, 0.75),
        "v3": _g("McNeese", "Nicholls", _at(19), 300, 320, 0.5),
        "l1": _g("Arizona", "UCLA", _at(21, 30), 5, 25, 0.55),
        # Hawaii at home, 12:30 ET: tonight's late game, not tomorrow's early one.
        "l2": _g("Hawaii", "UC Irvine", _at(0, 30, days=1), 150, 90, 0.45),
        # On now: close in the last five minutes; the underdog ahead in the second half.
        "n1": _g("Purdue", "Iowa", now - timedelta(minutes=90), 20, 60, 0.7,
                 status="in_progress", score=(70, 67), period="2nd", clock="3:12"),
        "n2": _g("Michigan St.", "Rutgers", now - timedelta(minutes=50), 25, 90, 0.8,
                 status="in_progress", score=(40, 45), period="2nd", clock="12:00"),
        "x1": _g("Texas", "Rice", _at(20), 30, 200, 0.9, status="postponed"),
        "y1": _g("Houston", "Tulane", _at(19, days=-1), 4, 150, 0.9, status="final",
                 score=(80, 60), period="2nd", clock="0:00"),
    }
    women = {
        "w1": _g("South Carolina", "LSU", _at(19), 1, 6, 0.7, ranks=(1, 5)),
        "w2": _g("UConn", "Villanova", _at(18), 2, 80, 0.9),
        # Women play quarters: the 4th with 2:00 left is late; the 2nd is not
        # the second half, whoever leads.
        "w3": _g("Iowa", "Maryland", now - timedelta(minutes=100), 20, 22, 0.55,
                 status="in_progress", score=(60, 56), period="4th", clock="2:00"),
        "w4": _g("Stanford", "California", now - timedelta(minutes=40), 30, 70, 0.7,
                 status="in_progress", score=(28, 31), period="2nd", clock="1:00"),
    }
    return {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "leagues": {"men": men, "women": women}}


STARS = {"cbb-men:duke": ["Duke", "/assets/images/duke.png"],
         "cbb-men:baylor": ["Baylor", "/assets/images/baylor.png"],
         # T-Rank's "McNeese St." is the scoreboard's "McNeese": the key comes
         # from the file, not from the name on the card.
         "cbb-men:mcneese-st": ["McNeese", "/assets/images/mcneese.png"]}


def _boot(feed, favorites=(), league=None, calendar=None):
    return f"""
localStorage.setItem('gs:favorites', JSON.stringify({json.dumps(list(favorites))}));
{"localStorage.setItem('league', %s);" % json.dumps(league) if league else "localStorage.removeItem('league');"}
window.__asked=[];
window.fetch=function(url){{
  window.__asked.push(String(url));
  var body=/workers\\.dev/.test(url)?{json.dumps(feed)}
    :/star-teams/.test(url)?{json.dumps(STARS)}
    :/espn\\.com/.test(url)&&{json.dumps(calendar is not None)}?{{leagues:[{{calendar:{json.dumps(list(calendar or []))}}}]}}:null;
  return Promise.resolve({{ok:body!=null, json:function(){{ return Promise.resolve(body); }}}});
}};
"""


READ = """(function(){
  var out={}, host=document.getElementById('wg-host');
  host.querySelectorAll('h3').forEach(function(h){
    out[h.firstChild.textContent.trim()]=Array.prototype.map.call(
      h.nextElementSibling.querySelectorAll('a.wg-g'), function(a){
        return {id:a.getAttribute('data-gid'), top:a.classList.contains('top'), href:a.getAttribute('href'),
          text:a.textContent, logos:a.querySelectorAll('img').length,
          tags:Array.prototype.map.call(a.querySelectorAll('.wg-tags span'), function(s){ return s.textContent; })};
      });
  });
  var sw=document.querySelector('.wg-lg'), up=document.querySelector('.page-updated');
  function shown(el){ return !!el&&el.getClientRects().length>0; }
  out._switch=shown(sw)?Array.prototype.map.call(sw.querySelectorAll('button'), function(b){
    return b.textContent+(b.getAttribute('aria-pressed')==='true'?'*':''); }).join('|'):null;
  out._how=shown(document.querySelector('.wg-how'));
  out._share=shown(document.querySelector('.gs-share-row'));
  out._updated=shown(up)?up.getAttribute('data-updated'):null;
  out._text=host.textContent.trim();
  out._league=localStorage.getItem('league');
  out._asked=window.__asked;
  return out;
})()"""


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    root = tmp_path_factory.mktemp("cbbwatch")
    # Beside the page as built, one whose season starts in ten days, for the
    # empty line when ESPN's calendar does not answer.
    soon = datetime.now(ET).date() + timedelta(days=10)
    for name, cfg in (("index.html", None), ("preseason.html", {**watch.config(),
                                                                "tipoff": soon.isoformat()})):
        (root / name).write_text(
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<style>.gs-share-row{display:flex}</style></head><body>"
            "<p class='page-updated' data-updated='2026-09-01T08:00-04:00'>Updated</p>"
            + watch.body(cfg) + "</body></html>", encoding="utf-8")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a: None
    server = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()


def _run(url: str, boot: str, steps: list):
    """Load the page with `boot` run first, then evaluate each step in turn,
    a moment apart; the last one's value comes back."""
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
                await send("Page.addScriptToEvaluateOnNewDocument", {"source": boot})
                await send("Page.navigate", {"url": url})
                value = None
                for step in steps:
                    await asyncio.sleep(2)
                    r = await send("Runtime.evaluate", {"expression": step, "returnByValue": True})
                    value = r["result"].get("value")
                return value
        return asyncio.run(go())
    finally:
        proc.terminate()
        reap(proc)


needs_chrome = pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")


@needs_chrome
def test_the_day_by_window_best_first(site):
    feed = _feed()
    got = _run(site, _boot(feed), [READ])
    # What is on leads; the close one late first, then the upset in the making.
    on = got["On now"]
    assert [g["id"] for g in on] == ["n1", "n2"]
    assert "Close late" in on[0]["tags"] and "2nd 3:12" in on[0]["text"]
    assert "Upset alert" in on[1]["tags"] and "Close late" not in on[1]["tags"]
    # Each window by score; the postponed game and yesterday's final are gone.
    assert [g["id"] for g in got["Early"]] == ["e1"]
    assert [g["id"] for g in got["Afternoon"]] == ["a1"]
    assert [g["id"] for g in got["Evening"]] == ["v1", "v2", "v3"]
    assert [g["id"] for g in got["Late"]] == ["l1", "l2"]
    assert got["Evening"][0]["top"] and not got["Evening"][1]["top"]
    # The chips are the docstring's numbers, with the tags that say why.
    duke = got["Evening"][0]["tags"]
    assert duke[0] == f"Watch {_score(3, 12, 0.6, lifts=1)}"
    assert duke[1:] == ["Top 25 matchup", "Upset watch"]
    assert got["Early"][0]["tags"] == [f"Watch {_score(100, 110, 0.5, lifts=1)}",
                                       "Toss-up", "Tournament"]
    assert got["Evening"][2]["tags"] == [f"Watch {_score(300, 320, 0.5)}", "Toss-up"]
    assert "Big Ten Tournament · First Round" in got["Early"][0]["text"]
    # Logos from star-teams.json where it knows the name; cards go to the board.
    assert got["Evening"][0]["logos"] == 1 and got["Evening"][0]["href"] == "/men/"
    assert got["_switch"] == "Men*|Women" and got["_how"] and got["_share"]
    assert "Star teams on the rankings" in got["_text"]
    # "Updated" is when the feed was pushed, not when the page was built.
    assert got["_updated"] == datetime.fromisoformat(feed["generated"]).astimezone(
        timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


@needs_chrome
def test_a_starred_team_goes_first(site):
    got = _run(site, _boot(_feed(), favorites=["cbb-men:mcneese-st", "cfb:333"]), [READ])
    evening = got["Evening"]
    assert [g["id"] for g in evening] == ["v3", "v1", "v2"]
    assert "Your team" in evening[0]["tags"]


@needs_chrome
def test_the_switch_swaps_leagues_and_remembers(site):
    got = _run(site, _boot(_feed()), [
        "document.querySelector('.wg-lg button[data-lg=women]').click()", READ])
    assert got["_switch"] == "Men|Women*" and got["_league"] == "women"
    on = {g["id"]: g for g in got["On now"]}
    assert set(on) == {"w3", "w4"}
    assert "Close late" in on["w3"]["tags"]
    # Second quarter: not late, and not yet the second half for an upset alert.
    assert not {"Close late", "Upset alert"} & set(on["w4"]["tags"])
    assert [g["id"] for g in got["Evening"]] == ["w1", "w2"]
    assert all(g["href"] == "/women/" for g in got["Evening"])
    assert "Star teams" not in got["_text"]          # the rankings' stars are the men's
    # Stored the nav's way, so the next visit opens on the women's games.
    again = _run(site, _boot(_feed(), league="women"), [READ])
    assert again["_switch"] == "Men|Women*" and "w1" in [g["id"] for g in again["Evening"]]


@needs_chrome
def test_no_games_is_one_line(site):
    """Last April's slate in the feed: no windows, no switch, no fold - the
    date of the next game from ESPN's calendar."""
    april = {"generated": "2026-04-08T01:00:21.229353",
             "leagues": {"men": {"1": _g("Michigan", "Connecticut",
                                         datetime(2026, 4, 6, 20, 50, tzinfo=ET), 2, 9, 0.6,
                                         status="final", score=(69, 63))},
                         "women": {}}}
    nxt = datetime.now(ET).date() + timedelta(days=5)
    got = _run(site, _boot(april, calendar=["2026-03-01T08:00Z", f"{nxt}T07:00Z"]), [READ])
    assert got["_text"] == f"No games until {nxt:%a, %b} {nxt.day}."
    assert got["_switch"] is None and not got["_how"] and not got["_share"]
    assert got["_updated"] is None
    assert not [k for k in got if not k.startswith("_")]            # no windows at all
    assert any("mens-college-basketball" in u for u in got["_asked"])
    # ESPN does not answer: the season's first game, while it is to come.
    got = _run(site + "preseason.html", _boot(april), [READ])
    soon = datetime.now(ET).date() + timedelta(days=10)
    assert got["_text"] == f"No games until {soon:%a, %b} {soon.day}."
