"""The home page's "My teams this week": the reader's starred college teams,
each with its game, our pick and the line (gordstats.my_teams_today).

Runs the real script in headless Chromium against a stubbed week.
"""
import json
import re
import time

import pytest

from gordstats import my_teams_today
from test_my_team_planner import CHROME, Browser

needs_chrome = pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")

WEEK = {"season": 2026, "teams": {"1": "Home U", "2": "Visitor St", "3": "Resting Tech",
                                  "4": "Road A&M", "5": "Host College"},
        "games": [
            {"id": "g1", "week": 5, "seasontype": 2, "kickoff": "2099-10-03T19:30:00Z",
             "time_known": True, "neutral": False, "tv": "ABC", "note": "", "state": "pre",
             "home": {"id": "1", "name": "Home U", "rank": 7, "pred": 31.0, "score": 0},
             "away": {"id": "2", "name": "Visitor St", "rank": None, "pred": 24.5, "score": 0},
             "home_win": 0.68, "book_spread": -6.0, "book_total": 55.5},
            {"id": "g2", "week": 5, "seasontype": 2, "kickoff": "2000-10-03T19:30:00Z",
             "time_known": True, "neutral": False, "tv": "", "note": "", "state": "post",
             "home": {"id": "5", "name": "Host College", "rank": None, "pred": 20.0, "score": 17},
             "away": {"id": "4", "name": "Road A&M", "rank": 12, "pred": 27.0, "score": 28},
             "home_win": 0.30, "book_spread": 3.5, "book_total": 50.0}]}


def _run(stars):
    script = re.sub(r"\{% (end)?raw %\}|</?script>", "", my_teams_today.JS)
    setup = (
        "document.body.innerHTML=\"<section><div id='mt-host'></div></section>\";"
        "window.fetch=function(){return Promise.resolve({ok:true,json:function(){"
        "return Promise.resolve(" + json.dumps(WEEK) + ");}});};"
        "(function(localStorage){" + script + "})({getItem:function(){return "
        + json.dumps(json.dumps(stars)) + ";}});true")
    browser = Browser()
    try:
        browser.evaluate(setup)
        time.sleep(0.5)
        return browser.evaluate("document.getElementById('mt-host').innerHTML")
    finally:
        browser.close()


@needs_chrome
def test_starred_games_with_the_pick_the_line_and_the_byes():
    html = _run(["cfb:1", "cfb:3", "cfb:4", "cbb-men:duke"])
    rows = re.findall(r'<a class="mt-row.*?</a>', html)
    assert len(rows) == 2, "one row per starred team's game"
    first, second = rows
    assert "Home U" in first and ">vs<" in first and "ABC" in first
    assert "GordStats: <b>Home U</b> by 6.5 · 68%" in first.replace("&middot;", "·")
    assert "Line: Home U \u22126" in first
    # The starred side leads, even away from home; a finished game is the result.
    assert re.search(r'<span class="me">Road A&amp;M</span> <span class="at">at</span>', second)
    assert "W 28\u201317" in second and "Line: Road A&amp;M \u22123.5" in second
    assert "Off this week: Resting Tech." in html


@needs_chrome
def test_with_nothing_starred_it_says_where_the_stars_are():
    html = _run(["cbb-men:duke"])
    assert "/cfb/power/" in html and "Star teams" in html


def test_it_leads_the_home_page_in_the_football_season():
    from datetime import date
    from cbb.render import render_home
    assert 'id="my-teams"' in render_home._cfb_graphics(date(2026, 9, 28))
    assert render_home._cfb_graphics(date(2026, 2, 1)) == ""
