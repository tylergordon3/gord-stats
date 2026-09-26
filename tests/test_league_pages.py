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


def test_the_readers_tables_have_a_dark_body():
    """`.sticky-table` in dark mode gives its cells a light slate, because the
    built tables are pandas Stylers whose cells mostly carry a heatmap colour
    and the slate is only what the styler left alone. These sections have no
    styler, so every cell fell through to it and a whole page came out light
    on a dark screen.

    The shared rule cannot simply change: `styles.style_win_loss` and its
    neighbours set a light background per cell and rely on inheriting that
    dark text.
    """
    from gordstats import my_draft, my_history, my_power, my_waivers, tables

    for mod, sel in ((my_history, ".hi"), (my_draft, ".dr"),
                     (my_waivers, ".wv"), (my_power, ".mp")):
        out = mod.section()
        assert tables.dark_rows(sel) in out, f"{mod.__name__} has no dark body"
    css = tables.dark_rows(".hi")
    assert "prefers-color-scheme: dark" in css
    assert ".hi table.sticky-table td{background:#16203a" in css
    # Scoped, or it would reach the built tables on the same page.
    assert "@media (prefers-color-scheme: dark){.hi " in css


def test_the_shared_slate_rule_is_left_alone():
    """Changing it globally would put light text on the pale green cells
    `style_win_loss` paints, on several other pages."""
    from conftest import ROOT

    css = (ROOT / "docs" / "assets" / "css" / "custom.css").read_text()
    assert ".sticky-table td {\n    background: #cbd5e1;" in css, \
        "the shared dark rule moved; re-check the scoped override"
    styles = (ROOT / "src" / "fantasy" / "site" / "styles.py").read_text()
    assert 'background-color: #c8e6c9"' in styles, \
        "style_win_loss changed; the reason for scoping may be gone"


def test_the_league_picker_is_styled():
    """It had no rule at all, so it rendered as the operating system's own
    dropdown - a white box on a dark page, beside controls that are all
    rounded slate."""
    from gordstats import my_league

    css = my_league.CSS
    # The base rule, not the dark-mode one - checking the whole stylesheet for
    # `.ml-bar select{` passes on the dark override alone, which leaves the
    # control unstyled for everybody in light mode.
    base = css[:css.index("@media (prefers-color-scheme: dark)")]
    assert ".ml-bar select{" in base, "the picker is unstyled"
    assert "border-radius:8px" in base[base.index(".ml-bar select{"):]
    assert "appearance:none" in base, "the platform arrow stays dark on a dark control"
    dark = css[css.index("prefers-color-scheme: dark"):]
    assert ".ml-bar select{background-color:#16203a" in dark
    assert ".ml-bar select option{" in dark, "the open list is drawn by the platform"


def test_the_college_matchups_mute_a_finished_player_too():
    """The classes are styled once in gordstats.matchup_page; the college page
    renders its own rows and has to mark them."""
    from cfb.site import matchups

    src = open(matchups.__file__).read()
    assert '" done" if state == "post"' in src, "finished players are not marked"
    # One helper feeds both the wide table and the paired phone view.
    assert src.count("_live_attrs(") >= 3
    from gordstats import matchup_page
    assert "table.mu-roster tr.done td{" in matchup_page.CSS
    assert ".mu-pr .mu-pp.done{" in matchup_page.CSS
