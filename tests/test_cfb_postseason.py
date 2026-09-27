"""Bowls and the CFP are part of the season, as week 20 - "Bowls".

The CFB section read ESPN's regular season only, so it went quiet after the
conference title games: no bowl predictions, lines, grading or scores through
January. ESPN files the postseason as seasontype 3, week 1 and CFBD as
seasonType=postseason, week 1; espn.query / cfbd._week translate. Bowls stay
out of the model's training, as the historical archive always kept them.
"""
import pandas as pd


def test_week_twenty_is_espns_postseason():
    from cfb import cfbd, espn

    assert espn.query(espn.POSTSEASON_WEEK) == {"week": 1, "seasontype": 3}
    assert espn.query(7) == {"week": 7, "seasontype": 2}
    assert cfbd._week(espn.POSTSEASON_WEEK) == {"week": 1, "seasonType": "postseason"}
    assert espn.week_label(espn.POSTSEASON_WEEK) == "Bowls" and espn.week_label(3) == "Week 3"


def test_the_calendar_ends_with_the_bowls(monkeypatch):
    from cfb import espn

    calendar = [
        {"label": "Regular Season", "entries": [
            {"value": "1", "label": "Week 1", "startDate": "2026-08-25", "endDate": "2026-09-01"}]},
        {"label": "Postseason", "entries": [
            {"value": "1", "label": "Bowls", "startDate": "2026-12-13", "endDate": "2027-01-28"},
            {"value": "999", "label": "CFP", "startDate": "2026-12-18", "endDate": "2027-01-27"}]},
        {"label": "Off Season", "entries": []},
    ]
    monkeypatch.setattr(espn, "_get", lambda params: {"leagues": [{"calendar": calendar}]})
    weeks = espn.weeks()
    assert [w["week"] for w in weeks] == [1, espn.POSTSEASON_WEEK]
    assert weeks[-1]["label"] == "Bowls" and weeks[-1]["end"] == "2027-01-28"


def test_bowls_do_not_train_the_model(monkeypatch):
    from cfb import espn, predict

    schedule = pd.DataFrame([
        {"week": 14, "state": "post", "home_score": 31.0, "away_score": 24.0, "home_id": "1"},
        {"week": espn.POSTSEASON_WEEK, "state": "post", "home_score": 28.0, "away_score": 27.0,
         "home_id": "2"},
        {"week": 3, "state": "post", "home_score": 0.0, "away_score": 0.0, "home_id": "3"},
    ])
    monkeypatch.setattr(espn, "schedule", lambda: schedule)
    got = predict._current_season_games()
    assert list(got["home_id"]) == ["1"], "a bowl or a cancelled 0-0 game trained the model"


def test_the_scoreboard_polls_the_postseason_as_espn_files_it():
    from cfb import espn
    from cfb.site import schedule

    assert schedule._live_url(espn.POSTSEASON_WEEK).endswith("week=1&dates=2026&seasontype=3")
    assert schedule._live_url(5).endswith("week=5&dates=2026&seasontype=2")


def test_a_bowl_without_its_teams_gets_no_prediction():
    """ESPN lists all 47 bowls from September with both sides TBD (-1, -2)."""
    from cfb import predict

    ids = pd.Series(["333", "-1", "-2", "2"])
    assert list(predict._placeholder(ids)) == [False, True, True, False]
