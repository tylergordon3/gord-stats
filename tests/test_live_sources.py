"""Each source's expected final and win bar move with the games.

Under a live 144.7 the matchup header still said "GordStats 130.4 · Sleeper
135.3" - the pre-game totals, fixed at kickoff - and there was one win bar.
Now the header carries each source's expected final (points so far plus the
unplayed share of that source's projections) and each source has a bar:
GordStats and Sleeper on the NFL page, GordStats and Yahoo on the college one,
Sleeper's and ours worked out the same way on the same spread.

The browser half runs the real scripts in headless Chromium; skips where there
is none.
"""
import json
import re
import time

import pytest

from gordstats import matchup_page as ui
from test_my_team_planner import CHROME, Browser

needs_chrome = pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")


def test_a_source_row_carries_its_finals_and_follows_its_own_chance():
    row = ui.source_bar("Sleeper", "sleeper", "1", "2", 131.26, 120.0, 0.6,
                        follows="sleeper", alt=True)
    assert row.count('data-src="sleeper"') == 4, "both bar halves and both percentages"
    assert "<b class='mu-src-a hi' data-tlive='1' data-src='sleeper'>131.3</b>" in row
    assert "mu-src alt" in row.replace("mu-src-sleeper ", "")
    plain = ui.source_bar("GordStats", "gs", "1", "2", 100, 110, 0.4)
    assert 'data-src="' not in plain and "<b class='mu-src-b hi'" in plain


def test_win_probability_is_even_on_level_finals_and_floored_when_all_but_over():
    assert ui.win_probability(100, 50, 100, 50) == 0.5
    # Nothing left to play and a point in it: still odds, not a certainty.
    assert 0.6 < ui.win_probability(101, 0, 100, 0) < 0.8


def _side(key: str, rows: str) -> str:
    return f"<div data-roster='{key}'><table><tbody>{rows}</tbody></table></div>"


def _head(keys) -> str:
    return "<div class='mu-head'>" + "".join(
        f"<div class='num' data-num='{k}' data-mu='m1' data-val=''></div>"
        f"<div class='sub'>GordStats {ui.live_total(k, 'gs', 0)} · "
        f"Yahoo {ui.live_total(k, 'yahoo', 0)} · Sleeper {ui.live_total(k, 'sleeper', 0)}</div>"
        for k in keys) + "</div>"


@needs_chrome
def test_the_college_poll_moves_both_totals_and_both_bars():
    # g1 is half played (3rd quarter, 15:00 left), g2 is over.
    games = {"g1": {"state": "in", "period": 3, "clock": "15:00"},
             "g2": {"state": "post", "period": 4, "clock": "0:00"}}
    payload = {"teams": {
        "A": {"points": 18, "win_probability": 0.7,
              "players": {"a1": {"points": 10}, "a2": {"points": 8}}},
        "B": {"points": 18, "win_probability": 0.3,
              "players": {"b1": {"points": 6}, "b2": {"points": 12}}}}}
    row = ("<tr class='starter' data-pid='{0}' data-gid='{1}' data-side='home' "
           "data-proj='{2}' data-yproj='{3}'><td class='mu-pts'></td></tr>")
    dom = ("<div id='wk-view-5'>" + _head("AB")
           + ui.source_bar("GordStats", "gs", "A", "B", 0, 0, 0.5, follows="gs")
           + ui.source_bar("Yahoo", "yahoo", "A", "B", 0, 0, 0.5, alt=True)
           + _side("A", row.format("a1", "g1", 20, 16) + row.format("a2", "g2", 10, 12))
           + _side("B", row.format("b1", "g1", 15, 15) + row.format("b2", "g2", 10, 10))
           + "</div>")
    browser = Browser()
    try:
        browser.evaluate(
            "document.body.innerHTML=" + json.dumps(dom) + ";" + ui.LIVE_GAMES_JS
            + ";window.MU_LIVE={root:'#wk-view-5',delay:1,interval:600000,fetch:function(){"
            "var R=document.querySelector('#wk-view-5'),G=" + json.dumps(games) + ";"
            "return Promise.resolve(muLiveProjections(muMergeGames(" + json.dumps(payload)
            + ",G,R),G,R,{yahoo:'data-yproj'}));}};"
            + re.sub(r"</?script>", "", ui.LIVE_JS) + ";true")
        time.sleep(1.0)
        got = json.loads(browser.evaluate(
            "JSON.stringify({t:Array.from(document.querySelectorAll('[data-tlive]'))"
            ".map(function(e){return e.getAttribute('data-tlive')+e.getAttribute('data-src')"
            "+'='+e.textContent;}),w:Array.from(document.querySelectorAll('.mu-bar i'))"
            ".map(function(e){return e.style.width;}),hi:Array.from(document.querySelectorAll("
            "'.mu-src .hi')).map(function(e){return e.getAttribute('data-tlive')"
            "+e.getAttribute('data-src');})})"))
    finally:
        browser.close()
    # A: 10 + 20/2 + 8 ours, 10 + 16/2 + 8 Yahoo's; B: 6 + 15/2 + 12 on both.
    assert got["t"][:2] == ["Ags=28.0", "Ayahoo=26.0"]
    assert got["t"][3:5] == ["Bgs=25.5", "Byahoo=25.5"]
    assert got["t"][2] == "Asleeper=0.0", "a source the payload has no number for stands"
    # Ours: 2.5 ahead with sd 12 and 9 halved still to play -> 59%. Yahoo's is Yahoo's.
    assert got["w"] == ["59%", "41%", "70%", "30%"]
    assert got["hi"] == ["Ags", "Ayahoo"], "each row marks the side it has ahead"


@needs_chrome
def test_the_nfl_poll_works_out_sleepers_chance_on_the_same_spread():
    from fantasy.site import matchups
    script = (matchups._LIVE_FETCH_JS.replace("__WEEK__", "3").replace("__INTERVAL__", "600000")
              .replace("__SLEEPER__", "x").replace("__ESPN__", "x"))
    row = ("<tr class='starter' data-pid='{0}' data-team='{1}' data-proj='{2}' data-sd='{3}' "
           "data-hproj='{2}' data-sproj='{4}'></tr>")
    dom = ("<div id='mm-built'><div id='wk-view-3'>"
           + _side("1", row.format("p1", "SF", 20, 5, 16) + row.format("p2", "KC", 10, 4, 14))
           + _side("2", row.format("q1", "SF", 15, 5, 15) + row.format("q2", "KC", 10, 4, 8))
           + "</div></div>")
    rows = [{"roster_id": 1, "matchup_id": 1, "points": 18, "players_points": {"p1": 10, "p2": 8}},
            {"roster_id": 2, "matchup_id": 1, "points": 18, "players_points": {"q1": 6, "q2": 12}}]
    games = {"SF": {"state": "in", "period": 3, "clock": "15:00"},
             "KC": {"state": "post", "period": 4, "clock": "0:00"}}
    browser = Browser()
    try:
        browser.evaluate("document.body.innerHTML=" + json.dumps(dom) + ";"
                         + ui.LIVE_GAMES_JS + ";" + script + ";true")
        got = json.loads(browser.evaluate(
            "JSON.stringify(MU_LIVE.compute(" + json.dumps(rows) + "," + json.dumps(games)
            + ").teams[1])"))
    finally:
        browser.close()
    assert got["tlive"] == {"gs": 28, "sleeper": 26}
    # Ours 2.5 ahead, Sleeper's 0.5, both on sd sqrt(5^2/2 * 2) = 5.
    assert abs(got["win_probability"] - ui.win_probability(28, 12.5, 25.5, 12.5)) < 1e-6
    assert abs(got["wps"]["sleeper"] - ui.win_probability(26, 12.5, 25.5, 12.5)) < 1e-6
