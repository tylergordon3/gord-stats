"""The site's own league, synced by id, still gets the built pages.

Every page that can show a reader's league checked only `have.site`, which
"Show this site's league" set. The site's own manager, having synced the league
he runs, got the browser-drawn pages meant for a stranger's league instead -
League Home without its all-time metrics and team profiles.
"""
import json
import re

import pytest

from fantasy.config import LEAGUE_IDS
from gordstats import my_league
from test_my_team_planner import CHROME, Browser

needs_chrome = pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")


def test_every_season_of_the_league_counts_as_the_site():
    snippet = my_league.site_league_js()
    for league_id in LEAGUE_IDS.values():
        assert f"'{league_id}'" in snippet
    assert "__SITE_IDS__" not in my_league.JS


@needs_chrome
@pytest.mark.parametrize("league_id, site", [(LEAGUE_IDS["2627"], True),
                                              ("1180250213485592576", None)])
def test_a_saved_league_is_marked_when_it_is_this_one(league_id, site):
    code = re.sub(r"\{% (end)?raw %\}|</?script>", "", my_league.site_league_js())
    saved = json.dumps({"id": league_id, "name": "x"})
    js = ("(function(){var store={gsSleeperLeague:" + json.dumps(saved) + "};"
          "var localStorage={getItem:function(k){return store[k]||null;},"
          "setItem:function(k,v){store[k]=v;}};" + code
          + "return store.gsSleeperLeague;})()")
    browser = Browser()
    try:
        got = json.loads(browser.evaluate(js))
    finally:
        browser.close()
    assert got.get("site") is site and got["id"] == league_id
