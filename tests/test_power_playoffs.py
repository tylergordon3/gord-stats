"""Played playoff weeks are taken as they happened.

The power simulation drew the fantasy bracket from scratch every time, so
after week 14 a team knocked out in week 15 kept its title odds into January.
Checked against the real brackets of 2023-24, 2024-25 and 2025-26: replayed
with their fourteen weeks and their playoff scores, each season's actual
champion comes out at 100%, against 30-38% for the favourite without them.
"""
import numpy as np
import pandas as pd

from fantasy.league import power

TEAMS = 10


def _league():
    rows, held = [], []
    pid = 0
    for team in range(TEAMS):
        for pos in ("QB", "RB", "RB", "WR", "WR", "WR", "TE", "K", "DEF"):
            pid += 1
            rows.append({"sleeper_id": str(pid), "pos": pos, "bye": 7, "mu": 10.0,
                         "sd": 5.0, "mu_se": 1.0, "avail": 0.9})
            held.append({"roster_id": team + 1, "sleeper_id": str(pid)})
    return pd.DataFrame(rows), pd.DataFrame(held)


def _schedule(weeks):
    table, rotating = [], list(range(1, TEAMS))
    for _ in range(weeks):
        pairs = [(0, rotating[0])] + [(rotating[i], rotating[-i]) for i in range(1, TEAMS // 2)]
        week = [0] * TEAMS
        for a, b in pairs:
            week[a], week[b] = b, a
        table.append(week)
        rotating = rotating[1:] + rotating[:1]
    return np.array(table)


def test_the_played_bracket_decides_the_title():
    board, rosters = _league()
    weeks = power.FANTASY_REG_WEEKS
    # Team i scores 100 + i every week, so the seeds are the top six indices,
    # 9 first: the sixth seed is index 4.
    regular = np.tile(100.0 + np.arange(TEAMS), (weeks, 1))
    playoff = np.full((power.PLAYOFF_WEEKS, TEAMS), 100.0)
    playoff[:, 4] = 200.0                     # the sixth seed wins every round

    got = power.simulate(board, rosters, sims=200, fixed_schedule=_schedule(weeks),
                         actual_points=regular, playoff_points=playoff)
    odds = dict(zip(got["roster_id"], got["title_odds"]))
    assert odds[5] == 1.0, odds
    assert sum(odds.values()) == 1.0


def test_playoff_points_read_only_the_weeks_sleeper_has_passed(monkeypatch):
    asked = []

    def get(url):
        asked.append(url.rsplit("/", 1)[-1])
        return [{"roster_id": 2, "points": 120.5}, {"roster_id": 9, "points": None}]

    monkeypatch.setattr(power, "_get", get)
    got = power.playoff_points([1, 2, 9], over=15, league_id="x")
    assert asked == ["15"] and got.tolist() == [[0.0, 120.5, 0.0]]
    assert power.playoff_points([1, 2], over=14, league_id="x") is None
