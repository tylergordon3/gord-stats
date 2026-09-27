"""The schedule's picks of the day lock on the day, not on first sight.

Once Saturday's last game kicked off, the schedule moved on to next week and
the picks code froze that week's first day straight away: 2026-09-26's picks
were locked on Sep 19, from 15 games. A later day is now a preview - shown,
never written - and the file is written by the first build on the day itself.
"""
from datetime import datetime

import pandas as pd

from cfb.config import LEAGUE_TZ


def _slate(day: str) -> pd.DataFrame:
    local = pd.Timestamp(f"{day} 12:00", tz=LEAGUE_TZ)
    return pd.DataFrame([{
        "game_id": "1", "week": 5, "home_conf": "SEC", "away_conf": "SEC",
        "dk_spread": -3.0, "gs_margin": 10.0, "local": local, "state": "pre",
        "date_utc": local.tz_convert("UTC").isoformat(),
    }])


def _at(monkeypatch, schedule, when: str):
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromisoformat(when).replace(tzinfo=LEAGUE_TZ).astimezone(tz)
    monkeypatch.setattr(schedule, "datetime", Frozen)


def test_a_later_day_is_a_preview_and_is_not_frozen(tmp_path, monkeypatch):
    from cfb.site import schedule

    monkeypatch.setattr(schedule, "PICKS_DIR", tmp_path)
    monkeypatch.setattr(schedule, "_compute_picks", lambda slate: {"legs": ["x"]})
    _at(monkeypatch, schedule, "2026-09-19T23:10")          # the Saturday before

    picks, day, locked_at = schedule._picks_for_day(_slate("2026-09-26"), 5)
    assert picks == {"legs": ["x"]} and str(day) == "2026-09-26"
    assert locked_at is None
    assert not list(tmp_path.iterdir()), "a day a week away was frozen"


def test_the_first_build_on_the_day_freezes_it(tmp_path, monkeypatch):
    from cfb.site import schedule

    monkeypatch.setattr(schedule, "PICKS_DIR", tmp_path)
    monkeypatch.setattr(schedule, "_compute_picks", lambda slate: {"legs": ["x"]})
    _at(monkeypatch, schedule, "2026-09-26T05:40")

    _, _, locked_at = schedule._picks_for_day(_slate("2026-09-26"), 5)
    assert locked_at and (tmp_path / "2026-09-26.json").exists()

    # Later builds read the file back rather than recomputing.
    monkeypatch.setattr(schedule, "_compute_picks", lambda slate: {"legs": ["moved"]})
    picks, _, again = schedule._picks_for_day(_slate("2026-09-26"), 5)
    assert picks == {"legs": ["x"]} and again == locked_at


def test_the_current_week_holds_while_its_late_games_are_still_on(monkeypatch):
    """After the night's last kickoff nothing in week 5 is still to start, but
    a game is still being played: the page stays on week 5 until it ends."""
    from cfb.site import schedule

    df = pd.DataFrame([
        {"week": 5, "state": "in", "date_utc": "2026-09-27T02:30:00+00:00"},
        {"week": 5, "state": "post", "date_utc": "2026-09-26T16:00:00+00:00"},
        {"week": 6, "state": "pre", "date_utc": "2026-10-03T16:00:00+00:00"},
    ])
    _at(monkeypatch, schedule, "2026-09-26T23:55")            # 03:55 UTC
    assert schedule._current_week(df) == 5
    df.loc[0, "state"] = "post"
    assert schedule._current_week(df) == 6
