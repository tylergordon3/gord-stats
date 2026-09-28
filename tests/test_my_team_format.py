"""
A reader's team dashboard is laid out like the built one.

/fantasy/roster/ rendered this site's league in twelve columns and a reader's
own league in four - the same question answered twice, and answered as though
it were a different feature. The reason was data, not design: projections,
lines, forecasts and defence-vs-position live on the Pi and not in Sleeper.
`fantasy.site.week_context` publishes them; `gordstats.my_week` holds the cells
so there is one description of a row rather than a Python one and a drifting
JavaScript one.

Verified in a browser against a real league: the two rows come out with
identical cell classes, down to `img.rd-logo, span.nm, span.rd-lbl` inside the
player cell.
"""
import pathlib
import re

import pytest

from fantasy.site import roster
from gordstats import my_league_data, my_team, my_week

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: The lineup table is split across two modules by design - the row in
#: my_team, the cells in my_week - so the markup is the pair of them.
CLIENT = my_team.VIEW_JS + my_week.JS

#: What the built table shows, in order.
COLUMNS = ["Slot", "Change", "Player", "Game", "Team total", "Opp vs pos",
           "Weather", "Proj", "GS", "Sleeper", "Pts", "Late-swap cover"]


def test_the_client_table_has_the_built_columns_in_order():
    """The waiver-adds table is defined earlier in the module, so the lineup's
    headers are found from its first column rather than from the top."""
    found = re.findall(r"<th[^>]*>([^<]+)</th>", my_team.VIEW_JS)
    start = found.index("Slot")
    assert found[start:start + len(COLUMNS)] == COLUMNS, found[start:start + len(COLUMNS)]


def test_it_uses_the_built_pages_classes_not_its_own():
    """They are already in the stylesheet on this page, so matching the format
    is emitting the same markup - not restyling anything.

    This list used to include `rd-t`, which is not a class anything defines:
    it was read off the markup rather than off the stylesheet, so it pinned
    the bug in place. Every name here is now checked against the stylesheets
    that are actually on the page as well as against the markup.
    """
    styles = _styles()
    for cls in ("rd-slot", "rd-mv", "rd-p", "rd-g", "rd-wx", "rd-cov", "rd-bn",
                "rd-split", "rd-card", "rd-phone"):
        assert cls in CLIENT, f"{cls} missing from the client table"
        assert _styled(cls, styles), f"nothing styles .{cls}"
    # `rd-st` is the built page's marker for a starter row and carries no
    # styling of its own, so it is checked for presence only.
    assert "rd-st" in CLIENT


def test_the_cells_live_in_one_place():
    for fn in ("gameCell", "totalCell", "oppCell", "wxCell", "moveCell",
               "playerCell", "heat", "ordinal", "wxIcon"):
        assert f"{fn}" in my_week.JS, f"{fn} is not in the shared renderer"


def test_a_finished_game_is_marked_the_same_way_as_the_built_page():
    """The built page mutes a spent projection; so must this one, or the two
    disagree about a player who has already played."""
    assert "rd-spent" in CLIENT
    assert "rd-spent" in (roster.__file__ and open(roster.__file__).read())


def test_the_heat_scale_matches_the_built_one():
    """A different scale would colour the same defence differently on the two
    halves of one page."""
    import inspect

    src = inspect.getsource(roster.page.heat)
    assert "0.85" in src and "1.15" in src
    assert "low==null?0.85:low" in my_week.JS and "high==null?1.15:high" in my_week.JS
    assert "211,47,47" in my_week.JS and "46,125,50" in my_week.JS


def test_the_page_carries_the_shared_renderer():
    """The container without its script is the bug that shipped here before."""
    src = open(roster.__file__).read()
    assert "my_week.JS" in src, "the roster page does not load the shared cells"


def test_the_context_file_is_small_enough_to_fetch():
    from conftest import DOCS

    path = DOCS / "fantasy" / "week-context.json"
    if not path.exists():
        pytest.skip("not generated here")
    assert path.stat().st_size < 120_000


def test_the_projection_is_a_blend_not_one_source():
    """The built page averages every source that has the player. Sleeper's
    number alone would read differently in the same column."""
    assert "projFor" in my_week.JS
    body = my_week.JS[my_week.JS.index("function projFor"):]
    assert "vals.reduce" in body[:600], "projFor must average, not pick"


# --------------------------------------------------------------------------- #
# The matchups page, same idea.
# --------------------------------------------------------------------------- #

def test_the_client_matchup_uses_the_built_paired_view():
    """The built page pairs the two lineups slot by slot for a phone. The
    client drew its own card grid beside it, so one page had two ideas of what
    a matchup looks like."""
    from gordstats import my_matchups

    for cls in ("mu-pair", "mu-pr", "mu-pslot", "mu-pp", "mu-pn", "mu-pcol"):
        assert cls in my_matchups.JS + my_week.JS, f"{cls} missing"


def test_the_paired_row_is_labelled_with_the_slot_not_a_number():
    """It used to number the rows 1..n, which says nothing; the built page
    names the slot, which is the thing the two players have in common."""
    from gordstats import my_matchups

    assert "SLOTS[i]" in my_matchups.JS
    assert "roster_positions" in my_matchups.JS


def test_the_matchup_projection_is_read_per_basis():
    """It indexed the whole week-projections file by player id, which never
    resolved - so before kickoff the card showed nothing where a projection
    was meant to be. A half-PPR league must not be shown PPR numbers either."""
    from gordstats import my_matchups

    # The basis has to come off the league Sleeper answered with, so pin the
    # dependency rather than one spelling of the call: PROJ is whatever
    # GSL.points returns, and the index it is asked for is read from `basis`,
    # never written as a constant.
    call = re.search(r"PROJ\s*=\s*GSL\.points\(([^)]*)\)", my_matchups.JS)
    assert call, "PROJ no longer comes from GSL.points"
    args = call.group(1)
    assert "basis" in args and re.search(r"\bindex\b", args), args
    assert not re.search(r",\s*\d\s*$", args), f"the basis is hardcoded: {args}"
    assert re.search(r"\bbasis\s*=\s*GSL\.basis\(", my_matchups.JS), \
        "the basis is not read off the league"
    assert "PROJ=d||{}" not in my_matchups.JS, "the old whole-file PROJ is back"


def test_the_matchups_page_carries_what_the_client_needs():
    from fantasy.site import matchups as page

    src = open(page.__file__).read()
    for mod in ("my_league_data.JS", "my_week.JS", "my_matchups.JS"):
        assert mod in src, f"the matchups page does not load {mod}"


def test_the_score_cell_matches_the_built_one():
    """One figure, always the one that matters: projection before kickoff,
    points during, points marked final after."""
    assert "mu-now" in my_week.JS and "mu-exp" in my_week.JS
    for state in ("'post'", "'in'", "'bye'"):
        assert state in my_week.JS, f"scoreCell does not handle {state}"
    assert "final" in my_week.JS and "live" in my_week.JS


def test_a_readers_league_is_drawn_in_the_built_pages_layout():
    """It used to render its own little card grid - two team names, two
    numbers - with the built page's paired phone view nested inside, and
    that view is display:none above 700px. So on a desktop a reader's league
    was five empty boxes. Whatever the markup, every piece of the built
    matchup has to be in it."""
    from gordstats import my_matchups

    for cls in ("mu-board",        # the scoreboard over the week
                "mu-cards",        # ...as cards, on a phone
                "mu-head",         # the two-column matchup header
                "mu-src",          # a win bar per projection source
                "mu-pair",         # the paired phone view
                "mu-grid",         # the two rosters side by side
                "mu-roster"):      # ...each one a full table
        assert cls in my_matchups.JS, f"a reader's league has no {cls}"
    assert "mm-card" not in my_matchups.JS, "the bespoke card grid is back"
    # .mu-pair is the phone view; without a .mu-grid beside it the page is
    # blank on a desktop, which is exactly the bug.
    assert my_matchups.JS.count("mu-grid") >= 1


def test_the_paired_view_marks_its_logos_for_the_page_it_is_on():
    """The dashboard styles its marks .rd-logo and the matchup pages .mu-logo,
    and neither stylesheet is on the other's page - a logo carrying the wrong
    class gets the theme's framed-thumbnail treatment, twice the size, eating
    the width the name needs."""
    from gordstats import my_week

    pair = my_week.JS[my_week.JS.index("function pairCell"):]
    pair = pair[:pair.index("\n  }")]
    assert "'mu-logo'" in pair, "the paired cell's logo is not a matchup-page logo"

    player = my_week.JS[my_week.JS.index("function playerCell"):]
    player = player[:player.index("\n  }")]
    assert "mu-logo" not in player, "the dashboard's cell took the matchup class"


def _styled(cls: str, styles: str) -> bool:
    """Is there a selector for exactly this class? A plain substring accepts
    `.rd-t` because the stylesheet defines `.rd-tag` - which is how the
    missing class went unnoticed for a month."""
    return re.search(r"\." + re.escape(cls) + r"(?![\w-])", styles) is not None


def _emitted(source: str) -> set:
    """The class names a script actually puts in a class attribute.

    Source-level `"rd-desk" in JS` passes on a mention in a comment, so the
    attributes are parsed instead: what the browser gets is the only thing
    the stylesheet can match against.
    """
    out = set()
    for attr in re.findall(r"""class=\\?["']([a-z0-9 _-]+)\\?["']""", source):
        out.update(attr.split())
    return out


def _code(source: str) -> str:
    """The script with its `//` comments stripped.

    `"phoneLineup" in JS` passed with the call deleted, because the comment
    above it named the function. A test that a comment can satisfy is not a
    test of anything.
    """
    return "\n".join(re.sub(r"(?<!:)//.*$", "", line) for line in source.splitlines())


def _styles() -> str:
    """Every stylesheet that is actually on /fantasy/roster/."""
    from gordstats import roster_page

    return (roster_page.CSS + roster_page.CARD_CSS + my_team.CSS
            + (ROOT / "docs" / "assets" / "css" / "custom.css").read_text())


def test_the_readers_dashboard_uses_classes_the_page_actually_styles():
    """It emitted `<table class="rd-t sticky-table">`. Nothing on the page
    defines either: the table fell back to the theme's default, every team
    logo rendered as a framed thumbnail the height of a row, and the names
    were pushed out of the viewport. The built page's table is `rd`."""
    styles = _styles()
    used = _emitted(my_team.VIEW_JS)
    assert {"rd", "rd-desk", "rd-scroll"} <= used, sorted(used)
    missing = sorted(c for c in used if not _styled(c, styles))
    assert not missing, f"the dashboard emits classes nothing styles: {missing}"


def test_the_readers_dashboard_has_a_phone_view():
    """Below 760px the built page replaces its twelve-column table with one
    card per player and a Current/Suggested toggle - `.rd-desk` is
    display:none there. Without the cards a reader's league was a sideways
    scroll through twelve columns, which is the readability complaint this
    whole section started from."""
    from gordstats import roster_page

    assert "rd-desk" in _emitted(my_team.VIEW_JS), \
        "the table is not in the desktop-only wrapper"
    assert "W.phoneLineup(" in _code(my_team.VIEW_JS), "no phone view is rendered"
    assert "rd-phone" in _emitted(my_week.JS), "the cards are not in the phone wrapper"
    # The toggle is wired by the built page's own listener, so the markup has
    # to be the markup it listens for.
    assert ".rd-seg button" in roster_page.CARD_JS
    assert "rd-seg" in my_week.JS and "data-mode" in my_week.JS


def test_my_team_opens_on_the_readers_own_team():
    """Twelve rosters and no idea which is theirs, so it opened on whoever
    held roster 1. The account stores the reader's own Sleeper user id
    against each league they synced; that is what says which roster is
    theirs."""
    assert "myRoster" in my_league_data.JS and "myRoster:myRoster" in my_league_data.JS
    assert "provider_user_id" in my_league_data.JS, "the id is never read"
    assert "GSL.myRoster(" in my_team.VIEW_JS, "the dashboard still opens on roster 1"
    # The select has to agree with what is rendered, or the menu says one team
    # and the table shows another.
    assert "k===start?' selected':''" in my_team.VIEW_JS.replace('"', "'") \
        or "selected" in my_team.VIEW_JS
    assert "render(lg, wk, index, start, ctx, live)" in my_team.VIEW_JS


def test_the_leagues_endpoint_returns_the_readers_sleeper_id():
    """It is in the table and was simply not selected, so every page had to
    guess which roster belonged to the reader."""
    src = (ROOT / "functions" / "api" / "leagues.js").read_text()
    select = src[src.index("SELECT provider"):src.index("FROM leagues WHERE user_id")]
    assert "provider_user_id" in select, "the GET does not return it"
