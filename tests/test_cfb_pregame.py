"""GordStats' pre-game projection is kept, not rebuilt with hindsight.

The matchups page said "GordStats had X going in" for a finished week but
rebuilt the number from today's fit and board, which had seen the games.
cfb.pregame records each projection until the player's kickoff, and the
recorded one stands after it.
"""
import pandas as pd


def _wk(proj, state):
    return pd.DataFrame({"proj_week": proj, "state": state},
                        index=pd.Index(["a", "b"], name="yahoo_id"))


def test_the_last_pre_kickoff_projection_stands_after_kickoff(tmp_path, monkeypatch):
    from cfb import pregame

    monkeypatch.setattr(pregame, "ARCHIVE", tmp_path)
    pregame.freeze(6, _wk([10.0, 20.0], ["pre", "pre"]), season=2026)
    pregame.freeze(6, _wk([12.0, 21.0], ["pre", "pre"]), season=2026)   # news moved it

    # Kickoff for "a"; today's fit now says 30 after watching him.
    got = pregame.freeze(6, _wk([30.0, 22.0], ["in", "pre"]), season=2026)
    assert got.loc["a", "proj_week"] == 12.0, "hindsight replaced the pre-game number"
    assert got.loc["b", "proj_week"] == 22.0, "an unstarted player follows the news"
    assert pregame.complete(got)


def test_a_week_started_before_the_archive_is_not_called_going_in(tmp_path, monkeypatch):
    from cfb import pregame

    monkeypatch.setattr(pregame, "ARCHIVE", tmp_path)
    got = pregame.freeze(5, _wk([30.0, 22.0], ["post", "post"]), season=2026)
    assert list(got["proj_week"]) == [30.0, 22.0]
    assert not pregame.complete(got)


def test_nfl_accuracy_scores_gordstats_only_on_numbers_kept_before_kickoff(tmp_path, monkeypatch):
    """Rebuilt after the games, our number had seen them - and it was scored
    against sources whose pre-game numbers were kept."""
    from fantasy import pregame
    from fantasy.site import matchups as page

    monkeypatch.setattr(pregame, "ARCHIVE", tmp_path)
    data = {"week": 3, "games": [], "matchups": [{"sides": [
        {"roster_id": 1, "starters": ["a"], "players_points": {"a": 20.0}}]}]}
    monkeypatch.setattr(page.data_mod, "week_final", lambda d: True)
    monkeypatch.setattr(page, "outside_sources", lambda d: {"sleeper": {"a": 15.0}})
    monkeypatch.setattr(page, "injury_status", lambda d: {})
    monkeypatch.setattr(page.data_mod, "week_projections", lambda board, games, injuries=None:
                        pd.DataFrame({"proj_week": [19.9], "state": ["post"]},
                                     index=pd.Index(["a"], name="sleeper_id")))
    table = page.accuracy({3: data}, {"board_frame": None})
    assert "gordstats" not in set(table["source"]), "a hindsight number was scored"

    pregame.path(3).parent.mkdir(parents=True)
    pregame.path(3).write_text('{"a": 12.0}')
    table = page.accuracy({3: data}, {"board_frame": None}).set_index("source")
    assert table.loc["gordstats", "mae"] == 8.0
