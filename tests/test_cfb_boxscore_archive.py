"""The box-score archive is added to, never shrunk by a bad run.

`refresh` (which the daily build passes) threw the archive away and refetched
every game of the season - 330 ESPN calls in week 5, four times a day - and
then wrote back only what that run got, so a failed request dropped a game
from defence-vs-position for good.
"""
import pandas as pd


def _setup(tmp_path, monkeypatch, fetched):
    from cfb import boxscores

    schedule = pd.DataFrame([
        {"game_id": "A", "week": 1, "state": "post", "home_score": 21, "away_score": 7},
        {"game_id": "B", "week": 2, "state": "post", "home_score": 30, "away_score": 3},
        {"game_id": "C", "week": 2, "state": "post", "home_score": 14, "away_score": 10},
    ])
    archive = tmp_path / "box.parquet"
    pd.DataFrame([{"game_id": "A", "team_id": "1", "athlete_id": "a1", "rush_yds": 50.0},
                  {"game_id": "B", "team_id": "1", "athlete_id": "b1", "rush_yds": 80.0},
                  {"game_id": "B", "team_id": "1", "athlete_id": "b2", "rush_yds": 5.0}]
                 ).to_parquet(archive, index=False)
    asked = []

    def fetch(game):
        asked.append(game[0])
        return fetched.get(game[0], [])

    monkeypatch.setattr(boxscores.espn, "schedule", lambda: schedule)
    monkeypatch.setattr(boxscores, "path", lambda season=None: archive)
    monkeypatch.setattr(boxscores, "rosters", lambda season=None: {})
    monkeypatch.setattr(boxscores, "_fetch", fetch)
    return boxscores, asked


def test_a_refresh_only_revisits_the_latest_week_and_keeps_what_fails(tmp_path, monkeypatch):
    new_c = [{"game_id": "C", "team_id": "2", "athlete_id": "c1", "rush_yds": 99.0}]
    boxscores, asked = _setup(tmp_path, monkeypatch, {"C": new_c})    # B's refetch fails
    frame = boxscores.capture(refresh=True)

    assert sorted(asked) == ["B", "C"], "week 1 is settled and must not be refetched"
    assert set(frame["game_id"]) == {"A", "B", "C"}
    assert len(frame[frame["game_id"] == "B"]) == 2, "a failed refetch dropped the game"


def test_a_game_that_comes_back_replaces_its_old_rows_whole(tmp_path, monkeypatch):
    corrected = [{"game_id": "B", "team_id": "1", "athlete_id": "b1", "rush_yds": 85.0}]
    boxscores, _ = _setup(tmp_path, monkeypatch, {"B": corrected})
    frame = boxscores.capture(refresh=True)
    b = frame[frame["game_id"] == "B"]
    assert list(b["athlete_id"]) == ["b1"] and float(b["rush_yds"].iloc[0]) == 85.0
