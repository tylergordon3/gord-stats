"""
What a search engine and a link preview are told about each page: its own
description, one <h1>, a canonical address that does not redirect, and what
happens to a game preview's address once the page has come down.

Found by the 2026-10-02 ops review: 38 pages shared the site's description,
Home and /cbb/ had no <h1>, the six .html pages named their redirecting
address as canonical, and expired previews 404'd. Search sent ~2 visits in two
weeks then; this is groundwork.
"""
import ast
import asyncio
import functools
import http.server
import json
import re
import shutil
import socketserver
import threading
import time
import urllib.request

import pandas as pd
import pytest

from browser_util import launch, reap
from conftest import DOCS, ROOT
from gordstats import frontmatter, preview_meta

SITE_URL = "https://www.gordstats.com"
CHROME = next((p for p in ("/usr/bin/chromium-browser", "/usr/bin/chromium",
                           shutil.which("chromium") or "", shutil.which("chromium-browser") or "")
               if p and shutil.which(p)), None)
CDP = 9620

# Page writers that may still go without a description of their own. The
# draft pages retired with the draft (cfb draft / draft_live; the three fantasy
# sections now render inside Draft Analytics, which has one), and the recaps'
# placeholder before week 1 is final.
NO_DESCRIPTION = {
    ("src/cfb/site/draft.py", "write_page"),
    ("src/cfb/site/draft_live.py", "write_page"),
    ("src/fantasy/site/draft_dna.py", "add_front_matter"),
    ("src/fantasy/site/draft_recap.py", "add_front_matter"),
    ("src/fantasy/site/draft_report.py", "add_front_matter"),
    ("src/cfb/site/recap.py", "add_front_matter"),
    ("src/fantasy/site/recap.py", "add_front_matter"),
}


def _front_matter(text: str) -> str:
    assert text.startswith("---\n"), "no front matter"
    return text[4:text.index("\n---\n", 4)]


# --------------------------------------------------------------------------- #
# Descriptions
# --------------------------------------------------------------------------- #

def test_every_page_writer_gives_its_page_a_description():
    """A page without one shows the site's description in search results and
    link previews - the same line on 38 pages."""
    missing = set()
    for path in sorted((ROOT / "src").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name not in ("add_front_matter", "write_page"):
                continue
            kws = {k.arg for k in node.keywords}
            if "description" not in kws and None not in kws:       # None: a **kwargs pass-through
                missing.add((str(path.relative_to(ROOT)), name))
    assert missing <= NO_DESCRIPTION, sorted(missing - NO_DESCRIPTION)


def test_the_hand_written_pages_have_descriptions():
    pages = ["404.html", "men/index.html", "women/index.html", "men/history.html",
             "women/history.html", "men/conference.html", "women/conference.html",
             "wnba/index.html", *[str(p.relative_to(DOCS)) for p in DOCS.glob("*/predict_*.html")]]
    site = (DOCS / "_config.yml").read_text(encoding="utf-8")
    for page in pages:
        fm = _front_matter((DOCS / page).read_text(encoding="utf-8"))
        m = re.search(r'^description: (".*")$', fm, re.M)
        assert m, page
        text = json.loads(m.group(1))
        assert 100 <= len(text) <= 160, (page, len(text))
        assert text[:40] not in site, page


def test_home_and_the_cbb_landing_say_what_they_hold():
    from cbb.render import render_home as rh
    descs = [rh.HOME_DESCRIPTION, rh.CBB_DESCRIPTION]
    assert all(110 <= len(d) <= 160 for d in descs) and descs[0] != descs[1]
    src = (ROOT / "src" / "cbb" / "render" / "render_home.py").read_text(encoding="utf-8")
    assert "json.dumps(HOME_DESCRIPTION)" in src and "json.dumps(CBB_DESCRIPTION)" in src


def test_a_description_is_written_as_a_json_string():
    page = frontmatter.add_front_matter("<p>x</p>", "T", description='A "quoted": line')
    assert 'description: "A \\"quoted\\": line"' in _front_matter(page)


# --------------------------------------------------------------------------- #
# Headings
# --------------------------------------------------------------------------- #

def test_home_has_one_h1_in_every_season(tmp_path, monkeypatch):
    from datetime import date

    from cbb import paths
    from cbb.render import render_home as rh
    monkeypatch.setattr(paths, "WEB_HOME", tmp_path / "index.html")
    monkeypatch.setattr(rh, "_my_teams", lambda today: "")
    for tipoff in (date(2099, 11, 1), date(2000, 11, 1)):        # before, then in season
        monkeypatch.setattr(rh, "CBB_TIPOFF", tipoff)
        monkeypatch.setattr(rh, "CBB_SEASON_END", date(2099, 12, 1))
        rh.render_home()
        page = (tmp_path / "index.html").read_text(encoding="utf-8")
        assert len(re.findall(r"<h1[\s>]", page)) == 1, tipoff
        assert 'class="home-h1"' in page
        assert re.search(r"^description: \"", _front_matter(page), re.M)
    # Small and muted, so a phone still opens on the cards - but visible.
    assert "font-size:13px" in rh.HOME_H1 and "display:none" not in rh.HOME_H1


def test_the_cbb_landing_has_its_h1(tmp_path, monkeypatch):
    from cbb import paths
    from cbb.render import render_home as rh
    (tmp_path / "_data").mkdir()
    shutil.copy(DOCS / "_data" / "countdowns.yml", tmp_path / "_data" / "countdowns.yml")
    monkeypatch.setattr(paths, "DOCS", tmp_path)
    monkeypatch.setattr(rh, "_top_ten", lambda: "")
    rh.render_cbb_home()
    page = (tmp_path / "cbb" / "index.html").read_text(encoding="utf-8")
    assert page.split("---\n", 2)[2].startswith("<h1>CBB</h1>")
    assert page.count("<h1") == 1 and "description: " in _front_matter(page)


# --------------------------------------------------------------------------- #
# Canonical addresses
# --------------------------------------------------------------------------- #

def test_canonical_goes_in_as_an_absolute_url():
    page = frontmatter.add_front_matter("<p>x</p>", "T", canonical="/men/conference")
    assert f'canonical_url: "{SITE_URL}/men/conference"' in _front_matter(page)
    assert "canonical_url" not in frontmatter.add_front_matter("<p>x</p>", "T")


def test_every_html_page_names_its_clean_address():
    """Cloudflare Pages 308s name.html to /name, so that is the canonical."""
    pages = [p for p in DOCS.rglob("*.html")
             if not any(part.startswith("_") for part in p.relative_to(DOCS).parts)
             and p.name != "index.html" and p.name != "404.html"
             and p.read_text(encoding="utf-8", errors="replace").startswith("---\n")]
    assert len(pages) >= 6
    for p in pages:
        clean = "/" + str(p.relative_to(DOCS))[:-len(".html")]
        fm = _front_matter(p.read_text(encoding="utf-8"))
        assert f'canonical_url: "{SITE_URL}{clean}"' in fm, p


def test_the_generators_of_html_pages_set_the_clean_address():
    conf = (ROOT / "src" / "cbb" / "render" / "render_conferences.py").read_text(encoding="utf-8")
    assert 'canonical=f"/{league}/conference"' in conf
    pred = (ROOT / "src" / "cbb" / "predictions.py").read_text(encoding="utf-8")
    assert 'canonical=f"/men/predict_{date}"' in pred
    assert 'canonical=f"/women/predict_{date}"' in pred


# --------------------------------------------------------------------------- #
# Sitemap and robots
# --------------------------------------------------------------------------- #

def test_the_signed_in_pages_stay_out_and_the_explainers_go_in():
    sitemap = (DOCS / "sitemap.xml").read_text(encoding="utf-8")
    skip = re.search(r'assign skip = "([^"]*)"', sitemap).group(1).split(",")
    assert {"/404.html", "/profile/", "/fantasy/sync/"} <= set(skip)
    for path in ("/how/", "/tweets/", "/changelog/"):
        assert path not in skip
    robots = (DOCS / "robots.txt").read_text(encoding="utf-8")
    assert "Disallow: /how/" not in robots and "Disallow: /tweets/" not in robots


def test_the_nav_does_not_loop_over_every_page():
    """It ran on every page, so the build grew with the square of the page
    count; the plugin works the newest bracket out once."""
    nav = (DOCS / "_includes" / "nav.html").read_text(encoding="utf-8")
    assert "for p in site.pages" not in nav
    assert "site.data.latest_predict.men" in nav
    assert (DOCS / "_plugins" / "latest_predict.rb").exists()


# --------------------------------------------------------------------------- #
# Game previews: the description, and the page outliving the window
# --------------------------------------------------------------------------- #

def _game(state="pre", away=None, home=None, ko="2026-09-26T19:30Z", neutral=False):
    return {"state": state, "ko": ko, "neutral": neutral,
            "away": {"name": "South Carolina", "score": away},
            "home": {"name": "Alabama", "score": home}}


def test_a_preview_describes_the_pick_before_and_the_score_after():
    assert preview_meta.describe(_game()) == (
        "South Carolina at Alabama, Sat, Sep 26: GordStats' pick against the line, "
        "and how the offenses and defenses match up.")
    final = preview_meta.describe(_game("post", 18.0, 49.0))
    assert final.startswith("Alabama 49, South Carolina 18 (Sat, Sep 26): how GordStats'")
    # The away side first on a tie; "vs" on a neutral field; no day if unknown.
    assert preview_meta.describe(_game("post", 20, 20)).startswith("South Carolina 20, Alabama 20")
    assert preview_meta.describe(_game(neutral=True, ko=None)).startswith(
        "South Carolina vs Alabama: GordStats'")
    # Live, or post without a score (cancelled): still the pick.
    assert "pick against the line, and" in preview_meta.describe(_game("in", 7, 3))
    assert "pick against the line, and" in preview_meta.describe(_game("post", None, None))
    for g in (_game(), _game("post", 18.0, 49.0)):
        assert len(preview_meta.describe(g)) <= 160


def test_finished_games_are_this_seasons_played_ones():
    from cfb.site import previews as cfb
    from nfl.site import previews as nfl
    frame = pd.DataFrame([
        {"game_id": "1", "state": "post", "home_score": 21.0, "away_score": 14.0, "detail": "Final"},
        {"game_id": "2", "state": "post", "home_score": 0.0, "away_score": 0.0, "detail": "Canceled"},
        {"game_id": "3", "state": "pre", "home_score": None, "away_score": None, "detail": ""},
        {"game_id": "4", "state": "post", "home_score": 7.0, "away_score": 10.0,
         "detail": "Postponed"}])
    assert cfb.finished(frame) == {"1"}
    assert cfb.finished(frame.iloc[0:0]) == set()
    played = pd.DataFrame({"game_id": ["7", "8"], "played": [True, False]})
    assert nfl.finished(played) == {"7"}


# --------------------------------------------------------------------------- #
# The 404 page, for a preview that has come down
# --------------------------------------------------------------------------- #

def test_the_404_page_knows_a_preview_address():
    page = (DOCS / "404.html").read_text(encoding="utf-8")
    assert r"/^\/(cfb|nfl|cbb)\/game\/\d+\/?$/" in page
    for href in ("/cfb/schedule/", "/nfl/schedule/", "/men/", "/cfb/power/", "/nfl/power/"):
        assert f'"{href}"' in page
    assert "This preview has passed" in page
    assert "style.display" not in page, "reveal with hidden (site-audit-2026-10-02)"


class _NotFound(http.server.SimpleHTTPRequestHandler):
    """Every path is the 404 page, as Cloudflare Pages answers a missing one."""
    body = b""

    def do_GET(self):
        self.send_response(404)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *a):
        pass


def _404_html() -> bytes:
    text = (DOCS / "404.html").read_text(encoding="utf-8").split("---\n", 2)[2]
    text = re.sub(r"\{%-?\s*comment\s*-?%\}.*?\{%-?\s*endcomment\s*-?%\}", "", text, flags=re.S)
    text = text.replace("{{ '/' | relative_url }}", "/")
    assert "{{" not in text and "{%" not in text
    css = "<style>[hidden]{display:none !important}</style>"
    return f"<!doctype html><title>Page Not Found</title>{css}{text}".encode()


async def _visit(ws_url, base, paths):
    import websockets
    out = {}
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
        for path in paths:
            await send("Page.navigate", {"url": base + path})
            await asyncio.sleep(0.6)
            r = await send("Runtime.evaluate", {"returnByValue": True, "expression": """({
              h1: document.querySelector('h1').textContent,
              title: document.title,
              game: !document.getElementById('nf-game').hidden,
              any: !document.getElementById('nf-any').hidden,
              links: [...document.querySelectorAll('#nf-game-links a')].map(a => a.getAttribute('href'))
            })"""})
            out[path] = r["result"]["value"]
    return out


@pytest.mark.skipif(CHROME is None, reason="no Chromium")
def test_a_passed_preview_points_to_the_schedule_not_a_dead_end():
    handler = type("H", (_NotFound,), {"body": _404_html()})
    server = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(handler))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    proc = launch(CHROME, CDP)
    try:
        for _ in range(80):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{CDP}/json"))
                page = next(t for t in tabs if t.get("type") == "page")
                break
            except Exception:                                  # noqa: BLE001 - still starting
                time.sleep(0.25)
        else:
            pytest.fail("Chromium did not come up")
        got = asyncio.run(_visit(page["webSocketDebuggerUrl"], base,
                                 ["/cfb/game/401752123/", "/nfl/game/401872957",
                                  "/cbb/game/12345/", "/cfb/gamez/1/", "/no/such/page"]))
    finally:
        proc.terminate()
        reap(proc)
        server.shutdown()
    cfb = got["/cfb/game/401752123/"]
    assert cfb["h1"] == "This preview has passed" and cfb["game"] and not cfb["any"]
    assert cfb["links"] == ["/cfb/schedule/", "/cfb/predictions/", "/cfb/power/"]
    assert cfb["title"].startswith("This preview has passed")
    assert got["/nfl/game/401872957"]["links"][0] == "/nfl/schedule/"
    assert got["/cbb/game/12345/"]["links"] == ["/men/", "/cbb/watch/", "/cbb/power/"]
    for other in ("/cfb/gamez/1/", "/no/such/page"):
        assert got[other]["h1"] == "404" and got[other]["any"] and not got[other]["game"]
