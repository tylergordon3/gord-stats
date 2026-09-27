"""Team logos are fetched at the size they are drawn.

ESPN's logo files are 500px squares and every page drew them at 14-56px:
/cfb/power/ moved 1.6 MB for 48 logos. gordstats.logos asks ESPN's image
combiner for a small copy instead; these keep the pages on it.
"""
import re
from pathlib import Path

from gordstats import logos

SRC = Path(__file__).resolve().parents[1] / "src"


def test_logos_come_from_the_resizer():
    assert logos.url("ncaa", 84) == (
        "https://a.espncdn.com/combiner/i?img=/i/teamlogos/ncaa/500/84.png&w=80&h=80")
    tag = logos.img("nfl", "KC", 18, cls="mu-logo")
    assert "teamlogos/nfl/500/kc.png&amp;w=80&amp;h=80" in tag
    assert "width='18' height='18'" in tag and "loading='lazy'" in tag


def test_washington_is_espns_wsh():
    assert "/nfl/500/wsh.png" in logos.url("nfl", "WAS")


def test_bigger_logos_fetch_a_bigger_copy():
    assert "w=160" in logos.url("ncaa", 84, logos.fetch_px(56))
    assert "w=80" in logos.url("ncaa", 84, logos.fetch_px(26))


def test_no_page_asks_espn_for_the_500px_file():
    """The raw /i/teamlogos/ path, outside the combiner, is the full-size file.

    src/cbb is the college-basketball site, which serves its own logos from
    docs/assets/images; the draft-day board (draft_live) is no longer built.
    """
    raw = re.compile(r"espncdn\.com/i/teamlogos")
    offenders = [
        str(p.relative_to(SRC)) for p in SRC.rglob("*.py")
        if p.parts[len(SRC.parts)] != "cbb" and p.name != "draft_live.py"
        and raw.search(p.read_text(errors="ignore"))]
    assert not offenders, f"full-size ESPN logos requested in: {offenders}"
