"""
"Will he play this week?" - fantasy.league.availability.

The chance a player on the NFL injury report plays, fitted on nflverse's
official reports against snap counts. Before it, Sleeper's tag alone priced
the week: Questionable a full game, Doubtful a quarter of one. Ten seasons of
reports say Doubtful is all but Out (1-2% took a snap) and Questionable runs
from about nine in ten (a lead player who practised in full) to under one in
three (a part-timer who sat out the last practice).

Small fixture frames only - no network (tests/conftest.py blocks it).
"""
import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from fantasy.league import availability as av


# --------------------------------------------------------------------------- #
# Fixtures: nflverse-shaped frames
# --------------------------------------------------------------------------- #

def _inj(rows):
    cols = ["season", "game_type", "week", "gsis_id", "position", "report_status",
            "practice_status", "date_modified"]
    return pd.DataFrame(rows, columns=cols)


def _snaps(rows):
    cols = ["season", "game_type", "week", "pfr_player_id", "position", "offense_snaps",
            "offense_pct", "st_snaps"]
    return pd.DataFrame(rows, columns=cols)


LIMITED = "Limited Participation in Practice"
FULL = "Full Participation in Practice"
DNP = "Did Not Participate In Practice"
T = pd.Timestamp


@pytest.fixture
def frames():
    players = pd.DataFrame({"gsis_id": ["g-lead", "g-share", "g-back", "g-rook", "g-k",
                                        "g-lb", "g-nopfr"],
                            "pfr_id": ["LeadAa00", "ShareB00", "BackC00", "RookD00", "KickE00",
                                       "LineF00", None]})
    injuries = _inj([
        # A lead receiver (80% of snaps this season), Questionable, limited Friday,
        # who played. Filed twice: Friday's Questionable stands, the stale row goes.
        (2020, "REG", 5, "g-lead", "WR", "Questionable", DNP, T("2020-10-07", tz="UTC")),
        (2020, "REG", 5, "g-lead", "WR", "Questionable", LIMITED, T("2020-10-09", tz="UTC")),
        # A part-timer (40%), Questionable, sat out Friday, did not play.
        (2020, "REG", 5, "g-share", "RB", "Questionable", DNP, T("2020-10-09", tz="UTC")),
        # Week 1: no snaps this season yet, so last season's last four decide (60%+).
        (2020, "REG", 1, "g-back", "TE", "Doubtful", DNP, T("2020-09-11", tz="UTC")),
        # A rookie: no snaps in either season.
        (2020, "REG", 5, "g-rook", "WR", "Out", DNP, T("2020-10-09", tz="UTC")),
        # A kicker is read on special-teams snaps.
        (2020, "REG", 5, "g-k", "K", "Questionable", FULL, T("2020-10-09", tz="UTC")),
        # Not kept: a linebacker, a player with no pfr id, a playoff game, no status.
        (2020, "REG", 5, "g-lb", "LB", "Questionable", FULL, T("2020-10-09", tz="UTC")),
        (2020, "REG", 5, "g-nopfr", "WR", "Questionable", FULL, T("2020-10-09", tz="UTC")),
        (2020, "WC", 19, "g-lead", "WR", "Questionable", FULL, T("2021-01-08", tz="UTC")),
        (2020, "REG", 4, "g-lead", "WR", None, FULL, T("2020-10-02", tz="UTC")),
    ])
    snaps = _snaps([
        # g-lead: weeks 1-4 of 2020 at 50/90/90/90/... last four: 1-4 -> 0.80, plays week 5.
        (2020, "REG", 1, "LeadAa00", "WR", 30, 0.50, 0),
        (2020, "REG", 2, "LeadAa00", "WR", 55, 0.90, 0),
        (2020, "REG", 3, "LeadAa00", "WR", 55, 0.90, 0),
        (2020, "REG", 4, "LeadAa00", "WR", 55, 0.90, 0),
        (2020, "REG", 5, "LeadAa00", "WR", 40, 0.70, 2),
        # A week-6 game must not leak into week 5's role.
        (2020, "REG", 6, "LeadAa00", "WR", 5, 0.08, 0),
        # g-share: 40% of snaps; week 5 only special teams -> did not play.
        (2020, "REG", 3, "ShareB00", "RB", 25, 0.40, 3),
        (2020, "REG", 4, "ShareB00", "RB", 25, 0.40, 3),
        (2020, "REG", 5, "ShareB00", "RB", 0, 0.0, 6),
        # g-back: last season's last four at 0.70 (an early 0.10 game falls off).
        (2019, "REG", 10, "BackC00", "TE", 5, 0.10, 0),
        (2019, "REG", 14, "BackC00", "TE", 40, 0.70, 0),
        (2019, "REG", 15, "BackC00", "TE", 40, 0.70, 0),
        (2019, "REG", 16, "BackC00", "TE", 40, 0.70, 0),
        (2019, "REG", 17, "BackC00", "TE", 40, 0.70, 0),
        # g-k: special teams only.
        (2020, "REG", 5, "KickE00", "K", 0, 0.0, 9),
    ])
    return injuries, snaps, players


def test_sample_reads_status_role_practice_and_whether_he_played(frames):
    out = av.sample(*frames).set_index("gsis_id")
    assert set(out.index) == {"g-lead", "g-share", "g-back", "g-rook", "g-k"}, \
        "linebacker, unmatched id, playoff and no-status rows are not fitted"
    lead = out.loc["g-lead"]
    assert (lead["status"], lead["practice"], lead["role"], lead["played"]) == \
        ("Questionable", "Limited", "lead", True), "the later report of the week stands"
    share = out.loc["g-share"]
    # Special-teams snaps are not a fantasy game: a back with none on offense sat.
    assert (share["role"], share["practice"], share["played"]) == ("share", "DNP", False)
    assert out.loc["g-back", "role"] == "lead", "week 1 reads last season's last four games"
    assert out.loc["g-rook", "role"] == "new" and not out.loc["g-rook", "played"]
    kick = out.loc["g-k"]
    assert kick["role"] == "kick" and kick["played"], "a kicker plays on special-teams snaps"


def test_role_cut_offs():
    assert av.role_of(0.60) == "lead" and av.role_of(0.59) == "share"
    assert av.role_of(0.35) == "share" and av.role_of(0.34) == "depth"
    assert av.role_of(None) == "new" and av.role_of(np.nan) == "new"


# --------------------------------------------------------------------------- #
# The table
# --------------------------------------------------------------------------- #

def _frame(cells):
    """[(status, role, practice, played, n)] -> a sample frame."""
    rows = []
    for status, role, practice, played, n in cells:
        rows += [{"season": 2020, "week": 5, "status": status, "role": role,
                  "practice": practice, "played": played}] * n
    return pd.DataFrame(rows)


def test_fit_shrinks_each_level_toward_the_one_above():
    frame = _frame([("Questionable", "lead", "Full", True, 18), ("Questionable", "lead", "Full", False, 2),
                    ("Questionable", "lead", "DNP", True, 1), ("Questionable", "lead", "DNP", False, 1),
                    ("Questionable", "depth", "Limited", False, 8)])
    rates = av.fit(frame, prior=10)
    n, s = 30, 19
    top = (s + 0.5) / (n + 1)
    assert rates["Questionable"] == [round(top, 4), 30]
    lead = (19 + 10 * top) / (22 + 10)
    assert rates["Questionable|lead"][0] == pytest.approx(lead, abs=1e-4)
    full = (18 + 10 * lead) / (20 + 10)
    assert rates["Questionable|lead|Full"][0] == pytest.approx(full, abs=1e-4)
    # Two cases of DNP say 50%; with ten borrowed from the lead rate they say
    # much closer to it - a thin cell leans on a thick one.
    dnp = rates["Questionable|lead|DNP"][0]
    assert 0.5 < dnp < lead and dnp == pytest.approx((1 + 10 * lead) / 12, abs=1e-4)


def test_lookup_backs_off_to_the_deepest_level_it_has():
    rates = {"Questionable": [0.63, 100], "Questionable|lead": [0.74, 40],
             "Questionable|lead|Full": [0.89, 10]}
    assert av.lookup(rates, "Questionable", "lead", "Full")[0] == 0.89
    assert av.lookup(rates, "Questionable", "lead", "DNP")[:2] == (0.74, 40)
    assert av.lookup(rates, "Questionable", "kick", None)[0] == 0.63
    assert av.lookup(rates, "Probable", "lead", "Full") == (None, 0, None)


def test_validate_scores_out_of_sample_and_beats_the_old_rule():
    rng = np.random.default_rng(7)
    rows = []
    for season in range(2016, 2024):
        for _ in range(200):
            role = rng.choice(["lead", "depth"])
            practice = rng.choice(["Full", "Limited", "DNP"])
            p = {"lead": 0.8, "depth": 0.5}[role] * {"Full": 1.1, "Limited": 1.0, "DNP": 0.6}[practice]
            rows.append({"season": season, "week": 5, "status": "Questionable", "role": role,
                         "practice": practice, "played": bool(rng.random() < min(p, 0.97))})
        for _ in range(30):
            rows.append({"season": season, "week": 5, "status": "Doubtful", "role": "lead",
                         "practice": "DNP", "played": bool(rng.random() < 0.02)})
    v = av.validate(pd.DataFrame(rows), split=2020)
    assert v["train"] == [2016, 2020] and v["test"] == [2021, 2023]
    q = v["questionable"]
    assert q["n"] == 600
    assert q["log_loss"] < q["status_only_log_loss"], "role and practice must add something"
    assert q["brier"] < q["old_rule_brier"], "Questionable as a sure thing is the old rule"
    assert abs(q["said"] - q["played"]) < 0.05
    # A calibration row per Questionable/Doubtful cell: said, played, n.
    cell = next(c for c in v["cells"] if c[:3] == ["Questionable", "lead", "Full"])
    assert 0.8 < cell[3] <= 1 and 0.8 < cell[4] <= 1 and cell[5] >= 10
    assert all(lo < hi for lo, hi, *_ in v["bins"])


def test_the_committed_table_is_small_and_says_what_the_reports_say():
    """data/fantasy/availability.json, refitted by `python -m
    fantasy.league.availability`: a few KB, Doubtful all but out, and a
    Questionable lead player's chance falling with his last practice."""
    assert av.TABLE_PATH.stat().st_size < 10_000
    table = json.loads(av.TABLE_PATH.read_text())
    rates = table["rates"]
    assert av.lookup(rates, "Doubtful")[0] < 0.05
    assert av.lookup(rates, "Out")[0] < 0.01
    full, ltd, dnp = (av.lookup(rates, "Questionable", "lead", p)[0]
                      for p in ("Full", "Limited", "DNP"))
    assert full > ltd > dnp
    assert av.lookup(rates, "Questionable", "lead", "Limited")[0] > \
        av.lookup(rates, "Questionable", "depth", "Limited")[0]
    v = table["validation"]["questionable"]
    assert v["log_loss"] < v["status_only_log_loss"] and v["brier"] < v["old_rule_brier"]
    roles = json.loads(av.ROLES_PATH.read_text())
    assert roles["season"] == table["seasons"][1] and av.ROLES_PATH.stat().st_size < 20_000


# --------------------------------------------------------------------------- #
# This week
# --------------------------------------------------------------------------- #

TABLE = {"seasons": [2016, 2025], "rates": {
    "Questionable": [0.63, 4000], "Questionable|lead": [0.74, 1900],
    "Questionable|lead|Full": [0.89, 320], "Questionable|lead|Limited": [0.75, 1260],
    "Questionable|lead|DNP": [0.53, 280], "Questionable|share": [0.65, 1000],
    "Questionable|new": [0.35, 170], "Questionable|kick": [0.68, 110],
    "Doubtful": [0.012, 520], "Doubtful|lead": [0.018, 220], "Out": [0.0007, 3100]}}


def test_reports_by_week_keeps_final_reports_on_fantasy_positions():
    frame = pd.DataFrame({
        "season": [2026] * 5, "game_type": ["REG"] * 5, "week": [4, 4, 4, 3, 4],
        "gsis_id": ["g1", "g2", "g3", "g1", "g9"],
        "position": ["WR", "RB", "LB", "WR", "TE"],
        "report_status": ["Questionable", None, "Out", "Doubtful", "Questionable"],
        "practice_status": [LIMITED, DNP, DNP, DNP, "\n"]})
    registry = pd.DataFrame({"gsis_id": ["g1", "g2", "g3", "g9"], "sleeper_id": ["101", "102", "103", "109"]})
    got = av.reports_by_week(frame, registry)
    # g2 has no game status yet - a mid-week practice, not the final report.
    assert got[4] == {"101": {"status": "Questionable", "practice": "Limited"},
                      "109": {"status": "Questionable", "practice": None}}
    assert got[3] == {"101": {"status": "Doubtful", "practice": "DNP"}}
    assert av.reports_by_week(pd.DataFrame(), registry) == {}


def test_snap_shares_read_this_season_before_the_week_then_last_season():
    usage = pd.DataFrame({
        "week": [1, 2, 3, 4, 5, 1, 2],
        "sleeper_id": ["a"] * 5 + ["b", "b"],
        "off_snp": [10, 50, 50, 50, 5, 0, 30],
        "tm_off_snp": [50, 50, 50, 50, 50, 60, 60]})
    shares = av.snap_shares(5, 2026, usage=usage, last={"a": 0.2, "c": 0.7})
    assert shares["a"] == pytest.approx((0.2 + 1 + 1 + 1) / 4), "his last four games before week 5"
    assert shares["b"] == pytest.approx(0.5), "a game with no offensive snaps is not one of them"
    assert shares["c"] == 0.7, "no snaps yet this season: last season's"
    assert "a" not in av.snap_shares(1, 2026, usage=usage, last={}), "week 1 has no games before it"


def test_week_chances_from_tag_role_and_the_final_report():
    tags = {"lead": "Questionable", "stale": "Questionable", "ir": "IR", "dbt": "Doubtful",
            "k": "Questionable", "rook": "Questionable", "fine": ""}
    reports = {"lead": {"status": "Questionable", "practice": "Full"},
               # The report says Doubtful, Sleeper still Questionable: a different
               # report, so its practice is not read into Sleeper's status.
               "stale": {"status": "Doubtful", "practice": "Full"},
               # On the official report, not tagged by Sleeper yet.
               "new-q": {"status": "Questionable", "practice": "DNP"}}
    shares = {"lead": 0.8, "stale": 0.9, "new-q": 0.75, "dbt": 0.7, "k": None}
    got = av.week_chances(tags, 4, 2026, positions={"k": "K"}, reports=reports, shares=shares,
                          table=TABLE)
    assert set(got) == {"lead", "stale", "ir", "dbt", "k", "rook", "new-q"}, \
        "untagged, unreported players play and are not listed"
    assert got["lead"]["p"] == 0.89 and got["lead"]["practice"] == "Full"
    assert got["stale"]["p"] == 0.74 and got["stale"]["practice"] is None
    assert got["new-q"]["p"] == 0.53 and got["new-q"]["status"] == "Questionable"
    assert got["ir"]["p"] == 0.0 and got["dbt"]["p"] == 0.018
    assert got["k"]["role"] == "kick" and got["k"]["p"] == 0.68
    assert got["rook"]["role"] == "new" and got["rook"]["p"] == 0.35


def test_without_last_seasons_roles_no_snaps_says_nothing(monkeypatch):
    """Week 1 reads last season's roles. If the yearly refit has not written
    them, a veteran with no snaps on file is not a rookie: his status prices him."""
    monkeypatch.setattr(av, "snap_shares", lambda week, year, last=None: {})
    monkeypatch.setattr(av, "last_season", lambda year: None)
    got = av.week_chances({"vet": "Questionable"}, 1, 2026, reports={}, table=TABLE)
    assert got["vet"]["role"] is None and got["vet"]["p"] == 0.63
    monkeypatch.setattr(av, "last_season", lambda year: {"someone": 0.8})
    got = av.week_chances({"rook": "Questionable"}, 1, 2026, reports={}, table=TABLE)
    assert got["rook"]["role"] == "new" and got["rook"]["p"] == 0.35


def test_without_a_table_the_old_rule_stands():
    assert av.chance("Questionable", "lead", "Full", table={})["p"] == 1.0
    assert av.chance("Doubtful", table={})["p"] == 0.25
    assert av.chance("Out", table={})["p"] == 0.0
    assert av.chance("", table=TABLE)["p"] == 1.0


def test_apply_prices_the_week_as_projection_times_chance():
    wk = pd.DataFrame({"proj_week": [20.0, 10.0, 8.0]}, index=pd.Index(["a", "b", "c"], name="sleeper_id"))
    got = av.apply(wk, {"a": {"p": 0.75}, "b": {"p": 0.0}})
    assert got["proj_full"].tolist() == [20.0, 10.0, 8.0]
    assert got["p_play"].tolist() == [0.75, 0.0, 1.0]
    assert got["proj_week"].tolist() == [15.0, 0.0, 8.0]
    assert wk["proj_week"].tolist() == [20.0, 10.0, 8.0], "the caller's frame is left alone"


def test_a_started_game_with_him_in_it_spends_the_chance():
    assert av.playing({"gp": 1.0}, None) and av.playing({}, 3.2)
    assert not av.playing({}, 0) and not av.playing(None, None)


# --------------------------------------------------------------------------- #
# Words
# --------------------------------------------------------------------------- #

def test_label_rounds_to_five_and_says_the_ends_as_ends():
    assert av.label(0.737) == "plays 75%" and av.label(0.66) == "plays 65%"
    assert av.label(0.012) == "plays <5%" and av.label(0.97) == "plays >95%"


def test_the_colour_follows_the_figure_shown():
    assert av.level(0.85) == "good" and av.level(0.826) == "good"     # shows 85%
    assert av.level(0.737) == "fair" and av.level(0.49) == "fair"     # 75%, 50%
    assert av.level(0.30) == "poor" and av.level(0.01) == "poor"


def test_tip_says_what_the_chance_is_read_from():
    tip = av.tip({"p": 0.749, "n": 1267, "status": "Questionable", "practice": "Limited",
                  "role": "lead"}, table=TABLE)
    assert tip.startswith("Questionable, limited in practice before the final report, a lead player")
    assert "75% of players like him played, 2016-25 (1,267 cases)" in tip
    assert "no final practice report yet" in av.tip(
        {"p": 0.74, "n": 0, "status": "Questionable", "practice": None, "role": "lead"}, table=TABLE)


HOLDS = {"Out", "Injured Reserve", "Doubtful"}


def test_back_label_from_espns_return_date():
    end = date(2027, 1, 10)
    entry = {"status": "Injured Reserve", "back": "2026-11-01"}
    assert av.back_label(entry, end, today=date(2026, 10, 1), holds=HOLDS) == "back ~Nov 1"
    assert av.back_label({"status": "Out", "back": "2027-02-15"}, end, date(2026, 10, 1),
                         holds=HOLDS) == "out for season"
    # ESPN dates a Doubtful player's return to the game he is doubtful for:
    # nothing past this week's games is said, so nothing is shown.
    assert av.back_label({"status": "Doubtful", "back": "2026-10-04"}, end,
                         today=date(2026, 10, 5), holds=HOLDS) == ""
    assert av.back_label({"status": "Questionable", "back": "2026-11-01"}, end,
                         date(2026, 10, 1), holds=HOLDS) == ""
    assert av.back_label({"status": "Out", "back": None}, end, holds=HOLDS) == ""
    assert av.back_label(None, end, holds=HOLDS) == ""


def test_return_labels_use_the_report_given_and_the_weeks_end(monkeypatch):
    monkeypatch.setattr(av, "season_end", lambda year: date(2027, 1, 10))
    report = {"1": {"status": "Injured Reserve", "back": "2026-11-08"},
              "2": {"status": "Doubtful", "back": "2026-10-04"},
              "3": {"status": "Out", "back": "2027-03-01"}}
    got = av.return_labels(["1", "2", "3", "4"], 2026, report=report, after=date(2026, 10, 6))
    assert got == {"1": "back ~Nov 8", "3": "out for season"}


def test_week_end_is_the_last_kickoff_day():
    games = [{"date": "2026-10-02T00:15Z"}, {"date": "2026-10-06T00:15Z"}, {"date": None}]
    assert av.week_end(games) == date(2026, 10, 6)
    assert av.week_end([]) is None
