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
    """A section listed in the bar should have a sub-nav key, and vice versa."""
    bar = {i["section"] for i in NAV["sections"] if i.get("section")}
    subs = set(NAV) - {"sections"}
    assert bar == subs, f"section bar {bar} does not match sub-nav keys {subs}"


def test_retired_draft_pages_are_gone_and_redirected():
    """Pages serves a matching asset before consulting _redirects, so the old
    directories had to be deleted for the 301s to fire at all."""
    for old in ("draft-recap", "draft-report", "draft-dna", "adp"):
        assert not (DOCS / "fantasy" / old).exists(), f"docs/fantasy/{old} still shadows its redirect"
        assert f"/fantasy/{old}/" in REDIRECTS, f"no redirect for /fantasy/{old}/"


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
