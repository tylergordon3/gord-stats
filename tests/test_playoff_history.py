"""
Playoff odds kept build by build (gordstats.playoff_history): written only when
they change, a week's baseline read back, long shots counted from zero.
"""
from datetime import datetime, timedelta

from gordstats import playoff_history as ph

NOW = datetime(2026, 10, 11, 23, 30, tzinfo=ph.ET)


def test_a_snapshot_is_written_only_when_the_odds_change(tmp_path):
    path = tmp_path / "h.json"
    odds = {"333": (0.73, 0.11), "61": (0.0001, 0.0)}
    assert ph.record(path, 2026, odds, now=NOW - timedelta(days=8))
    assert not ph.record(path, 2026, odds, now=NOW - timedelta(days=7))   # same again
    assert ph.record(path, 2026, {"333": (0.80, 0.12)}, now=NOW)
    import json
    data = json.loads(path.read_text())
    assert len(data["snapshots"]) == 2
    # The long shot is left out of the file.
    assert data["snapshots"][0]["odds"] == {"333": [0.73, 0.11]}


def test_the_baseline_is_the_newest_snapshot_a_week_old(tmp_path):
    path = tmp_path / "h.json"
    ph.record(path, 2026, {"333": (0.60, 0.1)}, now=NOW - timedelta(days=13))
    ph.record(path, 2026, {"333": (0.65, 0.1)}, now=NOW - timedelta(days=7))
    ph.record(path, 2026, {"333": (0.70, 0.1)}, now=NOW - timedelta(days=2))
    when, odds = ph.baseline(path, 2026, now=NOW)
    assert when == NOW - timedelta(days=7) and odds == {"333": [0.65, 0.1]}
    assert ph.change(0.80, odds, "333") == 0.80 - 0.65
    assert ph.change(0.05, odds, "999") == 0.05             # unlisted then: from zero


def test_no_baseline_before_a_week_or_for_another_season(tmp_path):
    path = tmp_path / "h.json"
    ph.record(path, 2026, {"333": (0.6, 0.1)}, now=NOW - timedelta(days=2))
    assert ph.baseline(path, 2026, now=NOW) == (None, None)
    assert ph.baseline(path, 2027, now=NOW) == (None, None)
    assert ph.baseline(tmp_path / "missing.json", 2026, now=NOW) == (None, None)
    # A new season starts a new file rather than appending to the old one.
    ph.record(path, 2027, {"333": (0.5, 0.1)}, now=NOW)
    import json
    assert json.loads(path.read_text())["season"] == 2027
