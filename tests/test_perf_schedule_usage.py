"""
The 2026-10-02 performance pass on the two most-read pages.

/cfb/usage/ (and /fantasy/usage/, which shares its table): every body cell
used to carry the views it shows in as classes - "v-overall v-rb v-wr v-te"
on 14,000 cells, 46% of a 1 MB page. Views now hide columns by position, from
the same column list that renders the header (gordstats.usage_page.css), so a
body cell is a bare <td>; a share's bar is a pseudo-element painted from the
cell's --w; a numeric cell carries data-v only where it differs from the text;
and the script moves a row only when the order changes, so a filter or a
search no longer lays the whole table out again.

/cfb/schedule/: each game's More panel waits in a <template> until it is
first opened, the empty drive-line box is built only for games in progress,
the week is re-laid out by moving only what is out of place, and on a phone
an off-screen card is not styled or laid out until it nears the screen.

The unit tests pin the markup; the two Chromium tests run each page's real
script on a small synthetic table.
"""
import asyncio
import json
import re
import shutil
import subprocess
import time
import urllib.request

import pandas as pd
import pytest

from browser_util import launch, reap

CHROME = next((p for p in ("/usr/bin/chromium-browser", "/usr/bin/chromium",
                           "/usr/bin/google-chrome") if shutil.which(p)), None)
CDP = 9611
needs_chrome = pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")
VIEWS = ("overall", "rb", "wr", "te")


# --------------------------------------------------------------------------- #
# Usage: the column list, the generated rules, the cells
# --------------------------------------------------------------------------- #

def _pages():
    from cfb.site import usage as cfb_usage
    from fantasy.site import usage as nfl_usage
    return [cfb_usage, nfl_usage]


def _hidden(css: str, scope: str) -> dict:
    """{"th": {1-based column}, "td": {...}} hidden by `{display:none}` rules
    written for `table.us<scope>`."""
    out = {"th": set(), "td": set()}
    for sels in re.findall(r"([^{}]+)\{display:none\}", css):
        for sel in sels.split(","):
            m = re.fullmatch(r"\s*table\.us" + re.escape(scope)
                             + r" (th|td):(?:nth-child\((\d+)\)|first-child)\s*", sel)
            if m:
                out[m.group(1)].add(int(m.group(2) or 1))
    return out


@pytest.mark.parametrize("page", _pages(), ids=["cfb", "nfl"])
def test_each_view_hides_a_column_in_its_header_and_its_cells_alike(page):
    from gordstats import usage_page as ui

    css = ui.css(page.COLUMNS)
    for view in VIEWS:
        got = _hidden(css, f".view-{view}")
        want = {i + 1 for i, c in enumerate(page.COLUMNS) if view not in c.views.split()}
        assert got["th"] == got["td"] == want, view
    # The sort each view opens on is a column it shows.
    for v in page.VIEWS:
        at = ui.sort_index(page.COLUMNS, v["sort"]) + 1
        assert at not in _hidden(css, f".view-{v['key']}")["td"], v["key"]


@pytest.mark.parametrize("page", _pages(), ids=["cfb", "nfl"])
def test_a_phone_drops_the_owner_and_season_columns_header_and_all(page):
    from gordstats import usage_page as ui

    css = ui.css(page.COLUMNS)
    block = css[css.index("@media (max-width:560px){"):]
    got = _hidden(block[:block.index("}") + 1], "")
    want = {i + 1 for i, c in enumerate(page.COLUMNS) if c.role in ("own", "lead")}
    assert got["th"] == got["td"] == want
    labels = {page.COLUMNS[i - 1].label for i in want}
    assert labels == {"Fantasy", "Season"}


@pytest.mark.parametrize("page", _pages(), ids=["cfb", "nfl"])
def test_the_header_is_the_column_list(page):
    from gordstats import usage_page as ui

    head = ui.head(page.COLUMNS)
    ths = re.findall(r"<th[^>]*>(.*?)</th>", head)
    assert ths == [c.label for c in page.COLUMNS]
    # No view classes anywhere in it: the views live in the stylesheet.
    assert not re.search(r"\bv-(overall|rb|wr|te)\b", head)
    # The roles the stylesheet and the scripts look for by class.
    for role in ("us-name", "us-own", "us-rank"):
        assert head.count(f'class="{role}"') == 1, role


def test_the_unranked_dash_is_a_dash():
    """`content:"\\2013"` in a plain Python string is chr(0o201) + "3": the
    greyed, unranked rows showed a 3 in the rank column."""
    from cfb.site import usage as cfb_usage
    from gordstats import usage_page as ui

    css = ui.css(cfb_usage.COLUMNS)
    rule = re.search(r"tr\.us-thin td:first-child::after\{content:\"([^\"]*)\"\}", css)
    assert rule and rule.group(1) == "\\2013", rule
    assert "\x81" not in css


def test_a_cell_keeps_its_sort_value_only_where_the_text_is_not_it():
    from gordstats import usage_page as ui

    assert ui.num(76.0) == "<td>76</td>"
    assert ui.num(2.5) == '<td data-v="2.5">2</td>'
    assert ui.num(float("nan")) == '<td data-v="">nan</td>'
    assert ui.pct(0.5512) == '<td data-v="0.5512">55%</td>'
    assert ui.pct(None) == '<td data-v="">&mdash;</td>'
    assert ui.fixed(0.0643, "{:+.2f}") == '<td data-v="0.0643">+0.06</td>'
    assert ui.fixed(18.0, "{:.1f}") == '<td data-v="18">18.0</td>'
    assert ui.cell("FA", cls="us-own") == '<td class="us-own">FA</td>'


def test_a_share_bar_is_painted_from_the_cell():
    from gordstats import usage_page as ui

    assert ui.bar(0.7308) == '<td data-v="0.7308" style="--w:73%">73%</td>'
    assert ui.bar(1.4) == '<td data-v="1.4" style="--w:100%">100%</td>'
    assert ui.bar(None) == '<td data-v="">&mdash;</td>'
    css = ui.css()
    assert "table.us tbody td[style]::before" in css
    assert "var(--w)" in css and ".us-bar" not in css


def _cfb_frames(rows):
    """(recent, season) shaped like cfb.usage.shares() after ownership.attach."""
    base = dict(team="Iowa", pos="RB", games=3, carries=40, targets=6, rec=5, rush_yds=200,
                rec_yds=40, rush_td=2, rec_td=0, fpts=40.0, car_share=0.5, tgt_share=0.1,
                rec_share=0.1, ppa=0.12, team_key="", owner="")
    recent = pd.DataFrame([{**base, **r} for r in rows])
    season = recent[["team", "athlete_id", "car_share", "tgt_share"]].copy()
    return recent, season


def _cfb_rows(rows):
    from cfb.site import usage as cfb_usage
    recent, season = _cfb_frames(rows)
    return cfb_usage._rows(recent, season, {"Iowa": "Big Ten", "Ohio State": "Big Ten"})


def _nfl_rows():
    from fantasy.site import usage as nfl_usage
    recent = pd.DataFrame([dict(
        sleeper_id="4034", player="Back One", team="KC", pos="RB", games=3, snap_share=0.7,
        rush_att=40, car_share=0.6, rec_tgt=8, tgt_share=0.1, off_snp=150, rec=6,
        air_share=0.05, rush_rz_att=4, rec_rz_tgt=1, rush_yd=180, rec_yd=40, rush_td=2,
        rec_td=0, pts_ppr=50.0)])
    season = recent.set_index("sleeper_id")[["snap_share", "car_share", "tgt_share"]].reset_index()
    return nfl_usage._rows(recent, season, {"4034": "3"}, {"3": "Team Three (Al)"})


def test_body_cells_carry_no_view_classes():
    from cfb.site import usage as cfb_usage
    from fantasy.site import usage as nfl_usage

    for html, cols in ((_cfb_rows([dict(athlete_id=1, player="A Back")]), cfb_usage.COLUMNS),
                       (_nfl_rows(), nfl_usage.COLUMNS)):
        tds = re.findall(r"<td[^>]*>", html)
        assert len(tds) == len(cols)
        classes = [re.search(r'class="([^"]*)"', t) for t in tds]
        assert [c.group(1) for c in classes if c] == ["us-own"], tds
    # The override for a reader's own league finds the owner cell by class.
    assert 'class="us-own"' in _nfl_rows() and 'data-pid="4034"' in _nfl_rows()


# --------------------------------------------------------------------------- #
# Schedule: the More panel, the live box, the phone cards
# --------------------------------------------------------------------------- #

def _game(**kw):
    g = dict(game_id="9001", week=5, state="pre", detail="", neutral=False, note="",
             home="Indiana", away="Purdue", home_abbr="IU", away_abbr="PUR",
             home_id="84", away_id="2509", home_rank=5.0, away_rank=float("nan"),
             home_score=float("nan"), away_score=float("nan"),
             gs_margin=10.4, gs_wp=0.81, gs_total=47.2, gs_home=28.8, gs_away=18.4,
             dk_spread=-7.5, dk_total=49.5, ml_home=-300.0, ml_away=240.0, fpi_wp=0.77,
             bd_spread_open=-6.5, bd_total_open=48.5, bd_ml_home_open=float("nan"),
             bd_ml_away_open=float("nan"), last5_home=None, last5_away=None, mq=55.0,
             weather=None, home_conf="Big Ten", away_conf="Big Ten", conference_game=True,
             tv="FOX", venue="Memorial Stadium", place="Bloomington, IN", time_valid=True,
             date_utc="2026-10-03T16:00Z",
             local=pd.Timestamp("2026-10-03T16:00Z").tz_convert("America/New_York"))
    g.update(kw)
    return g


@pytest.fixture
def sched(monkeypatch):
    from cfb.site import schedule
    from gordstats import preview_page
    monkeypatch.setattr(schedule, "_team_pages", lambda: frozenset())
    monkeypatch.setattr(preview_page, "href", lambda sport, gid: f"/cfb/game/{gid}/")
    return schedule


def _rows_of(sched, games, panels=None):
    from types import SimpleNamespace
    return "".join(sched._row(SimpleNamespace(**g), i, {}, panels) for i, g in enumerate(games))


def test_the_more_panels_are_a_file_of_their_own(sched):
    """A quarter of the page's weight, opened by few: the week's panels go to
    their own file and the card keeps an empty row to open them into."""
    panels = []
    html = _rows_of(sched, [_game(), _game(game_id="9002")], panels)
    assert '<tr class="det" data-for="g-9001"></tr>' in html
    assert "<template" not in html and "Opinions" not in html
    assert len(panels) == 2
    det = panels[0]
    assert det.startswith('<template data-for="g-9001"><td colspan="4">'), det[:80]
    assert det.endswith("</template>")
    # Everything the panel said is still there, links included.
    assert "<h4>Lines</h4>" in det and "<h4>Opinions</h4>" in det
    assert '<a href="/cfb/game/9001/">Full preview &rarr;</a>' in det
    # Inside the pattern the week fragments are ignored and copied under.
    assert sched.MORE_FILE % 5 == "week-5-more.html" and sched.WEEK_FILE % 5 == "week-5.html"
    assert sched.MORE_URL % 5 == "/cfb/schedule/week-5-more"


def test_without_a_list_the_panel_waits_inline(sched):
    html = _rows_of(sched, [_game()])
    det = html[html.index('<tr class="det"'):]
    assert det.startswith('<tr class="det" data-for="g-9001"><template data-for="g-9001">')
    assert det.endswith("</template></tr>")


def test_only_a_game_in_progress_carries_the_drive_line(sched):
    assert "sc-live" not in _rows_of(sched, [_game(), _game(game_id="9002", state="post",
                                                              home_score=24.0, away_score=17.0)])
    live = _rows_of(sched, [_game(state="in", detail="Q2 4:31", home_score=7.0, away_score=3.0)])
    assert sched._LIVE_BOX in live
    # At the foot of the matchup cell, where the poll adds it to a game that
    # kicks off later.
    mu = live[live.index('<td class="mu">'):live.index('<td class="t d"')]
    assert mu.endswith(sched._LIVE_BOX + "</td>")
    assert "function liveBox(row)" in sched._JS and "liveBox(row)" in sched._JS


def test_no_dead_attributes_on_a_card(sched):
    html = _rows_of(sched, [_game()])
    assert "data-l=" not in html, "data-l was never read; data-s labels the phone lines"
    assert 'class=""' not in html


def test_a_phone_lays_out_only_the_cards_near_the_screen(sched):
    phone = sched._CSS[sched._CSS.index("@media (max-width:700px){\n  #cfb-weeks"):]
    rule = re.search(r"table\.cfb-sched>tbody>tr\.g\{content-visibility:auto;"
                     r"contain-intrinsic-size:auto (\d+)px\}", phone)
    assert rule, "the phone cards lost content-visibility"
    # The estimate is a folded card's content box: 40px team lines and the
    # rest of a folded card come to 176px inside 15px of padding and 2px of
    # border. A wrong estimate only moves the scrollbar, never the text.
    assert rule.group(1) == "176"
    assert ".sc-team{min-height:40px}" in phone
    # A linked game lands below the pinned bar.
    assert re.search(r"table\.cfb-sched tr\.g\{scroll-margin-top:calc\(var\(--header-h,0px\) "
                     r"\+ var\(--pin-h,0px\)", sched._CSS)


# --------------------------------------------------------------------------- #
# The real scripts, in Chromium
# --------------------------------------------------------------------------- #

def _in_chromium(steps):
    """[(expression, seconds to wait after it)] in one page; every value."""
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

                async def send(method, params):
                    nonlocal n
                    n += 1
                    await ws.send(json.dumps({"id": n, "method": method, "params": params}))
                    while True:
                        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
                        if msg.get("id") == n:
                            return msg.get("result", {})
                await send("Emulation.setDeviceMetricsOverride",
                           {"width": 1200, "height": 900, "deviceScaleFactor": 1, "mobile": False})
                out = []
                for expression, wait in steps:
                    got = await send("Runtime.evaluate", {"expression": expression,
                                                          "returnByValue": True,
                                                          "awaitPromise": True})
                    if got.get("exceptionDetails"):
                        raise AssertionError(got["exceptionDetails"])
                    out.append(got["result"].get("value"))
                    await asyncio.sleep(wait)
                return out
        return asyncio.run(go())
    finally:
        proc.terminate()
        reap(proc)
        subprocess.run(["fuser", "-k", f"{CDP}/tcp"], capture_output=True)


def _strip_script(js: str) -> str:
    return re.sub(r"\{%\s*(end)?raw\s*%\}|</?script>", "", js)


@needs_chrome
def test_the_usage_script_on_a_table_with_no_view_classes():
    from cfb.site import usage as cfb_usage
    from gordstats import usage_page as ui

    # In the page's own build order: carry share, highest first.
    rows = _cfb_rows([
        dict(athlete_id=1, player="Ten Games", games=10, carries=60, car_share=0.6),
        dict(athlete_id=3, player="Hundred Games", games=100, carries=50, car_share=0.5),
        dict(athlete_id=2, player="Nine Games", games=9, carries=30, car_share=0.3),
        dict(athlete_id=4, player="Light Back", games=2, carries=4, car_share=0.04),
        dict(athlete_id=5, player="Wide Out", pos="WR", targets=30, tgt_share=0.3,
             carries=0, car_share=0.0, team="Ohio State"),
    ])
    # The G column's whole numbers sort on their text: no data-v to lean on.
    assert "<td>100</td>" in rows and "<td>9</td>" in rows
    controls = ui.pin(
        "<select id='us-own'><option value=''>Everyone</option><option value='mine'>My team"
        "</option><option value='fa'>FA</option></select>"
        "<select id='us-conf'><option value=''>All</option></select>"
        "<select id='us-team'><option value=''>All</option><option>Iowa</option></select>"
        "<input id='us-find' type='search'><input id='us-group' type='checkbox'>"
        "<button id='us-reset' type='button'>Reset</button>")
    cfg = json.dumps({"mine": "", "teams": {}, "storage": "x",
                      "sort": ui.sort_index(cfb_usage.COLUMNS, "car_share"),
                      "views": cfb_usage.VIEWS})
    page = (ui.css(cfb_usage.COLUMNS) + ui.views_bar(cfb_usage.VIEWS) + controls
            + "<div class='us-scroll'><table class='us view-overall' data-sticky-head>"
            f"<thead>{ui.head(cfb_usage.COLUMNS)}</thead><tbody>{rows}</tbody></table></div>"
            f"<script type='application/json' id='us-cfg'>{cfg}</script>")
    names = ("JSON.stringify([].filter.call(document.querySelectorAll('table.us tbody tr'),"
             "function(r){return r.style.display!=='none';}).map(function(r){"
             "return r.cells[1].textContent;}))")
    parity = """(function(){var t=document.querySelector('table.us'),out={};
      ['rb','wr','te','overall'].forEach(function(v){
        document.querySelector('.uv-btn[data-view='+v+']').click();
        var bad=[];
        [].forEach.call(t.tHead.rows[0].cells,function(th,i){
          var want=getComputedStyle(th).display;
          [].forEach.call(t.tBodies[0].rows,function(r){
            if(getComputedStyle(r.cells[i]).display!==want) bad.push(i);});});
        out[v]={bad:bad,shown:[].filter.call(t.tHead.rows[0].cells,function(th){
          return getComputedStyle(th).display!=='none';}).length};});
      return JSON.stringify(out);})()"""
    got = _in_chromium([
        # about:blank cannot take the script's hash-free address back.
        ("history.replaceState=function(){};document.body.innerHTML=" + json.dumps(page) + ";"
         "window.MOVES=0;new MutationObserver(function(m){m.forEach(function(x){"
         "MOVES+=x.addedNodes.length;});}).observe(document.querySelector('table.us tbody'),"
         "{childList:true});(0,eval)(" + json.dumps(_strip_script(ui.JS)) + ");true", 0.1),
        ("MOVES", 0),                                         # built in order: nothing moved
        (parity, 0),
        # G, descending: numbers, not text ("9" > "100" as strings).
        ("document.querySelectorAll('table.us thead th')[5].click();" + names, 0),
        ("MOVES=0;var f=document.getElementById('us-find');f.value='games';"
         "f.dispatchEvent(new Event('input'));JSON.stringify({moves:MOVES,shown:" + names + "})", 0),
        ("document.getElementById('us-reset').click();"
         "document.querySelector('.uv-btn[data-view=rb]').click();"
         "JSON.stringify([].map.call(document.querySelectorAll('table.us tbody tr'),function(r){"
         "return [r.cells[1].textContent,r.cells[0].textContent,"
         "getComputedStyle(r.cells[0],'::after').content];}))", 0),
    ])
    assert got[1] == 0, "boot moved rows already in their order"
    parity = json.loads(got[2])
    for view, res in parity.items():
        assert res["bad"] == [], f"{view}: a header and its cells disagree on {res['bad']}"
    assert parity["overall"]["shown"] == len(cfb_usage.COLUMNS) - 1     # no rank column
    assert parity["rb"]["shown"] == len(cfb_usage.COLUMNS) - 4
    assert json.loads(got[3])[:3] == ["Hundred Games", "Ten Games", "Nine Games"]
    find = json.loads(got[4])
    assert find["moves"] == 0, "a search moved rows instead of hiding them"
    assert sorted(json.loads(find["shown"])) == ["Hundred Games", "Nine Games", "Ten Games"]
    rb = {name: (rank, after) for name, rank, after in json.loads(got[5])}
    assert rb["Ten Games"][0] == "1" and rb["Hundred Games"][0] == "2"
    # Four carries is under the RB view's minimum: greyed, and a dash, not a rank.
    assert rb["Light Back"] == ("", '"–"')


@needs_chrome
def test_the_schedule_script_moves_nothing_it_does_not_have_to(sched):
    games = [_game(game_id="9001", date_utc="2026-10-03T16:00Z", home_rank=float("nan")),
             _game(game_id="9002", home="Ohio State", home_abbr="OSU", home_id="194",
                   date_utc="2026-10-03T19:30Z"),
             _game(game_id="9003", home="Iowa", home_abbr="IOWA", home_id="2294",
                   home_rank=float("nan"), date_utc="2026-10-04T00:00Z")]
    for g in games:
        g["local"] = pd.Timestamp(g["date_utc"]).tz_convert("America/New_York")
    panels = []
    view = sched._week_view(pd.DataFrame(games), {}, "", panels)
    page = (sched._CSS + sched._switcher([5], 5, {5: view}, controls=sched._controls({})))
    js = _strip_script(sched._JS % {"upset": "0.35", "current": 5, "cols": sched._COLS,
                                    "url": json.dumps("/api/cfb-scores?week=5")})
    # The live poll reads FEED; the week's panels file answers from MORE.
    feed = ("window.FEED={events:[]};window.MORE=" + json.dumps("".join(panels)) + ";"
            "window.ASKED=[];window.fetch=function(u){ASKED.push(u);"
            "return Promise.resolve({ok:true,json:function(){return Promise.resolve(window.FEED);},"
            "text:function(){return Promise.resolve(window.MORE);}});};")
    seq = ("JSON.stringify([].map.call(document.querySelector('#wk-view-5 tbody').rows,"
           "function(r){return r.className.replace(/^hdr sec$/,'hdr').replace(/ open\\b/,'')+':'"
           "+(r.getAttribute('data-for')||r.id||r.textContent);}))")
    got = _in_chromium([
        (feed + "document.body.innerHTML=" + json.dumps(page) + ";"
         "window.MOVES=0;new MutationObserver(function(m){m.forEach(function(x){"
         "MOVES+=x.addedNodes.length+x.removedNodes.length;});}).observe("
         "document.querySelector('#wk-view-5 tbody'),{childList:true});"
         "window.FIRST=[].slice.call(document.querySelector('#wk-view-5 tbody').rows);"
         "(0,eval)(" + json.dumps(js) + ");true", 0.3),
        ("MOVES", 0),
        (seq, 0),
        # The More panel comes from the week's file on the first press; the
        # file is read once, however many panels are opened.
        ("document.querySelector('#g-9002 .det-btn').click();"
         "new Promise(function(r){setTimeout(r,100);}).then(function(){"
         "document.querySelector('#g-9001 .det-btn').click();"
         "var d=document.querySelector('tr.det[data-for=\"g-9002\"]');"
         "return JSON.stringify({show:d.classList.contains('show'),"
         "text:d.textContent.indexOf('Opinions')>=0,"
         "first:document.querySelector('tr.det[data-for=\"g-9001\"]').textContent.indexOf('Lines')>=0,"
         "closed:document.querySelector('tr.det[data-for=\"g-9003\"]').cells.length,"
         "asked:ASKED.filter(function(u){return /week-5-more/.test(u);}).length});})", 0),
        # A filter, then Reset: back to the same nodes in the same order, the
        # day headers the page was built with among them.
        ("document.querySelector('.sc-chips button[data-f=ranked]').click();"
         "var a=" + seq + ";document.getElementById('sc-clear').click();"
         "var rows=[].slice.call(document.querySelector('#wk-view-5 tbody').rows);"
         "JSON.stringify({filtered:JSON.parse(a),same:rows.length===FIRST.length&&"
         "rows.every(function(r,i){return r===FIRST[i];})})", 0),
        # A game kicks off: it gets the drive line and moves under Live.
        ("FEED={events:[{id:'9003',date:'2026-10-04T00:00Z',competitions:[{status:{type:"
         "{state:'in',shortDetail:'Q1 9:12'}},situation:{possession:'2294',"
         "downDistanceText:'1st & 10 at IOWA 25',possessionText:'IOWA',lastPlay:{text:'Kickoff'}},"
         "competitors:[{team:{id:'2294'},score:'0'},{team:{id:'2509'},score:'0'}]}]}]};"
         "document.dispatchEvent(new Event('visibilitychange'));true", 0.4),
        ("var r=document.getElementById('g-9003'),b=r.querySelector('td.mu>.sc-live');"
         "JSON.stringify({state:r.getAttribute('data-state'),box:b&&b.innerText,"
         "shown:b&&getComputedStyle(b).display,boxes:document.querySelectorAll('.sc-live').length,"
         "seq:" + seq + "})", 0),
    ])
    assert got[1] == 0, "booting the page moved rows that were already in place"
    assert json.loads(got[2]) == ["hdr day:Saturday, October 3", "g:g-9001", "det:g-9001",
                                  "g:g-9002", "det:g-9002", "g:g-9003", "det:g-9003"]
    more = json.loads(got[3])
    assert more == {"show": True, "text": True, "first": True, "closed": 0, "asked": 1}
    reset = json.loads(got[4])
    # Ranked only: the one ranked game keeps the day header and its open
    # panel; the others stay in their places, hidden - an open panel too -
    # and headerless.
    assert reset["filtered"] == ["g hide:g-9001", "det:g-9001", "hdr day:Saturday, October 3",
                                 "g:g-9002", "det show:g-9002", "g hide:g-9003", "det:g-9003"]
    assert reset["same"], "Reset did not put back the rows and headers the page was built with"
    live = json.loads(got[6])
    assert live["state"] == "in" and live["shown"] == "block" and live["boxes"] == 1
    assert "1st & 10 at IOWA 25" in live["box"] and "Kickoff" in live["box"]
    order = json.loads(live["seq"])
    assert order[:3] == ["hdr:Live", "hdr day:Saturday, October 3", "g:g-9003"]
    assert order[4] == "hdr:Still to play"
