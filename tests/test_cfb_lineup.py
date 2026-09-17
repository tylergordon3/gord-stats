"""
The team dashboard's moving parts: the lineup planner (who starts, and which
slot a starter takes so the flex stays open longest), the receiver matcher the
target counts run on, and the name bridge between box scores and Yahoo.
"""
import pandas as pd
import pytest

from cfb import lineup, ownership, usage

SLOTS = [{"position": "QB", "count": 1}, {"position": "RB", "count": 2},
         {"position": "WR", "count": 1}, {"position": "W/R/T", "count": 1},
         {"position": "BN", "count": 3}, {"position": "IL", "count": 1}]

THU = pd.Timestamp("2026-09-17 23:30", tz="UTC")
SAT = pd.Timestamp("2026-09-19 16:00", tz="UTC")
LATE = pd.Timestamp("2026-09-20 02:30", tz="UTC")


def _p(pid, pos, slot, status=""):
    return {"yahoo_id": pid, "player": f"P{pid}", "pos": pos, "slot": slot, "status": status}


def test_latest_kickoff_takes_the_flex():
    roster = [_p("q", "QB", "QB"), _p("r1", "RB", "W/R/T"), _p("r2", "RB", "RB"),
              _p("r3", "RB", "RB"), _p("w", "WR", "WR")]
    proj = {"q": 25, "r1": 20, "r2": 15, "r3": 12, "w": 10}
    kick = {"q": SAT, "r1": THU, "r2": SAT, "r3": LATE, "w": SAT}
    got = lineup.plan(roster, SLOTS, proj, kick, locked=set())
    # All three backs start either way; the Thursday back must not sit in the
    # flex, and the late-night one must.
    assert got["slot"]["r1"] == "RB"
    assert got["slot"]["r3"] == "W/R/T"
    assert got["slot"]["r2"] == "RB"


def test_best_projection_starts_and_the_rest_sit():
    roster = [_p("q", "QB", "QB"), _p("r1", "RB", "RB"), _p("r2", "RB", "RB"),
              _p("w1", "WR", "WR"), _p("w2", "WR", "BN"), _p("w3", "WR", "W/R/T")]
    proj = {"q": 25, "r1": 20, "r2": 15, "w1": 9, "w2": 14, "w3": 5}
    kick = {i: SAT for i in proj}
    got = lineup.plan(roster, SLOTS, proj, kick, locked=set())
    assert got["start"] == {"q", "r1", "r2", "w1", "w2"}
    assert got["slot"]["w3"] == "BN"
    current = {p["yahoo_id"]: p["slot"] for p in roster}
    assert lineup.total(roster, got["slot"], proj) - lineup.total(roster, current, proj) == 9


def test_a_locked_player_stays_where_he_is():
    roster = [_p("r1", "RB", "BN"), _p("r2", "RB", "RB"), _p("r3", "RB", "RB"),
              _p("r4", "RB", "W/R/T")]
    proj = {"r1": 30, "r2": 5, "r3": 12, "r4": 11}
    kick = {"r1": THU, "r2": THU, "r3": SAT, "r4": SAT}
    got = lineup.plan(roster, SLOTS, proj, kick, locked={"r1", "r2"})
    # The benched 30 already played: he cannot come in, and the started 5 cannot leave.
    assert got["slot"]["r1"] == "BN"
    assert got["slot"]["r2"] == "RB"
    assert got["start"] == {"r2", "r3", "r4"}


def test_injured_list_is_not_available_and_a_missing_projection_is_zero():
    roster = [_p("r1", "RB", "IL", "O"), _p("r2", "RB", "BN"), _p("r3", "RB", "RB")]
    got = lineup.plan(roster, SLOTS, {"r1": 40, "r3": float("nan")}, {}, locked=set())
    assert got["slot"]["r1"] == "IL"
    assert {"r2", "r3"} <= got["start"]


def test_cover_is_eligible_projected_and_not_earlier():
    roster = [_p("r1", "RB", "RB"), _p("r2", "RB", "RB"), _p("w1", "WR", "WR"),
              _p("r3", "RB", "W/R/T"), _p("bw", "WR", "BN"), _p("br", "RB", "BN"),
              _p("bz", "RB", "BN")]
    proj = {"r1": 20, "r2": 19, "w1": 15, "r3": 18, "bw": 8, "br": 7, "bz": 0}
    kick = {"r1": THU, "r2": SAT, "w1": LATE, "r3": LATE, "bw": SAT, "br": LATE, "bz": LATE}
    got = lineup.plan(roster, SLOTS, proj, kick, locked=set())
    assert got["slot"]["r3"] == "W/R/T"
    # The flex takes any skill position still to play; the zero never covers.
    assert got["cover"]["r3"] == ["br"]
    # A dedicated slot takes its own position only, best first.
    assert got["cover"]["r1"] == ["br"]
    # Nobody at his position kicks off as late as the late receiver.
    assert got["cover"]["w1"] == []


def test_play_text_names_fold_to_the_roster_spelling():
    assert usage._split("J.Barney Jr.") == ("j", "barney")
    assert usage._split("T.Melin Öhrström") == ("t", "melin ohrstrom")
    assert usage._split("B. Young Jr.") == ("b", "young")
    assert usage._split("Coy Eakin") == ("c", "eakin")


def test_receiver_falls_back_past_a_stale_jersey_number():
    names = {"1": "Jacory Barney Jr.", "2": "Nyziah Hunter", "3": "Janiran Hunter"}
    find = usage._Receivers({"17 barney jr.": "1"}, names).find
    assert find("J.Barney Jr.", "17") == "1"
    assert find("J.Barney Jr.", "2") == "1"          # renumbered since the roster was cut
    assert find("N.Hunter", "1") == "2"              # initial separates the two Hunters
    assert find("X.Hunter", "1") is None             # surname alone would be a guess
    assert find("B. Nobody") is None


def test_target_patterns_cover_the_feeds_three_voices():
    jersey = usage._TARGET.search("#10 A.Colandrea pass complete short right to #3 K.Gilmer "
                                  "caught at NEB40")
    assert (jersey.group(1), jersey.group(2)) == ("3", "K.Gilmer")
    plain = usage._TARGET_PLAIN.search("O. McCown pass to B. Young Jr. for 1 yd, for a TD")
    assert plain.group(1) == "B. Young Jr."
    score = usage._TARGET_SCORE.search("Coy Eakin 32 Yd pass from Will Hammond (S Kick)")
    assert score.group(1) == "Coy Eakin"
    assert not usage._TARGET_PLAIN.search("#12 C.Creel pass attempt failed")


def test_ownership_index_matches_middle_names_and_nicknames():
    held = pd.DataFrame([
        {"player": "Ryan Coleman Williams", "school": "Alabama", "owner": "A"},
        {"player": "Hollywood Smothers", "school": "Texas", "owner": "B"},
        {"player": "Nick Marsh", "school": "Indiana", "owner": "C"}])
    index = ownership.Index(held)
    assert index.find("Ryan Williams", "Alabama")["owner"] == "A"
    assert index.find("Daylan Smothers", "Texas")["owner"] == "B"
    assert index.find("Nick Marsh", "Michigan State") is None      # same name, other school
    assert index.find("Omar Marsh", "Indiana") is None


# --------------------------------------------------------------------------- #
# Shared planner (gordstats.lineup) and the NFL dashboard's data
# --------------------------------------------------------------------------- #

def test_equal_kickoffs_never_ask_for_a_slot_swap():
    from gordstats import lineup as shared
    players = [{"id": "a", "pos": "RB", "slot": "RB"}, {"id": "b", "pos": "RB", "slot": "RB"},
               {"id": "c", "pos": "RB", "slot": "FLEX"}]
    got = shared.plan(players, {"RB": 2, "FLEX": 1}, {"a": 9, "b": 20, "c": 15},
                      {"a": SAT, "b": SAT, "c": SAT}, set(), flex="FLEX",
                      flex_positions=("RB", "WR", "TE"), reserve=("IR",))
    assert got["slot"] == {"a": "RB", "b": "RB", "c": "FLEX"}


def test_change_names_the_three_moves():
    from gordstats.lineup import change
    off = {"BN", "IR"}
    assert change("BN", "FLEX", off) == "in"
    assert change("RB", "BN", off) == "out"
    assert change("RB", "FLEX", off) == "swap"
    assert change("RB", "RB", off) == "" and change("BN", "BN", off) == ""
    assert change("IR", "IR", off) == ""


def test_nfl_defence_ratings_shrink_toward_par_on_a_thin_sample():
    from fantasy.league import defense
    week = {"AAA": {p: 30.0 for p in defense.POSITIONS},
            "BBB": {p: 10.0 for p in defense.POSITIONS}}
    one = defense.ratings(data={"1": week})
    # League average 20: AAA allows 1.5x par, but one game of five counts a fifth.
    assert one.loc["AAA", "RB"] == pytest.approx(1.1)
    assert one.loc["BBB", "RB"] == pytest.approx(0.9)
    full = defense.ratings(data={str(w): week for w in range(1, 6)})
    assert full.loc["AAA", "RB"] == pytest.approx(1.5)
    assert defense.ranks(full)["RB"] == {"AAA": 1, "BBB": 2}


def test_nfl_scoreboard_weather_reads_either_field_order():
    from fantasy.league.matchups import _weather
    ahead = _weather({"weather": {"displayValue": "Rain", "conditionId": "18",
                                  "temperature": 69}}, {"venue": {"indoor": False}})
    assert ahead == {"temp": 69.0, "cond": 18, "text": "Rain", "indoors": False}
    today = _weather({"weather": {"displayValue": "7", "conditionId": "Cloudy",
                                  "temperature": 75}}, {"venue": {}})
    assert (today["cond"], today["text"]) == (7, "Cloudy")
    assert _weather({}, {"venue": {"indoor": True}})["indoors"] is True
    assert _weather({}, {"venue": {}}) is None
