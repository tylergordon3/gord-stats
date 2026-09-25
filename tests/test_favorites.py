"""
Team favourites: the key format, the markup, and the wiring that carries them.

A favourite is stored in the reader's browser under the key this module emits,
so the key is the compatibility surface: change how a section names a team and
every star in that section silently stops matching. These tests pin the format
and the three pages that opt in.
"""

import re

import pytest

from conftest import DOCS
from gordstats import favorites

LAYOUT = (DOCS / "_layouts" / "default.html").read_text()
JS = (DOCS / "assets" / "js" / "favorites.js").read_text()


def test_key_carries_its_sport():
    """Two sections numbering their teams the same way must not collide."""
    assert favorites.team_key("cfb", 333) != favorites.team_key("cbb-men", 333)
    assert favorites.team_key("cfb", 333) == "cfb:333"


def test_name_key_is_slugified():
    """Punctuation and case in a school name can't reach the stored key."""
    assert favorites.name_key("cbb-men", "Michigan St.") == "cbb-men:michigan-st"
    assert (favorites.name_key("cbb-women", "Saint Joseph's")
            == favorites.name_key("cbb-women", "saint josephs"))


@pytest.mark.parametrize("sport", favorites.SPORTS)
def test_every_declared_sport_builds_a_key(sport):
    assert favorites.team_key(sport, "1").startswith(f"{sport}:")


def test_unknown_sport_raises():
    """A typo must fail the build, not render a star that can never match."""
    with pytest.raises(ValueError):
        favorites.team_key("nfl", "1")


def test_empty_team_id_raises():
    with pytest.raises(ValueError):
        favorites.team_key("cfb", "  ")


def test_markup_escapes_the_team_name():
    """A name with an apostrophe must not break out of the title attribute."""
    html = favorites.star("cbb-men", "st-johns", "St. John's")
    assert "St. John&#x27;s" in html
    assert "John's" not in html


def test_row_attr_and_star_agree_on_the_key():
    """The row and its button have to name the same team or nothing lights up."""
    attr = favorites.row_attr("cfb", 333)
    star = favorites.star("cfb", 333, "Georgia")
    key = re.search(r'data-fav="([^"]+)"', attr).group(1)
    assert f"data-fav-for='{key}'" in star


def test_name_helpers_agree_with_the_key_helpers():
    assert favorites.name_attr("cbb-men", "Duke") == favorites.row_attr("cbb-men", "duke")
    assert favorites.name_star("cbb-men", "Duke") == favorites.star("cbb-men", "duke", "Duke")


def test_filter_starts_hidden_but_the_hint_does_not():
    """An empty filter can only blank the table, so it waits for a favourite.

    The hint is the opposite: it is the only thing telling a reader the stars
    do anything, so it ships visible.
    """
    html = favorites.controls()
    assert "<div class='fav-controls'>" in html
    assert "class='fav-filter' aria-pressed='false' hidden" in html
    # The hint's own tag closes immediately, carrying no hidden attribute
    # (aria-hidden on the decorative glyph inside it does not count).
    assert "<span class='fav-hint'>" in html


def test_stars_are_never_invisible_at_rest():
    """The regression that shipped: `.fav-star { opacity: 0 }`.

    It hid the star until its row was hovered, so on a normal desktop browser
    the feature had no visible entry point at all, and the `@media (hover:none)`
    fallback meant it still looked fine in a headless screenshot. A star may be
    quiet; it may not be absent.
    """
    css = (DOCS / "assets" / "css" / "custom.css").read_text()
    block = css.split(".fav-star {")[1].split("}")[0]
    assert "opacity: 0" not in block
    assert "@media (hover: none)" not in css


def test_layout_loads_the_script():
    """Without this the attributes render and nothing ever reads them."""
    assert "assets/js/favorites.js" in LAYOUT


def test_script_tolerates_unavailable_storage():
    """Private windows throw on localStorage access rather than returning null."""
    assert JS.count("try {") >= 4
    assert "catch" in JS


def test_script_does_not_reorder_rows():
    """Ranked tables: starring a team highlights it, it never moves it.

    appendChild/insertBefore is how that rule gets broken, so the DOM-moving
    calls are banned everywhere except the two functions that build controls
    out of fresh elements and touch no row: `paintAccount` and `paintInvite`,
    which sit together for that reason. Excluding them by position keeps the
    rule precise - a move added anywhere else still fails, which a blanket ban
    would have stopped being able to say once the controls built themselves.
    """
    body = JS
    start = body.index("function paintAccount(")
    end = body.index("/* ---------- events ---------- */")
    outside = body[:start] + body[end:]
    for banned in ("appendChild", "insertBefore", "prepend("):
        assert banned not in outside, (
            f"favorites.js must not move rows ({banned} outside the builders)")


# Every module that marks table *rows* must also emit the scoped row CSS.
# Marking a row without it is the bug that shipped on the schedule page: the
# class was applied to twenty-three rows and nothing styled any of them, so a
# reader with favourites saw no difference at all. The predictions page is not
# here because it marks <article> cards, which custom.css styles directly.
ROW_MARKING_MODULES = [
    ("src/cfb/site/power.py", "table.cfb-power"),
    ("src/cfb/site/teams.py", "table.tm"),
    ("src/cbb/render/render_power.py", "table.cbb-power"),
    ("src/cfb/site/schedule.py", "table.cfb-sched"),
]


@pytest.mark.parametrize("module,selector", ROW_MARKING_MODULES)
def test_a_page_that_marks_rows_also_styles_them(module, selector):
    from conftest import ROOT
    src = (ROOT / module).read_text()
    assert "favorites.table_css(" in src, (
        f"{module} marks rows but never calls table_css - the highlight "
        "would be invisible")
    assert selector in src, f"{module} styles a table it does not render"


@pytest.mark.parametrize("module,sport", [
    ("src/cfb/site/power.py", "cfb"),
    ("src/cfb/site/teams.py", "cfb"),
    ("src/cbb/render/render_power.py", "cbb-men"),
])
def test_opted_in_pages_emit_rows_stars_and_a_filter(module, sport):
    """Each wired page needs all three, or the feature is half-present on it."""
    from conftest import ROOT
    src = (ROOT / module).read_text()
    assert "favorites" in src, f"{module} does not import the helper"
    assert f"'{sport}'" in src or f'"{sport}"' in src
    assert "_attr(" in src or "row_attr(" in src, f"{module} has no data-fav rows"
    assert "star(" in src, f"{module} has no star buttons"
    assert "favorites.controls()" in src, f"{module} has no filter control"


def test_account_menu_links_are_separated():
    """Two inline anchors in the menu read "Your profileSign out".

    They are built as siblings with no text between them, so the only thing
    keeping them apart is the stylesheet. A regression here is invisible to
    every other test and perfectly visible to a reader.
    """
    css = (DOCS / "assets" / "css" / "custom.css").read_text()
    rule = re.search(r"a\.acct-out\s*\{[^}]*\}", css)
    assert rule and "display: block" in rule.group(0)


def test_the_signed_out_invite_is_dismissible_and_stays_dismissed():
    """A banner that comes back after it is closed is an advert."""
    assert 'id = "gs-invite"' in JS
    assert "gs:invite" in JS
    # It is written on dismiss and read before the banner is built.
    assert re.search(r'setItem\(INVITE_KEY, "off"\)', JS)
    assert re.search(r'getItem\(INVITE_KEY\) === "off"', JS)


def test_the_invite_only_shows_to_a_signed_out_reader():
    """Signed in, or on a deploy with no accounts at all, there is nothing to
    offer - and the profile page makes the same offer in more room."""
    body = re.search(r"function paintInvite\(\) \{(.+?)\n  \}", JS, re.S)
    assert body, "paintInvite is gone"
    wanted = body.group(1)
    assert "account.configured" in wanted
    assert "!account.signedIn" in wanted
    assert "/profile" in wanted


def test_the_invite_is_repainted_when_the_account_is_known():
    """/api/me answers after the first paint, so a banner built only on load
    would never appear for the reader it is for."""
    assert re.search(r"paintAccount\(\);\s*\n\s*paintInvite\(\);", JS)
