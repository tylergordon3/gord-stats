"""College basketball in season: the pieces that had never run on the Pi.

The pipeline was run by hand in 2025-26, so its early-season paths were never
exercised: a non-D1 opponent crashed the scoreboard, "last ten" meant last
March, last season's NET was filed as today's, and nothing pushed the live
board at all.
"""
import json
import re
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


@pytest.mark.parametrize("failed, ran", [
    ([], ["M", "W", "archive"]),
    # Torvik's women's tables not out: the men's bracketology (and its ranks
    # on the scoreboard) goes on without them, and the task still says so.
    (["Women's Torvik"], ["M", "archive"]),
    (["Men's Torvik", "KenPom"], ["W", "archive"]),
    (["KenPom", "Women's Torvik"], []),
])
def test_each_league_waits_only_for_its_own_feeds(monkeypatch, failed, ran):
    from datetime import date as d

    from cbb import daily_data, lines, predictions
    from cbb.render import render_conferences, render_home
    from cbb.tools import archive_predictions
    from gordstats import daily

    monkeypatch.setattr(render_home, "CBB_TIPOFF", d(2000, 1, 1))
    monkeypatch.setattr(render_home, "CBB_SEASON_END", d(2100, 1, 1))
    monkeypatch.setattr(lines, "publish", lambda: 0)
    monkeypatch.setattr(daily_data, "failures", lambda: list(failed))
    calls = []
    monkeypatch.setattr(predictions, "predict", lambda day: (None, "men"))
    monkeypatch.setattr(predictions, "predict_womens", lambda day: (None, "women"))
    monkeypatch.setattr(render_conferences, "main", lambda df, g: calls.append(g))
    monkeypatch.setattr(archive_predictions, "archive", lambda: calls.append("archive"))
    if failed:
        with pytest.raises(RuntimeError, match=failed[0]):
            daily._cbb()
    else:
        daily._cbb()
    assert calls == ran


def test_every_feed_belongs_to_a_league():
    import inspect

    from cbb import daily_data
    names = set(re.findall(r'"([^"]+)"\s*:\s*\(paths\.', inspect.getsource(daily_data.failures)))
    assert names == set(daily_data.LEAGUE), names


def test_last_seasons_ats_records_are_refused(monkeypatch):
    """TeamRankings shows last season's final records until it turns to the
    new one; they used to be filed under November's dates and shown on the
    scoreboard as this season's (found by the 2026-10-03 rehearsal)."""
    from cbb.scrape import ats, net

    page = ("<html><select><option value='yearly_2025_2026' SELECTED>2025-2026</option>"
            "<option value='yearly_2024_2025'>2024-2025</option></select>"
            "<table><tr><th>Team</th><th>ATS Record</th></tr>"
            "<tr><td>Howard</td><td>22-8-1</td></tr></table></html>")

    class Page:
        content = page.encode()
    monkeypatch.setattr(ats.requests, "get", lambda *a, **k: Page())
    with pytest.raises(net.NotReleased, match="2026-27"):
        ats.parse_to_df("https://example.test/ats", 2027)
    df = ats.parse_to_df("https://example.test/ats", 2026)
    assert list(df["Team"]) == ["Howard"]


def test_the_scoreboard_carries_trank_beside_gordstats_rank(monkeypatch, tmp_path):
    """GordStats' rank is blank until the bracketology has the season's
    inputs; T-Rank's rides along so the watch guide has something to rank
    opening night on (the 2026-10-03 rehearsal: every game scored ~6)."""
    import pandas as pd

    from cbb import game_model, live_scraper
    from cbb.render import render_power

    monkeypatch.setattr(live_scraper.season, "get_last_x", lambda g, t, x: "")
    master = pd.DataFrame({"team": ["Duke", "Kansas"], "index": [0, 1],
                           "names": [["DUKE", "Duke"], ["KU", "Kansas"]], "short": ["Duke", "KU"]})
    g = {"home_team": {"abbreviation": "DUKE"}, "away_team": {"abbreviation": "KU"},
         "game_date": "Mon, 02 Nov 2026 19:00:00 -0500", "status": "pre_game"}
    out = live_scraper.format_event(g, {}, master, None, None, None, None, "M", None,
                                    {"Duke": 1, "Kansas": 9})
    assert out["home_model"] == "" and (out["home_trank"], out["away_trank"]) == (1, 9)
    # From the league's T-Rank cache, this season's only; the women's their own.
    men, women = tmp_path / "m.csv", tmp_path / "w.csv"
    men.write_text("rank,team,adjoe\n1,Duke,120\n2,SIU Edwardsville,100\n")
    monkeypatch.setattr(render_power, "_cache_path", lambda: men)
    monkeypatch.setattr(render_power, "_cache_path_w", lambda: women)
    monkeypatch.setattr(render_power, "TRANK_YEAR", 2027)
    assert game_model.trank_ranks("M", date(2026, 11, 2)) == {"Duke": 1, "SIUE": 2}
    assert game_model.trank_ranks("W", date(2026, 11, 2)) == {}
    assert game_model.trank_ranks("M", date(2027, 11, 2)) == {}, "last season's table"


def test_a_time_tba_game_is_not_a_one_oclock_tip(monkeypatch):
    """theScore files a game with no time yet at 18:00 UTC with `tba` set: 83
    of the 180 men's games on the 2026 opening Monday, a month out. They were
    "1:00 PM" on the scoreboard, My teams, the guides and the previews."""
    import pandas as pd

    from cbb import live_scraper
    from cbb.render import render_previews, render_watch

    monkeypatch.setattr(live_scraper.season, "get_last_x", lambda g, t, x: "")
    master = pd.DataFrame({"team": ["Duke", "Kansas"], "index": [0, 1],
                           "names": [["DUKE", "Duke"], ["KU", "Kansas"]], "short": ["Duke", "KU"]})
    g = {"home_team": {"abbreviation": "DUKE"}, "away_team": {"abbreviation": "KU"},
         "game_date": "Mon, 02 Nov 2026 18:00:00 -0000", "status": "pre_game", "tba": True}
    out = live_scraper.format_event(g, {}, master, None, None, None, None, "M", None,
                                    {"Duke": 1, "Kansas": 9})
    assert out["tba"] is True and out["start_time"] == "TBA" and out["date"] == "2026-11-02"
    assert out["start_time_utc"].startswith("2026-11-02T18:00")     # the day's anchor
    timed = live_scraper.format_event(dict(g, tba=False), {}, master, None, None, None, None,
                                      "M", None)
    assert timed["tba"] is False and timed["start_time"] == "1:00 PM"
    # The all-sports file and the previews take it as a time TBA.
    now = pd.Timestamp("2026-11-02 09:00", tz="America/New_York")
    hoops = render_watch.games({"men": {"5": out}}, now)
    assert hoops[0]["tk"] is False and hoops[0]["slot"] == "tba" and hoops[0]["day"] == "2026-11-02"
    for js in (render_watch.ADAPTER_JS, __import__("gordstats.my_teams_today").my_teams_today.JS):
        assert "g.tba!==true" in js
    data = {"feed": {"men": {"5": dict(out, home_win_prob=0.9)}}, "trank": {"Duke": 1, "Kansas": 9}}
    assert render_previews.build(data, now)[0]["tk"] is False


def test_cbb_home_says_the_bracket_is_last_seasons_until_this_seasons(tmp_path, monkeypatch):
    from cbb import paths as cbb_paths
    from cbb.render import render_home

    monkeypatch.setattr(cbb_paths, "WEB_M_DIR", tmp_path)
    (tmp_path / "predict_2026-03-15.html").write_text("")
    assert "Last season" in render_home._waiting_note(date(2026, 11, 2))
    (tmp_path / "predict_2026-11-12.html").write_text("")
    assert render_home._waiting_note(date(2026, 11, 12)) == ""
