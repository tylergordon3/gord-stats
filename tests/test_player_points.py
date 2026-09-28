"""NFL weekly points: identity joins that cannot multiply rows
(fantasy.stats.player_points).

pandas matches NaN keys to each other, so one nflverse row with no player id
joined every registry row with no gsis_id - 3,279 zero-point "games" a week
in 2026's file. And two players the registry had split in two (gsis_id on
one entry, Sleeper id on another) lost their real points.
"""
import numpy as np
import pandas as pd
import pytest

from fantasy import stats


class _Frame:
    def __init__(self, df):
        self.df = df

    def to_pandas(self):
        return self.df


@pytest.fixture
def stubbed(monkeypatch):
    players = pd.DataFrame({
        "player_id": ["00-1", "00-2", np.nan, "00-3"],
        "player_display_name": ["Alpha One", "Mike Washington Jr.", "Nobody", "Twin Name"],
        "position_group": ["WR", "RB", "WR", "WR"], "position": ["WR", "RB", "WR", "WR"],
        "team": ["SEA", "LV", "SEA", "KC"], "week": [1, 1, 1, 1],
        "fantasy_points": [10.0, 4.1, 0.0, 3.0], "fantasy_points_ppr": [12.0, 4.1, 0.0, 5.0]})
    registry = pd.DataFrame({
        "gsis_id": ["00-1", "00-2", np.nan, np.nan, "00-3", np.nan, np.nan],
        "sleeper_id": ["s1", np.nan, "s2", "s3", np.nan, "t1", "t2"],
        "full_name": ["Alpha One", "Mike Washington Jr.", "Mike Washington", "Loose End",
                      "Twin Name", "Twin Name", "Twin Name"],
        "team": ["SEA", "LV", "LV", "NYJ", "KC", "KC", "KC"]})
    monkeypatch.setattr(stats.nfl, "load_player_stats", lambda season, level: _Frame(players))
    monkeypatch.setattr(stats, "load_registry", lambda: registry)
    monkeypatch.setattr(stats, "defense_points", lambda season: pd.DataFrame())
    monkeypatch.setattr(stats, "kicker_points", lambda rows: pd.Series(0.0, index=rows.index))
    return stats.player_points(2026)


def test_missing_ids_join_nothing(stubbed):
    assert len(stubbed) == 3, "the id-less nflverse row, or the NaN-key join, is back"
    assert "s3" not in set(stubbed["sleeper_id"]), "a registry row with no gsis_id got a game"


def test_a_split_registry_entry_is_matched_on_exact_name_and_team(stubbed):
    got = dict(zip(stubbed["player_display_name"], stubbed["sleeper_id"]))
    assert got["Alpha One"] == "s1"
    assert got["Mike Washington Jr."] == "s2", "Jr. aside, same name, same team"
    assert pd.isna(got["Twin Name"]), "two registry players share the name and team: no guess"
