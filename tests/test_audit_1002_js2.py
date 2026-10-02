"""
Follow-ups to the 2026-10-02 audit's browser findings (test_audit_1002_js):

  * a reader's league saved in another season is not simulated on this
    season's board - Power (gordstats.my_power) and the trade page
    (fantasy.site.trade, on the same simulation) say which season it is;
  * a league that cannot be read is explained in the words of the site it is
    on (GSAPI.problem): an ESPN league kept private says how to open it, never
    "Sleeper may be busy";
  * the trade adapter names the league it read, for the deal's link;
  * the CBB watch guide's day ends at its own after-midnight hour.

Each page is served from a local directory and run in headless Chromium with
fetch stubbed in the page before any of its scripts (no network). CDP port
9561.
"""
import asyncio
import functools
import http.server
import json
import re
import shutil
import socketserver
import subprocess
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from browser_util import launch, reap

CHROME = next((p for p in ("/usr/bin/chromium-browser", "/usr/bin/chromium",
                           "/usr/bin/google-chrome") if shutil.which(p)), None)
pytestmark = pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")

CDP_PORT = 9561
SLEEPER = "https://api.sleeper.app/v1"
ESPN = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl"
LID = "1234567890123456789"
POS = ["QB", "RB", "WR", "TE", "K", "DEF"]


def _raw(src: str) -> str:
    """A module's scripts with the Jekyll wrappers off, <script> tags kept."""
    return re.sub(r"\{% (end)?raw %\}", "", src)


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class Browser:
    """Chromium plus a local server: write a page, open it, run JS in it."""

    def __init__(self):
        self.dir = Path(tempfile.mkdtemp(prefix="gs-audit-js2-"))
        (self.dir / "blank.html").write_text(
            "<!doctype html><meta charset=utf-8><title>t</title><body></body>")
        handler = functools.partial(_Quiet, directory=str(self.dir))
        self.httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        subprocess.run(["fuser", "-k", f"{CDP_PORT}/tcp"], capture_output=True)
        self.proc = launch(CHROME, CDP_PORT)
        for _ in range(60):
            try:
                targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json"))
                self.ws_url = next(t["webSocketDebuggerUrl"] for t in targets
                                   if t.get("type") == "page")
                break
            except Exception:                                   # noqa: BLE001
                time.sleep(0.5)
        else:
            raise RuntimeError("Chromium did not come up")

    def close(self):
        self.proc.terminate()
        reap(self.proc)
        self.httpd.shutdown()
        self.httpd.server_close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def _send(self, method, params):
        import websockets

        async def run():
            async with websockets.connect(self.ws_url, max_size=None) as ws:
                await ws.send(json.dumps({"id": 1, "method": method, "params": params}))
                while True:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
                    if msg.get("id") == 1:
                        return msg
        return asyncio.run(run())

    def ev(self, expression):
        """The value of an expression (a promise is awaited)."""
        msg = self._send("Runtime.evaluate", {"expression": expression, "returnByValue": True,
                                              "awaitPromise": True})
        result = msg.get("result", {})
        if result.get("exceptionDetails"):
            d = result["exceptionDetails"]
            raise AssertionError((d.get("exception") or {}).get("description") or d["text"])
        return result["result"].get("value")

    def _goto(self, name):
        self._send("Page.navigate", {"url": f"http://127.0.0.1:{self.port}/{name}"})
        for _ in range(100):
            try:
                if self.ev("location.pathname") == "/" + name and \
                        self.ev("document.readyState") == "complete":
                    return
            except AssertionError:
                pass
            time.sleep(0.05)
        raise RuntimeError(f"{name} did not load")

    def open(self, body: str, routes: list, storage: dict = None, wait=None, timeout=10.0):
        """Serve `body` behind a fetch stub answering `routes` ([regex, status,
        json] - the first match wins, anything else is a 404), with `storage`
        in localStorage before its scripts run; then wait for `wait` (an
        expression) to be truthy."""
        self._goto("blank.html")
        self.ev("localStorage.clear(); sessionStorage.clear(); true")
        for k, v in (storage or {}).items():
            self.ev(f"localStorage.setItem({json.dumps(k)}, {json.dumps(v)}); true")
        stub = """<script>
          window.__routes=%s; window.__asked=[]; window.__errs=[];
          (function(){ var ce=console.error;
            console.error=function(){ __errs.push([].map.call(arguments,String).join(' '));
              return ce.apply(console, arguments); }; })();
          window.fetch=function(u){ u=String(u); __asked.push(u);
            var hit=__routes.filter(function(r){ return new RegExp(r[0]).test(u); })[0];
            var st=hit?hit[1]:404, body=hit?hit[2]:null;
            return Promise.resolve({ok:st===200, status:st,
              json:function(){ return Promise.resolve(JSON.parse(JSON.stringify(body))); }});
          };
        </script>""" % json.dumps(routes)
        name = f"p{time.time_ns()}.html"
        (self.dir / name).write_text("<!doctype html><html><head><meta charset=utf-8></head>"
                                     "<body>" + stub + body + "</body></html>", encoding="utf-8")
        self._goto(name)
        if wait:
            end = time.time() + timeout
            while time.time() < end:
                if self.ev(wait):
                    break
                time.sleep(0.1)
            else:
                raise AssertionError(f"timed out waiting for {wait}: "
                                     + str(self.ev("document.body.innerHTML"))[-2000:])

    def html(self, sel):
        return self.ev(f"(document.querySelector({json.dumps(sel)})||{{}}).innerHTML||''")


@pytest.fixture(scope="module")
def browser():
    b = Browser()
    yield b
    b.close()


# --------------------------------------------------------------------------- #
# A small league, Sleeper's shapes, and the site's board
# --------------------------------------------------------------------------- #

def _sleeper(league_id=LID, season="2026"):
    """Routes for a four-team Sleeper league, three starters each."""
    rosters = [{"roster_id": r, "owner_id": f"u{r}",
                "players": [f"{3 * r - 2}", f"{3 * r - 1}", f"{3 * r}"]} for r in (1, 2, 3, 4)]
    users = [{"user_id": f"u{r}", "display_name": f"m{r}",
              "metadata": {"team_name": f"Team {r}"}} for r in (1, 2, 3, 4)]
    info = {"league_id": league_id, "name": "Test League", "season": season,
            "roster_positions": ["QB", "RB", "WR", "BN"],
            "scoring_settings": {"rec": 1},
            "settings": {"playoff_week_start": 15, "playoff_teams": 2, "leg": 1,
                         "last_scored_leg": 0}}
    base = re.escape(f"{SLEEPER}/league/{league_id}")
    return [[base + "$", 200, info], [base + "/rosters$", 200, rosters],
            [base + "/users$", 200, users]]


def _site_files():
    board = {}
    index = {}
    for n in range(1, 13):
        pos = (n - 1) % 3                       # QB, RB, WR in turn
        mu = 18.0 - n * 0.5
        board[str(n)] = [pos, 9, mu, round(mu * 0.4, 2), 1.0, 0.9, 0, 0]
        index[str(n)] = [f"Player {n}", POS[pos], "KC"]
    for n in range(13, 19):                     # a free agent at each position
        pos = n - 13
        board[str(n)] = [pos, 9, 6.0, 2.5, 0.7, 0.9, 0, 0]
        index[str(n)] = [f"Free {n}", POS[pos], "KC"]
    return [["/fantasy/season-board\\.json$", 200,
             {"year": 2026, "week": 0, "fields": [], "pos": POS, "board": board}],
            ["/fantasy/players-index\\.json$", 200, index],
            ["/fantasy/week-projections\\.json$", 200, {"week": 1, "year": 2026, "kick": {},
                                                         "proj": {}}]]


def _saved(league_id, name="My League"):
    return {"gsSleeperLeague": json.dumps({"id": league_id, "name": name})}


def _espn_private():
    """ESPN refusing every request for the league, as it does a private one."""
    return [[re.escape(ESPN) + ".*", 401, None]]


def _espn_past(league=42, season=2025):
    """ESPN answering a finished season's settings - and, as for any season
    that is over, no players on the rosters (league_api.rostersOf)."""
    d = {"id": league, "settings": {"name": "Old ESPN",
                                    "scheduleSettings": {"matchupPeriodCount": 14,
                                                         "playoffTeamCount": 4}},
         "teams": [{"id": t, "name": f"Team {t}"} for t in (1, 2, 3, 4)],
         "status": {"latestScoringPeriod": 18, "finalScoringPeriod": 17,
                    "previousSeasons": []}}
    return [[re.escape(f"{ESPN}/seasons/{season}/segments/0/leagues/{league}?") + ".*", 200, d]]


# --------------------------------------------------------------------------- #
# Power
# --------------------------------------------------------------------------- #

def _power(routes, storage, year=2026):
    from gordstats import league_api, my_league_data, my_power
    return (("<h2 id='pw-mine-h'>Your League</h2>" + my_power.section(year)
             + "<div id='pw-intro'>intro</div><div id='pw-built'>built</div>"
             + _raw(league_api.JS + my_league_data.JS + my_power.SIM_JS + my_power.JS)),
            routes, storage)


def _power_done():
    return ("(function(){ var h=document.getElementById('mp-host');"
            " return !!h && !/mp-load|Settling/.test(h.innerHTML) && h.innerHTML.length>0; })()")


def test_the_power_host_carries_the_season():
    from fantasy.config import UPCOMING_YEAR
    from gordstats import my_power
    assert f"data-year='{int(UPCOMING_YEAR)}'" in my_power.section(int(UPCOMING_YEAR))
    assert "data-year" not in my_power.section(), "no year, no attribute"


def test_power_ranks_this_seasons_league(browser):
    body, routes, storage = _power(_sleeper() + _site_files(), _saved(LID))
    browser.open(body, routes, storage, wait=_power_done())
    html = browser.html("#mp-host")
    assert "pw-table" in html and "Team 1" in html
    assert browser.ev("document.getElementById('pw-built').hidden") is True


def test_power_does_not_rank_last_seasons_league_as_this_one(browser):
    """A saved 2025 league was drawn as this season's ranking."""
    body, routes, storage = _power(_sleeper(season="2025") + _site_files(), _saved(LID))
    browser.open(body, routes, storage, wait=_power_done())
    html = browser.html("#mp-host")
    assert "This is your <b>2025</b> league" in html
    assert "pw-table" not in html, "no season simulated from it"
    assert "Pick its 2026 league in the bar above" in html
    assert browser.ev("document.getElementById('pw-built').hidden") is False
    # Not one season-week of it was read: the note comes before the schedule.
    assert not any("/matchups/" in u for u in browser.ev("__asked"))


def test_power_offers_an_espn_leagues_current_season(browser):
    """ESPN sends no players for a season that is over, so the check has to
    come before the rosters' - it read as "has not drafted yet"."""
    body, routes, storage = _power(_espn_past() + _site_files(), _saved("espn:2025:42"))
    browser.open(body, routes, storage, wait=_power_done())
    html = browser.html("#mp-host")
    assert "This is your <b>2025</b> league" in html
    assert 'data-gs-season="espn:2026:42"' in html and "Show its 2026 season" in html
    assert "has not drafted" not in html


def test_power_follows_the_page_year_over_the_boards(browser):
    """The page says which season it ranks; the board's year is the fallback."""
    body, routes, storage = _power(_sleeper() + _site_files(), _saved(LID), year=2027)
    browser.open(body, routes, storage, wait=_power_done())
    assert "This is your <b>2026</b> league" in browser.html("#mp-host")


def test_power_says_an_espn_league_is_private_in_espns_words(browser):
    body, routes, storage = _power(_espn_private() + _site_files(), _saved("espn:2026:7"))
    browser.open(body, routes, storage, wait=_power_done())
    html = browser.html("#mp-host")
    assert "ESPN keeps that league private" in html
    assert "Sleeper" not in html


def test_power_says_sleeper_for_a_sleeper_league_it_cannot_read(browser):
    body, routes, storage = _power(_site_files(), _saved(LID))
    browser.open(body, routes, storage, wait=_power_done())
    assert "Could not read that league from Sleeper" in browser.html("#mp-host")


def test_power_without_the_board_says_so(browser):
    body, routes, storage = _power(_sleeper(), _saved(LID))
    browser.open(body, routes, storage, wait=_power_done())
    html = browser.html("#mp-host")
    assert "projections" in html and "Sleeper" not in html


# --------------------------------------------------------------------------- #
# Trades & Pickups
# --------------------------------------------------------------------------- #

def _trade(routes, storage):
    from fantasy.site import trade as nfl_trade
    from gordstats import league_api, my_league_data, my_power, trade_page
    body = (trade_page.section("/fantasy/trade/", league=True)
            + _raw(league_api.JS + my_league_data.JS + my_power.SIM_JS + my_power.LEAGUE_JS
                   + trade_page.JS + nfl_trade.adapter_js() + trade_page.start()))
    return body, routes, storage


def _trade_done():
    return ("(function(){ var h=document.getElementById('tr-host');"
            " return !!h && (!!h.querySelector('.tr-p') || (!!h.querySelector('.tr-msg')"
            " && !/Reading the league/.test(h.textContent))); })()")


def test_the_trade_page_says_last_seasons_league_is_not_this_one(browser):
    body, routes, storage = _trade(_sleeper(season="2025") + _site_files(), _saved(LID))
    browser.open(body, routes, storage, wait=_trade_done())
    host = browser.html("#tr-host")
    assert "This is your <b>2025</b> league" in host
    assert "tr-p" not in host, "no rosters to trade from"
    # One paragraph: the note's words inside the page's own message, not a
    # paragraph inside a paragraph (which the parser splits into empty ones).
    assert browser.ev("document.querySelectorAll('#tr-host p').length") == 1
    assert browser.ev("__errs") == []


def test_the_trade_page_offers_an_espn_leagues_current_season(browser):
    body, routes, storage = _trade(_espn_past() + _site_files(), _saved("espn:2025:42"))
    browser.open(body, routes, storage, wait=_trade_done())
    host = browser.html("#tr-host")
    assert 'data-gs-season="espn:2026:42"' in host
    assert "not drafted" not in host


def test_the_trade_adapter_names_the_league_it_read(browser):
    from fantasy.config import UPCOMING_LEAGUE_ID
    body, routes, storage = _trade(_sleeper() + _site_files(), _saved(LID))
    browser.open(body, routes, storage, wait=_trade_done())
    assert browser.ev("!!document.querySelector('#tr-host .tr-p')"), browser.html("#tr-host")
    assert browser.ev("GSTradeAdapter.load().then(function(d){ return d.leagueId; })") == LID
    # This site's own league is 'site' in a link, as links have always said.
    body, routes, storage = _trade(_sleeper(league_id=str(UPCOMING_LEAGUE_ID))
                                   + _site_files(), {})
    browser.open(body, routes, storage, wait=_trade_done())
    assert browser.ev("GSTradeAdapter.load().then(function(d){ return d.leagueId; })") == "site"


# --------------------------------------------------------------------------- #
# The other reader pages: a private ESPN league in ESPN's words
# --------------------------------------------------------------------------- #

def _reader_page(hosts: str, scripts: str, host: str, league_id: str, routes=None):
    from gordstats import league_api, my_league_data
    body = hosts + _raw(league_api.JS + my_league_data.JS + scripts)
    wait = (f"(function(){{ var h=document.getElementById('{host}');"
            " return !!h && h.textContent.length>0 && !/Reading/.test(h.textContent); })()")
    return body, (routes if routes is not None else _espn_private()) + _site_files(), \
        _saved(league_id), wait


@pytest.mark.parametrize("which", ["home", "waivers", "draft", "strength"])
def test_a_private_espn_league_is_explained_in_espns_words(browser, which):
    from fantasy.site import strength
    from gordstats import my_draft, my_history, my_home, my_waivers
    pages = {
        "home": ("<div id='mh-metrics'></div><div id='mh-teams'></div>",
                 my_history.JS + my_home.JS, "mh-metrics"),
        "waivers": ("<div id='wv-host'></div>", my_waivers.JS, "wv-host"),
        "draft": ("<div id='dr-host'></div>", my_draft.JS, "dr-host"),
        "strength": ("<div id='st-mine'></div>", strength.READER_JS, "st-mine"),
    }
    hosts, scripts, host = pages[which]
    body, routes, storage, wait = _reader_page(hosts, scripts, host, "espn:2026:7")
    browser.open(body, routes, storage, wait=wait)
    text = browser.ev(f"document.getElementById('{host}').textContent")
    assert "ESPN keeps that league private" in text, text
    assert "Sleeper" not in text, text
    if which == "strength":
        assert "The table below is the NFL's" in text


@pytest.mark.parametrize("which", ["waivers", "draft"])
def test_a_sleeper_league_that_cannot_be_read_still_says_sleeper(browser, which):
    from gordstats import my_draft, my_waivers
    scripts, host = {"waivers": (my_waivers.JS, "wv-host"), "draft": (my_draft.JS, "dr-host")}[which]
    body, routes, storage, wait = _reader_page(f"<div id='{host}'></div>", scripts, host, LID,
                                               routes=[])
    browser.open(body, routes, storage, wait=wait)
    assert "Could not read that league from Sleeper" in browser.ev(
        f"document.getElementById('{host}').textContent")


def test_no_reader_page_blames_sleeper_by_name_unconditionally():
    """The fixed messages, as source: what is left names a site only through
    GSAPI or an ESPN check."""
    from fantasy.site import strength
    from gordstats import my_draft, my_home, my_power, my_waivers
    for js in (my_power.JS, my_home.JS, my_waivers.JS, my_draft.JS, strength.READER_JS):
        assert "Sleeper may be busy" not in js
        assert "Could not read that league from Sleeper" not in js


# --------------------------------------------------------------------------- #
# CBB watch guide
# --------------------------------------------------------------------------- #

def test_the_cbb_guide_ends_its_night_at_its_own_hour(browser):
    """The engine reads cfg.nightEnds (default 4, football's); CBB counts a
    tip only to 3 AM as the night before (AFTER_MIDNIGHT), so its day must
    turn over at the same hour."""
    from cbb.render import render_watch as watch
    capture = ("<script>(function(){ var real;"
               " Object.defineProperty(window,'GSWatch',{configurable:true,"
               "  get:function(){ return real&&function(D,cfg){ window.__cfg=cfg; return real(D,cfg); }; },"
               "  set:function(f){ real=f; }}); })();</script>")
    feed = {"generated": "2026-12-01T12:00:00Z", "leagues": {"men": {}, "women": {}}}
    routes = [["workers\\.dev", 200, feed], ["star-teams", 200, {}]]
    body = "<div class='page-updated'></div>" + capture + watch.body()
    browser.open(body, routes, {}, wait="!!window.__cfg")
    assert browser.ev("window.__cfg.nightEnds") == watch.AFTER_MIDNIGHT == 3
