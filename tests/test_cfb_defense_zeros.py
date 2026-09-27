"""A position held to nothing is a game played, at zero points.

Box scores have no row for a position that did nothing, so a defence that held
tight ends scoreless lost that game from its average and its game count alike:
132 of 228 defences had one, and stingy read as generous.
"""
import pandas as pd


def test_a_scoreless_position_counts_as_a_zero_not_a_missing_game(monkeypatch):
    from cfb import defense

    box = pd.DataFrame([
        # game 1: offence 10's TE catches 5 for 50 against defence 20
        {"game_id": "1", "team_id": "10", "opp_id": "20", "pos": "TE", "rec": 5, "rec_yds": 50},
        {"game_id": "1", "team_id": "20", "opp_id": "10", "pos": "QB", "pass_yds": 200},
        # game 2: offence 11 plays defence 20; only its QB scored
        {"game_id": "2", "team_id": "11", "opp_id": "20", "pos": "QB", "pass_yds": 250},
        {"game_id": "2", "team_id": "20", "opp_id": "11", "pos": "QB", "pass_yds": 150},
    ])
    frame = pd.DataFrame([
        {"game_id": "1", "home_id": "10", "away_id": "20", "pred_home": 28.0, "pred_away": 21.0},
        {"game_id": "2", "home_id": "11", "away_id": "20", "pred_home": 24.0, "pred_away": 17.0},
    ])
    monkeypatch.setattr(defense.boxscores, "load", lambda season=None: box)
    monkeypatch.setattr(defense.predict, "season", lambda: (frame, None, None))
    league = {"stat_modifiers": {}}
    monkeypatch.setattr(defense.players, "fantasy_points",
                        lambda df, lg: df.get("rec", 0).fillna(0) + df.get("rec_yds", 0).fillna(0) / 10)

    got = defense.allowed(league=league)
    te = got[(got["defense"] == "20") & (got["pos"] == "TE")].sort_values("game_id")
    assert list(te["game_id"]) == ["1", "2"], "the scoreless game went missing"
    assert list(te["points"]) == [10.0, 0.0]
