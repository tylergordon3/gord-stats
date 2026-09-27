"""Projection columns go live mid-game, and only in the week being played.

No projection feed moves in play - Sleeper still says 23.5 for a back who has
finished on 41 - so the Slpr/ESPN/FP/GS columns froze at kickoff while the
Sleeper app's own number kept moving. LIVE_JS now turns each marked cell
(data-pre) into points so far plus the unplayed share of that source's number.

It also writes only inside MU_LIVE.root. Every week's view is on the page with
the same roster keys, and the unscoped poll wrote this week's live points into
the weeks before it.

Runs the real script in headless Chromium; skips where there is none.
"""
import json
import re
import time

import pytest

from gordstats import matchup_page as ui
from test_my_team_planner import CHROME, Browser

pytestmark = pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")


def _week(n: int, hidden: bool) -> str:
    style = " style='display:none'" if hidden else ""
    return (f"<div id='wk-view-{n}' class='wk-view'{style}><div data-roster='1'><table><tbody>"
            "<tr class='starter' data-pid='a'><td class='mu-pts'><b class='mu-now'>7.0</b></td>"
            "<td data-col='gs' data-pre='10'>10.0</td><td data-col='s0' data-pre='20'>20.0</td></tr>"
            "<tr class='starter' data-pid='b'><td class='mu-pts'><b class='mu-now'>5.0</b></td>"
            "<td data-col='gs' data-pre='8'>8.0</td><td data-col='s0' data-pre='6'>6.0</td></tr>"
            "<tr class='total'><td data-tcol='gs'>18.0</td><td data-tcol='s0'>26.0</td></tr>"
            "</tbody></table></div></div>")


@pytest.fixture
def page():
    browser = Browser()
    payload = {"teams": {"1": {"points": 42.0, "players": {
        "a": {"points": 12.0, "state": "in", "done": 0.5},        # halfway through
        "b": {"points": 30.0, "state": "post", "done": 1.0},      # finished
    }}}}
    script = re.sub(r"</?script>", "", ui.LIVE_JS)
    setup = (
        "document.body.innerHTML=" + json.dumps("<div id='mm-built'>" + _week(2, True)
                                                + _week(3, False) + "</div>") + ";"
        "window.MU_LIVE={root:'#mm-built #wk-view-3',delay:1,interval:600000,"
        "fetch:function(){return Promise.resolve(" + json.dumps(payload) + ");}};"
        + script + ";true")
    try:
        browser.evaluate(setup)
        time.sleep(1.0)
        yield browser
    finally:
        browser.close()


def _cells(browser, week: int) -> list:
    return browser.evaluate(
        f"Array.from(document.querySelectorAll('#wk-view-{week} td[data-col],"
        f" #wk-view-{week} td[data-tcol]')).map(function(td){{return td.textContent;}})")


def test_a_player_in_play_projects_points_plus_the_unplayed_share(page):
    gs_a, s0_a, gs_b, s0_b, tot_gs, tot_s0 = _cells(page, 3)
    assert (gs_a, s0_a) == ("17.0", "22.0")        # 12 + 10/2, 12 + 20/2
    assert (gs_b, s0_b) == ("30.0", "30.0"), "a finished game is its points"
    assert (tot_gs, tot_s0) == ("47.0", "52.0"), "the starters' totals follow"


def test_the_pre_game_number_is_kept_on_hover(page):
    title = page.evaluate("document.querySelector('#wk-view-3 td[data-col=s0]').title")
    assert title == "Pre-game 20.0"


def test_weeks_gone_by_are_left_alone(page):
    assert _cells(page, 2) == ["10.0", "20.0", "8.0", "6.0", "18.0", "26.0"]
    assert page.evaluate("document.querySelector('#wk-view-2 .mu-now').textContent") == "7.0"


def test_returning_to_the_tab_mid_fetch_does_not_start_a_second_loop():
    """The visibility handler used to clear a timer that had already fired and
    poll again, so each return while a fetch was out added a polling loop."""
    browser = Browser()
    try:
        script = re.sub(r"</?script>", "", ui.LIVE_JS)
        browser.evaluate(
            "window.CALLS=0;window.RELEASE=[];"
            "window.MU_LIVE={delay:1,interval:600000,fetch:function(){CALLS++;"
            "return new Promise(function(r){RELEASE.push(r);});}};" + script + ";true")
        time.sleep(0.5)
        for _ in range(3):              # back to the tab three times, fetch still out
            browser.evaluate("document.dispatchEvent(new Event('visibilitychange'));true")
        assert browser.evaluate("CALLS") == 1
        browser.evaluate("RELEASE.forEach(function(r){r({teams:{}});});true")
        time.sleep(0.3)
        assert browser.evaluate("CALLS") == 1, "a finished fetch should wait for the interval"
    finally:
        browser.close()
