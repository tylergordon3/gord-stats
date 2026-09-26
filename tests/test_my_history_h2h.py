"""
Head-to-head for a reader's league: seasons, both books, and who your rival is.

The league home used to carry a head-to-head grid; it was replaced by the
team-profile block on 2026-09-13, and that block is this league's archive, so
a reader who picked their own league saw neither. This is the same idea built
from Sleeper: one game log, and three controls over it.

The log is the part worth guarding. Playoff games are the winners bracket's own
pairings looked up in the matchup feed, not "every game in a playoff week" -
otherwise a consolation game counts as a playoff meeting and the nemesis is
wrong.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]


def js():
    from gordstats import my_history
    return my_history.JS


def code():
    """The script with its `//` comments stripped - a comment naming a thing
    is not the thing."""
    return "\n".join(re.sub(r"(?<!:)//.*$", "", line) for line in js().splitlines())


def test_the_game_log_keeps_the_season_and_the_book():
    """Without both, there is nothing to move through and nothing to split."""
    src = code()
    assert "function gameLog(" in src
    assert "kind:wk.kind" in src.replace(" ", "")
    assert "season:wk.season.season" in src.replace(" ", "")
    # The old counter kept a winner tally and no games at all.
    assert "function headToHead(" not in src, "the old tally is back"


def test_a_playoff_game_is_a_bracket_game():
    """Placement games are not meetings anybody remembers, and the same two
    numbers the built league excludes are excluded here."""
    src = code()
    assert "var PLACEMENT={3:1, 5:1}" in src
    from fantasy.league import head_to_head
    assert head_to_head.PLACEMENT_GAMES == {3, 5}, \
        "the built rule moved; the browser's copy has not"
    # The week a bracket round lands in: start + r - 1, as _fetch_playoffs does.
    assert "(s.playoff_start||15)+(g.r||1)-1" in src


def test_rivals_follow_the_built_rule():
    """`team_profiles.rivals`: most meetings with the closest average margin
    breaking ties, and a nemesis needs enough games to mean anything."""
    src = code()
    assert "var MIN_SPLIT=3" in src
    from fantasy.site import team_profiles
    assert team_profiles.MIN_SPLIT_GAMES == 3, "the built threshold moved"
    assert "b.games-a.games" in src and "Math.abs(a.margin)-Math.abs(b.margin)" in src
    assert "nem.pct<0.5" in src and "fav.pct>0.5" in src


def test_the_three_controls_are_there():
    src = code()
    for control in ("hi-season", "hi-kind", "hi-who"):
        assert control in src, f"no {control} control"
    for kind in ('data-kind="regular"', 'data-kind="playoff"', 'data-kind="all"'):
        assert kind in src, kind
    # All three redraw the same two things off the one log, so moving through
    # seasons costs no further requests.
    assert src.count("draw();") >= 4


def test_it_opens_on_the_readers_own_manager():
    """Twelve managers and no reason to open on whoever sorts first."""
    src = code()
    assert "GSL.mine(have.id).uid" in src
    assert "ids.indexOf(String(MINE))>=0?String(MINE):ids[0]" in src


def test_the_grid_says_which_book_it_is_showing():
    """Reading a playoff grid as a regular-season one is a silent error."""
    src = code()
    assert "hi-legend" in src
    assert "Winners-bracket elimination games only" in src
