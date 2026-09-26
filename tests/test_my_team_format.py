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
import re

import pytest

from fantasy.site import roster
from gordstats import my_team, my_week

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
    is emitting the same markup - not restyling anything."""
    for cls in ("rd-t", "rd-slot", "rd-mv", "rd-p", "rd-g", "rd-wx", "rd-cov",
                "rd-st", "rd-bn", "rd-split"):
        assert cls in CLIENT, f"{cls} missing from the client table"


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

    assert "GSL.points(wk, GSL.basis(info).index)" in my_matchups.JS
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
