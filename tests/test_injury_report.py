"""
ESPN's NFL injury report (fantasy.league.injury_report): return dates turned
into the weeks a player misses, the Sleeper tag's flat count where ESPN has
no date, and only the facts kept from ESPN's payload.
"""
from datetime import date, timedelta

from fantasy.league import injury_report as ir

# Sundays of weeks 1-18, 2026.
DAYS = {w: date(2026, 9, 13) + timedelta(days=7 * (w - 1)) for w in range(1, 19)}


def test_a_return_date_counts_the_weeks_before_it():
    # Three weeks played; back on Nov 1 (week 8's Sunday): misses weeks 4-7.
    entry = {"status": "Injured Reserve", "back": "2026-11-01"}
    assert ir.weeks_out(entry, 3, DAYS, 18) == 4


def test_a_season_ending_date_is_the_rest_of_the_season():
    entry = {"status": "Injured Reserve", "back": "2027-02-15"}
    assert ir.weeks_out(entry, 3, DAYS, 18) == 15


def test_a_held_status_whose_date_has_passed_still_costs_the_week():
    assert ir.weeks_out({"status": "Out", "back": "2026-09-01"}, 3, DAYS, 18) == 1
    assert ir.weeks_out({"status": "Doubtful", "back": "2026-10-04"}, 3, DAYS, 18) == 1


def test_questionable_or_no_date_says_nothing():
    assert ir.weeks_out({"status": "Questionable", "back": "2026-10-04"}, 3, DAYS, 18) is None
    assert ir.weeks_out({"status": "Out", "back": None}, 3, DAYS, 18) is None
    assert ir.weeks_out(None, 3, DAYS, 18) is None


def test_held_out_prefers_espns_date_and_falls_back_to_the_tag():
    entries = {"1": {"status": "Injured Reserve", "back": "2027-02-15"},   # ACL
               "3": {"status": "Out", "back": "2026-10-25"}}              # untagged by Sleeper yet
    tags = {"1": "IR", "2": "IR", "4": "Questionable"}
    got = ir.held_out(tags, from_week=3, weeks=18, year=2026, entries=entries, week_days=DAYS)
    assert got == {"1": 15, "2": 4, "3": 3}


def test_only_the_facts_are_kept_keyed_by_sleeper_id():
    payload = {"injuries": [{"injuries": [
        {"status": "Out", "date": "2026-10-01T21:30Z",
         "shortComment": "news copy", "longComment": "more news copy",
         "athlete": {"links": [{"href": "https://www.espn.com/nfl/player/_/id/4429084/x"}]},
         "details": {"returnDate": "2026-10-25", "type": "Thumb"}},
        {"status": "Active", "athlete": {"links": [{"href": "https://x/id/999/y"}]}}]}]}
    got = ir._trim(payload, {"4429084": "4892"})
    assert got == {"4892": {"status": "Out", "back": "2026-10-25", "part": "Thumb",
                            "updated": "2026-10-01"}}
