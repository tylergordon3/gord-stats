"""The CFB projection scorecard: GordStats against Yahoo, fairly.

Both scored on the same player-weeks - starters who played, in finished
weeks, whom both projected before kickoff. Ours comes only from the pre-game
archive: a projection rebuilt after the games has seen them.
"""
import json

import pytest

from cfb import pregame
from cfb.site import matchups as mu


def _week(status="postevent", players=()):
    return {"matchups": [{"status": status}],
            "yahoo_proj": {pid: y for pid, _slot, _pts, _played, y in players if y is not None},
            "rosters": {"t1": [{"yahoo_id": pid, "slot": slot, "points": pts,
                                "stats": {"4": 1.0} if played else {}}
                               for pid, slot, pts, played, _y in players]}}


@pytest.fixture
def archive(tmp_path, monkeypatch):
    monkeypatch.setattr(pregame, "path", lambda week, season=None: tmp_path / f"w{week}.json")
    return lambda week, got: (tmp_path / f"w{week}.json").write_text(json.dumps(got))


def test_before_a_kept_week_yahoo_stands_alone(archive):
    datas = {1: _week(players=[("a", "QB", 20.0, True, 18.0), ("b", "BN", 30.0, True, 10.0)])}
    table, weeks, closer = mu.accuracy(datas)
    assert list(table["source"]) == ["yahoo"] and table["n"].tolist() == [1], "bench is out"
    assert closer is None and "week 5 is the first" in mu.accuracy_section(datas)


def test_both_on_the_same_players_and_who_was_closer(archive):
    archive(5, {"a": 22.0, "c": 5.0, "d": 9.0})
    datas = {
        5: _week(players=[("a", "QB", 20.0, True, 18.0),     # ours miss 2, theirs 2 -> tie
                          ("c", "RB", 10.0, True, 14.0),     # ours 5, theirs 4 -> Yahoo
                          ("d", "WR", 10.0, True, 12.0),     # ours 1, theirs 2 -> us
                          ("e", "TE", 8.0, True, 7.0),       # not kept before kickoff: out
                          ("f", "WR", 0.0, False, 9.0)]),    # did not play: out
        6: _week(status="midevent", players=[("a", "QB", 5.0, True, 18.0)]),   # not final
    }
    table, weeks, closer = mu.accuracy(datas)
    got = table.set_index("source")
    assert weeks == [5] and set(got["n"]) == {3}
    assert got.loc["gordstats", "mae"] == pytest.approx((2 + 5 + 1) / 3)
    assert got.loc["yahoo", "mae"] == pytest.approx((2 + 4 + 2) / 3)
    assert got.loc["average", "mae"] == pytest.approx((0 + 0.5 + 0.5) / 3)
    assert closer == pytest.approx((0.5 + 0 + 1) / 3)
    assert "GordStats was closer on <b>50%</b>" in mu.accuracy_section(datas)
