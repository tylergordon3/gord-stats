"""
The projected NFL playoff field (nfl.playoff): the tiebreak rules on
hand-set standings - head-to-head, division record, conference record, the
three-club sweep, the one-club-per-division wild-card rule and the restart
when a step separates only part of a tie - then a whole 32-team season that
gives one field, the same each time it is run. No network.
"""
import numpy as np
import pandas as pd
import pytest

from nfl import playoff
from nfl.playoff import League

# One conference: four divisions of four, local index = position.
DIVS = ["E"] * 4 + ["N"] * 4 + ["S"] * 4 + ["W"] * 4
MEMBERS = np.arange(16)


def standings(pct, div=None, conf=None, beat=(), coin=None):
    """One run's standings: win share overall, in the division and in the
    conference per team (default .5), and `beat` as (winner, loser) games."""
    def row(values):
        out = np.full((1, 16), 0.5)
        for t, v in (values or {}).items():
            out[0, t] = v
        return out
    st = {"all": row(pct), "div": row(div), "conf": row(conf)}
    wins = np.zeros((1, 16, 16), np.float32)
    met = np.zeros((16, 16), np.float32)
    for w, l in beat:
        wins[0, w, l] += 1
        met[w, l] += 1
        met[l, w] += 1
    st["beat"], st["met"] = wins, met
    flip = np.linspace(0.9, 0.1, 16)[None, :] if coin is None else np.array([coin])
    return st, flip


def seeds(pct, **kw):
    st, flip = standings(pct, **kw)
    return list(playoff.seed_conference(st, MEMBERS, DIVS, flip)[0])


# Everyone else well back, so the cases below decide the seeds they test.
BASE = {t: 0.30 for t in range(16)}
LEADERS = {0: 0.80, 4: 0.75, 8: 0.70, 12: 0.65}      # four clear division winners


def test_division_winners_are_seeded_by_record_and_wild_cards_follow():
    pct = {**BASE, **LEADERS, 1: 0.78, 5: 0.60, 13: 0.55}
    s = seeds(pct)
    assert s[:4] == [0, 4, 8, 12]
    # 1 has a better record than two division winners - and is still a wild card.
    assert s[4:] == [1, 5, 13]


def test_head_to_head_settles_a_division():
    pct = {**BASE, **LEADERS, 1: 0.80}
    # 1 swept 0, though 0 has the better division and conference records.
    s = seeds(pct, div={0: 0.83, 1: 0.67}, conf={0: 0.75}, beat=[(1, 0), (1, 0)])
    assert s[0] == 1 and 0 in s[4:]


def test_a_split_goes_to_division_record_then_conference_record():
    pct = {**BASE, **LEADERS, 1: 0.80}
    split = [(1, 0), (0, 1)]
    assert seeds(pct, div={0: 0.67, 1: 0.83}, beat=split)[0] == 1
    assert seeds(pct, div={0: 0.67, 1: 0.67}, conf={0: 0.75, 1: 0.70}, beat=split)[0] == 0


def test_the_coin_is_last():
    pct = {**BASE, **LEADERS, 1: 0.80}
    coin = list(np.linspace(0.1, 0.9, 16))          # 1 now wins the toss over 0
    assert seeds(pct, coin=coin)[0] == 1
    assert seeds(pct)[0] == 0


def test_a_wild_card_tie_inside_one_division_is_settled_there_first():
    """1 and 2 (East) and 5 (North) level for the last spot. 1 beat 2, so 1
    goes into the comparison and 2 does not - and 5 beat 1. The naive
    three-way mini-league would be 1-1 all round and hand it to 2 on
    conference record; the NFL's procedure gives it to 5."""
    pct = {**BASE, **LEADERS, 9: 0.62, 13: 0.62, 1: 0.55, 2: 0.55, 5: 0.55}
    s = seeds(pct, conf={2: 0.80, 1: 0.50, 5: 0.50}, beat=[(1, 2), (5, 1), (2, 5)])
    assert s[4:6] == [9, 13] or s[4:6] == [13, 9]
    assert s[6] == 5


def test_three_clubs_go_by_a_sweep_only():
    """Three wild-card clubs from different divisions, level. 5 beat both
    others: a sweep, so 5 goes first whatever the conference records say.
    Without a sweep (no one beat both), head-to-head is skipped and the
    conference record decides."""
    pct = {**BASE, **LEADERS, 1: 0.55, 5: 0.55, 9: 0.55}
    conf = {1: 0.75, 5: 0.40, 9: 0.60}
    swept = seeds(pct, conf=conf, beat=[(5, 1), (5, 9)])
    assert swept[4] == 5
    no_sweep = seeds(pct, conf=conf, beat=[(5, 1), (9, 5)])
    assert no_sweep[4] == 1
    # Once 1 is through, 5 and 9 are two clubs - and 9 beat 5.
    assert no_sweep[5] == 9


def test_two_wild_cards_go_by_head_to_head_when_they_met():
    pct = {**BASE, **LEADERS, 1: 0.55, 5: 0.55}
    assert seeds(pct, conf={1: 0.90, 5: 0.40}, beat=[(5, 1)])[4] == 5


# --------------------------------------------------------------------------- #
# A whole league
# --------------------------------------------------------------------------- #

def _league(played: bool, round_robin: bool = False) -> League:
    """32 teams. By default each plays its division twice, one other
    division of its conference and one of the other conference - fourteen
    games, results where played to the better rating plus home field. With
    `round_robin` everyone plays its whole conference once and the better
    team always wins, so every record in a conference is different and a
    finished season has exactly one field."""
    teams = sorted(playoff.DIVISIONS, key=lambda t: (playoff.DIVISIONS[t], int(t)))
    div = [playoff.DIVISIONS[t] for t in teams]
    conf = [d.split()[0] for d in div]
    by_div = {}
    for i, d in enumerate(div):
        by_div.setdefault(d, []).append(i)
    rating = np.linspace(30, -30, 32) if round_robin else np.linspace(8, -8, 32)
    edge = 1.0 if round_robin else 2.0
    games = []
    if round_robin:
        for x in range(32):
            for y in range(x + 1, 32):
                if conf[x] == conf[y]:
                    games.append((x, y) if (x + y) % 2 else (y, x))
    else:
        for members in by_div.values():
            games += [(x, y) for x in members for y in members if x != y]
        pairs = [("AFC East", "AFC North"), ("AFC South", "AFC West"),
                 ("NFC East", "NFC North"), ("NFC South", "NFC West"),
                 ("AFC East", "NFC West"), ("AFC North", "NFC South"),
                 ("AFC South", "NFC North"), ("AFC West", "NFC East")]
        for a, b in pairs:
            for k, x in enumerate(by_div[a]):
                for m, y in enumerate(by_div[b]):
                    games.append((x, y) if (k + m) % 2 else (y, x))
    rows = []
    for h, a in games:
        margin = rating[h] - rating[a] + edge
        result = (1.0 if margin > 0 else 0.0) if played else np.nan
        rows.append({"home": h, "away": a, "neutral": False, "played": played,
                     "result": result, "mean": margin, "ahead": 1})
    return League(teams=teams, names={t: (f"T{t}", f"A{t}") for t in teams},
                  conf=conf, div=div, rating=rating, home_edge=edge,
                  margin_sd=13.0, games=pd.DataFrame(rows), ahead=1)


def test_a_finished_season_gives_one_field_the_same_every_time():
    lg = _league(True, round_robin=True)
    res = playoff.simulate(lg, n=400, seed=11)
    assert set(np.unique(res.playoff)) <= {0.0, 1.0}
    assert res.playoff.sum() == pytest.approx(14.0)
    assert res.division.sum() == pytest.approx(8.0)
    assert res.top_seed.sum() == pytest.approx(2.0)
    assert res.title.sum() == pytest.approx(1.0)
    assert res.conf_title.sum() == pytest.approx(2.0)
    bracket = playoff.projected_bracket(res)
    for conf, order in bracket.items():
        assert len(set(order)) == 7
        for s, i in enumerate(order):
            assert res.seed_count[i, s] == 400       # one seed, every run
        # Ratings fall down the list, so the conference's first division
        # (East) has the best four records: its winner is the 1 seed and the
        # other three are the wild cards, below three worse division winners.
        east = [i for i in range(32) if lg.div[i] == f"{conf} East"]
        assert order[0] == east[0] and order[4:] == east[1:]
    again = playoff.simulate(lg, n=400, seed=11)
    assert np.array_equal(res.title, again.title)


def test_a_played_playoff_game_is_decided_as_it_was():
    """The 2 seed lost its wild-card game: it cannot reach the Super Bowl,
    and the 7 seed that beat it is through."""
    lg = _league(True, round_robin=True)
    afc = playoff.projected_bracket(playoff.simulate(lg, n=100, seed=2))["AFC"]
    two, seven = afc[1], afc[6]
    lg.results = {(two, seven): seven}
    res = playoff.simulate(lg, n=300, seed=2)
    assert res.title[two] == 0 and res.conf_title[two] == 0
    assert res.conf_title[seven] > 0


def test_a_season_to_play_adds_up_and_repeats():
    lg = _league(False)
    a = playoff.simulate(lg, n=500, seed=4)
    b = playoff.simulate(lg, n=500, seed=4)
    for field in ("playoff", "division", "top_seed", "conf_title", "title"):
        assert np.array_equal(getattr(a, field), getattr(b, field))
    assert a.playoff.sum() == pytest.approx(14.0)
    assert a.title.sum() == pytest.approx(1.0)
    # Every division has exactly one winner per run.
    for d in set(lg.div):
        assert a.division[[i for i in range(32) if lg.div[i] == d]].sum() == pytest.approx(1.0)


def test_records_count_a_tie_as_a_tie():
    lg = _league(True)
    lg.games.loc[0, "result"] = 0.5
    h, a = int(lg.games.loc[0, "home"]), int(lg.games.loc[0, "away"])
    rec = playoff.records(lg)
    assert rec[h][2] == 1 and rec[a][2] == 1
