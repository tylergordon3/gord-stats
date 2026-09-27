"""College basketball in season: the pieces that had never run on the Pi.

The pipeline was run by hand in 2025-26, so its early-season paths were never
exercised: a non-D1 opponent crashed the scoreboard, "last ten" meant last
March, last season's NET was filed as today's, and nothing pushed the live
board at all.
"""
import json
from datetime import date, datetime

import pytest


def test_last_ten_is_this_seasons_games_and_a_stranger_is_blank(tmp_path, monkeypatch):
    from cbb.scrape import season

    games = {"Duke": {"2026-03-01": {"win": False}, "2026-03-05": {"win": False},
                      "2026-11-04": {"win": True}, "2026-11-08": {"win": True}}}
    (tmp_path / "s.json").write_text(json.dumps(games))
    monkeypatch.setattr(season, "get_file", lambda gender: tmp_path / "s.json")
    monkeypatch.setattr(season.teams, "getTeamOfficialName", lambda t: t)

    class Nov(date):
        @classmethod
        def today(cls):
            return date(2026, 11, 10)
    monkeypatch.setattr(season, "date", Nov)

    assert season.get_last_x("M", "Duke", 10) == "2-0", "last March leaked into November"
    assert season.get_last_x("M", "Lynchburg", 10) == "", "a non-D1 opponent crashed it"


def test_last_seasons_net_is_refused(monkeypatch):
    from cbb.scrape import net

    class Page:
        content = b"<html><p>Through Games Apr. 06 2026</p><table><tr><th>Rank</th></tr></table></html>"
    monkeypatch.setattr(net.requests, "get", lambda *a, **k: Page())

    class Nov(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 10, 12)
    monkeypatch.setattr(net, "datetime", Nov)
    with pytest.raises(net.NotReleased):
        net.main("M")


def test_predictions_ignore_a_net_file_from_last_season(tmp_path):
    from cbb import predictions

    (tmp_path / "2026-03-15.json").write_text(json.dumps({"headers": [], "rows": []}))
    assert predictions._this_season_net(tmp_path, date(2026, 11, 10)) is None
    (tmp_path / "2026-12-02.json").write_text(json.dumps({"headers": ["Rank"], "rows": []}))
    assert predictions._this_season_net(tmp_path, date(2026, 12, 3)) == {"headers": ["Rank"], "rows": []}


def test_the_live_gate_sends_both_leagues_in_the_shape_live_js_reads():
    from cbb import live

    body = live.payload({"men": {"1": {}}, "women": {}})
    assert set(body["leagues"]) == {"men", "women"}
    assert body["meta"]["poll_interval_sec"] == live.TICK_SECONDS
    js = (__import__("conftest").DOCS / "assets" / "js" / "live.js").read_text()
    assert "data.leagues" in js


@pytest.mark.parametrize("hour, minute, on", [(10, 59, False), (11, 0, True), (23, 50, True),
                                              (1, 20, True), (1, 40, False), (6, 0, False)])
def test_the_live_gate_runs_in_playing_hours_only(hour, minute, on):
    from cbb import live

    assert live.in_hours(datetime(2026, 11, 10, hour, minute, tzinfo=live.ET)) is on
