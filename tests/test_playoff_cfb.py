"""
The projected College Football Playoff (cfb.playoff): the 2026-27 format's
rules on a hand-built league - the four power champions in whatever their
ranking, the best Group of Six team in whether or not it won its league,
Notre Dame in from the top 12, straight seeding with the byes to the top
four - the conference tiebreaks, the fixed bracket, a real field once ESPN
names it, and a fixed seed that gives the same page twice. No network.
"""
import numpy as np
import pandas as pd
import pytest

from cfb import playoff
from cfb.playoff import Format, League


# --------------------------------------------------------------------------- #
# A tiny league
# --------------------------------------------------------------------------- #

CONFS = {"ACC": ["a1", "a2"], "Big 12": ["b1", "b2"], "Big Ten": ["t1", "t2"],
         "SEC": ["s1", "s2"], "American": ["m1", "m2"],
         "Sun Belt": ["e1", "e2", "w1", "w2"], "Independent": ["87", "41"]}
DIVISION = {"e1": "East", "e2": "East", "w1": "West", "w2": "West"}


def league(ratings: dict, games: list, title: dict = None, **kw) -> League:
    """`games`: (home, away, home won: 1/0, or None for unplayed with this
    home win margin as `mean`). Conference games are the ones inside one."""
    teams = [t for members in CONFS.values() for t in members]
    conf = {t: c for c, members in CONFS.items() for t in members}
    index = {t: i for i, t in enumerate(teams)}
    rows = []
    for g in games:
        h, a, won = g[:3]
        mean = g[3] if len(g) > 3 else 0.0
        rows.append({"home": index[h], "away": index[a], "neutral": False,
                     "conf_game": conf[h] == conf[a] and conf[h] != "Independent",
                     "played": won is not None,
                     "home_won": np.nan if won is None else float(won),
                     "mean": mean, "ahead": 1})
    frame = pd.DataFrame(rows, columns=["home", "away", "neutral", "conf_game", "played",
                                        "home_won", "mean", "ahead"])
    return League(teams=teams, names={t: t.upper() for t in teams},
                  conf=[conf[t] for t in teams], division=[DIVISION.get(t, "") for t in teams],
                  rating=np.array([ratings.get(t, 0.0) for t in teams] + [-30.0]),
                  home_edge=3.0, margin_sd=16.0, games=frame, title=title or {}, **kw)


def idx(lg, team):
    return lg.teams.index(team)


# --------------------------------------------------------------------------- #
# Selection and seeding: the 2026-27 rules
# --------------------------------------------------------------------------- #

def _select(order_best_first, champs, fmt=playoff.FORMAT):
    """The field from a ranking (team ids, best first) and champions."""
    lg = league({}, [])
    score = np.zeros((1, len(lg.teams)))
    for rank, t in enumerate(order_best_first):
        score[0, idx(lg, t)] = 100.0 - rank
    champ = {c: np.array([idx(lg, t)]) for c, t in champs.items()}
    seeds = playoff.select(score, champ, lg, fmt)[0]
    return [lg.teams[i] for i in seeds]


RANKING = ["s1", "t1", "a1", "b1", "t2", "s2", "a2", "m2", "e1", "87", "w1", "b2",
           "m1", "e2", "w2", "41"]


def test_the_field_is_twelve_seeded_straight_by_the_ranking():
    """Every champion ranked inside the field: the field is the top twelve
    and seed n is rank n - champions get no bye they did not earn."""
    field = _select(RANKING, {"SEC": "s1", "Big Ten": "t1", "ACC": "a1", "Big 12": "b1"})
    assert field == RANKING[:12]


def test_a_power_champion_ranked_low_is_in_and_seeded_by_its_rank():
    """The Big 12 champion ranked 16th takes the field's last place, as the
    12th seed (straight seeding), and bumps the twelfth-ranked team."""
    ranking = [t for t in RANKING if t != "b2"] + ["b2"]
    field = _select(ranking, {"SEC": "s1", "Big Ten": "t1", "ACC": "a1", "Big 12": "b2"})
    assert len(field) == 12
    assert field[-1] == "b2"
    assert "m1" not in field            # 12th in the ranking, bumped
    assert field[:4] == ["s1", "t1", "a1", "b1"]   # the byes: the top four, b1 not a champion


def test_the_group_of_six_bid_goes_to_the_best_team_champion_or_not():
    """2026: the best Group of Six team holds the bid whether or not it won
    its league. m2 lost the American title game and is 11th - already in -
    so the champions ranked 15th and 16th stay out. Under 2024-25's rule the
    best G6 *champion* (m1, 15th) was in and the 12th-ranked team out."""
    ranking = ["s1", "t1", "a1", "b1", "t2", "s2", "a2", "b2", "87", "41",
               "m2", "e2", "e1", "w2", "m1", "w1"]
    champs = {"SEC": "s1", "Big Ten": "t1", "ACC": "a1", "Big 12": "b1",
              "American": "m1", "Sun Belt": "w1"}
    now = _select(ranking, champs)
    assert now == ranking[:12]
    then = _select(ranking, champs, Format(g6_needs_title=True))
    assert then == ranking[:11] + ["m1"]


def test_a_group_of_six_team_below_the_line_still_takes_the_bid():
    """An eight-team field (the format is constants, so a smaller one tests
    the same rule): the best G6 team ranked 11th takes the last place as the
    8th seed, and the 8th-ranked team is out."""
    ranking = ["s1", "t1", "a1", "b1", "t2", "s2", "a2", "b2", "87", "41",
               "m2", "e1", "w2", "m1", "e2", "w1"]
    champs = {"SEC": "s1", "Big Ten": "t1", "ACC": "a1", "Big 12": "b1"}
    field = _select(ranking, champs, Format(field=8, byes=0, independents=()))
    assert field == ranking[:7] + ["m2"]
    # With Notre Dame's bid (top 12, whatever the field's size) it is in too.
    field = _select(ranking, champs, Format(field=8, byes=0))
    assert field == ranking[:6] + ["87", "m2"]


def test_notre_dame_is_in_from_the_top_twelve_even_past_the_auto_bids():
    """Notre Dame 12th, with the Big 12 champion 13th taking a place: without
    its own bid Notre Dame would be the one squeezed out; with it, the
    11th-ranked team goes instead."""
    ranking = ["s1", "t1", "a1", "t2", "s2", "a2", "m2", "b2", "41", "e1", "w1", "87",
               "b1", "m1", "e2", "w2"]
    champs = {"SEC": "s1", "Big Ten": "t1", "ACC": "a1", "Big 12": "b1"}
    field = _select(ranking, champs)
    assert "87" in field and "b1" in field and "w1" not in field
    assert field[-2:] == ["87", "b1"]       # seeded where they rank
    assert "87" not in _select(ranking, champs, Format(independents=()))
    # 13th is not enough.
    ranking13 = ranking[:11] + ["b1", "87"] + ranking[13:]
    field = _select(ranking13, champs)
    assert "87" not in field and "w1" in field
    # UConn, the other independent, has no bid of its own.
    assert playoff.INDEPENDENT_BIDS == (("87", 12),)


def test_the_2024_rule_gave_the_byes_to_the_four_best_champions():
    """CHAMPION_BYES flips the seeding back to 2024's: the four highest
    champions take 1-4 and everyone else follows in rank order."""
    champs = {"SEC": "s1", "Big Ten": "t1", "ACC": "a2", "Big 12": "b1"}
    field = _select(RANKING, champs, Format(champion_byes=True))
    assert field[:4] == ["s1", "t1", "b1", "a2"]
    assert field[4:7] == ["a1", "t2", "s2"]


def test_the_bracket_is_fixed_one_eight_nine_against_four_five_twelve():
    assert playoff.first_round(12, 4) == [(5, 12), (6, 11), (7, 10), (8, 9)]
    assert playoff.bracket_order(8) == [1, 8, 4, 5, 2, 7, 3, 6]
    # A 16-team field with no byes would be the classic bracket.
    assert playoff.bracket_order(16)[:4] == [1, 16, 8, 9]


# --------------------------------------------------------------------------- #
# Conference tiebreaks
# --------------------------------------------------------------------------- #

def _two(pct, beat, games, rating):
    """The title game pair by cfb.playoff.order, local indices, one run."""
    pct = np.array([pct], float)
    beat = np.array([beat], np.float32)
    games = np.array(games, np.float32)
    return list(playoff.order(pct, beat, games, [np.array([rating], float)], 2)[0])


def test_head_to_head_breaks_a_two_way_tie():
    # 0 and 1 level at 6-2; 1 beat 0, though 0 rates higher.
    beat = np.zeros((3, 3)); beat[1, 0] = 1
    games = np.zeros((3, 3)); games[0, 1] = games[1, 0] = 1
    assert _two([0.75, 0.75, 0.5], beat, games, [10, 0, 5]) == [1, 0]


def test_a_three_way_circle_falls_to_the_rating():
    # 0 beat 1, 1 beat 2, 2 beat 0: every team 1-1 among the tied.
    beat = np.zeros((3, 3)); beat[0, 1] = beat[1, 2] = beat[2, 0] = 1
    games = np.ones((3, 3)) - np.eye(3)
    assert _two([0.75] * 3, beat, games, [1, 9, 5]) == [1, 2]


def test_a_tie_narrowed_to_two_starts_again_from_head_to_head():
    """0 beat both others; 1 and 2 then go by their own game (2 beat 1),
    not by the rating that favours 1."""
    beat = np.zeros((3, 3)); beat[0, 1] = beat[0, 2] = beat[2, 1] = 1
    games = np.ones((3, 3)) - np.eye(3)
    assert _two([0.75] * 3, beat, games, [0, 9, 1]) == [0, 2]


def test_teams_that_never_met_go_by_the_rating():
    beat = np.zeros((3, 3))
    games = np.zeros((3, 3))
    assert _two([0.75, 0.75, 0.75], beat, games, [3, 7, 5]) == [1, 2]


def test_the_sun_belt_title_game_is_east_against_west():
    """w1 and w2 both finish ahead of e1, but the title game is the
    division winners: e1 v w1 (w1 won their game)."""
    games = [("w1", "w2", 1), ("w1", "e2", 1), ("w2", "e2", 1), ("e1", "e2", 1),
             ("e1", "w1", 0), ("e1", "w2", 0)]
    lg = league({"w1": 5, "w2": 4, "e1": 3, "e2": 0}, games)
    res = playoff.simulate(lg, n=200, seed=1, sd_now=0.0, drift=0.0)
    sb = [idx(lg, t) for t in ("e1", "e2", "w1", "w2")]
    # Only the two division winners can win the title game.
    assert res.conf_title[idx(lg, "w2")] == 0 and res.conf_title[idx(lg, "e2")] == 0
    assert res.conf_title[sb].sum() == pytest.approx(1.0)
    assert res.conf_title[idx(lg, "e1")] > 0 and res.conf_title[idx(lg, "w1")] > 0


# --------------------------------------------------------------------------- #
# The whole run
# --------------------------------------------------------------------------- #

RATINGS = {"s1": 25, "s2": 12, "t1": 22, "t2": 20, "a1": 18, "a2": 8, "b1": 15, "b2": 5,
           "m1": 2, "m2": 6, "e1": 4, "e2": -5, "w1": 1, "w2": -3, "87": 19, "41": -10}


def _season(played: bool):
    """Everyone plays its conference mates and two others."""
    games = []
    for members in CONFS.values():
        if members == CONFS["Independent"]:
            continue
        for i, h in enumerate(members):
            for a in members[i + 1:]:
                games.append((h, a, (1 if RATINGS[h] > RATINGS[a] else 0) if played else None,
                              RATINGS[h] - RATINGS[a] + 3))
    extra = [("87", "s2"), ("87", "a2"), ("41", "m1"), ("41", "w2"), ("s1", "t2"),
             ("t1", "b2"), ("a1", "e1"), ("b1", "m2")]
    for h, a in extra:
        games.append((h, a, (1 if RATINGS[h] > RATINGS[a] else 0) if played else None,
                      RATINGS[h] - RATINGS[a] + 3))
    return games


def test_a_finished_season_with_its_title_games_picks_one_field():
    """Every result in, every title game played: the field and its seeds are
    fixed - the same twelve in every run, the champions among them - and only
    the bracket is left to chance."""
    titles = {"SEC": ("s1", "s2"), "Big Ten": ("t1", "t2"), "ACC": ("a2", "a1"),
              "Big 12": ("b1", "b2"), "American": ("m1", "m2"), "Sun Belt": ("e1", "w1")}
    lg = league(RATINGS, _season(True))
    lg.title = {c: {"pair": (idx(lg, w), idx(lg, l)), "winner": idx(lg, w)}
                for c, (w, l) in titles.items()}
    res = playoff.simulate(lg, n=500, seed=7, sd_now=0.0, drift=0.0)
    inn = {t for t in lg.teams if res.playoff[idx(lg, t)] == 1.0}
    out = {t for t in lg.teams if res.playoff[idx(lg, t)] == 0.0}
    assert len(inn) == 12 and len(inn) + len(out) == len(lg.teams)
    # a2 upset a1 in the ACC title game: the champion is in on its bid.
    assert {"s1", "t1", "a2", "b1"} <= inn
    assert "87" in inn                  # Notre Dame, well inside the top 12
    assert "41" in out
    # Seeds are fixed too: each team in has a single seed.
    for t in inn:
        assert res.seed_count[idx(lg, t)].max() == 500
    assert res.title.sum() == pytest.approx(1.0)
    assert res.bye.sum() == pytest.approx(4.0)
    # And the same seed gives the same answer.
    again = playoff.simulate(lg, n=500, seed=7, sd_now=0.0, drift=0.0)
    assert np.array_equal(res.title, again.title)


def test_a_season_still_to_play_is_the_same_twice_and_adds_up():
    lg = league(RATINGS, _season(False))
    a = playoff.simulate(lg, n=600, seed=3)
    b = playoff.simulate(lg, n=600, seed=3)
    for field in ("playoff", "bye", "conf_title", "title"):
        assert np.array_equal(getattr(a, field), getattr(b, field))
    assert a.playoff.sum() == pytest.approx(12.0)
    assert a.title.sum() == pytest.approx(1.0)
    # One champion a conference (independents have none).
    assert a.conf_title.sum() == pytest.approx(6.0)
    assert a.conf_title[idx(lg, "87")] == 0
    # The best team is the likeliest champion, and the field shape holds.
    assert a.title.argmax() == idx(lg, "s1")
    field = playoff.projected_field(a)
    assert len(field) == 12
    for c in ("SEC", "Big Ten", "ACC", "Big 12"):
        assert any(lg.conf[i] == c for i in field)


def test_a_different_seed_is_a_different_sample():
    lg = league(RATINGS, _season(False))
    assert not np.array_equal(playoff.simulate(lg, n=300, seed=1).playoff,
                              playoff.simulate(lg, n=300, seed=2).playoff)


def test_a_game_next_week_keeps_the_predictions_page_win_chance():
    """The wander is taken out of each game's own noise, so one game a week
    out is won as often as norm.cdf(margin / margin_sd) says."""
    from scipy.stats import norm
    rng = np.random.default_rng(0)
    n, sd_now, drift, sd = 200_000, 7.5, 1.0, 16.0
    S = playoff.shocks(rng, n, 2, 1, sd_now, drift)
    noise = playoff.game_noise(sd, sd_now, drift)
    margin = 5.0 + S[:, 0, 1] - S[:, 1, 1] + noise * rng.standard_normal(n)
    assert (margin > 0).mean() == pytest.approx(norm.cdf(5.0 / sd), abs=0.004)


def test_the_wander_shrinks_as_the_season_goes():
    assert playoff.rating_sd_now(1) == playoff.SD_NOW_BY_WEEK[0][1]
    assert playoff.rating_sd_now(5) > playoff.rating_sd_now(9) > playoff.rating_sd_now(14)


# --------------------------------------------------------------------------- #
# The real field, once ESPN has it
# --------------------------------------------------------------------------- #

def test_the_real_field_is_read_from_the_cfp_rows_and_decides_played_games():
    lg = league(RATINGS, _season(True))
    index = {t: i for i, t in enumerate(lg.teams)}
    order = ["s1", "t1", "a1", "87", "t2", "b1", "s2", "a2", "m2", "e1", "b2", "w1"]
    rank = {t: r + 1 for r, t in enumerate(order)}
    rows = []
    for hi, lo in playoff.first_round(12, 4):
        h, a = order[hi - 1], order[lo - 1]
        rows.append({"week": 20, "note": "College Football Playoff First Round Game",
                     "home_id": h, "away_id": a, "home_rank": rank[h], "away_rank": rank[a],
                     "state": "post", "home_score": 10.0, "away_score": 20.0})
    for s in range(1, 5):
        t = order[s - 1]
        rows.append({"week": 20, "note": "College Football Playoff Quarterfinal at a Bowl",
                     "home_id": t, "away_id": "-1", "home_rank": rank[t], "away_rank": None,
                     "state": "pre", "home_score": None, "away_score": None})
    rows.append({"week": 20, "note": "Some Other Bowl", "home_id": "41", "away_id": "w2",
                 "home_rank": None, "away_rank": None, "state": "pre",
                 "home_score": None, "away_score": None})
    seeds, results, final = playoff._real_field(pd.DataFrame(rows), index)
    assert [lg.teams[i] for i in seeds] == order
    assert not final
    # Every first-round game went to the road team.
    lg.cfp_seeds, lg.cfp_results = seeds, results
    res = playoff.simulate(lg, n=300, seed=5)
    for hi, lo in playoff.first_round(12, 4):
        assert res.playoff[idx(lg, order[lo - 1])] == 1.0
        assert res.title[idx(lg, order[hi - 1])] == 0.0      # lost at home
    assert res.title[idx(lg, "41")] == 0
