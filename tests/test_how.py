"""
"How this works" (gordstats.how, docs/assets/js/gs-how.js): an explanation
for each ranking, prediction and number, on a page of its own at
/how/<topic>/, opened in a dialog over the page by a small chip beside the
thing it explains.

What has to hold: every topic is complete, short, plain, American English
and literal to Jekyll, and every link in it goes somewhere; the chip is a
real link (it is the whole feature without the script), named for a screen
reader and 40px for a thumb; generate() writes every page with a
description; and in Chromium a tap opens the dialog with the fetched
explanation - once - Tab stays inside, Esc / the close button / the dimmed
page close it, focus comes back to the chip, the address does not change,
and nothing on the page behind moves or scrolls. On a phone it is a sheet
from the bottom of the screen.
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
from html.parser import HTMLParser

import pytest

from browser_util import launch, reap
from conftest import CSS, DOCS, ROOT, split_rules
from gordstats import how, js_assets

CHROME = next((p for p in ("/usr/bin/chromium-browser", "/usr/bin/chromium",
                           "/usr/bin/google-chrome") if shutil.which(p)), None)
CDP = 9580

TOPIC_IDS = [t.id for t in how.TOPICS]

# The spellings the site used to carry (memory: american-english). Word
# starts only, so "practiced" or "realized" are not caught by "practise"/"realise".
BRITISH = re.compile(
    r"\b(favour\w*|colour\w*|defence\w*|offence\w*|grey\w*|centre\w*|theatre|"
    r"behaviour\w*|honour\w*|neighbour\w*|rumour\w*|labour\w*|licence|"
    r"\w+ise[ds]?|\w+ising|\w+isation\w*|analys(e|ed|es|ing)|modell\w+|labell\w+|"
    r"cancell\w+|travell\w+|programme\w*|judgement\w*|whilst|amongst|towards|"
    r"practis\w+|fixture\w*|maths)\b", re.I)
# -ise words that are American too.
BRITISH_OK = {"rise", "rises", "raise", "raised", "raises", "wise", "otherwise", "likewise",
              "precise", "precisely", "concise", "exercise", "exercises", "advertise",
              "advise", "advised", "revise", "revised", "surprise", "surprised", "surprises",
              "expertise", "noise", "praise", "promise", "promised", "promises", "premise",
              "compromise", "comprise", "comprises", "disguise", "enterprise", "franchise",
              "merchandise", "supervise", "televise", "televised", "despise", "demise",
              "devise", "paradise", "poise", "porpoise", "treatise", "chastise", "improvise",
              "apprise", "arise", "arises", "anywise", "clockwise", "counterclockwise",
              "stepwise", "pairwise", "wise", "guise", "cruise", "bruise", "bruised",
              "excise", "incise", "franchises"}


def _words(html: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9%$.'-]+", re.sub(r"<[^>]+>", " ", html))


class _Tags(HTMLParser):
    """Open/close balance and every href, of an HTML fragment."""
    VOID = {"br", "img", "hr", "input", "meta", "link", "wbr", "source"}

    def __init__(self):
        super().__init__()
        self.stack, self.errors, self.hrefs = [], [], []

    def handle_starttag(self, tag, attrs):
        for k, v in attrs:
            if k == "href":
                self.hrefs.append(v)
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"</{tag}> closes {self.stack[-1:] or 'nothing'}")
        else:
            self.stack.pop()


def _parse(html: str) -> _Tags:
    p = _Tags()
    p.feed(html)
    p.close()
    return p


# --------------------------------------------------------------------------- #
# The registry
# --------------------------------------------------------------------------- #

def test_the_registry_is_complete_and_its_ids_are_unique():
    assert len(how.TOPICS) >= 15
    assert len(set(TOPIC_IDS)) == len(TOPIC_IDS)
    assert set(how.BY_ID) == set(TOPIC_IDS)
    for want in ("cfb-rankings", "cfb-predictions", "nfl-rankings", "nfl-predictions",
                 "bets-record", "playoff-odds", "game-previews", "watch-guide", "team-stats",
                 "fantasy-power", "fantasy-projections", "injuries", "trade-analyzer", "usage",
                 "schedule-strength", "recaps", "cbb-rankings", "cbb-predictions"):
        assert want in how.BY_ID, f"no explainer for {want}"


@pytest.mark.parametrize("topic", TOPIC_IDS)
def test_every_topic_has_each_part(topic):
    t = how.BY_ID[topic]
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", t.id)
    assert t.group in how.GROUPS
    for part in ("name", "title", "summary", "lede", "updates"):
        assert getattr(t, part).strip(), f"{topic} has no {part}"
    assert t.how and all(s.strip() for s in t.how)
    assert t.limits and all(s.strip() for s in t.limits)
    # The title goes into YAML front matter as a plain scalar and into the
    # <h1> unescaped (frontmatter.add_front_matter).
    assert not re.search(r"[:#&<>\"'{}\[\]]", t.title), t.title
    assert len(t.summary) <= 160, "the summary is a search result's line"
    for r in t.related:
        assert r in how.BY_ID and r != topic


@pytest.mark.parametrize("topic", TOPIC_IDS)
def test_every_explainer_is_short_and_plain(topic):
    """A newcomer reads it in a minute: about 120-220 words, the extra for
    the curious kept short too, and the lede one plain sentence (the owner's
    ask, 2026-10-02)."""
    t = how.BY_ID[topic]
    main = _words(" ".join([t.lede, *t.how, *t.limits, t.updates]))
    assert 110 <= len(main) <= 225, f"{topic}: {len(main)} words"
    assert len(_words(t.curious)) <= 90, f"{topic}: 'for the curious' runs long"
    assert len(_words(t.lede)) <= 40, f"{topic}: the lede is more than a sentence"
    body = how.article(topic)
    assert "Monte Carlo" not in body or "times (a Monte Carlo" in body


@pytest.mark.parametrize("topic", TOPIC_IDS)
def test_every_body_is_american_english_and_literal_to_jekyll(topic):
    t = how.BY_ID[topic]
    text = " ".join([t.name, t.title, t.summary, re.sub(r"<[^>]+>", " ", how.article(topic))])
    british = [w for w in (m.group(0) for m in BRITISH.finditer(text))
               if w.lower() not in BRITISH_OK]
    assert not british, f"{topic}: British spelling {british}"
    body = how.article(topic)
    assert "{{" not in body and "{%" not in body, "a Liquid tag in an explainer"
    assert "<script" not in body.lower()
    # Proper nouns and times kept in their case (str.capitalize() once
    # lowercased "AM and PM Eastern" in every "when it updates" line).
    assert not re.search(r"\beastern\b|\b\d (am|pm)\b|\bam and pm\b", text), topic
    # Dates, if any, in US order: "Sat, Oct 3", never "Sat 3 Oct".
    assert not re.search(r"\b\d{1,2} (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b", text)


@pytest.mark.parametrize("topic", TOPIC_IDS)
def test_every_body_is_well_formed(topic):
    p = _parse(how.article(topic))
    assert not p.errors and not p.stack, (topic, p.errors, p.stack)


def _site_paths() -> set:
    """Pages the site has: the nav's, and any path a generator writes or
    links (named as a literal in src/)."""
    nav = (DOCS / "_data" / "nav.yml").read_text()
    out = set(re.findall(r"url:\s*(/\S*)", nav))
    return out


def _known(path: str) -> bool:
    if (DOCS / path.strip("/") / "index.html").exists() and path != "/":
        return True
    if path.startswith(how.BASE):
        rest = path[len(how.BASE):].strip("/")
        return rest == "" or rest in how.BY_ID
    if path in _site_paths():
        return True
    for src in (ROOT / "src").rglob("*.py"):
        if src.name == "how.py":
            continue
        if f'"{path}' in src.read_text() or f"'{path}" in src.read_text():
            return True
    return False


@pytest.mark.parametrize("topic", TOPIC_IDS)
def test_every_link_goes_somewhere(topic):
    t = how.BY_ID[topic]
    hrefs = _parse(how.article(topic)).hrefs + [h for _l, h in t.pages]
    for href in hrefs:
        if href.startswith("http"):
            assert href.startswith("https://"), href
            continue
        assert href.startswith("/") and href.endswith("/"), href
        assert _known(href.split("#")[0]), f"{topic}: {href} is not a page here"


# --------------------------------------------------------------------------- #
# The chip
# --------------------------------------------------------------------------- #

def test_the_button_is_a_real_link_named_for_a_screen_reader():
    html = how.button("cfb-rankings")
    assert html.startswith("<a class='gs-how' href='/how/cfb-rankings/'")
    assert "data-how='cfb-rankings'" in html
    assert "aria-haspopup='dialog'" in html
    t = how.BY_ID["cfb-rankings"]
    assert f"aria-label='How this works: {t.name}'" in html
    assert ">How this works</span></a>" in html
    assert f"data-how-title='{t.title}'" in html


def test_the_button_escapes_its_label_and_knows_its_topics():
    html = how.button("cfb-rankings", label="How <b>'this'</b> works & more")
    assert "<b>" not in html and "&lt;b&gt;" in html and "&#x27;this&#x27;" in html
    with pytest.raises(KeyError):
        how.button("no-such-topic")
    note = how.section_note("fantasy-power")
    assert note.startswith("<p class='gs-how-note'><a class='gs-how'")


def _rule(css: str, selector: str) -> str:
    """The declarations of `selector`'s top-level rule (not a media block's)."""
    for sel, decl in split_rules(css):
        if sel.strip() == selector:
            return decl
    raise AssertionError(f"no rule for {selector}")


def test_the_chip_is_a_thumbs_width_and_readable(css_text):
    chip = _rule(css_text, ".gs-how")
    assert re.search(r"min-height:\s*40px", chip) and re.search(r"min-width:\s*40px", chip)
    size = float(re.search(r"font-size:\s*([\d.]+)px", chip).group(1))
    assert size >= 12
    # Dark mode has its own chip, not the light one on a dark page.
    assert re.search(r"prefers-color-scheme:\s*dark\)\s*\{[^@]*\.gs-how-chip\s*\{", css_text, re.S)


def test_the_tag_loads_the_file_by_its_hashed_url_and_the_twin_is_the_file():
    assert "'/assets/js/gs-how.js' | fingerprint | relative_url" in how.JS_TAG
    assert " defer " in how.JS_TAG and "GSHow" not in how.JS_TAG
    assert js_assets.source("gs-how.js") in how.JS
    assert how.LIQUID_TAG == ('<script defer src="{{ \'/assets/js/gs-how.js\' | fingerprint | '
                              'relative_url }}"></script>')
    js = js_assets.source("gs-how.js")
    assert "{{" not in js and "{%" not in js
    assert "history.pushState" not in js and "location.hash" not in js


def test_the_daily_run_builds_the_pages_with_the_changelog():
    src = (ROOT / "src" / "gordstats" / "daily.py").read_text()
    block = src[src.index("changelog.generate()"):src.index("tweets_page.generate()")]
    assert "how.generate()" in block


# --------------------------------------------------------------------------- #
# The pages
# --------------------------------------------------------------------------- #

def _front(text: str) -> dict:
    head = text.split("---\n")[1]
    return dict(line.split(": ", 1) for line in head.strip().splitlines())


def test_generate_writes_every_page_with_a_description(tmp_path, monkeypatch):
    monkeypatch.setattr(how, "OUT", tmp_path / "how")
    how.generate()
    for t in how.TOPICS:
        page = (tmp_path / "how" / t.id / "index.html").read_text()
        fm = _front(page)
        assert fm["layout"] == "default" and fm["title"] == t.title
        assert json.loads(fm["description"]) == t.summary
        assert "page-updated" not in page, "an explainer has nothing that goes out of date"
        assert "<article class='how-article'" in page and f"data-title='{t.title}'" in page
        assert "{% raw %}" in page, "the body is literal to Jekyll"
        assert "class='gs-share'" in page
    index = (tmp_path / "how" / "index.html").read_text()
    assert json.loads(_front(index)["description"]) == how.INDEX_DESCRIPTION
    for t in how.TOPICS:
        assert f"href='/how/{t.id}/'" in index


def test_the_built_pages_are_not_committed():
    out = subprocess.run(["git", "check-ignore", "docs/how/index.html",
                          "docs/how/cfb-rankings/index.html"],
                         cwd=ROOT, capture_output=True, text=True)
    assert out.stdout.split() == ["docs/how/index.html", "docs/how/cfb-rankings/index.html"]


# --------------------------------------------------------------------------- #
# In the browser
# --------------------------------------------------------------------------- #

TOPIC = "cfb-rankings"
FILLER = "".join(f"<p class='fill'>Row {i}: filler text that makes the page scroll.</p>"
                 for i in range(40))
HOST = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Host</title><link rel="stylesheet" href="/custom.css"></head><body>
<header id="site-header" style="height:56px">GordStats</header>
<main id="main_content">__FILLER__<h2 id="hd">Power ratings __BUTTON__</h2>__FILLER__
<p id="last">The end.</p></main>
<script>__JS__</script></body></html>"""
EXPLAINER = """<!doctype html><html><head><meta charset="utf-8"><title>__TITLE__</title>
</head><body><main>__BODY__</main></body></html>"""


def _strip_jekyll(page: str) -> str:
    body = page.split("---\n", 2)[2]
    return re.sub(r"\{%-?\s*(?:end)?raw\s*-?%\}", "", body)


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    root = tmp_path_factory.mktemp("how")
    out = root / "how"
    orig = how.OUT
    how.OUT = out
    try:
        how.generate()
    finally:
        how.OUT = orig
    for t in how.TOPICS:
        page = out / t.id / "index.html"
        page.write_text(EXPLAINER.replace("__TITLE__", t.title)
                        .replace("__BODY__", _strip_jekyll(page.read_text())))
    (root / "custom.css").write_text(CSS.read_text())
    (root / "index.html").write_text(
        HOST.replace("__BUTTON__", how.button(TOPIC)).replace("__FILLER__", FILLER)
        .replace("__JS__", js_assets.source("gs-how.js")))
    handler = functools.partial(_Quiet, directory=str(root))
    server = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class _Page:
    def __init__(self, ws):
        self.ws, self.n = ws, 0

    async def send(self, method, params=None):
        self.n += 1
        me = self.n
        await self.ws.send(json.dumps({"id": me, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=30))
            if msg.get("id") == me:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg.get("result", {})

    async def js(self, expression):
        r = await self.send("Runtime.evaluate", {"expression": expression,
                                                 "returnByValue": True, "awaitPromise": True})
        if "exceptionDetails" in r:
            raise RuntimeError(r["exceptionDetails"])
        return r["result"].get("value")

    async def until(self, expression, timeout=5.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if await self.js(expression):
                return True
            await asyncio.sleep(0.05)
        return False

    async def tap(self, x, y):
        for kind in ("mousePressed", "mouseReleased"):
            await self.send("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y,
                                                         "button": "left", "clickCount": 1})

    async def key(self, key, code, keycode, shift=False):
        mods = 8 if shift else 0
        for kind in ("rawKeyDown", "keyUp"):
            await self.send("Input.dispatchKeyEvent", {
                "type": kind, "key": key, "code": code, "modifiers": mods,
                "windowsVirtualKeyCode": keycode, "nativeVirtualKeyCode": keycode})


SETUP = """(function(){
  window.__shifts=[];
  new PerformanceObserver(function(l){ l.getEntries().forEach(function(e){
    window.__shifts.push({value:e.value, t:Math.round(e.startTime), input:e.hadRecentInput,
      nodes:(e.sources||[]).map(function(x){ return x.node ? (x.node.id||x.node.className||x.node.nodeName) : '?'; })}); }); }).observe({type:'layout-shift', buffered:true});
  window.__fetches=0;
  var f=window.fetch; window.fetch=function(){ window.__fetches++; return f.apply(this, arguments); };
  // Scrolled partway, the chip on screen: the page must stay put.
  window.scrollTo(0, document.getElementById('hd').offsetTop - 200);
  return true;
})()"""
# Where the page's things are, on the screen and in the document.
PLACES = """({scroll: window.scrollY,
  hd: document.getElementById('hd').getBoundingClientRect().toJSON(),
  last: document.getElementById('last').getBoundingClientRect().toJSON(),
  fill: document.querySelector('.fill').getBoundingClientRect().toJSON(),
  href: location.href, hist: history.length, cw: document.documentElement.clientWidth})"""
CHIP = ("(function(){var r=document.querySelector('.gs-how').getBoundingClientRect();"
        "return [r.left+r.width/2, r.top+r.height/2, r.width, r.height];})()")
OPEN = "(function(){var d=document.querySelector('dialog.gs-how-dlg');return !!(d&&d.open);})()"
LOADED = ("(function(){var d=document.querySelector('dialog.gs-how-dlg');"
          "return !!(d&&d.open&&d.querySelector('.gs-how-body article.how-article'));})()")


async def _scenario(ws_url, site, width, height, mobile):
    import websockets
    async with websockets.connect(ws_url, max_size=None) as ws:
        page = _Page(ws)
        await page.send("Page.enable")
        await page.send("Emulation.setDeviceMetricsOverride", {
            "width": width, "height": height, "deviceScaleFactor": 1, "mobile": mobile})
        await page.send("Page.navigate", {"url": site})
        assert await page.until("document.readyState==='complete' && !!window.GSHow")
        await page.js(SETUP)
        await asyncio.sleep(0.3)
        before = await page.js(PLACES)
        got_t0 = await page.js("Math.round(performance.now())")
        x, y, w, h = await page.js(CHIP)
        got = {"chip": [w, h], "before": before, "t0": got_t0}

        await page.tap(x, y)
        got["opened"] = await page.until(LOADED)
        await asyncio.sleep(0.4)                  # past the opening slide
        got["during"] = await page.js(PLACES)
        got["dialog"] = await page.js("""(function(){
          var d=document.querySelector('dialog.gs-how-dlg'), r=d.getBoundingClientRect();
          return {title: d.querySelector('.gs-how-title').textContent,
                  text: d.querySelector('.gs-how-body').textContent,
                  rect: r.toJSON(), vh: window.innerHeight, vw: window.innerWidth,
                  labelled: d.getAttribute('aria-labelledby'),
                  focus_inside: d.contains(document.activeElement),
                  locked: document.documentElement.classList.contains('gs-how-lock'),
                  page: d.querySelector('.gs-how-page').getAttribute('href')};
        })()""")
        # Tab and Shift+Tab, a dozen times each, never leave the dialog.
        inside = True
        for shift in (False, True):
            for _ in range(12):
                await page.key("Tab", "Tab", 9, shift)
                inside &= await page.js(
                    "document.querySelector('dialog.gs-how-dlg').contains(document.activeElement)")
        got["tab_stays"] = inside
        # A wheel over the dialog does not scroll the page behind it.
        await page.send("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": 5,
                                                     "y": height // 2, "deltaX": 0, "deltaY": 400})
        await asyncio.sleep(0.3)
        got["wheel_scroll"] = await page.js("window.scrollY")

        await page.key("Escape", "Escape", 27)
        got["esc_closed"] = await page.until("!(" + OPEN + ")")
        # The dialog's close event, which lets the page go, follows a task later.
        got["unlocked"] = await page.until(
            "!document.documentElement.classList.contains('gs-how-lock')", timeout=1.0)
        got["after"] = await page.js(PLACES)
        got["focus_back"] = await page.js("document.activeElement===document.querySelector('.gs-how')")

        # Again: shown from what was fetched the first time.
        await page.tap(x, y)
        got["reopened"] = await page.until(LOADED, timeout=1.0)
        got["fetches"] = await page.js("window.__fetches")
        if mobile:
            await page.js("document.querySelector('.gs-how-x').click()")
        else:
            await page.tap(4, 4)                 # the dimmed page around the dialog
        got["second_closed"] = (await page.until("!(" + OPEN + ")") and await page.until(
            "!document.documentElement.classList.contains('gs-how-lock')", timeout=1.0))
        got["focus_back_2"] = await page.js(
            "document.activeElement===document.querySelector('.gs-how')")
        got["shifts"] = await page.js("window.__shifts")
        got["final"] = await page.js(PLACES)
        return got


@pytest.fixture(scope="module")
def runs(site):
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
        return {"desktop": asyncio.run(_scenario(ws_url, site, 1280, 800, False)),
                "phone": asyncio.run(_scenario(ws_url, site, 390, 844, True))}
    finally:
        proc.terminate()
        reap(proc)


needs_chrome = pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")


@needs_chrome
@pytest.mark.parametrize("view", ["desktop", "phone"])
def test_a_tap_opens_the_explanation_in_a_dialog(runs, view):
    got = runs[view]
    t = how.BY_ID[TOPIC]
    assert got["chip"][1] >= 40 and got["chip"][0] >= 40, "the chip is a thumb's size"
    assert got["opened"], "the dialog did not show the fetched explanation"
    d = got["dialog"]
    assert d["title"] == t.title and d["labelled"] == "gs-how-title"
    assert re.sub(r"<[^>]+>", "", t.lede)[:40] in d["text"]
    assert d["focus_inside"] and d["locked"]
    assert d["page"] == f"/how/{TOPIC}/"
    assert got["tab_stays"], "Tab left the dialog"


@needs_chrome
@pytest.mark.parametrize("view", ["desktop", "phone"])
def test_esc_closes_it_focus_comes_back_and_it_is_fetched_once(runs, view):
    got = runs[view]
    assert got["esc_closed"] and got["focus_back"] and got["unlocked"]
    assert got["reopened"], "the second tap fetched again or did not open"
    assert got["fetches"] == 1
    assert got["second_closed"] and got["focus_back_2"]


@needs_chrome
@pytest.mark.parametrize("view", ["desktop", "phone"])
def test_nothing_behind_it_moves_scrolls_or_changes_address(runs, view):
    got = runs[view]
    b = got["before"]
    assert b["scroll"] > 300
    for state in ("during", "after", "final"):
        # Everything but the root's clientWidth, which drops its scrollbar
        # while locked even though the gutter is kept.
        assert {k: v for k, v in got[state].items() if k != "cw"} == \
            {k: v for k, v in b.items() if k != "cw"}, f"the page moved ({state})"
    assert got["after"]["cw"] == b["cw"]
    assert got["wheel_scroll"] == b["scroll"], "the page behind scrolled"
    assert sum(e["value"] for e in got["shifts"]) == 0, f"layout shifts {got['shifts']} (tap at {got['t0']})"


@needs_chrome
def test_on_a_desktop_it_is_centered_and_on_a_phone_a_sheet_from_the_bottom(runs):
    d = runs["desktop"]["dialog"]
    r = d["rect"]
    # Centered in the page's width: a classic scrollbar's gutter is kept, so
    # it sits half a gutter left of the window's middle.
    gutter = d["vw"] - runs["desktop"]["before"]["cw"]
    assert abs((r["left"] + r["right"]) / 2 - (d["vw"] - gutter) / 2) <= 1
    assert abs((r["top"] + r["bottom"]) / 2 - d["vh"] / 2) <= 1
    assert r["width"] <= 560
    p = runs["phone"]["dialog"]
    r = p["rect"]
    assert r["left"] == 0 and r["width"] == p["vw"]
    assert abs(r["bottom"] - p["vh"]) <= 1, "the sheet does not sit on the bottom edge"
    assert abs(r["height"] - p["vh"] * 0.88) <= 1


def test_a_heading_with_a_chip_keeps_its_title_centered_and_clear_of_the_rule():
    """The owner's screenshot (2026-10-02): centered as a group with the chip,
    a heading's title sat left of every heading without one, and the pill -
    taller than the letters - sat on the theme's dotted rule. Measured after
    the fix: titles 0px off center on a desktop, 4-15px above the rule."""
    css = CSS.read_text()
    pad = re.search(r":is\(h1, h2, h3\):has\(> \.gs-how\) \{\s*padding-bottom: (\d+)px;", css)
    assert pad and int(pad.group(1)) >= 16, "the pill reaches the dotted rule"
    grid = css[css.index("@media (min-width: 641px) {\n  :is(h1, h2, h3):has(> .gs-how)"):]
    grid = grid[:grid.index("\n}\n")]
    assert "grid-template-columns: 1fr auto 1fr" in grid, "equal outer columns center the title"
    assert ':not(.home-card-head h2)' in grid, "Home's card heads are left-aligned rows"
    assert 'content: ""' in grid and "justify-self: start" in grid
