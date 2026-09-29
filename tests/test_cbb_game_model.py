"""College basketball game predictions (cbb.game_model): Torvik's adjusted
efficiencies and tempo, the possession model, and constants fitted on a
finished season walked forward."""
import pytest

from cbb import game_model, paths

TABLE = {"Duke": (120.0, 90.0, 70.0), "Kansas": (110.0, 95.0, 66.0),
         "Even": (105.0, 105.0, 68.0)}


def test_the_better_side_is_favoured_and_home_court_counts():
    home = game_model.predict("Duke", "Kansas", TABLE)
    away = game_model.predict("Kansas", "Duke", TABLE)
    level = game_model.predict("Duke", "Kansas", TABLE, neutral=True)
    assert home["home_win_prob"] > level["home_win_prob"] > 0.5 > away["home_win_prob"]
    edge = game_model.FIT["M"]["home_edge"]
    margin = lambda p: p["pred_home"] - p["pred_away"]
    assert abs(margin(home) - margin(level) - edge) <= 0.15      # points rounded to 0.1
    # Home court moves the margin, not the total.
    assert abs(sum((home["pred_home"], home["pred_away"]))
               - sum((level["pred_home"], level["pred_away"]))) <= 0.15


def test_an_unrated_side_has_no_call():
    assert game_model.predict("Duke", "Lynchburg", TABLE) is None


def test_torvik_names_become_the_sites():
    snap = {"headers": ["Rk", "Team", "AdjOE", "AdjDE", "Adj T."],
            "rows": [["1", "SIU Edwardsville", "101.0", "99.0", "67.0"],
                     ["2", "Duke (1)", "128.1", "90.8", "65.8"]]}
    assert set(game_model.ratings(snap)) == {"SIUE", "Duke"}


@pytest.mark.skipif(not paths.M_SCHEDULE.exists(), reason="no 2025-26 season on disk")
def test_the_constants_are_last_seasons_fit():
    """Walked forward over 2025-26: every D-1 game from the last ratings
    published before it. If the model changes, refit FIT from this."""
    got = game_model.backtest()
    fit = game_model.FIT["M"]
    assert got["games"] > 5000 and got["winners"] > 0.69
    assert abs(got["home_edge"] - fit["home_edge"]) < 0.05
    assert abs(got["scale"] - fit["scale"]) < 0.01 and abs(got["margin_sd"] - fit["sd"]) < 0.05


def test_the_scoreboard_carries_the_call(monkeypatch):
    import pandas as pd
    from cbb import live_scraper
    monkeypatch.setattr(live_scraper.season, "get_last_x", lambda g, t, x: "")
    master = pd.DataFrame({"team": ["Duke", "Kansas"], "index": [0, 1],
                           "names": [["DUKE", "Duke"], ["KU", "Kansas"]], "short": ["Duke", "KU"]})
    g = {"home_team": {"abbreviation": "DUKE", "division": "NCAA Division I"},
         "away_team": {"abbreviation": "KU", "division": "NCAA Division I"},
         "game_date": "Tue, 10 Nov 2026 19:00:00 -0500", "status": "pre_game"}
    out = live_scraper.format_event(g, {}, master, None, None, None, None, "M", TABLE)
    assert out["home_win_prob"] > 0.5 and out["neutral"] is False
    assert out["pred_home"] > out["pred_away"]
    mte = live_scraper.format_event(dict(g, tournament_name="Maui Invitational"), {}, master,
                                    None, None, None, None, "M", TABLE)
    assert mte["neutral"] and mte["home_win_prob"] < out["home_win_prob"], "no home court at Maui"
    none = live_scraper.format_event(g, {}, master, None, None, None, None, "M", None)
    assert none["home_win_prob"] is None, "no ratings yet, no call"


def test_before_the_daily_tables_the_men_use_trank(tmp_path, monkeypatch):
    """No Torvik snapshot of this season yet (the daily scrape starts at
    tipoff): the men's calls come from T-Rank's own table, the power page's
    cache - and never from a previous season's."""
    from datetime import date
    from cbb import paths as cbb_paths
    from cbb.render import render_power
    csv = tmp_path / "trank_2027.csv"
    csv.write_text("team,adjoe,adjde,adjt\nDuke,125,92,68\nSIU Edwardsville,100,104,66\n")
    monkeypatch.setattr(render_power, "_cache_path", lambda: csv)
    monkeypatch.setattr(render_power, "TRANK_YEAR", 2027)
    monkeypatch.setattr(cbb_paths, "M_TOR_DIR", tmp_path / "none")
    table = game_model.today_table("M", date(2026, 11, 1))
    assert set(table) == {"Duke", "SIUE"}
    assert game_model.today_table("M", date(2027, 11, 1)) == {}, "a stale season's T-Rank"
    assert game_model.today_table("W", date(2026, 11, 1)) == {}
