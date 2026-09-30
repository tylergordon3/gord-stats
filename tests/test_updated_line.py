"""
"Updated ..." under every generated page's title (frontmatter.updated_line,
docs/assets/js/updated.js): when its data was last read, built in Eastern and
rewritten in the reader's clock with its age.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from conftest import ROOT
from gordstats.frontmatter import add_front_matter, updated_line

ET = ZoneInfo("America/New_York")


def test_every_page_says_when_by_default():
    page = add_front_matter("<p>body</p>", "Power Rankings", "sub")
    body = page.split("---\n", 2)[2]
    assert "<p class='page-sub'>sub</p><p class='page-updated' data-updated='" in body
    assert body.index("page-updated") < body.index("<p>body</p>")


def test_the_data_can_carry_its_own_clock():
    fetched = datetime(2026, 9, 29, 23, 30, tzinfo=ET)
    line = updated_line(fetched)
    assert "data-updated='2026-09-29T23:30-04:00'" in line
    assert "Updated Tue, Sep 29 &middot; 11:30 PM ET" in line
    # A naive time is the Pi's clock, Eastern; an aware one is converted.
    assert updated_line(datetime(2026, 9, 29, 23, 30)) == line
    assert updated_line(datetime(2026, 9, 30, 3, 30, tzinfo=ZoneInfo("UTC"))) == line
    page = add_front_matter("<p>x</p>", "T", updated=fetched)
    assert "2026-09-29T23:30-04:00" in page


def test_pages_with_nothing_to_date_leave_it_off():
    assert "page-updated" not in add_front_matter("<p>x</p>", "Your profile", updated=False)


def test_the_script_is_on_every_page():
    layout = (ROOT / "docs" / "assets" / "js" / "updated.js")
    assert layout.exists()
    assert "/assets/js/updated.js" in (ROOT / "docs" / "_layouts" / "default.html").read_text()


def test_the_rankings_pages_have_one_stamp_each():
    """The CFB rankings' own "Updated" line and the CBB rankings' are the
    standard one now; the CBB's carries T-Rank's download time."""
    cfb = (ROOT / "src" / "cfb" / "site" / "power.py").read_text()
    cbb = (ROOT / "src" / "cbb" / "render" / "render_power.py").read_text()
    assert "power-stamp" not in cfb
    assert "Updated {stamp}" not in cbb and "updated=fetched" in cbb
