"""
The NFL rankings page (nfl.site.power) and the FPI pull behind it (nfl.fpi):
fields read by the payload's own header rather than by position, "-" as a
figure ESPN has not computed, the trimmed cache, the NFL calendar as Move's
windows, the one-time seed of a mid-season archive, and the page itself on a
four-team league - GordStats order, team links, stars keyed nfl:<ESPN id>,
the Odds tab, and a page that still stands when ESPN has nothing.

The watch guide's half of the stars (nfl.site.watch's stars()) runs in
headless Chromium; it skips without Chromium. No network anywhere.
"""
import asyncio
import functools
import http.server
import json
import shutil
import socketserver
import subprocess
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from gordstats import favorites, rankmoves
from gordstats.js_assets import expand
from nfl import fpi
from nfl.site import power
from nfl.site import teams as teams_page
from browser_util import launch, reap

CHROME = next((p for p in ("/usr/bin/chromium-browser", "/usr/bin/chromium",
                           "/usr/bin/google-chrome") if shutil.which(p)), None)
CDP = 9458

# As the module declares it, before the fixture below widens it for a test.
_DECLARED = favorites.SPORTS


def test_nfl_is_a_favourites_section():
    """The rankings and team pages star teams as nfl:<ESPN id>, and
    gordstats.favorites refuses a section it does not know - so without
    "nfl" in SPORTS both pages fail to build."""
    assert "nfl" in _DECLARED


@pytest.fixture(autouse=True)
def _nfl_stars(monkeypatch):
    # The rest of this file tests the pages, not the section list above.
    if "nfl" not in favorites.SPORTS:
        monkeypatch.setattr(favorites, "SPORTS", favorites.SPORTS + ("nfl",))


# --------------------------------------------------------------------------- #
# The FPI payload
# --------------------------------------------------------------------------- #

def _team(tid, abbr, full, nick, div, conf, fpi_vals, fpi_shown, proj_vals, proj_shown):
    return {"team": {"id": tid, "abbreviation": abbr, "displayName": full,
                     "shortDisplayName": nick, "name": nick,
                     "logos": [{"href": "x"}] * 8,
                     "group": {"name": div, "parent": {"abbreviation": conf}}},
            "categories": [
                {"name": "fpi", "values": fpi_vals, "totals": fpi_shown},
                {"name": "projections", "values": proj_vals, "totals": proj_shown},
                {"name": "efficiencies", "values": [1.0], "totals": ["1"]}]}


def payload():
    """Two teams, the fpi category's columns in an order the fallback would
    misread (projections put before it, special teams moved to the front)."""
    fpi_names = ["epaspecialteams", "fpi", "epaoffense", "epadefense", "fpirank",
                 "accomplishmentrank", "avgsosrank", "sosremainingrank", "numwins",
                 "numlosses", "numties"]
    proj_names = ["projectedw", "projectedl", "probwinout", "probwinconf", "probwindiv",
                  "probmakeplayoffs", "probmakedivplayoffs", "probmaketitlegame",
                  "probwintitle", "probmakeconfchamp"]
    return {
        "requestedSeason": {"year": 2026}, "glossary": [{"displayName": "x"}] * 50,
        "categories": [{"name": "projections", "names": proj_names},
                       {"name": "fpi", "names": fpi_names},
                       {"name": "efficiencies", "names": ["totefficiency"]}],
        "teams": [
            _team("25", "SF", "San Francisco 49ers", "49ers", "NFC West", "NFC",
                  [0.4, 7.3, 6.6, 0.3, 1.0, 0.0, 31.0, 11.0, 3.0, 0.0, 0.0],
                  ["0", "7.3", "7", "0", "1st", "-", "31st", "11th", "3", "0", "0"],
                  [13.2, 3.8, 0.9, None, 78.9, 98.0, 86.1, 40.6, 25.3, 59.3],
                  ["13.2", "3.8", "0.9%", "-", "78.9%", "98%", "86.1%", "40.6%", "25.3%", "59.3%"]),
            _team("12", "KC", "Kansas City Chiefs", "Chiefs", "AFC West", "AFC",
                  [0.0, 4.8, 3.0, 1.8, 2.0, 0.0, 30.0, 12.0, 3.0, 0.0, 0.0],
                  ["0", "4.8", "3", "2", "2nd", "-", "30th", "12th", "3", "0", "0"],
                  [11.9, 5.0, 0.2, None, 79.7, 95.5, 73.3, 24.5, 12.4, 43.8],
                  ["11.9", "5.0", "0.2%", "-", "79.7%", "95.5%", "73.3%", "24.5%", "12.4%", "43.8%"]),
        ]}


def test_fields_are_read_by_name_not_position():
    rows = fpi.rows(payload())
    sf, kc = rows
    assert (sf["id"], sf["abbr"], sf["full"], sf["div"], sf["conf"]) == \
        ("25", "SF", "San Francisco 49ers", "NFC West", "NFC")
    assert sf["fpi"] == 7.3 and sf["epaspecialteams"] == 0.4 and sf["epaoffense"] == 6.6
    assert sf["probwintitle"] == 25.3 and sf["probwindiv"] == 78.9 and sf["probmaketitlegame"] == 40.6
    assert (sf["rank"], kc["rank"]) == (1, 2)


def test_a_dash_is_a_figure_espn_has_not_computed():
    """Strength of record is "-" until results say something - None, not the
    0.0 that sits in `values` beside it."""
    sf = fpi.rows(payload())[0]
    assert sf["accomplishmentrank"] is None and sf["avgsosrank"] == 31.0
    assert sf["numties"] == 0.0


def test_the_cache_keeps_only_what_the_page_reads():
    full = payload()
    slim = fpi._trim(full)
    assert fpi.rows(slim) == fpi.rows(full)
    text = json.dumps(slim)
    assert "logos" not in text and "glossary" not in text and "efficiencies" not in text


class _Answer:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


def test_an_unchanged_pull_only_touches_the_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(fpi, "DATA_DIR", tmp_path)
    monkeypatch.setattr(fpi.requests, "get", lambda *a, **k: _Answer(payload()))
    fpi.fetch(refresh=True)
    path = fpi.cache_path()
    before = path.read_text()
    import os
    os.utime(path, (1, 1))
    fpi.fetch(refresh=True)
    assert path.read_text() == before and path.stat().st_mtime > 1


def test_espn_down_falls_back_to_the_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(fpi, "DATA_DIR", tmp_path)
    monkeypatch.setattr(fpi.requests, "get", lambda *a, **k: _Answer(payload()))
    fpi.fetch(refresh=True)

    def down(*a, **k):
        raise fpi.requests.ConnectionError("down")
    monkeypatch.setattr(fpi.requests, "get", down)
    assert [t["abbr"] for t in fpi.rows(fpi.fetch(refresh=True))] == ["SF", "KC"]


def test_no_cache_and_espn_down_is_an_empty_answer(monkeypatch, tmp_path):
    monkeypatch.setattr(fpi, "DATA_DIR", tmp_path)

    def down(*a, **k):
        raise fpi.requests.ConnectionError("down")
    monkeypatch.setattr(fpi.requests, "get", down)
    assert fpi.by_id() == {}


# --------------------------------------------------------------------------- #
# A four-team league
# --------------------------------------------------------------------------- #

TEAMS = {"12": ("Chiefs", "KC"), "13": ("Raiders", "LV"), "25": ("49ers", "SF"),
         "28": ("Commanders", "WSH"), "-1": ("TBD", "TBD"), "-2": ("TBD", "TBD")}
RATING = {"12": 5.0, "28": 2.0, "25": 1.0, "13": -3.0}


class Model:
    def rating(self, team):
        return RATING.get(team, 0.0)

    def pace(self, team):
        return 0.5


def season_frame():
    """Week 1 played (KC beat LV, WSH beat SF), Week 2 to come, and an unpaired
    Wild Card game."""
    kick = pd.Timestamp("2026-09-13T17:00Z")

    def game(week, st, gid, home, away, date, hs=None, as_=None):
        played = hs is not None
        margin = RATING.get(home, 0) - RATING.get(away, 0) + 1.5
        return {"week": week, "seasontype": st, "game_id": gid, "date": date,
                "home_team": home, "away_team": away, "home_id": home, "away_id": away,
                "home": TEAMS[home][0], "away": TEAMS[away][0],
                "home_abbr": TEAMS[home][1], "away_abbr": TEAMS[away][1],
                "played": played, "home_score": hs, "away_score": as_,
                "actual_margin": (hs - as_) if played else np.nan,
                "pred_margin": margin, "pred_home": 22 + margin / 2, "pred_away": 22 - margin / 2,
                "home_win_prob": 0.5 + margin / 30, "neutral": False}
    return pd.DataFrame([
        game(1, 2, "1", "12", "13", kick, 24, 10),
        game(1, 2, "2", "25", "28", kick, 17, 20),
        game(2, 2, "3", "25", "12", kick + pd.Timedelta(days=7)),
        game(2, 2, "4", "28", "13", kick + pd.Timedelta(days=7)),
        game(1, 3, "5", "-1", "-2", kick + pd.Timedelta(days=120)),
    ])


def espn_rows():
    base = {f: None for fields in fpi.FIELDS.values() for f in fields}
    return {
        "12": {**base, "id": "12", "abbr": "KC", "full": "Kansas City Chiefs", "div": "AFC West",
               "fpi": 4.8, "rank": 1, "epaoffense": 3.0, "epadefense": 1.8,
               "epaspecialteams": 0.0, "projectedw": 11.9, "projectedl": 5.0,
               "probmakeplayoffs": 95.5, "probwindiv": 79.7, "probmaketitlegame": 24.5,
               "probwintitle": 12.4, "avgsosrank": 30.0, "sosremainingrank": 12.0},
        "25": {**base, "id": "25", "abbr": "SF", "full": "San Francisco 49ers", "div": "NFC West",
               "fpi": 2.0, "rank": 2, "projectedw": 9.0, "projectedl": 8.0,
               "probmakeplayoffs": 50.0, "probwindiv": 30.0, "probmaketitlegame": 5.0,
               "probwintitle": 0.0, "avgsosrank": 1.0, "sosremainingrank": 1.0},
    }


@pytest.fixture
def league(monkeypatch, tmp_path):
    frame = season_frame()
    monkeypatch.setattr(power, "HISTORY_DIR", tmp_path / "history")
    monkeypatch.setattr(power.predict, "season",
                        lambda asof=None: (frame, Model(), TEAMS))
    monkeypatch.setattr(power.fpi, "by_id", lambda refresh=False: espn_rows())
    monkeypatch.setattr(power.share_card, "ranked", lambda *a, **k: None)
    # The fixture's season is in the past; its seeding has tests of its own.
    monkeypatch.setattr(power, "seed_history", lambda spans, now=None: 0)
    return frame


def _rows_in_order(html):
    import re
    return re.findall(r"<tr data-fav=\"nfl:(\d+)\">", html)


def test_the_table_opens_in_gordstats_order_with_links_and_stars(league):
    html = power.body()
    assert _rows_in_order(html) == ["12", "28", "25", "13"]
    # The name goes to the team page; the star sits beside it, keyed by id.
    assert "<a href='/nfl/teams/chiefs/'><span class='pwr-masc'>Kansas City </span>Chiefs</a>" in html
    assert "data-fav-for='nfl:12'" in html and "aria-label='Follow Kansas City Chiefs'" in html
    # A team ESPN has no row for still gets its nickname, link and star.
    assert "<a href='/nfl/teams/commanders/'>Commanders</a>" in html
    assert "data-fav-for='nfl:28'" in html
    assert "table.cfb-power tr.is-fav > td" in html
    assert "class='fav-controls'" in html
    # The TBD playoff placeholder is nobody's row.
    assert "nfl:-1" not in html


def test_records_rating_and_the_fpi_split(league):
    html = power.body()
    assert "<span class='pwr-rec'>1-0</span>" in html        # KC
    assert "<span class='gs-rk'>1</span>+5.0" in html
    assert "<span class='gs-rk'>1</span>+4.8" in html        # KC's FPI and its rank
    assert "data-field='off'" in html and "data-field='st'" in html


def test_the_odds_tab_carries_espns_simulations(league):
    html = power.body()
    for field in ("projectedw", "probmakeplayoffs", "probwindiv", "probmaketitlegame",
                  "probwintitle"):
        assert f"data-field='{field}'" in html
    assert "11.9-5.0" in html and "95.5%" in html
    # A real 0% is a dot, sorted as the zero it is.
    assert "data-sort='0.0'><span class='mv-flat'>&middot;</span>" in html
    assert 'data-view="odds"' in html


def test_the_page_stands_without_espn(league, monkeypatch):
    monkeypatch.setattr(power.fpi, "by_id", lambda refresh=False: {})
    html = power.body()
    assert _rows_in_order(html) == ["12", "28", "25", "13"]
    assert "data-field='rank'" not in html and 'data-view="odds"' not in html
    # And the snapshot still went in, with no FPI rank.
    snap = rankmoves.history(power.HISTORY_DIR)
    assert snap["rank"].isna().all() and list(snap["gs_rank"]) == [1, 2, 3, 4]


def test_every_build_is_archived_small(league):
    power.body()
    snaps = list(power.HISTORY_DIR.glob("*.csv"))
    assert len(snaps) == 1 and snaps[0].stat().st_size < 4000
    frame = pd.read_csv(snaps[0], dtype={"key": str}).set_index("key")
    assert frame.loc["12", "rank"] == 1 and frame.loc["12", "gs"] == 5.0
    assert frame.loc["12", "abbr"] == "KC" and frame.loc["12", "probwintitle"] == 12.4


# --------------------------------------------------------------------------- #
# The calendar and the archive
# --------------------------------------------------------------------------- #

def test_the_playoffs_follow_the_regular_season():
    assert power.week_number(18, 2) == 18 and power.week_number(1, 3) == 19
    assert power.week_label(3) == "Wk 3" and power.week_label(19) == "WC"
    assert power.week_label(23) == "SB"


def test_week_spans_run_first_kickoff_to_four_hours_after_the_last():
    frame = season_frame()
    spans = {w: (a, b) for w, a, b in power.week_spans(frame)}
    assert set(spans) == {1, 2, 19}
    first, over = spans[1]
    assert over - first == timedelta(hours=4)


def test_a_mid_season_archive_is_seeded_once(monkeypatch, tmp_path):
    """Before Week 1, and after each finished week: the table as the fit on
    the games played by then had it."""
    monkeypatch.setattr(power, "HISTORY_DIR", tmp_path)
    asked = []
    frame = season_frame()

    def season(asof=None):
        asked.append(asof)
        return frame, Model(), TEAMS
    monkeypatch.setattr(power.predict, "season", season)
    k1, k2 = datetime(2026, 9, 13, 13), datetime(2026, 9, 20, 13)
    spans = [(1, k1, datetime(2026, 9, 14, 23)), (2, k2, datetime(2026, 9, 21, 23)),
             (19, datetime(2027, 1, 9, 16), datetime(2027, 1, 9, 20))]
    now = datetime(2026, 9, 25, 12)
    assert power.seed_history(spans, now=now) == 3
    stamps = sorted(p.stem for p in tmp_path.glob("*.csv"))
    assert stamps == ["20260913-120000", "20260915-000000", "20260922-000000"]
    # The record as of each moment: nobody had played before Week 1.
    pre = pd.read_csv(tmp_path / "20260913-120000.csv", dtype={"key": str}).set_index("key")
    after = pd.read_csv(tmp_path / "20260915-000000.csv", dtype={"key": str}).set_index("key")
    assert pre["numwins"].sum() == 0 and after.loc["12", "numwins"] == 1
    assert len(asked) == 3
    # Never twice.
    assert power.seed_history(spans, now=now) == 0


def test_a_week_that_just_ended_is_left_to_the_build(monkeypatch, tmp_path):
    """A stamp under GAP_HOURS old would block this build's own snapshot."""
    monkeypatch.setattr(power, "HISTORY_DIR", tmp_path)
    monkeypatch.setattr(power.predict, "season", lambda asof=None: (season_frame(), Model(), TEAMS))
    k1 = datetime(2026, 9, 13, 13)
    spans = [(1, k1, datetime(2026, 9, 14, 23))]
    assert power.seed_history(spans, now=datetime(2026, 9, 15, 6)) == 1      # Week 1's eve only


def test_move_reads_the_archive_and_opens_before_this_week(league, monkeypatch):
    """A snapshot from before Week 2 with the teams in another order: Move
    opens on it, and the rating's own change rides in its cell."""
    power.HISTORY_DIR.mkdir(parents=True)
    pd.DataFrame({"key": ["12", "28", "25", "13"], "rank": [2, None, 1, None],
                  "gs": [4.0, 2.5, 1.0, -3.0], "gs_rank": [1, 3, 2, 4]}).to_csv(
        power.HISTORY_DIR / "20260919-120000.csv", index=False)
    monkeypatch.setattr(power, "week_spans", lambda frame: [
        (1, datetime(2026, 9, 13, 13), datetime(2026, 9, 14, 23)),
        (2, datetime(2026, 9, 20, 13), datetime(2026, 9, 21, 23))])
    html = power.body()
    # The Since menu (shared with /cfb/power/) opens on that window.
    assert "<option value=\"pre2\" selected" in html and "Before Wk 2" in html
    blob = json.loads(html.split("id='pwr-deltas'>")[1].split("</script>")[0])
    # Commanders 3rd -> 2nd, 49ers 2nd -> 3rd; KC's FPI rank 2 -> 1.
    assert blob["deltas"]["pre2"]["gs_rank"] == [0, 1, -1, 0]
    assert blob["deltas"]["pre2"]["rank"][0] == 1
    assert "<span class='pwr-chg' data-chg='gs'><span class='mv-up'>+1.0</span></span>" in html


# --------------------------------------------------------------------------- #
# The watch guide reads the stars
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def guide(tmp_path_factory):
    from gordstats import watch_page
    from nfl.site import watch

    now = datetime.now(timezone.utc)
    day = now.astimezone(watch.ET).strftime("%Y-%m-%d")
    kick = now - timedelta(minutes=90)

    def game(gid, home, away, hid, aid, hk, ak, score):
        return {"id": gid, "ko": kick.strftime("%Y-%m-%dT%H:%M:%SZ"), "tk": True, "day": day,
                "slot": "early", "tv": "FOX", "n": False, "note": "", "state": "pre",
                "h": {"id": hid, "nm": home, "k": hk, "lg": "", "rec": "2-1", "sc": 0, "pr": 24.0},
                "a": {"id": aid, "nm": away, "k": ak, "lg": "", "rec": "1-2", "sc": 0, "pr": 20.0},
                "hw": 0.6, "fw": 0.6, "sp": -3.0, "mq": score, "score": score, "tags": [], "fav": "h"}
    # ESPN's id and Sleeper's abbreviation differ for Washington: 28 / WAS.
    data = {"season": 2026, "generated": now.astimezone(watch.ET).isoformat(timespec="minutes"),
            "slots": watch_page.slot_hours(watch.SLOTS),
            "games": [game("1", "Bills", "Patriots", "2", "17", "BUF", "NE", 80.0),
                      game("2", "Commanders", "Cowboys", "28", "6", "WAS", "DAL", 40.0),
                      game("3", "Texans", "Colts", "34", "11", "HOU", "IND", 60.0)],
            "rosters": {}}
    root = tmp_path_factory.mktemp("nflstars")
    (root / "index.html").write_text("<!doctype html><html><body>" + expand(watch.body(data))
                                     + "</body></html>")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a: None
    server = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()


BOOT = """
localStorage.setItem('gs:favorites', JSON.stringify(%s));
window.fetch=function(){
  return Promise.resolve({ok:true,json:function(){ return Promise.resolve({events:[]}); }});
};
"""

READ = """JSON.stringify({
  order: Array.prototype.map.call(document.querySelectorAll('#wg-host a.wg-g'),
    function(a){ return a.getAttribute('data-gid'); }),
  bar: (document.querySelector('#wg-host .wg-bar')||{}).innerHTML||''
})"""


def _run(url: str, boot: str, expression: str):
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
                await asyncio.sleep(2)
                r = await send("Runtime.evaluate", {"expression": expression, "returnByValue": True})
                return r["result"].get("value")
        return asyncio.run(go())
    finally:
        proc.terminate()
        reap(proc)
        subprocess.run(["fuser", "-k", f"{CDP}/tcp"], capture_output=True)


@pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")
def test_a_team_starred_on_the_rankings_leads_the_watch_guide(guide):
    got = json.loads(_run(guide, BOOT % "[]", READ))
    assert got["order"] == ["1", "3", "2"]
    assert "/nfl/power/" in got["bar"]                     # the hint says where stars come from
    # Washington starred by its ESPN id: the guide knows it as WAS, and its
    # game jumps the window. A college star with the same number does nothing.
    got = json.loads(_run(guide, BOOT % '["nfl:28", "cfb:2"]', READ))
    assert got["order"] == ["2", "1", "3"]
    assert "/nfl/power/" not in got["bar"]
