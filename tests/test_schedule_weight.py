"""
The schedule page carries one week, not fifteen.

Every week used to be rendered into the page and all but one hidden with
`display:none`: 4.2 MB and 125,000 DOM nodes to show about 70 games. A phone
parses and holds all of that whatever it ends up painting, and this is the page
the site is most often read on at a tailgate. The rest are fetched on the first
click instead.

Measured on a 4x-throttled phone viewport: 124,902 nodes and 2,710 ms to
DOMContentLoaded became 11,557 and 899 ms.
"""
import re

import pytest

from conftest import DOCS, needs_built_site

PAGE = DOCS / "cfb" / "schedule" / "index.html"

pytestmark = needs_built_site


@pytest.fixture(scope="module")
def page() -> str:
    if not PAGE.exists():
        pytest.skip("the schedule page has not been built here")
    return PAGE.read_text(encoding="utf-8")


def test_only_one_week_has_rows_in_it(page):
    """The whole point. A second week of markup means the lazy load broke and
    the page quietly went back to carrying the season."""
    views = re.findall(r'<div id="wk-view-(\d+)"[^>]*>(.*?)(?=<div id="wk-view-|\Z)',
                       page, re.S)
    assert views, "no week views on the page at all"
    with_rows = [w for w, html in views if 'class="g"' in html]
    assert len(with_rows) == 1, (
        f"{len(with_rows)} weeks have rows in the page; only the current one should")


def test_every_other_week_says_where_to_fetch_it(page):
    views = re.findall(r'<div id="wk-view-(\d+)"([^>]*)>', page)
    lazy = [w for w, attrs in views if "data-src" in attrs]
    assert len(lazy) == len(views) - 1, "every week but the current one is fetched"
    for week, attrs in views:
        if "data-src" in attrs:
            assert f"week-{week}" in attrs, f"week {week} points at the wrong file"
            assert ".html'" not in attrs, (
                "ask for the bare path: Cloudflare Pages 308s /x.html to /x, "
                "and a redirect is a round trip per week")


def test_the_fragments_exist_beside_the_page(page):
    """A data-src with nothing behind it is a week that will not open."""
    for week in re.findall(r"data-src='/cfb/schedule/week-(\d+)'", page):
        assert (PAGE.parent / f"week-{week}.html").exists(), f"week {week} is missing"


def test_a_fragment_is_markup_not_a_page(page):
    """These are injected with innerHTML, so front matter or a layout would
    render as text in the middle of the table."""
    first = next(PAGE.parent.glob("week-*.html"))
    body = first.read_text(encoding="utf-8")
    assert not body.lstrip().startswith("---"), f"{first.name} has front matter"
    assert "<html" not in body.lower() and "{%" not in body


def test_the_page_is_a_fraction_of_what_it_was(page):
    """It was 4.2 MB. Anything near that means the weeks are back."""
    assert len(page) < 1_200_000, f"{len(page):,} chars - the season may be back in it"


def test_late_rows_get_the_current_sort_and_the_readers_favourites(page):
    """Rows injected after boot have been through neither. Missing either is
    invisible until someone notices their filter or their stars do nothing."""
    assert "layout(view)" in page, "an injected week must be sorted and filtered"
    assert "GSFavorites.repaint" in page, "an injected week must be re-starred"


def test_a_failed_fetch_is_recoverable(page):
    """Stadium wifi drops requests. A week that fails must say so and be
    clickable again, not sit blank for ever."""
    assert "could not be loaded" in page
    assert "setAttribute('data-src'" in page, "a failure must leave the week retryable"


def test_browsing_the_season_does_not_rebuild_the_old_page(page):
    """Lazy loading alone only defers the cost: a reader working through the
    weeks would arrive back at 125,000 nodes. Three fetched weeks are kept,
    measured at 21,220 nodes after visiting all fifteen."""
    assert "KEEP_WEEKS" in page
    assert "shownOrder" in page and "function evict()" in page


def test_an_evicted_week_can_come_back(page):
    """Dropping the rows without remembering where they came from is a week
    that never loads again."""
    assert "data-was" in page, "an evicted week must remember its source"
    assert "v.setAttribute('data-src',v.getAttribute('data-was'))" in page


def test_the_week_in_the_page_is_never_evicted(page):
    """It was rendered server-side and has no fragment to fetch, so dropping
    it would empty the tab for good. It has no data-was, which is what keeps
    it - and the week being read is skipped besides."""
    assert "if(old===current) continue;" in page
    assert "if(!v||!v.getAttribute('data-was')) continue;" in page
