"""The home page's "My teams": the reader's starred college teams, each with
its game, our pick or rank and the line (gordstats.my_teams_today) - football's
week and basketball's day.

Runs the real script in headless Chromium against a stubbed week and scoreboard.
"""
import json
import re
import time
from datetime import date, datetime, timedelta, timezone

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


HOOP_TEAMS = {"cbb-men:duke": ["Duke", "/assets/images/duke.png"],
              "cbb-men:st-johns": ["St. John's", "/assets/images/st johns.png"],
              "cbb-men:siu-edwardsville": ["SIUE", "/assets/images/siue.png"]}


def _iso(hours):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat(timespec="seconds")


def _et_day(hours):
    """The Eastern date cbb.live_scraper files a game under."""
    from zoneinfo import ZoneInfo
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).astimezone(
        ZoneInfo("America/New_York")).date().isoformat()


def _hoops(generated_hours=0.0):
    """Today's scoreboard as the Worker serves it (cbb.live_scraper.format_event)."""
    base = {"home_rank": None, "away_rank": None, "overtime": False, "is_mm": False,
            "is_nit": False, "game_description": "", "clock": "", "period": ""}
    games = {"generated": _iso(generated_hours), "leagues": {"men": {
        "1": dict(base, status="final", start_time_utc=_iso(-3), home_team="Duke",
                  away_team="Kansas", home_score=81, away_score=77, overtime=True,
                  home_rank=4, away_rank=9, home_model=3, away_model=11, spread_close="DUKE -2.5"),
        "2": dict(base, status="in_progress", start_time_utc=_iso(-1), home_team="Villanova",
                  away_team="St. John's", home_score=40, away_score=44, period="2nd",
                  clock="15:02", home_model=30, away_model=18, spread_close="SJU -3",
                  pred_home=70.1, pred_away=73.4, home_win_prob=0.39),
        "3": dict(base, status="pre_game", start_time_utc=_iso(2), home_team="Butler",
                  away_team="Xavier", home_model=50, away_model=60),
        # The feed runs a week ahead: Duke's next game is not today's.
        "4": dict(base, status="pre_game", start_time_utc=_iso(72), home_team="Duke",
                  away_team="Arizona", home_model=3, away_model=8)}}}
    for g in games["leagues"]["men"].values():
        g["date"] = _et_day((datetime.fromisoformat(g["start_time_utc"])
                             - datetime.now(timezone.utc)).total_seconds() / 3600)
    return games


def _run(stars, cfb=True, cbb=False, week=WEEK, hoops=None):
    script = re.sub(r"\{% (end)?raw %\}|</?script>", "", my_teams_today.JS)
    routes = {"/cfb/week-games.json": week, "/cbb/star-teams.json": HOOP_TEAMS,
              "https://cbb-live-scores.tmgordon33.workers.dev/scores?league=men": hoops}
    setup = (
        "document.body.innerHTML=\"<section><div id='mt-host' data-cfb='" + str(int(cfb))
        + "' data-cbb='" + str(int(cbb)) + "'></div></section>\";"
        "var R=" + json.dumps(routes) + ";window.ASKED=[];"
        "window.fetch=function(u){ASKED.push(u);return Promise.resolve({ok:R[u]!=null,json:function(){"
        "return Promise.resolve(R[u]);}});};"
        "(function(localStorage){" + script + "})({getItem:function(){return "
        + json.dumps(json.dumps(stars)) + ";}});true")
    browser = Browser()
    try:
        browser.evaluate(setup)
        time.sleep(0.5)
        return (browser.evaluate("document.getElementById('mt-host').innerHTML"),
                browser.evaluate("JSON.stringify(ASKED)"),
                browser.evaluate("document.querySelector('section').hidden"))
    finally:
        browser.close()


@needs_chrome
def test_starred_games_with_the_pick_the_line_and_the_byes():
    html, asked, _ = _run(["cfb:1", "cfb:3", "cfb:4", "cbb-men:duke"])
    assert "workers.dev" not in asked, "no basketball out of its season"
    rows = re.findall(r'<a class="mt-row.*?</a>', html)
    assert len(rows) == 2, "one row per starred team's game"
    second, first = rows  # by start time: the finished game leads
    assert "Home U" in first and ">vs<" in first and "ABC" in first
    assert "GordStats: <b>Home U</b> by 6.5 · 68%" in first.replace("&middot;", "·")
    assert "Line: Home U \u22126" in first
    # The starred side leads, even away from home; a finished game is the result.
    assert re.search(r'<span class="me">Road A&amp;M</span> <span class="at">at</span>', second)
    assert "W 28\u201317" in second and "Line: Road A&amp;M \u22123.5" in second
    assert "Off this week: Resting Tech." in html


@needs_chrome
def test_with_nothing_starred_it_says_where_the_stars_are():
    html, _, _ = _run(["cbb-men:duke"])
    assert "/cfb/power/" in html and "Star teams" in html
    assert "/cbb/power/" not in html, "basketball is not on yet"
    html, _, _ = _run([], cfb=True, cbb=True)
    assert "/cfb/power/" in html and "/cbb/power/" in html


@needs_chrome
def test_basketball_games_beside_football_with_the_sport_marked():
    html, asked, _ = _run(["cfb:1", "cbb-men:duke", "cbb-men:st-johns", "cbb-men:siu-edwardsville"],
                          cfb=True, cbb=True, hoops=_hoops())
    rows = re.findall(r'<a class="mt-row.*?</a>', html)
    assert len(rows) == 3, "Duke, St. John's, and Home U's football game; not Butler-Xavier"
    duke, johns, home = rows
    assert "W 81\u201377 OT" in duke and "Kansas" in duke and 'href="/men/"' in duke
    assert "GordStats rank: <b>Duke</b> #3, Kansas #11" in duke
    assert "Line: DUKE \u22122.5" in duke and '<span class="mt-sp">CBB</span>' in duke
    # St. John's is on the road and on now; its logo's file name has a space.
    assert ' live"' in johns and "Live 44\u201340 \u00b7 2nd 15:02" in johns.replace("&middot;", "\u00b7")
    assert re.search(r'<span class="me">St\. John\'s</span> <span class="at">at</span>', johns)
    # GordStats' call where the game has one (cbb.game_model); ranks where not (Duke).
    assert "GordStats: <b>St. John's</b> by 3.3 \u00b7 61%" in johns.replace("&middot;", "\u00b7")
    assert "/assets/images/st%20johns.png" in johns
    assert '<span class="mt-sp">CFB</span>' in home and "Home U" in home, "sorted by start time"
    assert "/cbb/star-teams.json" in asked


@needs_chrome
def test_the_card_is_the_days_basketball_and_a_stale_feed_is_ignored():
    html, _, _ = _run(["cbb-men:duke"], cfb=False, cbb=True, hoops=_hoops())
    assert "Arizona" not in html, "the feed's week ahead is not today"
    html, _, hidden = _run(["cbb-men:siu-edwardsville"], cfb=False, cbb=True, hoops=_hoops())
    assert "None of your teams plays today." in html and not hidden
    # Not pushed for two days: the Pi has gone quiet and the scores can't be
    # trusted, so basketball is treated as not there at all.
    html, _, hidden = _run(["cbb-men:duke"], cfb=False, cbb=True,
                           hoops=_hoops(generated_hours=-48))
    assert "Duke" not in html and hidden


@needs_chrome
def test_no_basketball_fetch_without_a_basketball_star_and_no_empty_frame():
    _, asked, _ = _run(["cfb:1"], cfb=True, cbb=True, hoops=_hoops())
    assert "workers.dev" not in asked and "/cbb/star-teams.json" not in asked
    # Football's file missing and only football starred: the card goes, not a blank box.
    _, _, hidden = _run(["cfb:1"], cfb=True, cbb=True, week=None, hoops=_hoops())
    assert hidden


def test_it_leads_the_home_page_in_either_season():
    from cbb.render import render_home
    fall = render_home._my_teams(date(2026, 9, 28))
    assert 'data-cfb="1" data-cbb="0"' in fall and "My teams this week" in fall
    both = render_home._my_teams(date(2026, 12, 5))
    assert 'data-cfb="1" data-cbb="1"' in both and ">My teams<" in both
    assert 'data-cfb="1" data-cbb="1"' in render_home._my_teams(date(2027, 1, 12)), "the playoff final"
    spring = render_home._my_teams(date(2027, 2, 1))
    assert 'data-cfb="0" data-cbb="1"' in spring and 'href="/men/"' in spring
    assert render_home._my_teams(date(2027, 6, 1)) == ""
    assert 'id="my-teams"' not in render_home._cfb_graphics(date(2026, 9, 28))


def test_a_basketball_star_finds_its_team_on_the_scoreboard(tmp_path, monkeypatch):
    """The stars are keyed on T-Rank's names; the scoreboard uses the site's."""
    import pandas as pd

    from cbb.render import render_power

    master = tmp_path / "master.json"
    pd.DataFrame({"team": ["SIUE", "McNeese", "Miami FL"], "index": [0, 1, 2],
                  "names": [["SIU Edwardsville", "SIUE"], ["MCN"], ["Miami (FL)", "Miami"]],
                  "path": ["siue.png", "mcneese.png", "miami fl.png"],
                  "short": ["SIUE", "McN", "Miami"]}).to_json(master)
    monkeypatch.setattr(render_power.paths, "MASTER_DICT", master)
    got = render_power.star_teams(["SIU Edwardsville", "McNeese St.", "Miami FL", "West Florida"])
    assert got == {"cbb-men:siu-edwardsville": ["SIUE", "/assets/images/siue.png"],
                   "cbb-men:mcneese-st": ["McNeese", "/assets/images/mcneese.png"],
                   "cbb-men:miami-fl": ["Miami FL", "/assets/images/miami fl.png"]}, \
        "a school new to D-1 is left out: the scoreboard cannot name it either"
