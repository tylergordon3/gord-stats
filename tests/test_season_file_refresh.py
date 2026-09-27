"""The season being played has its season file refreshed by the scheduled
preset - but only when a week has finished that the file does not hold yet.

The preset ran no data jobs at all, so 2026-27's file sat at the two weeks it
had on the day it was added; the schedule page, League Home's records and
head-to-head all read it.
"""
import pandas as pd


def _setup(tmp_path, monkeypatch, have_weeks, end_week):
    from fantasy import data_manager as dm

    (tmp_path / "season").mkdir()
    pd.DataFrame({"week": list(range(1, have_weeks + 1))}).to_json(
        tmp_path / "season" / "2627.json")
    calls = []

    def fetch(end, league_id):
        calls.append(end)
        return pd.DataFrame({"week": list(range(1, end + 1))})

    monkeypatch.setattr(dm, "DATA_DIR", tmp_path)
    monkeypatch.setattr(dm, "CURRENT_SEASON_STR", "2627")
    monkeypatch.setattr(dm, "_end_week", lambda season_str: end_week)
    monkeypatch.setattr(dm.season_data, "get_season", fetch)
    return dm, calls


def test_a_newly_finished_week_is_fetched(tmp_path, monkeypatch):
    dm, calls = _setup(tmp_path, monkeypatch, have_weeks=2, end_week=3)
    dm.update_season("2026", "2627")
    assert calls == [3]
    assert dm._weeks_in(tmp_path / "season" / "2627.json") == 3


def test_a_file_already_through_the_last_finished_week_costs_no_request(tmp_path, monkeypatch):
    dm, calls = _setup(tmp_path, monkeypatch, have_weeks=3, end_week=3)
    dm.update_season("2026", "2627")
    assert calls == []


def test_the_scheduled_preset_refreshes_the_season_file():
    from fantasy import rebuild

    assert "season" in rebuild.plan_from_preset("pages").data_jobs
