"""A kickoff ESPN has not set yet is not a kickoff at midnight.

ESPN files an unscheduled game at 04:00 UTC with `timeValid: false`. The
schedule printed 37 of week 6's games as "12:00 AM", and the homepage clock
would count down to midnight Saturday rather than to the first real kickoff.
"""
from datetime import datetime, timezone

import numpy as np
import pandas as pd


def _games():
    return pd.DataFrame([
        {"week": 6, "state": "pre", "date_utc": "2026-10-03T04:00Z", "time_valid": False},
        {"week": 6, "state": "pre", "date_utc": "2026-10-03T16:00Z", "time_valid": True},
    ])


def test_the_homepage_clock_skips_a_kickoff_that_is_not_set():
    from cfb.site import countdown

    got = countdown.payload(_games(), datetime(2026, 10, 2, 20, tzinfo=timezone.utc))
    assert "12:00 PM" in str(got), got
    assert "12:00 AM" not in str(got), got


def test_a_schedule_cached_before_the_column_existed_still_counts():
    from cfb.site import countdown

    old = _games().drop(columns="time_valid")
    got = countdown.payload(old, datetime(2026, 10, 2, 20, tzinfo=timezone.utc))
    assert got.get("mode") != "off"


def test_the_schedule_reads_a_numpy_false_as_not_set():
    """Rows come out of a DataFrame as numpy booleans, and np.False_ is not
    the `False` singleton - an `is False` test would read every game as set."""
    from types import SimpleNamespace

    from cfb.site import schedule

    assert schedule._time_known(SimpleNamespace(time_valid=np.False_)) is False
    assert schedule._time_known(SimpleNamespace(time_valid=np.True_))
    assert schedule._time_known(SimpleNamespace(time_valid=np.nan))
    assert schedule._time_known(SimpleNamespace())
