"""A reader's League Home, in the built page's format and with its arithmetic.

It used to be a different page from everybody else's - champions, a table per
season, an all-time table and a head-to-head grid, one after another. It now
draws the built page's two sections (All-Time Metrics, the team profiles)
from Sleeper. Checked against the built league itself on 2026-09-28: every
record, SOS, SOV and expected-wins figure matched the archive's table, bar
two single-point stat corrections the archive predates.
"""
import json
import math
import re

import pytest

from fantasy.config import EXPW_RATIO
from gordstats import my_history, my_home
from test_my_team_planner import CHROME, Browser

needs_chrome = pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")


def _scripts() -> str:
    strip = lambda js: re.sub(r"\{% (end)?raw %\}|</?script>", "", js)  # noqa: E731
    # my_home reads GSL at load; a stub is all the arithmetic needs.
    return ("window.GSL={saved:function(){return null;}};" + strip(my_history.JS) + ";"
            + strip(my_home.JS) + ";")


def test_the_page_carries_the_reading_and_the_drawing_in_order():
    from fantasy.site import homepage
    src = open(homepage.__file__).read()
    assert "my_history.JS + my_home.JS" in src, "my_home runs before GSHist exists"
    section = homepage.mine_section()
    assert 'id="mh-metrics"' in section and 'id="mh-teams"' in section
    assert "/fantasy/history/" in section and "/fantasy/draft-review/" in section
    # The built profiles' markup, so team_profiles.CSS dresses both.
    for cls in ("tp-card", "tp-tiles", "tp-rivals", "tp-vs", "tp-seasons", "strip-wide"):
        assert cls in my_home.JS, cls
    assert f"var RATIO={EXPW_RATIO};" in my_home.JS


def _built_formulas(records, games):
    """homepage.all_time_metrics, in plain Python over the same inputs."""
    winp = {k: w / (w + l) for k, (w, l, _pf, _pa) in records.items()}
    opps = {k: [] for k in records}
    beat = {k: [] for k in records}
    h2h = {k: [0, 0] for k in records}
    for a, b, ap, bp in games:
        for me, them, mine, theirs in ((a, b, ap, bp), (b, a, bp, ap)):
            opps[me].append(them)
            if mine > theirs:
                beat[me].append(them)
                h2h[me][0] += 1
            elif mine < theirs:
                h2h[me][1] += 1
    avg = lambda v: sum(v) / len(v) if v else 0.0  # noqa: E731
    ow = {k: avg([winp[o] for o in opps[k]]) for k in records}
    out = {}
    for k, (w, l, pf, pa) in records.items():
        oow = avg([ow[o] for o in opps[k]])
        share = pf ** EXPW_RATIO / (pf ** EXPW_RATIO + pa ** EXPW_RATIO)
        out[k] = {"sos": round((ow[k] * 2 + oow) / 3, 3), "sov": round(avg([winp[o] for o in beat[k]]), 3),
                  "expw": f"{share * sum(h2h[k]):.1f} ({h2h[k][0]})"}
    return out


@needs_chrome
def test_all_time_metrics_are_the_built_tables_arithmetic():
    records = {"A": (6, 2, 520.0, 450.0), "B": (5, 3, 480.0, 470.0),
               "C": (3, 5, 455.0, 490.0), "D": (2, 6, 430.0, 475.0)}
    games = [("A", "B", 130, 120), ("C", "D", 110, 115), ("A", "C", 140, 100),
             ("B", "D", 125, 118), ("A", "D", 105, 112), ("B", "C", 119, 121)]
    seasons = [{"season": "2025", "teams": [
        {"owner": k, "wins": w, "losses": l, "ties": 0, "pf": pf, "pa": pa, "champion": k == "A"}
        for k, (w, l, pf, pa) in records.items()]}]
    log = [{"season": "2025", "week": i + 1, "kind": "regular", "a": a, "b": b, "ap": ap, "bp": bp}
           for i, (a, b, ap, bp) in enumerate(games)]
    names = {k: k for k in records}
    browser = Browser()
    try:
        html = browser.evaluate(_scripts() + "GSHome.metrics(" + json.dumps(seasons) + ","
                                + json.dumps(log) + "," + json.dumps(names) + ")")
    finally:
        browser.close()
    rows = {}
    for tr in re.findall(r"<tr><td>(.*?)</tr>", html):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", "<td>" + tr)
        rows[cells[0]] = cells
    want = _built_formulas(records, games)
    for k in records:
        assert float(rows[k][5]) == pytest.approx(want[k]["sos"], abs=1e-3), k
        assert float(rows[k][6]) == pytest.approx(want[k]["sov"], abs=1e-3), k
        assert rows[k][7] == want[k]["expw"], k
    assert list(rows) == ["A", "B", "C", "D"], "ordered by wins, then points"
    assert "&#128081;" in rows["A"][1] and rows["B"][1] == "-"


@needs_chrome
@pytest.mark.parametrize("roster, want", [
    (1, "Champion"), (2, "Runner-up"), (3, "Lost semifinal"), (5, "Lost quarterfinal"),
    (9, "Missed playoffs")])
def test_the_bracket_finish_is_team_profiles_own(roster, want):
    # Six-team bracket: 1 and 2 on byes; 3 beats 6, 4 beats 5; 1 beats 4, 2 beats 3; 1 beats 2.
    bracket = [{"r": 1, "t1": 3, "t2": 6, "w": 3, "l": 6}, {"r": 1, "t1": 4, "t2": 5, "w": 4, "l": 5},
               {"r": 2, "t1": 1, "t2": 4, "w": 1, "l": 4}, {"r": 2, "t1": 2, "t2": 3, "w": 2, "l": 3},
               {"r": 3, "t1": 1, "t2": 2, "w": 1, "l": 2, "p": 1},
               {"r": 3, "t1": 3, "t2": 4, "w": 4, "l": 3, "p": 3}]
    season = {"season": "2025", "bracket": bracket,
              "teams": [{"owner": f"o{r}", "roster_id": r, "champion": r == 1} for r in (1, 2, 3, 4, 5, 6, 9)]}
    browser = Browser()
    try:
        got = browser.evaluate(_scripts() + "GSHome.finish(" + json.dumps(season) + ",'o" + str(roster) + "')")
    finally:
        browser.close()
    assert got == want
