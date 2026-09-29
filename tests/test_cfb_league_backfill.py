"""The college league's power history, backfilled to the draft from what was
known before each week (cfb.league_backfill)."""
from datetime import datetime

import numpy as np
import pandas as pd

from cfb import in_season, league_backfill, league_sim, yahoo


def test_each_week_is_priced_from_the_morning_it_began():
    lg = yahoo.league()
    assert league_backfill.asof(1, lg) == datetime(2026, 9, 2, 12)     # the day before week 1
    assert league_backfill.asof(2, lg) == datetime(2026, 9, 8, 5)      # week 1 ended the 7th


def test_later_games_are_unplayed_and_their_results_hidden(monkeypatch):
    frame = pd.DataFrame({"date": pd.to_datetime(["2026-09-05T20:00Z", "2026-09-12T20:00Z"]),
                          "state": ["post", "post"], "home_score": [30.0, 21.0],
                          "away_score": [10.0, 24.0], "actual_margin": [20.0, -3.0],
                          "played": [True, True]})
    monkeypatch.setattr(league_backfill.predict, "season", lambda asof=None: (frame.copy(), None, None))
    got = league_backfill.frame_asof(datetime(2026, 9, 8, 5))
    assert got.loc[0, "state"] == "post" and got.loc[0, "home_score"] == 30.0
    assert got.loc[1, "state"] == "pre" and np.isnan(got.loc[1, "home_score"])
    assert np.isnan(got.loc[1, "actual_margin"]) and not got.loc[1, "played"]


def test_the_standings_and_points_are_the_weeks_before():
    lg = yahoo.league()
    got = league_sim.regular_season(lg, before=3)
    assert all(w + l == 4 for w, _, l in got.values()), "two weeks, head to head and median"
    played = in_season.yahoo_season(before_week=2)["played"]
    assert played.max() <= 1, "only week 1 counted"


def test_old_method_snapshots_move_aside(tmp_path, monkeypatch):
    monkeypatch.setattr(league_backfill, "HISTORY_DIR", tmp_path)
    (tmp_path / "20260910-050000.csv").write_text("key,rank,team,lineup,vs_avg\nt1,1,A,2500,100\n")
    (tmp_path / "20260920-050000.csv").write_text("key,rank,team,per_week,wk_vs_avg\nt1,1,A,180,5\n")
    assert league_backfill.supersede_old() == ["20260910-050000.csv"]
    assert (tmp_path / "superseded" / "20260910-050000.csv").exists()
    assert (tmp_path / "20260920-050000.csv").exists()
