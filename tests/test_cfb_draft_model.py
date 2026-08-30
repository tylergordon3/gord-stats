"""
The college draft model: projections, replacement level, and the live board.

Every test here is a bug that happened while this was being written, or an
invariant the board is unusable without.
"""

import json
import re

import numpy as np
import pytest

from cfb import players, projections, schools, yahoo
from cfb.site import draft_live

from conftest import ROOT


# --------------------------------------------------------------------------- #
# The points curve
# --------------------------------------------------------------------------- #

def test_curve_never_rises_with_rank():
    """A points curve that crosses itself makes WR30 worth more than WR20.

    Averaging two seasons at each rank can do exactly that where one season's
    tail is noisier than the other's, which is what the running minimum in
    _smooth exists to stop.
    """
    for pos, curve in projections.points_curve().items():
        assert np.all(np.diff(curve) <= 1e-9), f"{pos} curve rises with rank"


def test_lookup_past_the_curve_keeps_falling_and_stays_positive():
    """Clamping the tail made the 400th player worth exactly what the 100th was.

    A board is 480 deep and a position's curve is not, so ranks past its end are
    routine; a flier has to be worth less than the last real player.
    """
    curve = np.array([100.0, 80.0, 60.0, 40.0, 20.0])
    beyond = projections._lookup(curve, np.array([5.0, 6.0, 7.0, 40.0]))
    assert beyond[0] == pytest.approx(20.0)
    assert beyond[1] < beyond[0]
    assert np.all(beyond >= 0.0), "extrapolation went below zero points"


def test_projection_is_flatter_than_the_curve_it_reads_from():
    """The whole reason projections integrate over finishes rather than reading
    the curve at a rank: the player ranked first can only fall, so his expected
    season has to sit below the curve's first value, and the last-ranked
    player's above his."""
    curve = projections.points_curve()["RB"]
    est = projections.expected_points(curve, [1, 5, 20])
    assert est["proj"].iloc[0] < curve[0]
    assert est["proj"].iloc[0] > curve[4], "flattened past the point of meaning"
    assert list(est["proj"]) == sorted(est["proj"], reverse=True)


def test_floor_and_ceiling_bracket_the_projection():
    curve = projections.points_curve()["WR"]
    est = projections.expected_points(curve, [1, 10, 30, 60])
    assert (est["floor"] <= est["proj"]).all()
    assert (est["proj"] <= est["ceiling"]).all()


# --------------------------------------------------------------------------- #
# Replacement level
# --------------------------------------------------------------------------- #

def test_replacement_follows_this_league_not_a_generic_one():
    """Two starting quarterbacks is the single fact this league turns on.

    Replacement has to land near the 20th quarterback, not the 10th; getting
    this wrong halves the position's value and the board stops recommending
    them at all.
    """
    league = yahoo.league()
    board = projections.value_board()
    levels = projections.replacement_levels(board, league)

    qbs = board[board["pos"] == "QB"].sort_values("proj", ascending=False)
    starters = projections.starter_demand(league)["dedicated"]["QB"]
    assert starters == 20, "league settings changed; this test's premise has not"
    assert levels["QB"] == pytest.approx(qbs["proj"].iloc[starters], rel=1e-6)


def test_flex_lifts_replacement_at_the_positions_it_can_hold():
    """The flex slots are handed out one at a time to whichever position has the
    best player left, so they raise RB/WR replacement and leave QB alone."""
    league = yahoo.league()
    board = projections.value_board()
    demand = projections.starter_demand(league)
    levels = projections.replacement_levels(board, league)

    for pos in projections.FLEX_POSITIONS:
        pool = board[board["pos"] == pos].sort_values("proj", ascending=False)
        dedicated = demand["dedicated"][pos]
        assert levels[pos] <= pool["proj"].iloc[dedicated] + 1e-6, (
            f"{pos} replacement ignored the flex")


# --------------------------------------------------------------------------- #
# Scoring, and the two stats Yahoo gives the same name
# --------------------------------------------------------------------------- #

def test_offensive_and_defensive_interceptions_do_not_collide():
    """Yahoo calls both the quarterback's interception and the defense's "Int",
    and they have opposite signs. The offensive lookup takes the first, the
    defensive one the last; reading either the wrong way silently reprices the
    whole quarterback board."""
    league = yahoo.league()
    assert players.modifiers(league)["pass_int"] < 0
    assert projections._def_modifiers(league)["Int"] > 0


def test_defense_scores_more_for_allowing_less():
    """A defense's projection is built from the game model's predicted opponent
    score, integrated over Yahoo's points-allowed brackets - so it has to fall
    as the predicted score rises, without a bracket boundary reversing it."""
    league = yahoo.league()
    mods = projections._def_modifiers(league)
    allowed = np.arange(5.0, 45.0, 2.0)
    value = projections._points_allowed_value(allowed, mods)
    assert np.all(np.diff(value) < 0), "points-allowed value is not monotone"


# --------------------------------------------------------------------------- #
# The board the page ships
# --------------------------------------------------------------------------- #

def test_team_offence_units_are_off_the_board():
    """Yahoo ranks team offences and this league cannot start one. Leaving them
    in does not just add unusable rows: every rank below them reads a few picks
    cheaper than it is."""
    board = projections.value_board()
    assert "OFF" not in set(board["pos"])
    assert set(board["pos"]) <= set(projections.POSITIONS)


def test_every_board_school_resolves_to_a_real_team():
    """The three feeds spell schools three ways. An unmapped one silently loses
    its players' schedule, their offence and, for a defense, their projection."""
    board = projections.value_board()
    assert board["school"].notna().all(), (
        f"unmapped: {sorted(set(board.loc[board['school'].isna(), 'team_full']))}")
    ids = schools.espn_ids()
    assert set(board["school"]) <= set(ids)


def test_defenses_are_priced_and_ranked():
    board = projections.value_board()
    defenses = board[board["pos"] == "DEF"]
    assert len(defenses) > 20
    assert defenses["proj"].notna().all()
    assert defenses["proj"].max() > defenses["proj"].min() + 20


# --------------------------------------------------------------------------- #
# The page and its script have to agree about the payload
# --------------------------------------------------------------------------- #

def test_field_order_matches_the_indices_the_script_reads():
    """The board ships as bare arrays to keep the page small, so the column
    order is a contract between Python and the JavaScript that reads it.
    Inserting a field in one place and not the other mis-prices every row
    without erroring anywhere."""
    source = (ROOT / "src" / "cfb" / "site" / "draft_live.py").read_text()
    block = re.search(r"var NAME = 0,(.*?);", source, re.S).group(1)
    declared = dict(re.findall(r"(\w+)\s*=\s*(\d+)", "NAME = 0," + block))
    names = {"NAME": "player", "POS": "pos", "TEAM": "team", "SCHOOL": "school",
             "BYE": "bye", "ADP": "adp", "PCTD": "pct_drafted", "ADPSD": "adp_sd",
             "RANK": "rank", "POSRK": "pos_rank", "PROJ": "proj", "FLOOR": "floor",
             "CEIL": "ceiling", "VORP": "vorp", "TIER": "tier",
             "PLAYOFF": "playoff_ratio", "TSCORED": "team_scored",
             "OPPALL": "opp_allowed", "YID": "yahoo_id"}
    assert set(declared) == set(names), "the script and this test disagree"
    for const, field in names.items():
        assert draft_live._FIELDS[int(declared[const])] == field, (
            f"{const} points at {draft_live._FIELDS[int(declared[const])]}, not {field}")


def test_payload_carries_every_row_and_the_league_shape():
    board = projections.value_board()
    league = yahoo.league()
    config = draft_live.config(board, league)

    assert len(config["rows"]) == len(board)
    assert all(len(row) == len(draft_live._FIELDS) for row in config["rows"])
    assert config["rounds"] == 17 and config["numTeams"] == 10
    assert ["QB", 2] in config["slots"], "the two-quarterback roster is the point"
    assert config["flexSlot"] == "W/R/T"
    json.dumps(config)                       # NaN would make this unparseable


def test_ids_the_page_matches_on_are_unique_strings():
    """The live feed joins on Yahoo's player id. A duplicate or a float-typed
    one means a pick lands on the wrong player, or on none."""
    board = projections.value_board()
    ids = list(board["yahoo_id"])
    assert all(isinstance(i, str) and i.isdigit() for i in ids)
    assert len(set(ids)) == len(ids)
