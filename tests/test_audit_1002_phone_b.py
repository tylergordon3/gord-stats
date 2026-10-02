"""Phone fixes from the 2026-10-02 audit (reviewers at 390/360/320px, light
and dark): the trade analyzer's pickup table and chips, the result brought
into view, preview links a thumb can hit, the season-trend charts drawn for a
phone, injury names, the draft board's values, the CFB pinned bar and Top 25
names, dark contrast, the CBB logo tag and tip-off date.

The trade page is laid out in headless Chromium (DevTools port 9488) at phone
widths; without Chromium those tests skip.
"""
import asyncio
import json
import re
import shutil
import subprocess
import time
import urllib.request
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from browser_util import launch, reap

CHROME = next((p for p in ("/usr/bin/chromium-browser", "/usr/bin/chromium",
                           "/usr/bin/google-chrome") if shutil.which(p)), None)
PORT = 9488


def _js(block: str) -> str:
    block = block.replace("{% raw %}", "").replace("{% endraw %}", "")
    return re.sub(r"</?script[^>]*>", "", block)


# --------------------------------------------------------------------------- #
# A browser that can be resized
# --------------------------------------------------------------------------- #

class Browser:
    def __init__(self):
        subprocess.run(["fuser", "-k", f"{PORT}/tcp"], capture_output=True)
        self.proc = launch(CHROME, PORT)
        self.n = 0
        for _ in range(60):
            try:
                targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
                self.ws_url = next(t["webSocketDebuggerUrl"] for t in targets
                                   if t.get("type") == "page")
                return
            except Exception:                                   # noqa: BLE001
                time.sleep(0.5)
        raise RuntimeError("Chromium did not come up")

    def close(self):
        self.proc.terminate()
        reap(self.proc)
        subprocess.run(["fuser", "-k", f"{PORT}/tcp"], capture_output=True)

    def send(self, method, params=None):
        import websockets

        async def run():
            async with websockets.connect(self.ws_url, max_size=None) as ws:
                self.n += 1
                await ws.send(json.dumps({"id": self.n, "method": method,
                                          "params": params or {}}))
                while True:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=60))
                    if msg.get("id") == self.n:
                        return msg.get("result", {})
        return asyncio.run(run())

    def evaluate(self, expression):
        res = self.send("Runtime.evaluate", {"expression": expression,
                                             "returnByValue": True, "awaitPromise": True})
        if res.get("exceptionDetails"):
            raise AssertionError(str(res["exceptionDetails"]))
        return res["result"].get("value")

    def size(self, width, height=800):
        self.send("Emulation.setDeviceMetricsOverride",
                  {"width": width, "height": height, "deviceScaleFactor": 1,
                   "mobile": width < 700})


@pytest.fixture(scope="module")
def browser():
    if CHROME is None:
        pytest.skip("no Chromium to lay the page out in")
    b = Browser()
    yield b
    b.close()


# --------------------------------------------------------------------------- #
# The trade analyzer on a phone
# --------------------------------------------------------------------------- #

def _stub_adapter() -> str:
    """Two sixteen-man rosters with long names, injury tags and next-man-up
    chips - the rows that squeezed the names to nothing - and five pickups."""
    players, rosters = {}, {"1": [], "2": []}
    pos = ["QB", "QB", "RB", "RB", "RB", "RB", "WR", "WR", "WR", "WR", "WR", "TE", "TE",
           "K", "DEF", "WR"]
    for team in ("1", "2"):
        for i, p in enumerate(pos):
            pid = f"{team}-{i}"
            name = "Jacory Croskey-Merritt" if i == 5 else f"Player Number{i}"
            players[pid] = {"name": name, "short": "J. Croskey-Merritt" if i == 5 else f"P. Num{i}",
                            "pos": p, "ppw": 10.0 + i,
                            "tag": "Out 4w" if i in (3, 9) else "",
                            "boost": [4.9, "+4.9 Achane out"] if i in (5, 8) else None}
            rosters[team].append(pid)
    for i in range(5):
        players[f"fa{i}"] = {"name": f"Free Agent{i}", "short": f"F. Agent{i}", "pos": "WR",
                             "ppw": 9.0, "tag": "Out 1w" if i == 2 else "",
                             "boost": [-0.6, "-0.6 Mayfield out"] if i == 3 else None}
    stat = {"ppw": 120.0, "wins": 14.0, "losses": 14.0, "playoffs": 0.55, "title": 0.12}
    data = {"league": "x", "teams": [{"id": "1", "name": "Drink Maye (tgordon3)"},
                                     {"id": "2", "name": "CCAM's Convicts"}],
            "mine": "1", "players": players, "rosters": rosters,
            "before": {"1": stat, "2": stat}, "note": "", "sims": 1000}
    return """
      window.GSTradeAdapter = {
        load: function(){ return Promise.resolve(__D); },
        evaluate: function(t){
          var s = __D.before['1'];
          var up = Object.assign({}, s, {playoffs: s.playoffs + .05, title: s.title + .03});
          return Promise.resolve({after: {'1': up, '2': s}, moves: {}});
        },
        candidates: function(){ return ['fa0','fa1','fa2','fa3','fa4']; },
        pickup: function(team, pid){
          var s = __D.before['1'];
          return Promise.resolve({before: s, drop: '1-15',
            after: Object.assign({}, s, {playoffs: s.playoffs + .123, title: s.title - .004})});
        }
      };
    """.replace("__D", json.dumps(data))


def _load(browser, width, hash_=""):
    from gordstats import trade_page
    browser.size(width, 600)
    section = trade_page.section("/fantasy/trade/")
    browser.evaluate("history.replaceState(null,'','#" + hash_ + "');"
                     "document.body.innerHTML='';document.body.style.margin='0';"
                     "document.body.style.padding='0 16px';window.scrollTo(0,0);true")
    browser.evaluate(_js(trade_page.JS) + ";" + _stub_adapter() + ";true")
    browser.evaluate("document.body.insertAdjacentHTML('beforeend', "
                     + json.dumps(section + "<div style='height:2px'></div>") + ");"
                     "window.GSTrade(document.getElementById('tr-host'), window.GSTradeAdapter);"
                     "true")


PICKUP = """
new Promise(function(done){
  var tries = 0;
  (function wait(){
    var rows = document.querySelectorAll('.tr-pk tbody tr');
    var ready = rows.length === 5 && !/Playing each/.test(document.querySelector('.tr-out').textContent);
    if(!ready){ if(++tries > 200) return done('no table'); return setTimeout(wait, 50); }
    var wrap = document.querySelector('.tr-pk-wrap'), head = document.querySelector('.tr-pk thead tr');
    var shown = function(el){ return getComputedStyle(el).display !== 'none'; };
    var cells = [].filter.call(head.cells, shown);
    var subs = [].map.call(document.querySelectorAll('.tr-pk-sub'), function(s){
      return shown(s) ? s.textContent : null; });
    done({over: wrap.scrollWidth - wrap.clientWidth,
          heads: cells.map(function(c){ return c.textContent; }),
          titleRight: cells[cells.length-1].getBoundingClientRect().right,
          wrapRight: wrap.getBoundingClientRect().right,
          subs: subs, names: [].map.call(document.querySelectorAll('.tr-pk .tr-name'),
            function(n){ return n.getBoundingClientRect().width; })});
  })();
})
"""


def test_the_pickup_answer_fits_a_phone_and_the_drop_moves_under_the_player(browser):
    """At 390px the Playoffs and Title columns ran off a 369px box that hid its
    overflow: the whole answer was invisible."""
    for width in (390, 320):
        _load(browser, width, "pickup")
        got = browser.evaluate(PICKUP)
        assert isinstance(got, dict), got
        assert got["over"] <= 0, (width, got)
        assert got["heads"] == ["Pick up", "Playoffs", "Title"], got["heads"]
        assert got["titleRight"] <= got["wrapRight"] + 0.5, (width, got)
        assert all(s and s.startswith("Drop ") for s in got["subs"]), got["subs"]
        assert min(got["names"]) >= 60, (width, got["names"])
    # A desktop keeps the Drop column and no line under the player.
    _load(browser, 1000, "pickup")
    got = browser.evaluate(PICKUP)
    assert got["heads"] == ["Pick up", "Drop", "Playoffs", "Title"], got["heads"]
    assert not any(got["subs"]), got["subs"]


TRADE = """
new Promise(function(done){
  var tries = 0;
  (function wait(){
    var rows = document.querySelectorAll('.tr-p');
    if(rows.length < 32){ if(++tries > 200) return done('no lists'); return setTimeout(wait, 50); }
    done([].map.call(rows, function(b){
      var n = b.querySelector('.tr-name'), c = b.querySelector('.tr-boost, .tr-tag');
      var nr = n.getBoundingClientRect(), br = b.getBoundingClientRect();
      return {w: nr.width, chip: c ? c.textContent : '',
              below: c ? c.getBoundingClientRect().top >= nr.bottom - 1 : null,
              inside: c ? c.getBoundingClientRect().right <= br.right + 0.5 : true,
              size: c ? parseFloat(getComputedStyle(c).fontSize) : 12};
    }));
  })();
})
"""


def test_a_next_man_up_chip_no_longer_squeezes_the_name(browser):
    """"+4.9 Achane out" took the row and left the name 8-14px at 390, none
    at 320. On a phone the tag and chip go to a line of their own."""
    for width, least in ((390, 90), (320, 60)):
        _load(browser, width)
        rows = browser.evaluate(TRADE)
        assert isinstance(rows, list), rows
        assert min(r["w"] for r in rows) >= least, (width, sorted(r["w"] for r in rows)[:4])
        chipped = [r for r in rows if r["chip"]]
        assert chipped and all(r["below"] and r["inside"] for r in chipped), chipped
        assert all(r["size"] >= 12 for r in chipped)
    _load(browser, 1000)
    rows = browser.evaluate(TRADE)
    assert all(not r["below"] for r in rows if r["chip"]), "a desktop keeps them in line"


def test_the_verdict_is_brought_up_on_a_phone_once(browser):
    """The verdict landed ~700px under the lists, off screen, on a phone."""
    reveal = """
    new Promise(function(done){
      var tries = 0;
      (function wait(){
        var a = document.querySelectorAll('.tr-side')[0], b = document.querySelectorAll('.tr-side')[1];
        if(!a){ if(++tries > 200) return done('no lists'); return setTimeout(wait, 50); }
        a.querySelectorAll('.tr-p')[2].click();
        b.querySelectorAll('.tr-p')[2].click();
        (function res(){
          if(!document.querySelector('.tr-verdict')){
            if(++tries > 400) return done('no result'); return setTimeout(res, 50); }
          setTimeout(function(){
            var top = document.querySelector('.tr-out').getBoundingClientRect().top;
            done({y: scrollY, top: top, h: innerHeight});
          }, 1500);
        })();
      })();
    })
    """
    _load(browser, 390)
    got = browser.evaluate(reveal)
    assert isinstance(got, dict), got
    assert got["y"] > 0 and 0 <= got["top"] < got["h"] / 2, got
    _load(browser, 1000)
    got = browser.evaluate(reveal)
    assert got["y"] == 0, "a desktop is left where the reader put it"


def test_trade_css_says_it():
    from gordstats import trade_page
    css = trade_page.CSS
    assert ".tr-pk-wrap{border:1px solid #e2e8f0;border-radius:10px;overflow-x:auto}" in css
    for cls in ("tr-pos", "tr-tag", "tr-boost"):
        assert re.search(r"\." + cls + r"\{[^}]*font-size:12px", css), cls


# --------------------------------------------------------------------------- #
# Preview links a thumb can hit; the kickoff is never the part cut
# --------------------------------------------------------------------------- #

def _game():
    return pd.Series({
        "home": "Cleveland Browns", "away": "Pittsburgh Steelers", "home_id": 5, "away_id": 23,
        "pred_margin": 1.2, "home_win_prob": 0.54, "market_spread": -2.5, "pred_total": 41.0,
        "neutral": False, "date": datetime(2026, 10, 1, 20, 15, tzinfo=ZoneInfo("America/New_York")),
        "time_valid": True, "game_id": "401", "place": "Cleveland, OH", "tv": "Prime Video",
        "completed": False})


def test_the_preview_link_is_thumb_sized_and_the_kickoff_is_never_cut(browser, monkeypatch):
    from cfb.site import predictions
    from gordstats import preview_page
    monkeypatch.setattr(predictions, "_scores", lambda g: (None, None))
    monkeypatch.setattr(preview_page, "href", lambda sport, gid: "/cfb/game/401/")
    card = predictions._card(_game())
    assert "<span class='pg-where'>&nbsp;&middot; Cleveland, OH</span>" in card
    css = predictions._CSS.replace("{accent}", "#2563eb")
    for width in (390, 320):
        browser.size(width)
        got = browser.evaluate(
            "document.body.innerHTML=" + json.dumps(css + "<div class='pred-grid'>" + card + "</div>")
            + ";document.body.style.padding='0 16px';(function(){"
            "var w=document.querySelector('.pg-when'),at=w.children[0],a=w.querySelector('a');"
            "var r=a.getBoundingClientRect(),tv=w.querySelector('.pg-tv').getBoundingClientRect();"
            "return {atCut:at.scrollWidth>at.clientWidth+1,linkH:r.height,"
            "hit:document.elementFromPoint(r.left+r.width/2,r.top+2)===a,"
            "overlap:at.getBoundingClientRect().right>tv.left+0.5&&"
            "Math.abs(at.getBoundingClientRect().top-tv.top)<4,"
            "tvOut:tv.right>w.getBoundingClientRect().right+0.5}})()")
        assert not got["atCut"] and not got["overlap"] and not got["tvOut"], (width, got)
        assert got["linkH"] >= 40 and got["hit"], (width, got)


def test_the_nfl_schedules_preview_row_is_padded_and_its_labels_read():
    from nfl.site import schedule
    src = open(schedule.__file__, encoding="utf-8").read()
    assert ".ns-pv .ns-v a{display:inline-block" in src
    assert re.search(r"\.ns-lab\{[^}]*font-size:11\.5px", src)


# --------------------------------------------------------------------------- #
# Charts drawn for a phone
# --------------------------------------------------------------------------- #

def test_a_picture_chart_ships_a_phone_drawing_at_half_its_pixels(tmp_path, monkeypatch):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from gordstats import charts
    monkeypatch.setattr(charts, "CHART_DIR", tmp_path)

    def draw(width):
        plt.subplots(figsize=(width, 2))
        plt.plot([0, 1], [1, 0])

    draw(8)
    tag = charts.save_picture("sec", "trend", lambda: draw(3), alt="A line")
    assert (tmp_path / "sec" / "trend.png").exists()
    assert (tmp_path / "sec" / "trend-phone.png").exists()
    src = re.search(r'<source media="\(max-width: 600px\)" srcset="[^"]*trend-phone\.png[^"]*" '
                    r'width="(\d+)" height="(\d+)">', tag)
    img = re.search(r'<img class="gs-chart" src="[^"]*trend\.png[^"]*" alt="A line" '
                    r'width="(\d+)" height="(\d+)"', tag)
    assert src and img, tag
    from PIL import Image
    with Image.open(tmp_path / "sec" / "trend-phone.png") as png:
        assert abs(png.size[0] / 2 - int(src.group(1))) <= 1, "drawn at 2x, sized at 1x"
    assert int(src.group(1)) < int(img.group(1))


# --------------------------------------------------------------------------- #
# Names a reader can read
# --------------------------------------------------------------------------- #

def test_the_injury_table_names_players_rather_than_lookup_keys(monkeypatch):
    from fantasy.site import injuries
    names = {("JaMarrChase", "WR"): "Ja'Marr Chase", ("JaMarrChase", None): "Ja'Marr Chase",
             ("JKDobbins", "RB"): "J.K. Dobbins", ("JKDobbins", None): "J.K. Dobbins"}
    assert injuries.display_name("JaMarrChase", "WR", names) == "Ja'Marr Chase"
    assert injuries.display_name("JKDobbins", "RB", names) == "J.K. Dobbins"
    # Not in the table: split where a word starts.
    assert injuries.display_name("AnthonyRichardson", "QB", {}) == "Anthony Richardson"
    assert injuries.display_name("JKDobbins", "RB", {}) == "JK Dobbins"

    monkeypatch.setattr(injuries, "_player_names", lambda: names)
    detail = pd.DataFrame([{"Name": "JaMarrChase", "Pos.": "WR", "season": "2025-2026",
                            "roster_id": 1, "Pick": "1.3", "Med PPG": 20.0,
                            "Games Missed": 5, "Est. Pts Lost": 100.0}])
    html = injuries.top_injuries(detail).to_html()
    assert "Ja&#39;Marr Chase" in html or "Ja'Marr Chase" in html
    assert "JaMarrChase" not in html


def test_the_draft_board_cuts_the_name_never_the_value():
    from gordstats import my_draft
    css, js = my_draft.CSS, my_draft.JS
    td = re.search(r"table\.dr-b td\{([^}]*)\}", css).group(1)
    assert "ellipsis" not in td and "max-width" not in td
    assert ".dr-cell .dr-nm{min-width:0;overflow:hidden;text-overflow:ellipsis}" in css
    assert ".dr-cell .dr-pos,.dr-cell .dr-v{flex:none}" in css
    assert "slice(0,14)" not in js, "a manager's name is no longer cut at 14 letters"
    assert '<span class="dr-cell">' in js


def test_the_top25_card_has_a_short_form_for_long_names(monkeypatch):
    from cfb.site import homecards
    assert homecards._short_name("Mississippi State", "Mississippi St") == "Miss State"
    assert homecards._short_name("Boise State", "Boise St") == "Boise St"
    assert homecards._short_name("Notre Dame", "Notre Dame") is None
    assert homecards._short_name("Western Michigan", "W Michigan") == "W Michigan"
    assert homecards._short_name("Some Long University", "Some Long Univ") is None, \
        "no short form that would still not fit"
    teams = {"1": {"name": "Mississippi State", "short": "Miss State", "logo": None,
                   "ap": 1, "gs": 1, "fpi": 1},
             "2": {"name": "Texas", "short": None, "logo": None, "ap": 2, "gs": 2, "fpi": 2}}
    monkeypatch.setattr(homecards, "_rankings", lambda: (teams, True))
    html = homecards.top25_html(limit=2)
    assert "<span class='hc-sh'>Miss State</span><span class='hc-tm'>Mississippi State</span>" in html
    assert "<span class='hc-tm'>Texas</span>" in html and "hc-sh'>Texas" not in html
    assert "td.hc-tc .hc-sh+.hc-tm{display:none}" in homecards._T25_PHONE_CSS


# --------------------------------------------------------------------------- #
# The CFB pinned bar, dark contrast
# --------------------------------------------------------------------------- #

def test_the_cfb_power_menu_gives_way_before_the_bar_overflows():
    from cfb.site import power
    src = open(power.__file__, encoding="utf-8").read()
    assert ".pwr-pin>.win-pick{flex:0 1 auto;min-width:0}" in src
    assert ".win-sel{min-width:0;max-width:100%}" in src
    assert re.search(r"@media \(max-width:380px\)\{\s*\.pwr-pin \.win-pick \.switch-label"
                     r"\{display:none\}", src)


def test_dark_theme_meta_and_consolation_heading_read():
    from cfb.site import league
    from wnba import wnba_remaining
    src = open(league.__file__, encoding="utf-8").read()
    dark = src[src.index("@media (prefers-color-scheme: dark)"):]
    assert ".wv-col .mu-meta{color:#94a3b8}" in dark
    wsrc = open(wnba_remaining.__file__, encoding="utf-8").read()
    assert ".bracket-title.consolation-title{color:#94a3b8}" in wsrc


# --------------------------------------------------------------------------- #
# CBB: one lazy, sized logo tag with alt; one tip-off date
# --------------------------------------------------------------------------- #

def test_every_cbb_logo_helper_writes_the_lazy_sized_tag():
    from cbb import html_util, predictions, scraper
    want = ('<img src="/assets/images/duke.png" class="team-logo" loading="lazy" '
            'decoding="async" width="40" height="40" alt="">')
    assert html_util.image_formatter("/assets/images/duke.png") == want
    assert scraper.image_formatter("/assets/images/duke.png") == want
    assert predictions.image_formatter("/assets/images/duke.png") == want
    assert 'alt="Duke &quot;Blue&quot; Devils"' in html_util.image_formatter(
        "/x.png", alt='Duke "Blue" Devils')
    from pathlib import Path
    teams_src = (Path(predictions.__file__).parent / "render" / "render_teams.py").read_text()
    assert 'class="team-logo" >' not in teams_src
    # The tracked conference pages, written in March and not rebuilt until
    # tip-off, carry the same tag.
    docs = Path(__file__).resolve().parent.parent / "docs"
    for page in ("men/conference.html", "women/conference.html"):
        html = (docs / page).read_text(encoding="utf-8")
        assert 'class="team-logo" >' not in html, page


def test_the_cbb_clock_and_the_scoreboards_name_the_same_day():
    from cbb.render import render_home as rh
    target = rh._countdown_targets()["cbb"]
    assert target.date() == rh.CBB_TIPOFF, "the clock counts to the first game"
    assert "November 1" in rh._season_status(date(2026, 10, 2), "-")
