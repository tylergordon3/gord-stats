"""League Home leads with the week: every matchup and the standings, drawn
from Sleeper for whichever league is on screen (gordstats.week_strip).

Runs the real script in headless Chromium against a stubbed Sleeper.
"""
import json
import re
import time
from datetime import datetime, timedelta, timezone

import pytest

from fantasy.config import UPCOMING_LEAGUE_ID
from gordstats import league_api, week_strip
from test_my_team_planner import CHROME, Browser

needs_chrome = pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")


def _iso(hours):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_it_is_on_league_home_first_and_reads_the_site_league_by_default():
    from fantasy.site import homepage
    src = open(homepage.__file__).read()
    assert "+ week_strip.section()\n            + mine_section()" in src
    assert "+ week_strip.JS" in src
    assert f'"siteLeague":"{UPCOMING_LEAGUE_ID}"' in week_strip.JS_TAG


@needs_chrome
def test_matchups_standings_and_states():
    # Teams KC (done), NE (playing now), SF (not yet, tomorrow).
    wk = {"week": 4, "kick": {"KC": _iso(-8), "NE": _iso(-1), "SF": _iso(20)},
          "proj": {"p1": [20, 20, 20, "KC", ""], "p2": [10, 10, 10, "KC", ""],
                   "p3": [15, 15, 15, "NE", ""], "p4": [12, 12, 12, "SF", ""],
                   "p5": [9, 9, 9, "SF", ""], "p6": [11, 11, 11, "SF", ""]}}
    sleeper = {
        "/state/nfl": {"season": "2026", "display_week": 4},
        "/league/L": {"season": "2026", "settings": {"league_average_match": 1}, "scoring_settings": {"rec": 1}},
        "/league/L/rosters": [
            {"roster_id": 1, "owner_id": "u1", "settings": {"wins": 2, "losses": 4, "fpts": 400}},
            {"roster_id": 2, "owner_id": "u2", "settings": {"wins": 5, "losses": 1, "fpts": 450}},
            {"roster_id": 3, "owner_id": "u3", "settings": {"wins": 5, "losses": 1, "fpts": 470}},
            {"roster_id": 4, "owner_id": "u4", "settings": {"wins": 0, "losses": 6, "fpts": 380}}],
        "/league/L/users": [{"user_id": f"u{i}", "display_name": f"m{i}",
                             "metadata": {"team_name": f"Team {i}"}} for i in (1, 2, 3, 4)],
        "/league/L/matchups/4": [
            {"roster_id": 1, "matchup_id": 1, "points": 30.5, "starters": ["p1", "p2"]},
            {"roster_id": 2, "matchup_id": 1, "points": 12.0, "starters": ["p3"]},
            {"roster_id": 3, "matchup_id": 2, "points": 0, "starters": ["p4", "p5"]},
            {"roster_id": 4, "matchup_id": 2, "points": 0, "starters": ["p6"]}],
    }
    # GSAPI comes with the league control on every page that has the strip.
    script = re.sub(r"\{% (end)?raw %\}|</?script>", "", league_api.JS + week_strip.JS)
    setup = (
        "document.body.innerHTML=\"<div id='ws-host'></div>\";"
        "var S=" + json.dumps(sleeper) + ",WK=" + json.dumps(wk) + ";"
        "window.fetch=function(url){var p=url.replace('https://api.sleeper.app/v1','');"
        "return Promise.resolve({ok:p in S,json:function(){return Promise.resolve(S[p]);}});};"
        "window.GSL={saved:function(){return {id:'L'};},week:function(){return Promise.resolve(WK);},"
        "basis:function(){return {index:0};},"
        "points:function(wk,i){var o={};for(var k in wk.proj)o[k]=wk.proj[k][i];return o;},"
        "myRoster:function(){return '3';}};" + script + ";true")
    browser = Browser()
    try:
        browser.evaluate(setup)
        time.sleep(0.8)
        html = browser.evaluate("document.getElementById('ws-host').innerHTML")
    finally:
        browser.close()
    rows = re.findall(r'<a class="ws-mu( me)?".*?</a>', html)
    assert len(rows) == 2 and rows[0] == " me", "the reader's matchup comes first"
    mine, other = re.findall(r'<a class="ws-mu.*?</a>', html)
    assert "Team 3" in mine and "projected" in mine and "21.0" in mine, "12 + 9 before kickoff"
    assert "11.0" in mine
    assert "live" in other and "30.5" in other, "NE is on now"
    standings = re.findall(r'<td class="t">(Team \d)</td>', html)
    assert standings == ["Team 3", "Team 2", "Team 1", "Team 4"], "wins, then points"
    assert '<tr class="me"><td class="rk">1</td><td class="t">Team 3' in html
    assert "median games included" in html
