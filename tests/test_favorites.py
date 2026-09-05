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


def test_controls_start_hidden():
    """An empty filter can only blank the table, so it stays out of the way."""
    assert favorites.controls().startswith("<div class='fav-controls' hidden>")


def test_layout_loads_the_script():
    """Without this the attributes render and nothing ever reads them."""
    assert "assets/js/favorites.js" in LAYOUT


def test_script_tolerates_unavailable_storage():
    """Private windows throw on localStorage access rather than returning null."""
    assert JS.count("try {") >= 4
    assert "catch" in JS


def test_script_does_not_reorder_rows():
    """Ranked tables: starring a team highlights it, it never moves it.

    appendChild/insertBefore on a row is how that rule gets broken.
    """
    for banned in ("appendChild", "insertBefore", "prepend("):
        assert banned not in JS, f"favorites.js must not reorder rows ({banned})"


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
