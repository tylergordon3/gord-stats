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


def test_kenpom_errors_say_what_happened():
    """kenpom_wrapper returns an HTTP error instead of raising it, which used to
    surface as "DataFrame constructor not properly called!"."""
    import requests

    from cbb.scrape import kenpom

    with pytest.raises(RuntimeError, match="KenPom has no 2027 ratings"):
        kenpom._table(requests.HTTPError("400 Client Error: Bad Request"), "ratings", 2027)


def test_a_game_with_no_description_does_not_sink_the_scoreboard(monkeypatch):
    """Found by the rehearsal: theScore leaves game_description out of some
    early-season events, and `"NCAA Tournament" in None` lost the snapshot."""
    import inspect

    from cbb import live_scraper

    src = inspect.getsource(live_scraper.format_event)
    assert 'g.get("game_description") or ""' in src


def test_a_game_on_the_scoreboard_carries_its_own_teams_not_the_whole_league(monkeypatch):
    """Every game used to carry Torvik's full 365-team table (~92 KB, read by
    nothing): ~30 MB on opening night, past KV's 25 MB value limit, and
    downloaded by every phone on /men/ each poll."""
    import pandas as pd

    from cbb import live_scraper

    monkeypatch.setattr(live_scraper.season, "get_last_x", lambda g, t, x: "")
    master = pd.DataFrame({"team": ["Duke", "Kansas"], "index": [0, 1],
                           "names": [["DUKE", "Duke"], ["KU", "Kansas"]], "short": ["Duke", "KU"]})
    tor = {"rows": [[i, f"School {i}"] + [str(i)] * 19 + ["+1.0"] for i in range(365)]
           + [[400, "Duke"] + ["1"] * 19 + ["+9.5"], [401, "Kansas"] + ["1"] * 19 + ["+4.2"]]}
    net = {"rows": [["3", "Duke"], ["12", "Kansas"]]}
    g = {"home_team": {"abbreviation": "DUKE"}, "away_team": {"abbreviation": "KU"},
         "game_date": "Tue, 03 Nov 2026 19:00:00 -0500", "status": "pre_game"}

    out = live_scraper.format_event(g, {}, master, None, net, None, tor, "M")
    assert "torvik" not in out
    assert out["wab_home"] == "+9.5" and out["wab_away"] == "+4.2"
    assert len(json.dumps(out)) < 3000, "one game, not the league"
    assert out["conference_home"] == "", "no conference (a non-D1 opponent) took the snapshot down"
