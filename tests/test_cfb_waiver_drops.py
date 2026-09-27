"""The waiver page's "drop" suggestions put ruled-out players first - not
anyone with a tag. Questionable and probable play, and their projection stands
(weekly.STATUS_FACTOR), but the list used to sort every tagged player ahead of
the bench: a Q starter projecting 21 points was offered up before a bench
receiver projecting nothing.
"""
import pandas as pd


def test_a_questionable_starter_is_not_a_drop_ahead_of_dead_weight():
    from cfb import waivers

    held = pd.DataFrame([
        {"team_key": "t", "pos": "RB", "status": "Q", "proj": 21.0, "player": "starter"},
        {"team_key": "t", "pos": "WR", "status": "P", "proj": 14.0, "player": "probable"},
        {"team_key": "t", "pos": "WR", "status": "", "proj": 0.0, "player": "nobody"},
        {"team_key": "t", "pos": "WR", "status": "O", "proj": 0.0, "player": "out"},
        {"team_key": "t", "pos": "TE", "status": None, "proj": 3.0, "player": "bench te"},
    ])
    got = list(waivers.drops(held, per_team=3)["player"])
    assert got == ["out", "nobody", "bench te"]


def test_ruled_out_means_worth_nothing_this_week():
    from cfb import waivers

    assert waivers.ruled_out("O") and waivers.ruled_out("IR") and waivers.ruled_out("SUSP")
    assert not waivers.ruled_out("Q") and not waivers.ruled_out("P")
    assert not waivers.ruled_out("D"), "doubtful still plays one game in four"
    assert not waivers.ruled_out("") and not waivers.ruled_out(None)
