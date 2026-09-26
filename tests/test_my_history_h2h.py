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


def test_the_margin_strip_is_back():
    """One dot per game by margin, wins right of zero, playoff games ringed -
    the drawing team_profiles puts under each manager."""
    from gordstats import my_history

    src = code()
    assert "function stripSvg(" in src and "function marginStrip(" in src
    # Defined is not drawn: the profile has to call it, or the strip is dead
    # code that a test about the strip happily passes over.
    assert "marginStrip(games, names, who)" in src.replace("+marginStrip", " marginStrip"), \
        "the strip is never rendered"
    profile = src[src.index("function renderProfile("):]
    profile = profile[:profile.index("\n  }")]
    assert "marginStrip(" in profile, "the strip is not in the manager profile"
    # Two drawings: scaling the wide one down turns every dot into a speck.
    assert "strip-wide" in src and "strip-narrow" in src
    assert "stripSvg(games, names, who, 640" in src
    assert "stripSvg(games, names, who, 340" in src
    # The ring is an outline, not a third fill colour.
    assert "circle.po{stroke" in my_history.CSS
    dark = my_history.CSS[my_history.CSS.index("prefers-color-scheme: dark"):]
    assert "circle.po{stroke" in dark, "the ring vanishes on a dark page"


def test_the_wire_totals_are_by_account():
    """A manager renames his team most years, so totalling on the team name
    listed one person once per name he had used - the opposite of the
    high-level view the page is for."""
    from gordstats import my_waivers

    src = my_waivers.JS
    assert "owners:" in src and "who:" in src, "the account never reaches the summary"
    assert "var id=(t.owners||{})[rid]" in src
    assert "by[id]=by[id]" in src, "still keyed by something other than the account"
    assert "by[name]=by[name]" not in src, "the team-name key is back"
