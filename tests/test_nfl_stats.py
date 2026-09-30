"""
The NFL team stats page (nfl.advanced, nfl.site.stats) on a hand-built
play-by-play: the team figures and what garbage time leaves out, drives and
third downs, the opponent adjustment's direction and its leave-one-out, the
player minimums, the cache's staleness rule, and the page itself. No network:
the nflverse download is monkeypatched.
"""
import json
import os
import time

import pandas as pd
import pytest

from nfl import advanced
from nfl.site import stats

DEFAULTS = {
    "season_type": "REG", "pass": 0, "rush": 1, "play_type": "run", "epa": 0.0, "qb_epa": None,
    "two_point_attempt": 0, "wp": 0.5, "qtr": 1, "down": 1, "half_seconds_remaining": 1200,
    "yards_gained": 3, "yardline_100": 60, "fixed_drive": 1, "fixed_drive_result": "Punt",
    "interception": 0, "fumble_lost": 0, "posteam_score": 0, "posteam_score_post": 0,
    "qb_dropback": 0, "sack": 0, "third_down_converted": 0, "third_down_failed": 0,
    "xpass": 0.5, "passer_id": None, "passer": None, "cpoe": None, "rusher_player_id": None,
    "rusher_player_name": None, "receiver_player_id": None, "receiver_player_name": None,
    "complete_pass": 0, "air_yards": None,
}


class Game:
    """Plays of one game, snapped in order with the clock running down."""

    def __init__(self, week, home, away, score=(0, 0)):
        self.week, self.home, self.away, self.score = week, home, away, score
        self.id = f"2026_{week:02d}_{away}_{home}"
        self.rows = []

    def play(self, off, **kw):
        n = len(self.rows)
        row = dict(DEFAULTS, game_id=self.id, week=self.week, home_team=self.home,
                   away_team=self.away, posteam=off,
                   defteam=self.away if off == self.home else self.home,
                   home_score=self.score[0], away_score=self.score[1],
                   play_id=float(n + 1), game_seconds_remaining=3600 - 30 * n)
        row.update(kw)
        self.rows.append(row)
        return self

    def dropback(self, off, **kw):
        return self.play(off, **{"pass": 1, "rush": 0, "play_type": "pass", "qb_dropback": 1,
                                 **kw})


def frame(*games):
    return pd.DataFrame([r for g in games for r in g.rows])


def one_game():
    """KC 7, LV 3. KC's figures, worked by hand in test_team_figures."""
    g = Game(1, "KC", "LV", score=(7, 3))
    # KC drive 1: 12-yard run (explosive), incompletion, 25-yard 3rd-down
    # completion (explosive, converted), then a TD run from the 5.
    g.play("KC", epa=0.5, yards_gained=12, yardline_100=75)
    g.dropback("KC", epa=-0.1, yards_gained=0, down=2, yardline_100=63)
    g.dropback("KC", epa=0.2, yards_gained=25, down=3, yardline_100=63,
               third_down_converted=1)
    g.play("KC", epa=0.0, yards_gained=5, yardline_100=5, fixed_drive_result="Touchdown",
           posteam_score=0, posteam_score_post=6)
    g.play("KC", **{"rush": 0, "play_type": "extra_point", "epa": 0.0, "posteam_score": 6,
                    "posteam_score_post": 7, "fixed_drive_result": "Touchdown"})
    # LV drive 2: a run, a pass, a field goal.
    g.play("LV", fixed_drive=2, epa=-0.2, fixed_drive_result="Field goal")
    g.dropback("LV", fixed_drive=2, epa=0.4, yards_gained=8, fixed_drive_result="Field goal")
    g.play("LV", **{"fixed_drive": 2, "rush": 0, "play_type": "field_goal", "epa": 0.3,
                    "posteam_score": 0, "posteam_score_post": 3, "fixed_drive_result": "Field goal",
                    "yardline_100": 20})
    # KC drive 3: sacked on 3rd down, punt.
    g.dropback("KC", fixed_drive=3, epa=-1.0, yards_gained=-7, down=3, sack=1,
               third_down_failed=1)
    g.play("KC", **{"fixed_drive": 3, "rush": 0, "play_type": "punt", "epa": 0.1})
    # LV drive 4: one run, punt.
    g.play("LV", fixed_drive=4, epa=-0.3, qtr=4, wp=0.3)
    g.play("LV", **{"fixed_drive": 4, "rush": 0, "play_type": "punt", "epa": 0.0, "qtr": 4})
    # KC drive 5, garbage time (4th quarter, KC's win chance 97%): a big run
    # and an interception - out of EPA, in the drive and turnover figures.
    g.play("KC", fixed_drive=5, epa=3.0, qtr=4, wp=0.97, fixed_drive_result="Turnover")
    g.dropback("KC", fixed_drive=5, epa=-3.0, qtr=4, wp=0.97, interception=1,
               fixed_drive_result="Turnover")
    # A two-point try and a kneel are not plays at all.
    g.dropback("KC", fixed_drive=5, epa=1.0, two_point_attempt=1, down=None)
    g.play("KC", **{"fixed_drive": 5, "rush": 0, "play_type": "qb_kneel", "epa": -0.5})
    return g


INFO = pd.DataFrame([
    {"team_abbr": "KC", "team_nick": "Chiefs", "team_name": "Kansas City Chiefs",
     "team_conf": "AFC", "team_division": "AFC West"},
    {"team_abbr": "LV", "team_nick": "Raiders", "team_name": "Las Vegas Raiders",
     "team_conf": "AFC", "team_division": "AFC West"},
    {"team_abbr": "LA", "team_nick": "Rams", "team_name": "Los Angeles Rams",
     "team_conf": "NFC", "team_division": "NFC West"},
    {"team_abbr": "SF", "team_nick": "49ers", "team_name": "San Francisco 49ers",
     "team_conf": "NFC", "team_division": "NFC West"},
])


def test_team_figures():
    teams = {t["abbr"]: t for t in advanced.teams(frame(one_game()), INFO)}
    kc, lv = teams["KC"], teams["LV"]
    assert (kc["w"], kc["l"], kc["g"], kc["name"], kc["div"]) == (1, 0, 1, "Chiefs", "AFC West")
    assert (lv["w"], lv["l"]) == (0, 1)
    # Five non-garbage plays: 0.5, -0.1, 0.2, 0.0, -1.0.
    assert kc["off_epa"] == pytest.approx(-0.08)
    assert kc["off_pass"] == pytest.approx((-0.1 + 0.2 - 1.0) / 3, abs=1e-4)
    assert kc["off_rush"] == pytest.approx(0.25)
    assert kc["off_sr"] == pytest.approx(0.4)            # 0.0 is not a success
    assert kc["off_xpl"] == pytest.approx(0.4)           # the 12-yard run, the 25-yard pass
    # The defence is the other side of the same plays.
    assert lv["def_epa"] == kc["off_epa"] and lv["def_sr"] == kc["off_sr"]
    assert lv["off_epa"] == pytest.approx(-0.1 / 3, abs=1e-4)   # -0.2, 0.4, -0.3; no FG
    # Counting figures take every snap, garbage time included.
    assert kc["off_sack"] == pytest.approx(0.25)         # one sack in four dropbacks
    assert kc["off_third"] == pytest.approx(0.5)
    assert kc["off_ppg"] == pytest.approx(7)             # 3 runs + 4 dropbacks; no try, no kneel
    # Three possessions: a touchdown (7 with the try), a punt, a turnover.
    assert kc["off_ppd"] == pytest.approx(7 / 3, abs=1e-4)
    assert kc["off_to"] == pytest.approx(1 / 3, abs=1e-4)
    assert kc["off_rz"] == 1.0
    assert lv["off_ppd"] == pytest.approx(1.5) and lv["off_rz"] == 0.0
    assert lv["def_ppd"] == kc["off_ppd"] and lv["def_to"] == kc["off_to"]


def test_garbage_time_moves_nothing_but_the_counts():
    base = one_game()
    more = one_game()
    # A second garbage-time blowout play: EPA and success untouched, plays up.
    more.play("KC", fixed_drive=5, epa=4.0, qtr=4, wp=0.99, yards_gained=40)
    a = {t["abbr"]: t for t in advanced.teams(frame(base), INFO)}["KC"]
    b = {t["abbr"]: t for t in advanced.teams(frame(more), INFO)}["KC"]
    for key in ("off_epa", "off_sr", "off_xpl", "off_rush"):
        assert a[key] == b[key]
    assert b["off_ppg"] == a["off_ppg"] + 1
    # The same win chance in the third quarter is not garbage time.
    early = one_game()
    early.play("KC", fixed_drive=5, epa=4.0, qtr=3, wp=0.99)
    c = {t["abbr"]: t for t in advanced.teams(frame(early), INFO)}["KC"]
    assert c["off_epa"] > a["off_epa"]


def _matchups(games, epa):
    """Plays for `games` [(game id, offence, defence)], each offence's plays
    worth epa[(offence, defence)] - 60 of them, so a game is a game."""
    rows = []
    for gid, off, dfn in games:
        for _ in range(60):
            rows.append({"game_id": gid, "posteam": off, "defteam": dfn,
                         "epa": epa[(off, dfn)], "garbage": False})
    return pd.DataFrame(rows)


def test_adjustment_evens_out_two_ordinary_offences():
    # D is awful both ways: every offence gains +0.4 a play on it and its own
    # offence manages -0.4. Everyone else is ordinary - 0.0 against each other.
    # A met D and B; E met B and C and never D. Raw, A looks 0.2 better than E;
    # allowing for who they played, they are the same team.
    games = [("g1", "A", "D"), ("g1", "D", "A"), ("g2", "B", "D"), ("g2", "D", "B"),
             ("g3", "C", "D"), ("g3", "D", "C"), ("g4", "A", "B"), ("g4", "B", "A"),
             ("g5", "E", "C"), ("g5", "C", "E"), ("g6", "E", "B"), ("g6", "B", "E")]
    epa = {(o, d): 0.4 if d == "D" else -0.4 if o == "D" else 0.0 for _, o, d in games}
    p = _matchups(games, epa)
    raw = p.groupby("posteam")["epa"].mean()
    assert raw["A"] - raw["E"] == pytest.approx(0.2)
    loose = advanced.adjust(p, prior_off=1, prior_def=1)
    assert loose["A"][0] < raw["A"] and loose["E"][0] > raw["E"]
    assert loose["A"][0] == pytest.approx(loose["E"][0], abs=0.01)
    # D stays the worst both ways, by about the 0.4 it was built with.
    others = [t for t in loose if t != "D"]
    assert all(loose["D"][1] - loose[t][1] == pytest.approx(0.4, abs=0.02) for t in others)
    assert all(loose[t][0] - loose["D"][0] == pytest.approx(0.4, abs=0.02) for t in others)
    # The shipped priors pull opponents toward average on a few games' worth:
    # the same direction, less of it.
    shipped = advanced.adjust(p)
    assert loose["A"][0] < shipped["A"][0] < raw["A"]


def test_adjustment_leaves_out_the_game_itself():
    # X's only game is against A. A shredding X must not make X "a bad
    # defence" that is then taken back off A: with nothing else known of X,
    # A's adjusted figure is its raw one.
    games = [("g1", "A", "X"), ("g1", "X", "A")]
    p = _matchups(games, {("A", "X"): 0.5, ("X", "A"): -0.5})
    adj = advanced.adjust(p, prior_off=1, prior_def=1)
    assert adj["A"][0] == pytest.approx(0.5)
    assert adj["X"][1] == pytest.approx(0.5)


ROSTER = pd.DataFrame([
    {"gsis_id": "q1", "full_name": "Starter Quarterback", "position": "QB"},
    {"gsis_id": "q2", "full_name": "Backup Quarterback", "position": "QB"},
    {"gsis_id": "r1", "full_name": "Lead Back", "position": "RB"},
    {"gsis_id": "r2", "full_name": "Second Back", "position": "RB"},
    {"gsis_id": "w1", "full_name": "Wide Out", "position": "WR"},
    {"gsis_id": "t1", "full_name": "Tight End", "position": "TE"},
    {"gsis_id": "w2", "full_name": "Few Targets", "position": "WR"},
    {"gsis_id": "w3", "full_name": "Gadget Runner", "position": "WR"},
])


def two_games_of_players():
    """KC's two games, sized around the minimums: 15 dropbacks, 6 carries and
    3 targets a team game, so 30, 12 and 6."""
    games = [Game(1, "KC", "LV", (20, 10)), Game(2, "LV", "KC", (13, 17))]
    for g in games:
        for i in range(15):
            g.dropback("KC", passer_id="q1", passer="S.Quarterback", epa=0.3, qb_epa=0.3,
                       cpoe=5.0)
        for i in range(6):
            g.play("KC", rusher_player_id="r1", rusher_player_name="L.Back", epa=0.1,
                   yards_gained=5)
        for who in ("w1", "t1"):
            for i in range(3):
                g.dropback("KC", receiver_player_id=who, receiver_player_name=who, epa=0.5,
                           complete_pass=1, air_yards=8)
        for i in range(6):
            g.play("KC", rusher_player_id="w3", rusher_player_name="G.Runner", epa=0.9)
    # One short of every minimum, and what does not count toward one: the
    # backup's garbage-time dropback and his dropback a penalty wiped out.
    for i in range(29):
        games[0].dropback("KC", passer_id="q2", passer="B.Quarterback", epa=0.5, qb_epa=0.5)
    games[0].dropback("KC", passer_id="q2", epa=0.5, qb_epa=0.5, qtr=4, wp=0.99)
    games[0].dropback("KC", passer_id="q2", epa=0.5, qb_epa=0.5, play_type="no_play")
    for i in range(11):
        games[0].play("KC", rusher_player_id="r2", rusher_player_name="S.Back", epa=0.2)
    for i in range(5):
        games[0].dropback("KC", receiver_player_id="w2", epa=0.9, complete_pass=1, air_yards=20)
    return frame(*games)


def test_player_minimums_scale_with_team_games():
    board = advanced.players(two_games_of_players(), ROSTER)
    assert [p["id"] for p in board["qb"]] == ["q1"]
    q1 = board["qb"][0]
    assert (q1["name"], q1["team"], q1["n"], q1["epa"], q1["cpoe"]) == \
        ("Starter Quarterback", "KC", 30, 0.3, 5.0)
    assert [p["id"] for p in board["rb"]] == ["r1"]       # the WR's 12 runs are not an RB's
    assert sorted(p["id"] for p in board["wr"]) == ["t1", "w1"]
    w1 = next(p for p in board["wr"] if p["id"] == "w1")
    assert (w1["n"], w1["catch"], w1["adot"]) == (6, 1.0, 8.0)


def sf_la(week=2):
    g = Game(week, "SF", "LA", (24, 20))
    return g.dropback("SF", epa=0.3, yards_gained=22).play("LA", epa=-0.1)


def _payload():
    return frame(one_game(), sf_la())


def test_page_renders(tmp_path, monkeypatch):
    monkeypatch.setattr(advanced, "DATA_DIR", tmp_path)
    monkeypatch.setattr(advanced, "_download",
                        lambda season: (pd.concat([two_games_of_players(), frame(sf_la())]),
                                        ROSTER, INFO))
    monkeypatch.setattr(stats, "OUT", tmp_path / "index.html")
    stats.generate()
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "title: Team Stats" in html and "NFL 2026 &middot; through Week 2" in html
    for name in ("Chiefs", "Raiders", "Rams", "49ers"):
        assert f">{name}</" in html or f"{name}<" in html
    # nflverse's LA is ESPN's lar; logos come resized, never the 500px file.
    assert "teamlogos/nfl/500/lar.png&amp;w=" in html
    assert "500/la.png" not in html
    assert "<option value='AFC West'>AFC West</option>" in html
    assert "<option value='NFC'>NFC</option>" in html
    assert "data-f='AFC West AFC'" in html
    assert "Player leaders" in html and "Starter Quarterback" in html
    assert "What the columns mean" in html and "garbage time" in html
    # Opens on the Overview, sorted by adjusted net EPA.
    assert "table class='st-t view-overview'" in html
    assert "data-k='net_adj'" in html


def test_cache_is_read_until_stale_and_kept_when_the_download_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(advanced, "DATA_DIR", tmp_path)
    calls = []

    def download(season):
        calls.append(season)
        return _payload(), ROSTER, INFO

    monkeypatch.setattr(advanced, "_download", download)
    first = advanced.refresh()
    assert calls == [2026] and first["teams"] and first["updated"]
    assert advanced.refresh() == first and calls == [2026]      # fresh: no download

    path = advanced.cache_path()
    old = time.time() - (advanced.STALE_HOURS + 1) * 3600
    os.utime(path, (old, old))
    # Stale, same numbers: downloaded, the file left as it was but touched.
    before = path.read_text()
    assert advanced.refresh()["updated"] == first["updated"] and len(calls) == 2
    assert path.read_text() == before and time.time() - path.stat().st_mtime < 60

    os.utime(path, (old, old))

    def broken(season):
        raise OSError("nflverse is down")

    monkeypatch.setattr(advanced, "_download", broken)
    assert advanced.refresh() == first
    assert json.loads(path.read_text()) == first
