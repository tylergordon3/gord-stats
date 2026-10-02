"""
Phone fixes from the 2026-10-02 audit (390/360/320px, both themes), batch A.

  * the header copy over long tables (stickyhead.js) kept the frozen first
    column in place only until the reader swiped sideways - it translated the
    whole copy, frozen cell and all;
  * the usage and matchup-strength tables lost their column names past the
    first screen, and the strength table clipped its last column at 390px;
  * Slate's 1px #373737 grid came through as black side bars on every table
    that styles only the rule under a row;
  * 11px table type on small phones, a link blue under AA, a 2.4:1 star;
  * near-black ESPN marks vanished on the dark theme;
  * white on the dark theme's orange (2.26:1) in the watch guides;
  * 12-20px tap targets (PT links, playoff names, team-page opponents);
  * the team dashboard pushing a 320px page sideways;
  * strips 3px over their box faded as if they scrolled.

The browser checks run the real scripts and stylesheet rules in headless
Chromium on small synthetic pages; they skip without Chromium.
"""
import asyncio
import functools
import http.server
import inspect
import json
import re
import shutil
import socketserver
import subprocess
import threading
import time
import urllib.request

import pytest

from browser_util import reap
from conftest import ROOT, dark_block, declared, light_block, split_rules
from gordstats import contrast

CHROME = next((p for p in ("/usr/bin/chromium-browser", "/usr/bin/chromium",
                           "/usr/bin/google-chrome") if shutil.which(p)), None)
CDP = 9493
JS_DIR = ROOT / "docs" / "assets" / "js"


def _px(value: str) -> float:
    return float(re.match(r"\s*([\d.]+)px", value).group(1))


def _rules(css: str) -> dict:
    """{selector: every declaration it gets outside the dark blocks}."""
    out = {}
    for sel, body in split_rules(light_block(css)):
        out[sel] = out.get(sel, "") + body + ";"
    return out


# --------------------------------------------------------------------------- #
# Markup and stylesheet guards
# --------------------------------------------------------------------------- #

def test_the_strength_defence_table_fits_and_keeps_its_header():
    from gordstats import strength_page as sp

    html = sp.defense_table([("A", {"QB": 1.0}, 1.0)], ("QB",))
    assert "<table class='st st-fit' data-sticky-head>" in html
    for sel in (".st-rk", ".st-bye"):
        body = _rules(sp.CSS)[sel]
        assert _px(declared(body, "font-size")) >= 12, sel


def test_both_usage_tables_ask_for_the_following_header():
    from cfb.site import usage as cfb_usage
    from fantasy.site import usage as nfl_usage

    for mod in (cfb_usage, nfl_usage):
        assert "<table class='us view-overall' data-sticky-head>" in inspect.getsource(mod)


def test_every_espn_logo_carries_the_dark_theme_hook(css_text):
    from gordstats import logos

    assert "class='gs-logo'" in logos.img("ncaa", 194, 22)
    assert "class='gs-logo mu-logo'" in logos.img("nfl", "KC", 18, cls="mu-logo")
    dark = {sel: body for sel, body in split_rules(dark_block(css_text))}
    assert declared(dark.get("img.gs-logo", ""), "background")
    assert "gs-logo" not in light_block(css_text).split("img.team-logo")[0]


def test_the_theme_grid_is_reset_to_a_light_rule(css_text):
    rules = {}
    for sel, body in split_rules(light_block(css_text)):
        rules.setdefault(sel, "")
        rules[sel] += body + ";"
    assert declared(rules["table"], "border") == "0"
    for side in ("top", "right", "left"):
        assert declared(rules["td"], f"border-{side}-width") == "0"
        assert declared(rules["th"], f"border-{side}-width") == "0"
    dark = {sel: body for sel, body in split_rules(dark_block(css_text))}
    assert declared(dark["td"], "border-bottom-color") != declared(rules["td"],
                                                                     "border-bottom-color")


def test_small_phone_tables_hold_the_12px_floor(css_text):
    for width in ("320", "360"):
        for block in re.findall(rf"@media \(max-width: {width}px\) \{{(.*?)\n\}}", css_text, re.S):
            for sel, body in split_rules(block):
                if "table" in sel and declared(body, "font-size"):
                    assert _px(declared(body, "font-size")) >= 12, (width, sel)


def test_links_and_stars_are_readable_in_daylight(css_text):
    light = {}
    for sel, body in split_rules(light_block(css_text)):
        light.setdefault(sel, "")
        light[sel] += body + ";"
    link = declared(light["a"], "color")
    for ground in ("#ffffff", "#f7f9fc", "#f1f5f9"):
        assert contrast.ratio(link, ground) >= contrast.AA_NORMAL, (link, ground)
    dark = {sel: body for sel, body in split_rules(dark_block(css_text))}
    assert declared(dark["a"], "color") != link          # the dark theme keeps its own
    star = declared(light[".fav-star"], "color")
    for ground in ("#ffffff", "#f8fafc", "#f1f5f9"):
        assert contrast.ratio(star, ground) >= 3.0, (star, ground)


def test_the_jump_to_label_and_home_links_do_not_break_badly(css_text):
    rules = dict(split_rules(css_text))
    assert declared(rules[".section-nav strong"], "white-space") == "nowrap"
    assert declared(rules[".home-card-links.hc-row"], "display") == "flex"
    from cbb.render import render_home
    src = inspect.getsource(render_home)
    assert "</a> ·" not in src and 'class="home-card-links hc-row"' in src


def test_the_320px_nav_rows_lose_their_link_margins(css_text):
    block = re.search(r"@media \(max-width: 340px\) \{(.*?)\n\}", css_text, re.S).group(1)
    rules = dict(split_rules(block))
    assert declared(rules[".sub-nav a"], "margin-right") == "0"


def _wg_vars(css: str, dark: bool) -> dict:
    block = re.search(r"@media \(prefers-color-scheme: dark\)\{(.*?)\n\}", css, re.S).group(1) \
        if dark else css.split("@media")[0]
    return dict(re.findall(r"--(wg-[a-z-]+):(#[0-9a-fA-F]{3,6})", block))


def test_watch_guide_text_on_the_accent_reads_in_both_themes():
    from gordstats import watch_page

    css = watch_page.CSS
    for dark in (False, True):
        v = _wg_vars(css, dark)
        assert contrast.ratio(v["wg-on-acc"], v["wg-acc"]) >= contrast.AA_NORMAL, (dark, v)
    # Nothing paints a fixed white on the accent any more.
    assert not re.search(r"background:var\(--wg-acc\)[^}]*color:#fff", css)
    rules = _rules(css)
    for sel in (".wg-q .aud", ".wg-q .tm .rk", ".wg-q .ch .sp"):
        assert _px(declared(rules[sel], "font-size")) >= 12, sel
    for sel in (".wg-view button", ".wg-bar select"):
        assert _px(declared(rules[sel], "min-height")) >= 40, sel


def test_the_pt_link_is_readable_and_the_source_label_fits():
    from gordstats import matchup_page as mp

    rules = dict(split_rules(mp.PLAY_CSS))
    assert _px(declared(rules[".mu-pt"], "font-size")) >= 12
    assert ".mu-pt::after" in rules
    phone = re.search(r"@media \(max-width:600px\)\{(.*?)\n\}", mp.CSS, re.S).group(1)
    cols = declared(dict(split_rules(phone))[".mu-src"], "grid-template-columns")
    assert int(cols.split("px")[0]) >= 76            # "GORDSTATS" at 11.5px is 71px


def test_waiver_gains_use_the_themed_class():
    from cfb.site import roster as cfb_roster
    from fantasy.site import roster as nfl_roster

    for mod in (cfb_roster, nfl_roster):
        src = inspect.getsource(mod)
        assert "style='color:#15803d'" not in src
        assert "class='rd-c-do rd-gain'" in src


def test_team_dashboard_controls_are_thumb_sized():
    from gordstats import roster_page

    css = roster_page.CARD_CSS
    phone = re.search(r"@media \(max-width:760px\)\{(.*?)\n\}", css, re.S).group(1)
    rules = dict(split_rules(phone))
    assert _px(declared(rules[".rd-pick button"], "min-height")) >= 40
    assert _px(declared(rules[".rd-seg button"], "min-height")) >= 40
    assert declared(rules[".rd-pick select"], "min-width") == "0"


def test_playoff_headers_and_names_on_a_phone():
    from gordstats import playoff_page

    phone = re.search(r"@media \(max-width:600px\)\{(.*?)\n\}", playoff_page.CSS, re.S).group(1)
    rules = dict(split_rules(phone))
    assert _px(declared(rules["table.po-t th"], "font-size")) >= 12
    assert ".po-name a::after" in rules and "table.po-t .po-tn a::after" in rules


# --------------------------------------------------------------------------- #
# In the browser
# --------------------------------------------------------------------------- #

ROWS = "".join(f"<tr><td>Team {i}</td><td>{i}</td><td>{100 - i}</td><td>x</td><td>y</td></tr>"
               for i in range(60))
STICKY = f"""<!doctype html><html><head><meta name=viewport content="width=device-width">
<style>body{{margin:0;font:16px sans-serif}}
.pin-bar{{position:sticky;top:0;height:50px;background:#fff;z-index:20}}
.power-wrap{{overflow-x:auto;border:1px solid #ccc;margin:0 10px}}
table{{border-collapse:collapse;width:800px}}
td,th{{padding:8px;border:1px solid #ccc;background:#fff}}
table.frozen th:first-child,table.frozen td:first-child{{position:sticky;left:0;z-index:1}}
.own{{max-height:300px;overflow:auto}}
.gs-sticky-head{{position:fixed;z-index:19;overflow:hidden!important}}</style></head><body>
<div class=pin-bar>controls</div><p style="height:300px">intro</p>
<div class=power-wrap><table class=frozen><thead><tr><th>Team</th><th>A</th><th>B</th><th>C</th>
<th>D</th></tr></thead><tbody>{ROWS}</tbody></table></div>
<p style="height:200px">gap</p>
<div class=own><table data-sticky-head><thead><tr><th>Own</th><th>A</th></tr></thead>
<tbody>{ROWS}</tbody></table></div>
<div style="height:4000px"></div>
<script>__STICKY__</script></body></html>"""

STRIPS = """<!doctype html><html><head><meta name=viewport content="width=device-width">
<style>body{margin:0}.view-switch,.table-scroll{overflow-x:auto;width:300px;display:flex}
.view-switch b,.table-scroll b{flex:none;display:block}</style></head><body>
<div class=view-switch id=s3><b style="width:303px">wk</b></div>
<div class=view-switch id=s40><b style="width:340px">wk</b></div>
<div class=table-scroll id=t3><b style="width:303px">tbl</b></div>
<script>__SCROLL__</script></body></html>"""


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    from gordstats import matchup_page as mp

    root = tmp_path_factory.mktemp("phone_a")
    (root / "sticky.html").write_text(
        STICKY.replace("__STICKY__", (JS_DIR / "stickyhead.js").read_text()))
    (root / "strips.html").write_text(
        STRIPS.replace("__SCROLL__", (JS_DIR / "table-scroll.js").read_text()))
    (root / "pt.html").write_text(
        "<!doctype html><html><head><meta name=viewport content='width=device-width'>"
        f"<style>body{{margin:20px;font:16px sans-serif}}{mp.PLAY_CSS}</style></head><body>"
        "<div style='height:200px'></div><div style='display:flex;flex-direction:column;"
        "width:170px'><span>J. Gibbs</span><span>RB · DET</span><span class='mu-pav'>"
        "<span class='mu-play fair'>60%</span><a class='mu-pt' id='pt' href='#'>PT&nbsp;&#8599;"
        "</a></span><span>at CAR · Sun 8:20p</span></div></body></html>")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a: None
    server = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()


@pytest.fixture(scope="module")
def browser():
    if CHROME is None:
        pytest.skip("no Chromium to run the JS in")
    import websockets  # noqa: F401
    subprocess.run(["fuser", "-k", f"{CDP}/tcp"], capture_output=True)
    proc = subprocess.Popen([CHROME, "--headless=new", "--no-sandbox", "--disable-gpu",
                             f"--remote-debugging-port={CDP}", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ws_url = None
    for _ in range(60):
        try:
            ws_url = next(t["webSocketDebuggerUrl"] for t in json.load(
                urllib.request.urlopen(f"http://127.0.0.1:{CDP}/json")) if t["type"] == "page")
            break
        except Exception:                                   # noqa: BLE001
            time.sleep(0.5)
    yield ws_url
    proc.terminate()
    reap(proc)


def _run(ws_url: str, url: str, expression: str):
    import websockets

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
            await send("Emulation.setDeviceMetricsOverride",
                       {"width": 390, "height": 800, "deviceScaleFactor": 1, "mobile": True})
            await send("Page.enable")
            await send("Page.navigate", {"url": url})
            # Loaded, and this page rather than the last one: on a busy machine
            # a fixed sleep evaluated against the previous test's page.
            ready = f"location.href==={json.dumps(url)}&&document.readyState==='complete'"
            for _ in range(100):
                r = await send("Runtime.evaluate", {"expression": ready, "returnByValue": True})
                if r.get("result", {}).get("value") is True:
                    break
                await asyncio.sleep(0.1)
            await asyncio.sleep(0.5)
            r = await send("Runtime.evaluate", {"expression": expression, "returnByValue": True,
                                                "awaitPromise": True})
            assert "exceptionDetails" not in r, r["exceptionDetails"]
            return r["result"].get("value")
    return json.loads(asyncio.run(go()))


def test_the_header_copy_keeps_the_frozen_column_after_a_swipe(browser, site):
    """The copy scrolls with the table's scroller rather than sliding as one
    piece, so a position:sticky first cell stays over the frozen column."""
    got = _run(browser, site + "sticky.html", """(async function(){
      function wait(){ return new Promise(function(r){ setTimeout(r,150); }); }
      var t=document.querySelector('.power-wrap > table'), wrap=t.parentElement;
      var boxes=document.querySelectorAll('.gs-sticky-head');
      window.scrollTo(0, t.getBoundingClientRect().top+scrollY+700); await wait();
      wrap.scrollLeft=130; await wait();
      var copy=boxes[0].querySelectorAll('th'), row=t.tBodies[0].rows[20].cells;
      var res={shown:!boxes[0].hidden,
        frozen:[Math.round(copy[0].getBoundingClientRect().left), Math.round(row[0].getBoundingClientRect().left)],
        moving:[Math.round(copy[2].getBoundingClientRect().left), Math.round(row[2].getBoundingClientRect().left)]};
      var own=document.querySelector('.own'), ot=own.querySelector('table');
      window.scrollTo(0, own.getBoundingClientRect().top+scrollY-60); await wait();
      own.scrollTop=900; await wait();
      res.ownShown=!boxes[1].hidden;
      window.scrollTo(0, own.getBoundingClientRect().top+scrollY+200); await wait();
      res.ownShownPast=!boxes[1].hidden;
      return JSON.stringify(res);
    })()""")
    assert got["shown"]
    assert got["frozen"][0] == got["frozen"][1], got     # was -119 against 11
    assert got["moving"][0] == got["moving"][1], got
    # A wrapper with its own vertical scroller keeps its own header in view.
    assert not got["ownShown"] and not got["ownShownPast"]


def test_a_strip_a_few_pixels_over_does_not_fade(browser, site):
    got = _run(browser, site + "strips.html", """(async function(){
      await new Promise(function(r){ setTimeout(r,200); });
      function c(id){ return document.getElementById(id).classList.contains('is-scrollable'); }
      return JSON.stringify({s3:c('s3'), s40:c('s40'), t3:c('t3')});
    })()""")
    assert got == {"s3": False, "s40": True, "t3": True}


def test_the_pt_link_is_a_thumb_target(browser, site):
    got = _run(browser, site + "pt.html", """(function(){
      var a=document.getElementById('pt'), b=a.getBoundingClientRect();
      var cx=b.left+b.width/2, cy=b.top+b.height/2, d, up=0, dn=0, l=0, r=0;
      function hit(x,y){ return document.elementFromPoint(x,y)===a; }
      for(d=0;d<40&&hit(cx,cy-d);d++) up=d;  for(d=0;d<40&&hit(cx,cy+d);d++) dn=d;
      for(d=0;d<60&&hit(cx-d,cy);d++) l=d;   for(d=0;d<60&&hit(cx+d,cy);d++) r=d;
      return JSON.stringify({w:l+r+1, h:up+dn+1, fs:parseFloat(getComputedStyle(a).fontSize)});
    })()""")
    assert got["fs"] >= 12
    assert got["h"] >= 40 and got["w"] >= 44, got      # was a 32x12 target
