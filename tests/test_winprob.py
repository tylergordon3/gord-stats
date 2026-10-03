"""Live win probability: ESPN's number on the CFB and NFL schedule cards while a
game is on, and a chart of it on the game previews (gs-winprob.js).

No network. ESPN is played by fixtures recorded 2026-10-02/03 and trimmed to
the fields the scripts read (tests/fixtures/winprob/):

  cfb_summary_final.json  Pitt at Virginia Tech, final - every second entry of
                          `winprobability` and the plays they name
  cfb_summary_ot.json     North Texas at Tulsa, final in overtime - every third
  nfl_summary_live.json   Pittsburgh at Cleveland (TNF), cut at 8:50 of the
                          third quarter: what the summary reads mid-game
  cfb_summary_pre.json    Alabama at Mississippi State before kickoff: an
                          empty `winprobability`
  cfb_scoreboard.json,    a final and a game to come as ESPN served them, and
  nfl_scoreboard.json     one set in progress with the `situation` block ESPN
                          adds during a game (situation.lastPlay.probability);
                          no game was on to record one
"""
import asyncio
import json
import re
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

import pandas as pd
import pytest

from gordstats import js_assets, preview_page

FIX = Path(__file__).parent / "fixtures" / "winprob"
CHROME = next((p for p in ("/usr/bin/chromium-browser", "/usr/bin/chromium",
                           "/usr/bin/google-chrome") if shutil.which(p)), None)
needs_chrome = pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")
CDP = 9630
WINPROB = js_assets.source("gs-winprob.js")


def _fx(name):
    return json.loads((FIX / name).read_text())


def _game(sport="cfb", state="in", ko="2026-10-03T00:00Z", tk=True, gid="401858245",
          teams=(("Pittsburgh", "PITT"), ("Virginia Tech", "VT"))):
    (an, aa), (hn, ha) = teams
    return {"sport": sport, "id": gid, "state": state, "ko": pd.Timestamp(ko), "tk": tk,
            "away": {"name": an, "abbr": aa}, "home": {"name": hn, "abbr": ha}}


NFL_TEAMS = (("Steelers", "PIT"), ("Browns", "CLE"))


# --------------------------------------------------------------------------- #
# The preview's section, as built
# --------------------------------------------------------------------------- #

def test_the_section_names_the_game_for_espn_and_starts_hidden():
    html = preview_page.winprob_block({**_game(state="pre"), "how": {"units": "game-previews"}})
    assert html.startswith("<section class='pv-sec pv-lwp' data-gs-wp ")
    for attr in ("data-league='college-football'", "data-id='401858245'",
                 "data-ko='2026-10-03T00:00:00Z'", "data-tk='1'", "data-state='pre'",
                 "data-home='VT'", "data-away='PITT'"):
        assert attr in html, attr
    assert "hidden>" in html, "nothing shows before kickoff"
    assert "how/game-previews/" in html, "the method is the explainer's, behind a chip"
    assert "gs-how" not in preview_page.winprob_block(_game()), "no topic named, no chip"
    # The reveal runs as the section is parsed: just after it, on it.
    assert html.endswith("(document.currentScript.previousElementSibling);</script>")
    nfl = preview_page.winprob_block(_game(sport="nfl", gid="401872964"))
    assert "data-league='nfl'" in nfl and "data-state='in'" in nfl


def test_only_sports_with_espn_ids_get_one():
    assert preview_page.winprob_block(_game(sport="cbb")) == "", "CBB ids are theScore's"
    assert preview_page.winprob_block({**_game(), "ko": None}) == ""


def test_the_page_loads_the_chart_script_only_with_the_section():
    game = {**_game(), "call": {"margin": 4.2, "prob": 0.64}}
    body = preview_page.body(game)
    tags = re.findall(r"<script[^>]*src=\"[^\"]*gs-winprob\.js[^\"]*\"", body)
    assert len(tags) == 1 and " defer" in tags[0]
    assert "| fingerprint" in tags[0], "loaded by its hashed URL"
    # Under the header, above The call.
    assert body.index("pv-head") < body.index("data-gs-wp") < body.index("pv-call")
    cbb = preview_page.body({**game, "sport": "cbb"})
    assert "data-gs-wp" not in cbb and not re.search(r"<script[^>]*gs-winprob", cbb)


def test_every_line_of_the_section_has_a_fixed_height():
    css = preview_page.CSS
    for rule in (".pv-lwp-now{", ".pv-lwp-at{", ".pv-lwp-play{", ".pv-lwp-chart{"):
        block = css[css.index(rule):css.index("}", css.index(rule))]
        assert re.search(r"(^|[{;])height:\d+px", block), rule


# --------------------------------------------------------------------------- #
# Chromium
# --------------------------------------------------------------------------- #

def _run(steps, width=390, height=844):
    """[(expression, seconds to wait after it)] in one headless page at a
    phone's size; every value, in order."""
    import websockets
    from browser_util import launch, reap
    subprocess.run(["fuser", "-k", f"{CDP}/tcp"], capture_output=True)
    proc = launch(CHROME, CDP)
    try:
        ws_url = None
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

                async def send(method, params):
                    nonlocal n
                    n += 1
                    await ws.send(json.dumps({"id": n, "method": method, "params": params}))
                    while True:
                        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
                        if msg.get("id") == n:
                            return msg.get("result", {})
                await send("Emulation.setDeviceMetricsOverride", {
                    "width": width, "height": height, "deviceScaleFactor": 1, "mobile": False})
                out = []
                for expression, wait in steps:
                    got = await send("Runtime.evaluate", {"expression": expression,
                                                          "returnByValue": True,
                                                          "awaitPromise": True})
                    if got.get("exceptionDetails"):
                        raise AssertionError(got["exceptionDetails"])
                    out.append(got["result"].get("value"))
                    await asyncio.sleep(wait)
                return out
        return asyncio.run(go())
    finally:
        proc.terminate()
        reap(proc)
        subprocess.run(["fuser", "-k", f"{CDP}/tcp"], capture_output=True)


def _write(html: str) -> str:
    """Load `html` as a page is parsed - inline scripts run where they stand,
    document.currentScript and all."""
    return f"document.open();document.write({json.dumps(html)});document.close();true"


def _lib(fixtures: dict) -> str:
    """window.GSWinProb with the fixtures in window.FX, outside any page."""
    return ("window.FX=" + json.dumps(fixtures) + ";" + WINPROB + ";true")


@needs_chrome
def test_the_series_puts_each_play_on_the_game_clock():
    fx = {k: _fx(f"{k}.json") for k in ("cfb_summary_final", "cfb_summary_ot",
                                       "nfl_summary_live", "cfb_summary_pre")}
    probe = """(function(){var o={};Object.keys(FX).forEach(function(k){var s=GSWinProb.series(FX[k]),
      xs=s.pts.map(function(p){return p.x;});
      o[k]={state:s.state,detail:s.detail,n:s.pts.length,span:s.span,ots:s.ots,timed:s.timed,
        home:s.home,away:s.away,first:s.pts[0]||null,last:s.pts[s.pts.length-1]||null,
        mono:xs.every(function(x,i){return !i||x>=xs[i-1];}),
        pers:s.pts.reduce(function(a,p){a[p.per]=(a[p.per]||0)+1;return a;},{}),
        q:s.pts.filter(function(p){return p.per>=1&&p.per<=4;}).every(function(p){
          return p.x>=(p.per-1)*900&&p.x<=p.per*900;})};});
      o.pct=[1,0.996,0.83,0.5].map(GSWinProb.pct);return JSON.stringify(o);})()"""
    got = json.loads(_run([(_lib(fx), 0), (probe, 0)])[1])
    final = got["cfb_summary_final"]
    assert (final["state"], final["timed"], final["ots"], final["span"]) == ("post", True, 0, 3600)
    assert final["mono"] and final["q"], "every play inside its own quarter, never backwards"
    assert set(final["pers"]) == {"1", "2", "3", "4"}
    assert final["first"]["x"] == 0 and final["first"]["p"] == pytest.approx(0.438)
    assert final["last"]["x"] == pytest.approx(3600, abs=60) and final["last"]["p"] == 0
    assert (final["home"]["abbr"], final["away"]["abbr"]) == ("VT", "PITT")
    ot = got["cfb_summary_ot"]
    assert ot["ots"] >= 1 and ot["span"] == 3600 + 450 * ot["ots"]
    assert ot["last"]["x"] == pytest.approx(ot["span"]), "overtime after the fourth, to the end"
    live = got["nfl_summary_live"]
    assert (live["state"], live["detail"]) == ("in", "8:50 - 3rd")
    # 8:50 left in the third: 30 minutes and 6:10 into the game.
    assert live["last"]["x"] == 1800 + 370 and live["last"]["per"] == 3
    assert live["last"]["p"] == pytest.approx(0.8344)
    assert live["last"]["text"], "the drive under way (drives.current) is read too"
    assert live["mono"] and live["q"]
    assert got["cfb_summary_pre"]["n"] == 0 and got["cfb_summary_pre"]["state"] == "pre"
    assert got["pct"] == ["100%", ">99%", "83%", "50%"]


def _preview(game, answers: dict, delay_ms: int = 300) -> str:
    """A preview page: the shared CSS, a header with its middle, the section
    and a block under it - with fetch answering from `answers` (URL part ->
    JSON) after `delay_ms`, recording every URL and every timer set."""
    stub = ("<script>window.ASKED=[];window.DELAYS=[];window.HIDDEN=false;"
            "Object.defineProperty(document,'hidden',{configurable:true,get:function(){return HIDDEN;}});"
            "var _st=window.setTimeout;window.setTimeout=function(f,ms){DELAYS.push(ms);"
            "return _st(f,ms>5000?1e9:ms);};"
            "window.ANSWERS=" + json.dumps(answers) + ";"
            "window.fetch=function(u){ASKED.push(u);var k=Object.keys(ANSWERS).filter(function(k){"
            "return u.indexOf(k)>=0;})[0];return new Promise(function(res,rej){_st(function(){"
            "if(!k)return rej(new Error('no answer'));res({ok:true,status:200,json:function(){"
            "return Promise.resolve(ANSWERS[k]);}});}," + str(delay_ms) + ");});};</script>")
    team = ("<div class='pv-team'><span class='pv-nologo'></span><span class='pv-nm'>{}</span>"
            "<span class='pv-rec'>2-1</span></div>")
    head = ("<div class='pv' data-gs-preview='1'><div class='pv-head'>" + team.format("Pittsburgh")
            + "<div class='pv-mid'><span>at</span></div>" + team.format("Virginia Tech") + "</div>"
            + preview_page.winprob_block(game) + "<section id='after' class='pv-sec'>"
            "<h2>The call</h2></section></div>")
    return ("<!doctype html><html><head><style>[hidden]{display:none!important}"
            "body{margin:0;font-family:sans-serif}</style></head><body>" + stub
            + preview_page.CSS + head + "<script>" + WINPROB + "</script></body></html>")


SNAP = """JSON.stringify((function(){var s=document.querySelector('[data-gs-wp]'),
  a=document.getElementById('after'),svg=s.querySelector('svg'),mid=document.querySelector('.pv-mid');
  return {hidden:s.hidden,h:s.getBoundingClientRect().height,after:a.getBoundingClientRect().top,
    big:s.querySelector('.pv-lwp-big').textContent,lab:s.querySelector('.pv-lwp-lab').textContent,
    at:s.querySelector('.pv-lwp-at').textContent,play:s.querySelector('.pv-lwp-play').textContent,
    svg:svg?{w:+svg.getAttribute('width'),h:+svg.getAttribute('height'),
      q:[].map.call(svg.querySelectorAll('.wp-ql'),function(t){return t.textContent;}),
      dot:!!svg.querySelector('.wp-dot'),label:svg.getAttribute('aria-label')}:null,
    mid:mid.textContent,live:!!mid.querySelector('small.pv-live'),
    asked:ASKED.length,delays:DELAYS.slice()};})())"""


@needs_chrome
def test_a_live_game_is_charted_without_moving_the_page_and_read_every_minute():
    page = _preview(_game(sport="nfl", gid="401872964", teams=NFL_TEAMS),
                    {"nfl/summary?event=401872964": _fx("nfl_summary_live.json")})
    got = _run([(_write(page), 0), (SNAP, 0.8), (SNAP, 0),
                # Hidden tab: the minute's read is skipped; back, it reads at once.
                ("HIDDEN=true;document.dispatchEvent(new Event('visibilitychange'));"
                 "HIDDEN=false;document.dispatchEvent(new Event('visibilitychange'));true", 0.6),
                (SNAP, 0)])
    before, after, back = (json.loads(x) for x in (got[1], got[2], got[4]))
    assert before["hidden"] is False and before["svg"] is None, "shown before the data, empty"
    assert before["asked"] == 1
    assert after["h"] == before["h"] and after["after"] == before["after"], \
        "the chart filled a box already its size: nothing moved"
    assert after["big"] == "CLE 83%" and after["lab"] == "to win · ESPN live"
    assert after["at"] == "8:50 - 3rd · PIT 10, CLE 21"
    assert after["play"].startswith("Last play: ")
    assert after["svg"]["h"] == 170 and after["svg"]["w"] > 300
    assert after["svg"]["q"] == ["Q1", "Q2", "Q3", "Q4"] and after["svg"]["dot"]
    assert "83% now" in after["svg"]["label"]
    assert after["mid"] == "10–21" + "8:50 - 3rd" and after["live"], "the header's score too"
    assert 60000 in after["delays"], "read again in a minute while the game is on"
    assert back["asked"] == 2, "back to the tab: one read, not one per event"


@needs_chrome
def test_a_final_is_read_once_and_says_how_close_the_winner_came():
    page = _preview(_game(state="post"),
                    {"college-football/summary?event=401858245": _fx("cfb_summary_final.json")})
    got = json.loads(_run([(_write(page), 0.8), (SNAP, 0)])[1])
    assert got["big"] == "PITT won" and got["at"] == "Final · PITT 35, VT 33"
    assert re.fullmatch(r"PITT won after its chance fell to \d+% \(Q\d [\d:]+\)\.", got["play"]), got
    assert not got["svg"]["dot"], "no live dot on a final"
    assert 60000 not in got["delays"] and got["asked"] == 1, "a final is not read again"


@needs_chrome
def test_before_kickoff_nothing_shows_and_espn_is_not_asked():
    future = (pd.Timestamp.now(tz="UTC") + pd.Timedelta(hours=30)).isoformat()
    past = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(minutes=5)).isoformat()
    pre = _preview(_game(state="pre", ko=future), {"summary": _fx("cfb_summary_pre.json")})
    got = json.loads(_run([(_write(pre), 0.6), (SNAP, 0)])[1])
    assert got["hidden"] and got["h"] == 0 and got["asked"] == 0
    # Built before kickoff, read after it: shown at once, waiting for the first play.
    late = _preview(_game(state="pre", ko=past), {"summary": _fx("cfb_summary_pre.json")})
    got = json.loads(_run([(_write(late), 0.8), (SNAP, 0)])[1])
    assert not got["hidden"] and got["asked"] == 1
    assert got["big"] == "Not started" and got["at"] == "Waiting for kickoff"
    assert 60000 in got["delays"]
    # An untimed game (ESPN's midnight placeholder) waits for a real kickoff.
    untimed = _preview(_game(state="pre", ko=past, tk=False), {"summary": _fx("cfb_summary_pre.json")})
    got = json.loads(_run([(_write(untimed), 0.6), (SNAP, 0)])[1])
    assert got["hidden"] and got["asked"] == 0


@needs_chrome
def test_a_game_espn_never_charted_takes_its_section_away():
    called_off = {"header": {"competitions": [{"status": {"type": {
        "state": "post", "completed": True, "name": "STATUS_CANCELED", "shortDetail": "Canceled"}},
        "competitors": []}]}, "winprobability": []}
    page = _preview(_game(state="post"), {"summary": called_off})
    got = json.loads(_run([(_write(page), 0.8), (SNAP, 0)])[1])
    assert got["hidden"] and got["asked"] == 1


@needs_chrome
def test_the_crosshair_reads_out_a_play_and_lets_go():
    page = _preview(_game(state="post"),
                    {"college-football/summary?event=401858245": _fx("cfb_summary_final.json")},
                    delay_ms=0)
    hover = ("(function(){var c=document.querySelector('.pv-lwp-chart'),r=c.getBoundingClientRect();"
             "c.dispatchEvent(new PointerEvent('pointermove',{bubbles:true,pointerType:'mouse',"
             "clientX:r.left+80,clientY:r.top+50}));var g=c.querySelector('.wp-x');"
             "return JSON.stringify({at:document.querySelector('.pv-lwp-at').textContent,"
             "shown:g.style.display!=='none'});})()")
    leave = ("(function(){var c=document.querySelector('.pv-lwp-chart');"
             "c.dispatchEvent(new PointerEvent('pointerleave',{pointerType:'mouse'}));"
             "return document.querySelector('.pv-lwp-at').textContent;})()")
    got = _run([(_write(page), 0.5), (hover, 0), (leave, 0)])
    on = json.loads(got[1])
    assert on["shown"] and re.match(r"Q1 \d+:\d\d · PITT \d+, VT \d+ · (VT|PITT) \d+%",
                                    on["at"]), on
    assert got[2] == "Final · PITT 35, VT 33"


# --------------------------------------------------------------------------- #
# The schedule cards
# --------------------------------------------------------------------------- #

def _cfb_rows():
    from cfb.site import schedule

    def side(tid, name, ball=False):
        # _side_row's markup, as a game under way is built: score in, the
        # ball with the side that has it in the feed below.
        return (f'<div class="sc-row{" sc-ball" if ball else ""}" data-tid="{tid}">'
                '<span class="sc-team"><img alt="" width="20" height="20">'
                f'<span class="sc-name"><span class="sc-tn">{name}</span>'
                '<span class="sc-rec">2-1</span></span></span><span class="sc-pts">7</span></div>')

    def row(gid, state, away, home, box):
        return (f'<tr class="g" id="g-{gid}" data-state="{state}"><td class="mu"><div class="sc-mu">'
                + side(*away) + side(*home) +
                f'</div>{schedule._LIVE_BOX if box else ""}</td><td class="t d"><div class="c">'
                f'<span class="t-when">-</span></div></td></tr>')
    return ("<table class='cfb-sched'><tbody>"
            + row("401858250", "in", ("87", "Notre Dame"), ("153", "North Carolina", True), True)
            + row("401858245", "in", ("221", "Pittsburgh"), ("259", "Virginia Tech"), True)
            + row("401856707", "pre", ("333", "Alabama"), ("344", "Mississippi St"), False)
            + "</tbody></table>")


@needs_chrome
def test_a_cfb_card_shows_espns_number_in_room_it_already_had():
    from cfb.site import schedule
    js = schedule._JS % {"upset": "0.3", "current": 5, "cols": schedule._COLS, "url": '"/x"'}
    fns = js[js.index("function liveBox(row){"):js.index("// One loop, ever")]
    board = _fx("cfb_scoreboard.json")
    quiet = json.loads(json.dumps(board))                   # the same, ESPN's number missing
    del quiet["events"][1]["competitions"][0]["situation"]["lastPlay"]["probability"]
    page = ("<!doctype html><html><body>" + schedule._CSS + _cfb_rows() + "<script>" + fns + "</script></body></html>")
    probe = """JSON.stringify(['401858250','401858245','401856707'].map(function(id){
      var r=document.getElementById('g-'+id),w=r.querySelector('.sc-wp'),b=r.querySelector('.sc-live');
      return {h:r.getBoundingClientRect().height,state:r.getAttribute('data-state'),
        wp:w?w.textContent:null,seen:w?getComputedStyle(w).visibility:null,
        box:b?getComputedStyle(b).display:null};}))"""
    # The first measure waits for the page's fonts (the football after the
    # side with the ball is an emoji, drawn from a font loaded on first use).
    got = _run([(_write(page), 0.5), ("document.fonts.ready.then(function(){return " + probe + ";})", 0),
                ("window.Q=" + json.dumps(quiet) + ";Q.events.forEach(apply);true", 0), (probe, 0),
                ("window.B=" + json.dumps(board) + ";B.events.forEach(apply);true", 0), (probe, 0)])
    start, quiet_, live = (json.loads(got[i]) for i in (1, 3, 5))
    assert start[0]["seen"] == "hidden", "held, unseen, until ESPN sends a number"
    assert quiet_[0]["seen"] == "hidden" and quiet_[0]["h"] == start[0]["h"]
    assert live[0]["wp"] == "ESPN win prob: ND 78%" and live[0]["seen"] == "visible"
    assert live[0]["h"] == start[0]["h"], "the number came into room the card already had"
    # The final: the live box, and the number with it, are gone.
    assert live[1]["state"] == "post" and live[1]["box"] == "none"
    assert live[2]["wp"] is None, "a game to come has none"
    # A read without a number keeps the last one.
    again = _run([(_write(page), 0),
                  ("window.B=" + json.dumps(board) + ";B.events.forEach(apply);"
                   "window.Q=" + json.dumps(quiet) + ";Q.events.forEach(apply);"
                   "document.querySelector('#g-401858250 .sc-wp').textContent", 0)])
    assert again[1] == "ESPN win prob: ND 78%"


@needs_chrome
def test_an_nfl_card_puts_espns_number_on_its_status_line():
    from nfl.site import schedule

    def card(gid, home, away, kick):
        g = pd.Series({"game_id": gid, "week": 4, "seasontype": 2, "date": pd.Timestamp(kick),
                       "home": home, "away": away, "home_id": home.lower(), "away_id": away.lower(),
                       "home_abbr": home[:3].upper(), "away_abbr": away[:3].upper(),
                       "home_score": None, "away_score": None, "played": False, "state": "pre",
                       "detail": "10/4 - 4:25 PM EDT", "tv": "CBS", "neutral": False, "place": ""})
        call = {"margin": 4.1, "prob": 0.62, "spread": -4.5, "total": 47.5}
        return schedule._card(g, call, {})
    cards = (card("401872976", "Raiders", "Chiefs", "2026-10-04T20:25Z")
             + card("401872964", "Browns", "Steelers", "2026-10-02T00:15Z"))
    js = schedule._JS
    fns = js[js.index("  function setMark("):js.index("  function sleep(){")]
    page = ("<!doctype html><html><body><div class='ns'>" + schedule._CSS
            + "<div class='ns-grid'>" + cards + "</div></div><script>" + fns
            + "</script></body></html>")
    probe = """JSON.stringify(['401872976','401872964'].map(function(id){
      var g=document.getElementById('g-'+id),t=g.querySelector('.ns-top'),w=t.querySelector('.ns-wp');
      return {h:g.getBoundingClientRect().height,top:t.getBoundingClientRect().height,
        state:g.getAttribute('data-state'),wp:w?w.textContent:null,
        shown:w?getComputedStyle(w).display:null,
        order:[].map.call(t.children,function(c){return c.className;})};}))"""
    board = _fx("nfl_scoreboard.json")
    got = _run([(_write(page), 0), (probe, 0),
                ("window.B=" + json.dumps(board) + ";B.events.forEach(apply);true", 0), (probe, 0)])
    before, after = json.loads(got[1]), json.loads(got[3])
    live, final = after
    assert live["state"] == "in" and live["wp"] == "ESPN win prob: KC 92%"
    assert live["shown"] != "none" and live["order"] == ["ns-l", "ns-wp", "ns-tv"]
    assert (live["h"], live["top"]) == (before[0]["h"], before[0]["top"]), \
        "a line every card has: the number moves nothing"
    assert final["state"] == "post" and final["wp"] is None
