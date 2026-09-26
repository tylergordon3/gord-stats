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


def test_the_dark_table_body_is_dark():
    """`.sticky-table` used to give its cells a light slate in dark mode. The
    reasoning held for a pandas table whose cells mostly carry a heatmap
    colour - the slate was only the fallback - but a table with no styler came
    out light on a dark screen, whole, which is how League Home was reported.
    """
    from conftest import ROOT

    css = (ROOT / "docs" / "assets" / "css" / "custom.css").read_text()
    dark = css[css.index("@media (prefers-color-scheme: dark)"):]
    body = dark[dark.index(".sticky-table td {"):]
    body = body[:body.index("}")]
    assert "background: #16203a" in body, body
    assert "color: #dde5ef" in body, body


def test_every_styler_that_paints_a_light_cell_states_its_own_ink():
    """The blocker for the rule above. A styler that sets only a background
    inherits the table's text colour, which is now light - so a pale green
    record cell would have had light text on it.
    """
    from fantasy.site import styles

    assert styles.ON_LIGHT.startswith("color:"), styles.ON_LIGHT
    for fn, arg in ((styles._record_color, "3-1"),
                    (styles._record_color, "1-3"),
                    (styles._record_color, "2-2")):
        out = fn(arg)
        assert "background-color" in out and "color:" in out.replace("background-color", ""), out

    import pandas as pd
    roto = styles.highlight_roto(pd.Series(["5-1", "3-3", "1-5"]))
    for cell in roto:
        if "background-color" in cell:
            assert styles.ON_LIGHT in cell, cell

    # The CBB homepage highlight paints a pale green row the same way.
    from conftest import ROOT
    home = (ROOT / "src" / "cbb" / "render" / "render_home.py").read_text()
    for line in home.splitlines():
        if "background:#e8f7e8" in line:
            assert "color:#0f172a" in line, line


def test_the_grid_header_leaves_its_colours_to_the_theme():
    """pandas emits these as `#T_xxx th`, an ID rule that outranks custom.css,
    so a colour here is one colour for both themes - a light header over what
    is now a dark body."""
    from fantasy.site import styles

    props = dict(styles.GRID_TH["props"])
    assert "background-color" not in props, props
    assert "color" not in props, props


def test_rank_movement_is_a_class_not_an_inline_colour():
    """Those cells have no fill of their own, so they sit on the table's own
    background - white by day, navy at night. `color: black` inline was about
    to become invisible."""
    from cbb import html_util
    from conftest import ROOT

    assert not hasattr(html_util, "_color_arrow"), "the inline colour is back"
    assert [html_util._arrow_class(v) for v in ("NR", "-", 5, -3, 0)] == \
        ["rk-flat", "rk-flat", "rk-up", "rk-down", "rk-flat"]

    css = (ROOT / "docs" / "assets" / "css" / "custom.css").read_text()
    assert ".rk-up { color: #15803d; }" in css, "no light-mode colour"
    dark = css[css.index("@media (prefers-color-scheme: dark)"):]
    assert ".rk-up { color: #6ee7b7; }" in dark, "no dark-mode colour"
    assert ".rk-down" in dark and ".rk-flat" in dark
    # gordstats.rankmoves owns `.mv-*` for the small arrow spans it puts
    # inside a cell; these tint a whole cell and must not collide.
    from gordstats import rankmoves
    assert ".mv-up{" in rankmoves.CSS and "rk-up" not in rankmoves.CSS


def test_the_scoped_override_is_gone():
    """It was the workaround for the shared rule; the shared rule is fixed, so
    two descriptions of one dark table would only drift."""
    from conftest import ROOT

    assert not (ROOT / "src" / "gordstats" / "tables.py").exists()
    for mod in ("my_history", "my_draft", "my_waivers", "my_power"):
        src = (ROOT / "src" / "gordstats" / f"{mod}.py").read_text()
        assert "dark_rows" not in src, mod


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
