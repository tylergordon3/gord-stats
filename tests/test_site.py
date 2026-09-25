"""
Structural checks on the generated site.

Covers the navigation failures: links that pointed nowhere, and a layout script
that rewrote them at click time so they only broke in a browser.
"""

import re
from datetime import datetime

import pytest
import yaml

from conftest import DOCS, ROOT

NAV = yaml.safe_load((DOCS / "_data" / "nav.yml").read_text())
LAYOUT = (DOCS / "_layouts" / "default.html").read_text()
REDIRECTS = (DOCS / "_redirects").read_text() if (DOCS / "_redirects").exists() else ""


def _targets():
    """(where it came from, url) for every link in nav.yml."""
    for section, items in NAV.items():
        for item in items:
            if item.get("url"):
                yield section, item["url"]


def _resolves(url: str) -> bool:
    """Does this URL correspond to a file that will exist in the built site?"""
    path = url.split("#")[0].lstrip("/")
    if not path or path.endswith("/"):
        path += "index.html"
    if (DOCS / path).exists():
        return True
    # a redirect rule counts as resolving
    return any(line.split()[0].rstrip("*").rstrip("/") == "/" + url.rstrip("/").lstrip("/")
               for line in REDIRECTS.splitlines() if line and not line.startswith("#"))


@pytest.mark.parametrize("section,url", list(_targets()))
def test_nav_links_point_at_real_pages(section, url):
    assert _resolves(url), f"nav.yml [{section}] -> {url} has no page behind it"


def test_no_script_rewrites_nav_hrefs():
    """The bug: a 'league-aware nav rewrite' prepended /men to every
    root-relative nav href without .no-rewrite, turning /fantasy/adp/ into
    /men/fantasy/adp/. It only fired on click, so fetching the URLs directly
    always returned 200 and hid it."""
    assert "LEAGUE-AWARE NAV REWRITE" not in LAYOUT
    assert not re.search(r"a\.href\s*=\s*[`'\"]\s*/\$\{league\}", LAYOUT), \
        "something in the layout is rewriting nav hrefs at runtime"


def test_every_section_in_the_bar_has_a_landing_page():
    for item in NAV["sections"]:
        assert _resolves(item["url"]), f"section {item['title']} -> {item['url']} is missing"


def test_sub_nav_sections_match_the_bar():
    """A section listed in the bar, or a league under Fantasy, should have a
    sub-nav key, and vice versa."""
    bar = {i["section"] for i in NAV["sections"] if i.get("section")}
    leagues = {lg["pages"] for lg in NAV["fantasy_leagues"]}
    subs = set(NAV) - {"sections", "fantasy_leagues"}
    assert bar | leagues == subs, f"section bar {bar} + leagues {leagues} do not match sub-nav keys {subs}"
    for lg in NAV["fantasy_leagues"]:
        assert _resolves(lg["url"]), f"league {lg['title']} -> {lg['url']} is missing"


def test_retired_draft_pages_are_gone_and_redirected():
    """Pages serves a matching asset before consulting _redirects, so the old
    directories had to be deleted for the 301s to fire at all."""
    for old in ("draft-recap", "draft-report", "draft-dna", "adp"):
        assert not (DOCS / "fantasy" / old).exists(), f"docs/fantasy/{old} still shadows its redirect"
        assert f"/fantasy/{old}/" in REDIRECTS, f"no redirect for /fantasy/{old}/"
    # The CFB scoreboard folded into the schedule page the same way.
    assert not (DOCS / "cfb" / "scoreboard").exists(), "docs/cfb/scoreboard still shadows its redirect"
    assert "/cfb/scoreboard/" in REDIRECTS, "no redirect for /cfb/scoreboard/"


# --------------------------------------------------------------------------- #
# Countdown clocks
# --------------------------------------------------------------------------- #

COUNTDOWNS = yaml.safe_load((DOCS / "_data" / "countdowns.yml").read_text())
_COUNTDOWN_KEY = re.compile(r'include\s+countdown\.html\s+key="([^"]+)"')


def _countdown_uses():
    """(where it was written, key) for every countdown placed on a page.

    The generators are read as well as the pages: docs/index.html is written by
    src/cbb/render/render_home.py and docs/fantasy/index.html by the fantasy
    site build, so a bad key added there would only surface on the next daily
    rebuild.
    """
    for path in sorted(DOCS.rglob("*.html")):
        if "_site" in path.parts:
            continue
        for key in _COUNTDOWN_KEY.findall(path.read_text(encoding="utf-8")):
            yield path.relative_to(ROOT), key
    for path in sorted((ROOT / "src").rglob("*.py")):
        for key in _COUNTDOWN_KEY.findall(path.read_text(encoding="utf-8")):
            yield path.relative_to(ROOT), key


def test_every_countdown_on_a_page_has_data_behind_it():
    """A key with no entry renders nothing at all — the include is silent about
    it, so the clock just quietly stops appearing."""
    missing = [f"{where} -> {key!r}" for where, key in _countdown_uses()
               if key not in COUNTDOWNS]
    assert not missing, ("countdowns.yml has no entry for:\n  " + "\n  ".join(missing))


def test_the_homepage_carries_both_countdowns():
    """They live inside the preview boxes; two clocks on one page is the case
    the old per-page includes could not do, since each hardcoded id="days"."""
    keys = _COUNTDOWN_KEY.findall((DOCS / "index.html").read_text(encoding="utf-8"))
    assert "cbb" in keys and "fantasy" in keys, f"homepage countdowns: {keys}"


@pytest.mark.parametrize("key", sorted(COUNTDOWNS))
def test_countdown_entries_are_complete_and_parseable(key):
    entry = COUNTDOWNS[key]
    for field in ("eyebrow", "title", "target", "expired"):
        assert entry.get(field), f"countdowns.yml [{key}] is missing {field}"
    # Naive on purpose: the browser reads it as the reader's local time, so a
    # trailing Z or an offset would move the clock for everyone but the author.
    datetime.fromisoformat(entry["target"])
    assert not entry["target"].endswith("Z") and "+" not in entry["target"], \
        f"countdowns.yml [{key}] target must be local, not zoned"


def test_the_old_per_page_countdowns_are_gone():
    """Three copies of one clock, two of them hand-written, is how the styles
    drifted apart in the first place."""
    assert not (DOCS / "_includes" / "cbb_countdown.html").exists()
    stale = [p.relative_to(ROOT) for p in DOCS.rglob("*.html")
             if "_site" not in p.parts and "cbb_countdown.html" in p.read_text(encoding="utf-8")]
    assert not stale, f"still including the retired countdown: {stale}"


def test_brand_icons_exist():
    for name in ("icon-32.png", "icon-180.png", "icon-192.png", "icon-512.png"):
        assert (DOCS / "assets" / "images" / "brand" / name).exists(), f"missing {name}"
    assert (DOCS / "favicon.ico").exists()
    assert (DOCS / "site.webmanifest").exists()


def test_lang_attribute_has_no_nested_quotes():
    """It rendered as lang=" en-US" — a double quote inside the Liquid closed
    the attribute early, leaving a leading space in the tag.

    Checked structurally rather than by capturing the value: a naive
    `lang="([^"]*)"` stops at the inner quote and happily matches the broken
    form, which is how an earlier version of this test passed either way.
    """
    m = re.search(r'<html lang=(.*?)>', LAYOUT)
    assert m, "no lang attribute"
    attr = m.group(1)
    assert attr.count('"') == 2, f"nested quotes in the lang attribute: {attr}"


def test_local_assets_are_cache_busted():
    """Cloudflare serves JS and CSS with max-age=14400.

    Without a version in the URL, a reader who visited in the last four hours
    runs the previous build's JavaScript against the current build's HTML. That
    shipped once: the sign-in control was in the markup and invisible on a
    phone that had loaded the site earlier the same day.
    """
    for asset in re.findall(r"'(/assets/(?:js|css)/[^']+)' \| relative_url }}(\?v=\{\{ v \}\})?",
                            LAYOUT):
        path, version = asset
        assert version, f"{path} is served without ?v= and will be cached stale"


# --------------------------------------------------------------------------- #
# Usage tables: a column is hidden by class, so the header and the body have to
# agree about which classes a column carries.
# --------------------------------------------------------------------------- #

USAGE_PAGES = ["fantasy/usage/index.html", "cfb/usage/index.html"]


def _usage_table(path):
    doc = (DOCS / path).read_text()
    head = re.search(r"<thead>(.*?)</thead>", doc, re.S)
    body = re.search(r"<tbody>(.*?)</tbody>", doc, re.S)
    assert head and body, f"{path} has no usage table"
    ths = re.findall(r"<th[^>]*>", head.group(1))
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", body.group(1), re.S)
    return ths, rows


@pytest.mark.parametrize("path", USAGE_PAGES)
def test_usage_rows_have_one_cell_per_column(path):
    ths, rows = _usage_table(path)
    for i, row in enumerate(rows):
        tds = re.findall(r"<td[^>]*>", row)
        assert len(tds) == len(ths), f"{path} row {i}: {len(tds)} cells for {len(ths)} columns"


@pytest.mark.parametrize("path", USAGE_PAGES)
def test_usage_headers_hide_with_their_column(path):
    """Every class that hides a cell - the position views and the two the phone
    layout drops - has to be on the header too.

    A header without its column's class stays visible when the cells go, and
    every column right of it reads under the wrong heading. That shipped once:
    on a phone the owner cell was hidden and its "Fantasy" header was not, so
    games sat under Fantasy and carries under G.
    """
    ths, rows = _usage_table(path)
    hiders = re.compile(r"\b(v-overall|v-rb|v-wr|v-te|us-own|us-lead)\b")

    def marks(tag):
        cls = re.search(r"class=[\"']([^\"']*)[\"']", tag)
        return set(hiders.findall(cls.group(1))) if cls else set()

    head_marks = [marks(t) for t in ths]
    for i, row in enumerate(rows):
        for col, td in enumerate(re.findall(r"<td[^>]*>", row)):
            assert marks(td) == head_marks[col], (
                f"{path} row {i} column {col}: cell has {marks(td) or '{}'}, "
                f"header has {head_marks[col] or '{}'}")


# --------------------------------------------------------------------------- #
# The two fantasy leagues are navigated the same way
# --------------------------------------------------------------------------- #

def test_both_fantasy_leagues_offer_the_same_tabs():
    """The league switcher keeps the reader on their tab by matching `key`
    across the two lists, so a key on one side with no twin on the other
    silently drops them back at a league home."""
    nfl = [i.get("key") for i in NAV["fantasy"]]
    cfb = [i.get("key") for i in NAV["cfb_fantasy"]]
    assert None not in nfl and None not in cfb, "every fantasy tab needs a key"
    assert nfl == cfb, f"tab keys differ: NFL {nfl} vs CFB {cfb}"


def test_pages_behind_a_hub_are_still_reachable():
    """Moving a page out of the sub-nav and behind Analytics must not strand
    it: every url a chip `covers` has to exist, and be linked from the hub."""
    for section in ("fantasy", "cfb_fantasy"):
        for item in NAV[section]:
            if not item.get("covers"):
                continue
            hub = (DOCS / item["url"].strip("/") / "index.html")
            assert hub.exists(), f"{section}: hub page {item['url']} is missing"
            # Reachable from the hub, or from a page the hub links to: the
            # draft sub-pages hang off Draft Analytics rather than sitting on
            # the hub itself, and the chip stays lit for them all the same.
            reach = hub.read_text()
            for linked in set(re.findall(r'href=[\'"](/[^\'"#?]*)', reach)):
                child = DOCS / linked.strip("/") / "index.html"
                if child.exists():
                    reach += child.read_text()
            for url in item["covers"].split():
                assert _resolves(url), f"{section}: {url} is covered but does not exist"
                assert url in reach, (
                    f"{section}: {url} is covered by {item['url']} but nothing "
                    "on or one hop from the hub links to it")


# --------------------------------------------------------------------------- #
# "Show my league" on the usage page
# --------------------------------------------------------------------------- #

MY_LEAGUE = (ROOT / "src" / "gordstats" / "my_league.py").read_text()


def test_the_league_override_works_without_an_account():
    """Local first, like the stars: a league id typed on the page is kept in
    this browser and works signed out. The account only carries it to another
    device, and must never become the gate."""
    assert "localStorage" in MY_LEAGUE
    # The account lookup is a later refinement, not a precondition: it is
    # fetched after the saved league has already been drawn.
    assert MY_LEAGUE.index("var have=saved();") < MY_LEAGUE.index("'/api/leagues'")


def test_asking_for_the_sites_own_league_sticks():
    """Otherwise the account lookup re-applies the synced league a moment after
    the reader asked for this one, and the button looks broken."""
    assert "save({site:true})" in MY_LEAGUE
    assert "if(have&&have.site) return;" in MY_LEAGUE


def test_only_ownership_is_re_pointed():
    """Snaps, carries and targets are properties of the NFL, not of anyone's
    league. If this ever starts rewriting them, the page is lying."""
    for cell in ("snap_share", "car_share", "tgt_share", "data-v"):
        assert cell not in MY_LEAGUE, f"the override touches {cell}"


def test_usage_rows_carry_the_player_id_the_override_needs():
    doc = (DOCS / "fantasy" / "usage" / "index.html").read_text()
    body = re.search(r"<tbody>(.*?)</tbody>", doc, re.S).group(1)
    rows = re.findall(r"<tr[^>]*>", body)
    assert rows, "no usage rows"
    assert all("data-pid=" in r for r in rows), "a row has no Sleeper id to match on"
