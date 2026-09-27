"""A title-game rematch has its own line.

Every archived season has a conference title game or two repeating a regular-
season pairing (2025: Texas Tech-BYU, Boise-UNLV, Jax St-Kennesaw). Keyed on
(home, away) alone, the December line wrote over September's - and the cover
ticks and both teams' ATS records with it.
"""
import pandas as pd


def test_the_same_pairing_in_two_weeks_keeps_two_lines(tmp_path, monkeypatch):
    from cfb import odds

    pd.DataFrame([
        {"season": 2026, "week": 4, "captured": "2026-09-20T10:00:00+00:00",
         "home_id": "1", "away_id": "2", "spread": -3.5, "total": 55.5},
        {"season": 2026, "week": 15, "captured": "2026-12-01T10:00:00+00:00",
         "home_id": "1", "away_id": "2", "spread": 2.5, "total": 49.5},
    ]).to_parquet(tmp_path / "2026.parquet", index=False)
    monkeypatch.setattr(odds, "ODDS_DIR", tmp_path)

    board = odds.latest(2026).set_index("week")
    assert board.loc[4, "spread"] == -3.5 and board.loc[15, "spread"] == 2.5

    games = pd.DataFrame({"week": [4, 15], "home_id": ["1", "1"], "away_id": ["2", "2"]})
    joined = games.merge(board.reset_index()[odds.KEY + ["spread"]], on=odds.KEY, how="left")
    assert list(joined["spread"]) == [-3.5, 2.5]
