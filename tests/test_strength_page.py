"""
Matchup strength, both leagues: gordstats.strength_page, its college adapter
(cfb.site.strength, /cfb/strength/) and its NFL one (fantasy.site.strength,
/fantasy/strength/).

  * the pricing: a player is priced on the weeks he plays, weighted by his
    projection, and a bye is left out (and counted, where starters are marked);
  * the college page draws exactly what it drew before the tables moved into
    the shared module (the expected markup below was produced by the
    pre-refactor code on the same fixture);
  * the NFL page: who starts, the reserve list, the shipped JSON, escaping;
  * the browser: a reader's own league drawn by SCHEDULE_JS + READER_JS comes
    out identical to the Python table for the same league. Runs in headless
    Chromium (DevTools 9461, HTTP 8801); skips without it.
"""
import asyncio
import functools
import http.server
import json
import re
import shutil
import socketserver
import subprocess
import threading
import time
import urllib.request

import pandas as pd
import pytest

from gordstats import strength_page as sp
from browser_util import launch, reap

CHROME = next((p for p in ("/usr/bin/chromium-browser", "/usr/bin/chromium",
                           "/usr/bin/google-chrome") if shutil.which(p)), None)
CDP, HTTP = 9461, 8801


# --------------------------------------------------------------------------- #
# The shared arithmetic and tables
# --------------------------------------------------------------------------- #

RATINGS = {"D1": {"RB": 1.2, "WR": 0.9, "QB": 0.8},
           "D2": {"RB": 1.0, "WR": 1.1, "QB": 1.3}}
OPP = {("X", 1): "D1", ("Y", 1): "D2", ("X", 2): "D2",          # Y is on a bye in week 2
       ("Z", 1): "D1", ("Z", 2): "D2", ("T", 1): "D1", ("T", 2): "D1"}


def test_a_schedule_is_priced_on_the_weeks_a_player_plays():
    players = [
        {"key": "a", "label": "Alpha", "team": "X", "pos": "RB", "weight": 10.0, "starter": True},
        {"key": "a", "label": "Alpha", "team": "Y", "pos": "WR", "weight": 5.0, "starter": True},
        {"key": "b", "label": "Bravo", "team": "Z", "pos": "QB", "weight": 20.0},
        # A position nobody rated: no price, and not a bye either.
        {"key": "b", "label": "Bravo", "team": "T", "pos": "TE", "weight": 9.0, "starter": True},
        # Nothing to price at all: the roster is dropped rather than drawn empty.
        {"key": "c", "label": "Charlie", "team": "NOPE", "pos": "RB", "weight": 9.0},
    ]
    rows = sp.price(players, [1, 2], OPP, RATINGS)
    assert [r["key"] for r in rows] == ["a", "b"]
    a, b = rows
    assert a["weeks"][1] == pytest.approx((1.2 * 10 + 1.1 * 5) / 15)
    assert a["weeks"][2] == pytest.approx(1.0)                   # the bye is left out...
    assert a["byes"] == {1: 0, 2: 1}                             # ...and counted
    assert a["mean"] == pytest.approx((a["weeks"][1] + 1.0) / 2)
    assert b["weeks"] == {1: pytest.approx(0.8), 2: pytest.approx(1.3)}
    assert b["byes"] == {1: 0, 2: 0}


def test_equal_schedules_keep_name_order():
    players = [{"key": k, "label": k, "team": "Z", "pos": "QB", "weight": 1.0}
               for k in ("m", "c", "x")]
    assert [r["key"] for r in sp.price(players, [1], OPP, RATINGS)] == ["c", "m", "x"]


def test_the_defence_table_ranks_toughest_first_and_shades_both_ways():
    rows = [("<b>A</b>", {"QB": 0.8, "RB": float("nan")}, 0.85),
            ("B", {"QB": 1.2, "RB": 1.0}, 1.1)]
    html = sp.defense_table(rows, ("QB", "RB"), titles={"RB": "it's <backs>"})
    assert re.findall(r"<span class='st-rk'>(\d+)</span>([^<]*(?:<b>A</b>)?)", html) == [
        ("1", "<b>A</b>"), ("2", "B")]
    assert "<td style=''>&mdash;</td>" in html                    # missing: a dash, unshaded
    assert "rgba(211,47,47" in html and "rgba(46,125,50" in html  # red stingy, green generous
    assert "<th title='it&#x27;s &lt;backs&gt;'>RB</th>" in html
    # Phone padding and a header that follows the 139 college rows down (2026-10-02).
    assert "<table class='st st-fit' data-sticky-head>" in html


def test_the_phone_layout_puts_the_average_beside_the_name():
    rows = sp.price([{"key": "7", "label": "<i>Fred's</i> \"team\"", "team": "X", "pos": "RB",
                      "weight": 1.0, "starter": True}], [1, 2], OPP, RATINGS)
    fit = sp.schedule_table(rows, [1, 2], byes=True, keyed=True, fit=True)
    assert "<tr><th>Team</th><th>Avg</th><th>Wk 1</th><th>Wk 2</th></tr>" in fit
    assert "<table class='st st-fit'>" in fit and "data-key='7'" in fit
    assert "<i>" not in fit and "&lt;i&gt;Fred&#x27;s&lt;/i&gt; &quot;team&quot;" in fit
    assert "<span class='st-tn'>" in fit
    assert "<span class='st-bye'>1 bye</span>" not in fit         # X plays both weeks
    plain = sp.schedule_table(rows, [1, 2])
    assert "<tr><th>Team</th><th>Wk 1</th><th>Wk 2</th><th>Average</th></tr>" in plain
    assert "data-key" not in plain and "st-bye" not in plain


def test_a_bye_note_counts():
    assert sp.bye_note(0) == ""
    assert sp.bye_note(1) == "<span class='st-bye'>1 bye</span>"
    assert sp.bye_note(3) == "<span class='st-bye'>3 byes</span>"


def test_the_heat_scale_is_the_dashboards():
    from gordstats import roster_page
    for v in (0.7, 0.9, 1.0, 1.06, 1.4):
        assert sp.heat(v) == roster_page.heat(v)
    assert sp.heat(None) == "" and sp.heat(float("nan")) == ""


# --------------------------------------------------------------------------- #
# The college page is unchanged
# --------------------------------------------------------------------------- #

# What cfb.site.strength drew for these fixtures before its tables moved into
# gordstats.strength_page (rendered by that version of the module) - the
# defence table since with the phone padding and the following header
# (2026-10-02 phone audit).
OLD_DEFENCE = (
    "<div class='st-scroll'><table class='st st-fit' data-sticky-head><thead><tr><th>Defense</th><th>QB</th><th>RB</th>"
    "<th>WR</th><th>TE</th><th>All</th></tr></thead><tbody><tr><td class='st-name'><span "
    "class='st-rk'>1</span>33</td><td style=''>&mdash;</td><td style='background:rgba(46,125,50,"
    "0.15)'>1.05</td><td style='background:rgba(211,47,47,0.45)'>0.70</td><td style='background:"
    "rgba(211,47,47,0.42)'>0.86</td><td style='background:rgba(211,47,47,0.39)'>0.87</td></tr>"
    "<tr><td class='st-name'><span class='st-rk'>2</span>&lt;Bad&gt;</td><td style='background:"
    "rgba(211,47,47,0.45)'>0.80</td><td style='background:rgba(211,47,47,0.30)'>0.90</td><td "
    "style='background:rgba(211,47,47,0.15)'>0.95</td><td style='background:rgba(46,125,50,0.00)'>"
    "1.00</td><td style='background:rgba(211,47,47,0.26)'>0.91</td></tr><tr><td class='st-name'>"
    "<span class='st-rk'>3</span>Tex &amp; As</td><td style='background:rgba(46,125,50,0.45)'>1.21"
    "</td><td style='background:rgba(46,125,50,0.00)'>1.00</td><td style='background:rgba(46,125,"
    "50,0.30)'>1.10</td><td style='background:rgba(46,125,50,0.45)'>1.30</td><td style='background:"
    "rgba(46,125,50,0.45)'>1.15</td></tr></tbody></table></div>")
OLD_SCHEDULE = (
    "<div class='st-scroll'><table class='st'><thead><tr><th>Team</th><th>Wk 5</th><th>Wk 6</th>"
    "<th>Average</th></tr></thead><tbody><tr><td class='st-name'><span class='st-rk'>1</span>Amy"
    "</td><td style=''>&mdash;</td><td style='background:rgba(46,125,50,0.45)'>1.21</td><td style="
    "'background:rgba(46,125,50,0.45)'><b>1.21</b></td></tr><tr><td class='st-name'><span class="
    "'st-rk'>2</span>Zed&#x27;s</td><td style='background:rgba(211,47,47,0.09)'>0.97</td><td "
    "style='background:rgba(46,125,50,0.15)'>1.05</td><td style='background:rgba(46,125,50,0.03)'>"
    "<b>1.01</b></td></tr></tbody></table></div>")


def _cfb_grid():
    grid = pd.DataFrame({"QB": [1.21, 0.8, float("nan")], "RB": [1.0, 0.9, 1.05],
                         "WR": [1.1, 0.95, 0.7], "TE": [1.3, 1.0, 0.86]}, index=["11", "22", "33"])
    grid["all"] = grid.mean(axis=1)
    return grid.sort_values("all", ascending=False)


def test_the_college_tables_are_what_they_were(monkeypatch):
    from cfb.site import strength

    grid = _cfb_grid()
    names = {"11": "Tex & As", "22": "<Bad>"}
    assert strength.defense_section(grid, names) == OLD_DEFENCE

    players = pd.DataFrame([
        {"manager": "Zed's", "pos": "RB", "school_id": "11", "proj": 10.0},
        {"manager": "Zed's", "pos": "WR", "school_id": "22", "proj": 5.5},
        {"manager": "Amy", "pos": "QB", "school_id": "33", "proj": 20.0},
        {"manager": "Amy", "pos": "K", "school_id": "33", "proj": 8.0},
        {"manager": "Bo", "pos": "TE", "school_id": "99", "proj": 4.0}])
    frame = pd.DataFrame([{"week": 5, "played": False, "home_id": "11", "away_id": "22"},
                          {"week": 6, "played": False, "home_id": "33", "away_id": "11"},
                          {"week": 4, "played": True, "home_id": "33", "away_id": "22"}])
    ratings = {str(k): {p: (None if pd.isna(v) else float(v)) for p, v in row.items()}
               for k, row in grid.iterrows()}
    monkeypatch.setattr(strength, "_roster_players", lambda board: players)
    assert strength.schedule_section(ratings, names, frame, None) == OLD_SCHEDULE


def test_the_college_dashboard_still_finds_its_heat():
    from cfb.site import roster, strength
    assert roster._heat is strength._heat is sp.heat
    assert strength.WEEKS_AHEAD == sp.WEEKS_AHEAD == 6


# --------------------------------------------------------------------------- #
# The NFL page
# --------------------------------------------------------------------------- #

SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF", "SUPER_FLEX", "BN", "BN", "IR"]
TEAMS = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
NAMES = {"1": "Alpha <b>&\"Quote's\"</b>", "2": "{% raw %}Bravo {{ site.title }}",
         "3": "Charlie"}


def _board() -> pd.DataFrame:
    """Every team's QB, two backs, two receivers, a tight end, a kicker and a
    defence, with projections that tie here and there."""
    rows = []
    for i, team in enumerate(TEAMS):
        for j, (pos, mu) in enumerate([("QB", 18 + i), ("RB", 12 + i % 3), ("RB", 8.0),
                                       ("WR", 13 - i % 2), ("WR", 8.0), ("TE", 7 + i % 2),
                                       ("K", 8.0), ("DEF", 6.5 + i / 4)]):
            pid = team if pos == "DEF" else f"{i}{j}"
            rows.append({"sleeper_id": pid, "player": pid, "pos": pos, "team": team,
                         "mu": float(mu)})
    return pd.DataFrame(rows)


def _rosters() -> dict:
    """roster id -> (players, reserve), drawn from the board above."""
    return {"1": (["00", "01", "11", "03", "14", "05", "06", "AAA", "10", "22", "13", "24"],
                  ["22"]),
            "2": (["20", "21", "12", "23", "04", "15", "16", "BBB", "30", "31", "33", "44"], []),
            "3": (["40", "41", "42", "43", "34", "45", "46", "CCC", "50", "51", "53", "55",
                   "unknown"], ["55"])}


def _schedule() -> pd.DataFrame:
    """Weeks 1-12: rotating pairs, with two teams off in weeks 5 and 6."""
    rows = []
    for week in range(1, 13):
        order = TEAMS[week % 6:] + TEAMS[:week % 6]
        pairs = [(order[0], order[1]), (order[2], order[3]), (order[4], order[5])]
        if week in (5, 6):
            pairs = pairs[1:]                                   # order[0] and order[1] off
        for home, away in pairs:
            rows.append({"week": week, "seasontype": 2, "home_abbr": home, "away_abbr": away})
    rows.append({"week": 1, "seasontype": 3, "home_abbr": "TBD", "away_abbr": "TBD"})
    return pd.DataFrame(rows)


def _dvp() -> dict:
    out = {}
    for week in (1, 2):
        out[str(week)] = {team: {pos: 10.0 + (i * 3 + week * 2 + k) % 7
                                 for k, pos in enumerate(("QB", "RB", "WR", "TE", "K", "DEF"))}
                          for i, team in enumerate(TEAMS)}
    return out


def _week(week: int, final: bool) -> dict:
    rosters = _rosters()
    sides = [{"roster_id": int(k), "players": players, "points": 100.0 if final else 0.0}
             for k, (players, _r) in rosters.items()]
    return {"week": week,
            "matchups": [{"matchup_id": 1, "sides": sides[:2]}, {"matchup_id": 2, "sides": sides[2:]}],
            "teams": {k: {"name": NAMES[k], "manager": "Tyler" if k == "2" else f"M{k}",
                          "reserve": rosters[k][1]} for k in rosters},
            "games": [{"state": "post" if final else "pre"}]}


@pytest.fixture
def nfl(monkeypatch):
    from fantasy.config import UPCOMING_YEAR
    from fantasy.league import defense
    from fantasy.league import matchups as data_mod
    from fantasy.site import matchups as mu
    from fantasy.site import strength
    from nfl import games

    datas = {1: _week(1, True), 2: _week(2, True), 3: _week(3, False)}
    monkeypatch.setattr(data_mod, "capture", lambda year=None, **k: [1, 2, 3])
    monkeypatch.setattr(data_mod, "week_matchups", lambda w, year=None, **k: datas[w])
    monkeypatch.setattr(data_mod, "league",
                        lambda *a, **k: {"roster_positions": SLOTS, "playoff_week_start": 7})
    monkeypatch.setattr(mu, "_board", lambda weeks, d: _board())
    monkeypatch.setattr(defense, "capture", lambda year=None: _dvp())
    monkeypatch.setattr(games, "SEASON", UPCOMING_YEAR)
    monkeypatch.setattr(games, "schedule", lambda **k: _schedule())
    return strength


def test_starters_fill_the_named_slots_then_the_flex(nfl):
    players = [("q1", "QB", 20.0), ("q2", "QB", 15.0), ("r1", "RB", 14.0), ("r2", "RB", 9.0),
               ("r3", "RB", 9.0), ("w1", "WR", 12.0), ("w2", "WR", 11.0), ("w3", "WR", 3.0),
               ("t1", "TE", 6.0), ("k1", "K", 8.0)]
    got = nfl.starters(players, ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF", "BN"])
    # The two 9-point backs tie: the lower id takes the RB slot, the other the
    # FLEX (nobody better is left for it). No defence on the roster, no DEF.
    assert got == {"q1", "r1", "r2", "w1", "w2", "t1", "k1", "r3"}
    tie = nfl.starters(players, ["RB", "RB"])
    assert tie == {"r1", "r2"}
    # A superflex goes to the second quarterback, and is filled after the plain flex.
    sf = nfl.starters(players, ["SUPER_FLEX", "QB", "FLEX", "RB"])
    assert sf == {"q1", "r1", "q2", "w1"}


def test_the_reserve_and_unpriced_players_are_left_out(nfl):
    lg = nfl.League()
    data = lg.data
    sides = [s for m in data["matchups"] for s in m["sides"]]
    players = nfl.roster_players(sides, data["teams"], lg.board, lg.slots)
    by_roster = {}
    for p in players:
        by_roster.setdefault(p["key"], []).append(p)
    assert len(by_roster["1"]) == 11                       # twelve, less "22" on the reserve
    assert len(by_roster["3"]) == 11                       # thirteen, less IR and an unknown id
    assert sum(p["starter"] for p in by_roster["2"]) == 10  # every starting slot filled


def test_the_league_reads_the_weeks_ahead(nfl):
    lg = nfl.League()
    assert lg.first == 3 and lg.ship == [3, 4, 5, 6, 7, 8]
    assert lg.weeks == [3, 4, 5, 6]                        # playoffs start in week 7
    assert lg.played == 2 and lg.mine() == "2"
    payload = lg.payload()
    assert payload["weeks"] == lg.ship and payload["ahead"] == 6
    assert set(payload["opp"]) == set(TEAMS)               # TBD (postseason) is not a team
    # Two teams are off in weeks 5 and 6, and a bye is an empty string.
    assert sum(1 for t in TEAMS if payload["opp"][t][2] == "") == 2
    assert all(len(v) == len(lg.ship) for v in payload["opp"].values())
    assert payload["p"]["AAA"] == ["AAA", "DEF", 6.5]
    assert set(payload["dvp"]["AAA"]) == {"QB", "RB", "WR", "TE", "K", "DEF"}
    json.dumps(payload)


def test_the_page_escapes_names_and_stays_literal(nfl, tmp_path, monkeypatch):
    from gordstats.frontmatter import add_front_matter

    lg = nfl.League()
    html = nfl.body(lg)
    assert "Alpha &lt;b&gt;&amp;&quot;Quote&#x27;s&quot;&lt;/b&gt;" in html
    assert "<b>&\"Quote" not in html
    assert "<span class='st-bye'>" in html                 # weeks 5 and 6 have byes
    assert "<tr><th>Team</th><th>Avg</th><th>Wk 3</th><th>Wk 4</th><th>Wk 5</th>" \
           "<th>Wk 6</th></tr>" in html
    assert "id='st-mine'" in html and "id='st-built'" in html
    assert "window.GSStrength" in html and "GSStrengthLeague" in html and "window.GSL" in html
    assert "GSStrength.mark(document.getElementById('st-built'),k||\"2\")" in html
    # Toughest first: the defence table's All column climbs.
    alls = [float(x) for x in re.findall(r"<td style='[^']*'>([\d.]+)</td></tr>",
                                         html.split("id='defence'")[1])]
    assert alls == sorted(alls) and len(alls) == len(TEAMS)
    page = add_front_matter(html, "NFL Matchup Strength")
    # The team named with Liquid is inside a raw block, so Jekyll prints it as written.
    at = page.index("Bravo {{ site.title }}")
    assert page.rfind("{% raw %}", 0, at) > page.rfind("{% endraw %}", 0, at)

    monkeypatch.setattr(nfl, "OUT", tmp_path / "strength" / "index.html")
    monkeypatch.setattr(nfl, "DATA_OUT", tmp_path / "strength.json")
    nfl.generate()
    assert (tmp_path / "strength" / "index.html").exists()
    shipped = json.loads((tmp_path / "strength.json").read_text())
    assert shipped["weeks"] == [3, 4, 5, 6, 7, 8] and len(shipped["p"]) == len(_board())


def test_a_season_without_a_week_left_says_so(nfl):
    lg = nfl.League()
    lg.weeks = []
    assert "The regular season is over." in nfl.body(lg)


# --------------------------------------------------------------------------- #
# In the browser: a reader's league drawn the way the page draws its own
# --------------------------------------------------------------------------- #

def _strip(js: str) -> str:
    return re.sub(r"</?script>", "", js.replace("{% raw %}", "").replace("{% endraw %}", ""))


def _reader_league(nfl, lg, start: int):
    """The fixture league as GSL.league() returns it, and the Python table for
    it with that league's playoffs starting in week `start`."""
    data = lg.data
    sides = [s for m in data["matchups"] for s in m["sides"]]
    teams = data["teams"]
    js_league = {"info": {"settings": {"playoff_week_start": start}}, "slots": SLOTS,
                 "names": {k: t["name"] for k, t in teams.items()},
                 "rosters": [{"roster_id": s["roster_id"], "players": s["players"],
                              "reserve": teams[str(s["roster_id"])]["reserve"]} for s in sides]}
    weeks = [w for w in lg.ship if w < start][:sp.WEEKS_AHEAD]
    rows = sp.price(nfl.roster_players(sides, teams, lg.board, lg.slots), weeks,
                    lg.opponent_map(), lg.ratings)
    return js_league, sp.schedule_table(rows, weeks, byes=True, keyed=True, fit=True)


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture
def reader_site(nfl, tmp_path):
    lg = nfl.League()
    js_league, expected = _reader_league(nfl, lg, start=6)
    (tmp_path / "fantasy").mkdir()
    (tmp_path / "fantasy" / "strength.json").write_text(json.dumps(lg.payload()))
    scripts = _strip(sp.SCHEDULE_JS) + _strip(nfl.READER_JS)

    def page(league_js: str) -> str:
        return ("<!doctype html><html><body><div id='st-mine'></div>"
                "<template id='want'>" + expected + "</template><script>"
                "window.GSL={saved:function(){return {id:'L1',name:'Theirs'};},"
                f"league:function(){{return {league_js};}},"
                "myRoster:function(){return '3';}};" + scripts + "</script></body></html>")

    (tmp_path / "index.html").write_text(page(f"Promise.resolve({json.dumps(js_league)})"))
    (tmp_path / "fail.html").write_text(page("Promise.reject(new Error('gone'))"))
    handler = functools.partial(_Quiet, directory=str(tmp_path))
    socketserver.TCPServer.allow_reuse_address = True
    server = socketserver.TCPServer(("127.0.0.1", HTTP), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{HTTP}/"
    server.shutdown()
    server.server_close()


def _run(pages: list) -> list:
    """Load each (url, expression) in headless Chromium and return the values."""
    import websockets
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
                out = []
                for url, expression in pages:
                    await send("Page.navigate", {"url": url})
                    await asyncio.sleep(1.5)
                    r = await send("Runtime.evaluate", {"expression": expression,
                                                        "returnByValue": True})
                    out.append(r["result"].get("value"))
                return out
        return asyncio.run(go())
    finally:
        proc.terminate()
        reap(proc)


@pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")
def test_a_readers_league_is_drawn_like_the_built_table(reader_site):
    same, fail = _run([
        (reader_site, """JSON.stringify((function(){
          var host=document.getElementById('st-mine');
          var mine=host.querySelector('tr.st-mine');
          var key=mine&&mine.getAttribute('data-key');
          if(mine) mine.classList.remove('st-mine');
          mine=host.querySelector('tr[class=""]'); if(mine) mine.removeAttribute('class');
          var want=document.createElement('div');
          want.innerHTML=document.getElementById('want').innerHTML;
          return {same: want.innerHTML===host.innerHTML, mine: key,
                  rows: host.querySelectorAll('tbody tr').length,
                  heads: [].map.call(host.querySelectorAll('th'),function(t){return t.textContent;}),
                  got: host.innerHTML, want: want.innerHTML};
        })())"""),
        (reader_site + "fail.html", "document.getElementById('st-mine').textContent"),
    ])
    got = json.loads(same)
    assert got["same"], (got["got"], got["want"])
    assert got["rows"] == 3 and got["mine"] == "3"
    # Their playoffs start in week 6, so their table stops a week before the site's.
    assert got["heads"] == ["Team", "Avg", "Wk 3", "Wk 4", "Wk 5"]
    assert "Could not read that league" in fail


def test_the_power_page_points_here_for_every_league():
    """The link sits outside #pw-intro, which a reader's own league hides -
    and this page draws their league too."""
    from fantasy.site import power

    intro, _, after = power.INTRO.partition("</p>")
    assert 'href="/fantasy/strength/"' in after and "/fantasy/strength/" not in intro
