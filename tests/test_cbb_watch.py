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
import re
import shutil
import socketserver
import subprocess
import threading
import time
import urllib.request
from datetime import datetime, time as dtime, timedelta, timezone

import pytest

from cbb.render import render_watch as watch
from gordstats.js_assets import expand
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
    """How games are ranked is the cbb-watch explainer (gordstats.how), opened
    from the chip under the guide: its numbers are the ones the page runs on."""
    from gordstats import how
    cfg = watch.config()
    assert (cfg["half"], cfg["toss"], cfg["upset"], cfg["close"]) == (100, [0.42, 0.58], 0.35, 6)
    text = re.sub(r"<[^>]+>", "", how.article("cbb-watch"))
    numbers = set(re.findall(r"#?\d+%?", text))
    assert {f"#{cfg['half'] + 1}", f"#{2 * cfg['half'] + 1}"} <= numbers, numbers
    assert {f"{cfg['toss'][0]:.0%}", f"{cfg['toss'][1]:.0%}", f"{cfg['upset']:.0%}"} <= numbers
    assert f"within {cfg['close']} points" in text
    page = expand(watch.body())
    assert "class='wg-how'" in page and "href='/how/cbb-watch/'" in page
    assert "How games are ranked" not in page


def test_the_page_carries_no_games_only_the_adapter():
    html = expand(watch.body())
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
    monkeypatch.setattr(render_power, "trank_women",
                        lambda refresh=False: calls.append("trank_women"))
    monkeypatch.setattr(render_power, "generate", lambda: calls.append("power"))
    monkeypatch.setattr(watch, "generate", lambda: calls.append("watch"))
    from cbb.render import render_previews, render_stats
    monkeypatch.setattr(render_stats, "generate", lambda: calls.append("stats"))
    monkeypatch.setattr(render_previews, "generate", lambda: calls.append("previews"))
    daily._cbb_power()
    assert calls == ["trank", "trank_women", "power", "previews", "watch", "stats"]


def test_a_failed_preview_run_still_builds_the_guide_then_says_so(monkeypatch):
    import pytest
    from cbb.render import render_power, render_previews, render_stats
    from gordstats import daily
    calls = []
    monkeypatch.setattr(render_power, "trank", lambda refresh=False: None)
    monkeypatch.setattr(render_power, "trank_women", lambda refresh=False: None)
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
            + expand(watch.body(cfg)) + "</body></html>", encoding="utf-8")
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


# --------------------------------------------------------------------------- #
# games.json, for the all-sports guide (gordstats.watch_all)
# --------------------------------------------------------------------------- #

def _fx(home, away, kick, hm="", am="", p=None, status="pre_game", ht=None, at=None,
        ranks=(None, None), **kw):
    """A feed game at `kick` (Eastern), as cbb.live_scraper.format_event writes one."""
    import pandas as pd
    k = pd.Timestamp(kick, tz=ET)
    g = {"date": k.strftime("%Y-%m-%d"), "start_time_utc": k.tz_convert("UTC").isoformat(),
         "status": status, "home_team": home, "away_team": away, "home_model": hm,
         "away_model": am, "home_trank": ht, "away_trank": at, "home_rank": ranks[0],
         "away_rank": ranks[1], "home_record": "", "away_record": "", "home_win_prob": p,
         "pred_home": None, "pred_away": None, "spread_close": None, "home_score": None,
         "away_score": None, "game_description": "", "game_type": "", "is_mm": False,
         "is_nit": False, "neutral": False}
    g.update(kw)
    return g


def _opening_night():
    """Monday Nov 2, 2026: GordStats' ranks still blank (the bracketology has
    no 2026-27 inputs yet), T-Rank's on the feed, no women's table at all."""
    return {"men": {
        "11": _fx("Duke", "Army", "2026-11-02 19:00", p=0.99, ht=1, at=353, spread_close="DUKE -30.5"),
        "12": _fx("Gonzaga", "Purdue", "2026-11-02 21:00", p=0.55, ht=6, at=4),
        "13": _fx("Florida", "Miami FL", "2026-11-02 19:30", p=0.70, ht=8, at=45),
        # 12:30 AM Tuesday in Hawaii's gym: Monday night's game on the guide.
        "14": _fx("Hawaii", "Utah St.", "2026-11-03 00:30", p=0.40, ht=150, at=40),
        "15": _fx("Kansas", "Texas", "2026-11-03 19:00", p=0.60, ht=10, at=30),
        "16": _fx("Kentucky", "Duke", "2026-11-04 19:00", p=0.50, ht=12, at=1),   # the day after
        "17": _fx("Texas Tech", "Rice", "2026-11-02 20:00", p=0.9, ht=20, at=200,
                  status="postponed"),
        # GordStats' rank, once there is one, before T-Rank's.
        "18": _fx("Houston", "Tulane", "2026-11-03 20:00", hm=2, am=150, p=0.95, ht=50, at=60)},
        "women": {
        "21": _fx("South Carolina", "Clemson", "2026-11-02 18:00", ranks=(1, None)),
        # No rank, no poll, no call: every such game scores alike - left out.
        "22": _fx("Oakland", "Cleary University", "2026-11-02 18:00")}}


def test_the_all_sports_file_is_each_leagues_best_of_today_and_tomorrow(monkeypatch):
    import pandas as pd
    from cbb.render import render_previews as rp
    now = pd.Timestamp("2026-11-02 11:40", tz=ET)
    teams = {"Duke": ("duke", "/assets/images/duke.png")}
    got = watch.games(_opening_night(), now, {}, teams, pv=["12"])
    by = {g["id"]: g for g in got}
    # Monday's four (Hawaii's 12:30 AM tip counts to Monday) and Tuesday's
    # two; not Wednesday's, nor the postponed game.
    assert by["14"]["day"] == "2026-11-02" and by["15"]["day"] == "2026-11-03"
    assert set(by) == {"11", "12", "13", "14", "15", "18", "21"}
    # Best first within a league's day, on T-Rank's ranks while GordStats'
    # are blank - and the cut is the best PER_DAY: Duke's 30-point cupcake goes.
    monday = [g["id"] for g in got if g["league"] == "men" and g["day"] == "2026-11-02"]
    assert monday == ["12", "13", "14", "11"]
    monkeypatch.setattr(watch, "PER_DAY", 3)
    assert [g["id"] for g in watch.games(_opening_night(), now)
            if g["day"] == "2026-11-02" and g["league"] == "men"] == ["12", "13", "14"]
    assert by["12"]["score"] == rp.watch_score(6, 4, 0.55)[0]
    assert by["18"]["score"] == rp.watch_score(2, 150, 0.95)[0]
    # The women's: the AP-ranked team's game, tagged; the unrankable one left out.
    assert set(g["id"] for g in got if g["league"] == "women") == {"21"}
    assert by["21"]["badge"] == "WCBB" and by["11"]["badge"] == ""
    # Keys as the browser half makes them; a preview where there is one.
    assert by["11"]["h"]["k"] == "cbb-men:duke" and by["11"]["h"]["lg"] == "/assets/images/duke.png"
    assert by["11"]["a"]["k"] == "cbb-men:army" and by["21"]["h"]["k"] == "cbb-women:south-carolina"
    assert by["12"]["href"] == "/cbb/game/12/" and by["11"]["href"] == "/men/"
    assert by["21"]["href"] == "/women/"
    assert by["11"]["lt"] == "DUKE −30.5" and by["11"]["fav"] == "h"
    assert by["11"]["ko"] == "2026-11-03T00:00:00Z" and by["11"]["tk"] is True


def test_a_feed_without_trank_ranks_on_the_cached_table():
    """A push from before the feed carried `home_trank`: the caller's map."""
    import pandas as pd
    from cbb.render import render_previews as rp
    feed = {"men": {"12": _fx("Gonzaga", "Purdue", "2026-11-02 21:00", p=0.55)}}
    now = pd.Timestamp("2026-11-02 11:40", tz=ET)
    got = watch.games(feed, now, {"men": {"Gonzaga": 6, "Purdue": 4}})
    assert got[0]["score"] == rp.watch_score(6, 4, 0.55)[0]
    feed["men"]["12"]["home_win_prob"] = None
    assert watch.games(feed, now, {}) == [], "nothing to rank it on"


def test_write_games_beside_the_page_and_keeps_the_last_when_the_feed_fails(tmp_path, monkeypatch):
    import pandas as pd
    import requests
    from cbb import game_model
    from cbb.render import render_previews as rp
    monkeypatch.setattr(watch, "OUT", tmp_path / "cbb" / "watch" / "index.html")
    monkeypatch.setattr(rp, "feed", lambda: {"leagues": _opening_night(), "generated": "x"})
    monkeypatch.setattr(rp, "tv", lambda ids, path="ncaab": {i: "ESPN2" for i in ids})
    monkeypatch.setattr(game_model, "trank_ranks", lambda gender="M", day=None: {})
    now = pd.Timestamp("2026-11-02 11:40", tz=ET)
    assert watch.write_games(now) == 7
    out = tmp_path / "cbb" / "watch" / "games.json"
    data = json.loads(out.read_text())
    assert data["season"] == 2027 and data["generated"].startswith("2026-11-02T11:40")
    assert {g["tv"] for g in data["games"]} == {"ESPN2"}
    assert len(out.read_text()) < 6000, "a few KB for Home's Tonight card"

    def down():
        raise requests.ConnectionError("no route")
    monkeypatch.setattr(rp, "feed", down)
    before = out.read_text()
    assert watch.write_games(now) == -1 and out.read_text() == before
