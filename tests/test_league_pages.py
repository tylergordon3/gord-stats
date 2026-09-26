"""
League Home and Analytics each hold two versions of themselves.

This league's, built on the Pi out of the archive, and the reader's, rendered
in the browser from Sleeper. Only one of them answers "what am I looking at",
so only one is ever on the page - `my_league.takeover` picks before the first
paint, off localStorage rather than off /api/leagues, because a section that
arrives a second late has already been scrolled past.

Analytics used to be eight cards standing between the reader and every page
behind it. Two of the eight were the history and the drafts of the league whose
home page is one tab away.
"""
import pathlib
import re

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
NAV = yaml.safe_load((ROOT / "docs" / "_data" / "nav.yml").read_text())


def _ids(html: str) -> set:
    return set(re.findall(r"id=['\"]([a-z0-9-]+)['\"]", html))


def test_league_home_holds_both_versions_and_shows_one():
    from fantasy.site import homepage

    src = open(homepage.__file__).read()
    assert "lh-mine" in src and "lh-built" in src
    assert 'takeover("lh-mine", "lh-built")' in src
    # The reader's half is hidden in the markup, so a browser with no league
    # never paints it at all.
    assert "id='lh-mine' hidden" in src


def test_analytics_holds_both_versions_and_shows_one():
    from fantasy.site import analytics

    src = open(analytics.__file__).read()
    assert 'takeover("an-mine", "an-built")' in src
    assert "id='an-mine' hidden" in src


def test_the_takeover_runs_before_the_account_answers():
    """Off localStorage, inline, and with no fetch: waiting on /api/leagues
    means painting this league's page and then replacing it."""
    from gordstats import my_league

    js = my_league.takeover("a", "b")
    assert "localStorage.getItem('gsSleeperLeague')" in js
    assert "fetch(" not in js and "addEventListener" not in js
    # Both halves are decided by the one flag, so they can never both show.
    assert "m.hidden=!own" in js and "b.hidden=own" in js


def test_analytics_renders_its_studies_rather_than_linking_them():
    """"The analytics page also feels clunky." It was a grid of cards. The
    four studies are on the page now; what stays a link is a page that
    answers one question well and is too big to inline."""
    from fantasy.site import analytics

    src = open(analytics.__file__).read()
    for fn in ("schedule_section", "transactions_section", "injury_section"):
        assert f"def {fn}" in src, f"{fn} is not rendered here"
    assert "adp.all_time_section()" in src
    # The old hub, and the two cards that moved to League Home.
    assert "hub.cards" not in src, "the card grid is back"
    assert "/fantasy/history/" not in src, "history is on League Home now"
    assert "/fantasy/draft-review/" not in src, "the drafts are on League Home now"


def test_the_moved_pages_are_covered_by_league_home():
    """A page out of the sub-nav needs a chip that lights for it, and it has
    to be the chip whose page carries the content."""
    covers = {i["url"]: (i.get("covers") or "").split() for i in NAV["fantasy"]}
    home = covers["/fantasy/index.html"]
    assert "/fantasy/history/" in home and "/fantasy/draft-review/" in home
    analytics = covers["/fantasy/analytics/"]
    assert "/fantasy/history/" not in analytics
    assert "/fantasy/draft-review/" not in analytics


def test_the_readers_sections_use_the_sites_table():
    """They sit beside built `sticky-table`s on League Home and Analytics now,
    and two table styles on one page read as two different features."""
    from gordstats import my_draft, my_history, my_waivers

    for mod, dead in ((my_history, "hi-t"), (my_draft, "dr-t"), (my_waivers, "wv-t")):
        assert 'class="sticky-table"' in mod.JS or 'sticky-table ' in mod.JS, mod.__name__
        assert f'class="{dead}"' not in mod.JS, f"{dead} is back in {mod.__name__}"
        assert f"table.{dead}" not in mod.CSS, f"{dead} styling is back"


def test_the_draft_board_keeps_its_own_dark_mode():
    """Its dark rules shared a selector with the summary table that became a
    `sticky-table`, and stripping the one took the other with it."""
    from gordstats import my_draft

    dark = my_draft.CSS[my_draft.CSS.index("prefers-color-scheme: dark"):]
    flat = "".join(dark.split())
    assert "table.dr-btd{" in flat, "the board has no dark rules"
    assert "table.dr-bth" in flat
