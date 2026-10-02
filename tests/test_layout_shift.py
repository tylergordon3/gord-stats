"""Nothing drawn after the first paint pushes the page down.

Cloudflare's Web Analytics (2026-10-02) put layout shift at 0.31 on Fantasy
League Home (over 0.25 is "poor"), 0.13 on Home and 0.14 on Matchups. Every
cause was a block a script drew into a container that had no height until then:
the week strip (432px), the league bar (34px), Home's My teams prompt (32px on
a desktop, more on a phone) and the sign-in invite (~45px, inserted at the top
of every page once /api/me answered). Each now has its room before it draws.
"""
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
LAYOUT = (ROOT / "docs/_layouts/default.html").read_text()
FAV = (ROOT / "docs/assets/js/favorites.js").read_text()


def test_the_league_bar_holds_its_line_until_it_draws():
    from gordstats import my_league
    css = my_league.CSS
    assert ".ml-bar:empty{min-height:34px}" in css
    phone = css[css.index("@media (max-width:560px)"):]
    assert ".ml-bar:empty{min-height:40px}" in phone.split("}\n}")[0] + "}"


def test_the_week_strip_holds_its_height_in_season_and_lets_go_whatever_happens():
    from gordstats import week_strip
    assert "class='ws-wait'" in week_strip.section(date(2026, 10, 4))
    assert "class='ws-wait'" in week_strip.section(date(2027, 1, 20))
    assert "class='ws-wait'" not in week_strip.section(date(2026, 7, 1)), "an offseason gap"
    assert ".ws-wait:empty{min-height:432px}" in week_strip.CSS
    js = week_strip.JS
    # Drawn, offseason, a failed read, an error, no scripts: every way out
    # drops the hold, or the offseason page keeps a 432px hole.
    assert js.count("settle()") >= 5
    assert "if(!host||!window.GSL){ settle(); return; }" in js


def test_my_teams_draws_the_no_stars_prompt_with_the_page():
    """Most readers have starred nothing: their card is the prompt, so the
    page carries it rather than the script putting it in a moment later."""
    from gordstats import my_teams_today
    html = my_teams_today.section(cfb=True, cbb=False)
    host = html[html.index('<div id="mt-host"'):]
    assert host.split(">", 1)[1].startswith('<p class="mt-none">Star teams (&#9734;) on the '
                                            '<a href="/cfb/power/">college football</a> rankings')
    assert "with our pick and the live score." in host
    both = my_teams_today.section(cfb=True, cbb=True)
    assert "college football</a> or <a href=\"/cbb/power/\">college basketball</a>" in both
    assert "with the live score." in my_teams_today.section(cfb=False, cbb=True)


def test_the_invite_is_part_of_the_page_and_leaves_before_it_paints():
    m = re.search(r"\{%- unless page\.url contains '/profile' or content contains \"id='ml-bar'\" %\}"
                  r"(.+?)\{%- endunless %\}", LAYOUT, re.S)
    assert m, "the invite moved out of the layout"
    block = m.group(1)
    assert 'id="gs-invite"' in block and "gs-invite-shut" in block
    # The inline check reads what favorites.js writes, before the first paint.
    assert "localStorage.getItem('gs:acct')" in block and "gs:invite" in block
    assert 'var ACCT_KEY = "gs:acct";' in FAV
    assert "localStorage.setItem(ACCT_KEY" in FAV


def test_favorites_leaves_the_drawn_invite_alone_until_the_account_is_known():
    body = re.search(r"function paintInvite\(\) \{(.+?)\n  \}", FAV, re.S).group(1)
    assert body.lstrip().startswith('var bar = document.getElementById("gs-invite");\n    if (!known) {')
    assert "wireInvite(bar)" in body
    # No API at this address is an answer ("no accounts here"), not a wait.
    assert "r.ok === false ? { configured: false, signedIn: false } : r.json()" in FAV


def test_the_trade_analyzer_holds_a_screen_until_it_has_drawn_or_given_up():
    """Its first line is "Reading the league...", so an :empty hold let go at
    once and the page jumped twice (0.12-0.2)."""
    from gordstats import trade_page
    assert "class='tr tr-wait'" in trade_page.section("/fantasy/trade/")
    assert ".tr-wait{min-height:80vh}" in trade_page.CSS
    js = trade_page.JS
    assert js.count("settle();") >= 3, "drawn, no rosters, failed: each lets go"
    assert "function draw(){\n    settle();" in js


def test_the_profile_account_line_holds_its_row_and_no_scrollbar_shoves_the_page():
    from gordstats import profile_page
    assert "#pf-who{min-height:36px}" in profile_page.CSS
    css = (ROOT / "docs/assets/css/custom.css").read_text()
    assert "scrollbar-gutter: stable" in css
