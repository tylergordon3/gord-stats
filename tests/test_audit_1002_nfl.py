"""
The 2026-10-02 audit's NFL findings, one test (or a few) per bug that was
there: the 2026 Super Bowl never fetched (ESPN moved it from postseason week 5
to week 4 when the Pro Bowl left the calendar), playoff odds after week 18
re-drawn by coin run to run, an ESPN outage taking the section down, a
cancelled game holding the week open forever, playoff games in the regular
season's records, untimed kickoffs read as midnight, a tie graded right for
an away pick, the bets card on a week with no lines, a lopsided stakes game,
refits shown as calls, TBD games archived and carded, "through Week 4" on a
Friday, a void bet that never settled, a false "agree on every game", a
playoff history overwritten after a bad parse, and power-history windows an
hour off in January. No network: ESPN, nflverse and the season are built here.
"""
import json
import os
from datetime import datetime

import numpy as np
import pandas as pd
import pytest
import requests

from cfb import results as cfb_results
from gordstats import bets_card, playoff_history, stakes, watch_page
from nfl import advanced, games, playoff, predict, results
from nfl.config import TZ
from nfl.site import homecards, power, predictions, previews, schedule, teams, watch
from nfl.site import playoff as playoff_site

from test_playoff_nfl import _league


# --------------------------------------------------------------------------- #
# 1. The Super Bowl's week comes from ESPN's calendar
# --------------------------------------------------------------------------- #

# The two layouts, as ESPN's scoreboard carries them (leagues[0].calendar).
CAL_2026 = [{"label": "Regular Season", "value": "2", "entries": []},
            {"label": "Postseason", "value": "3", "entries": [
                {"label": "Wild Card", "value": "1"}, {"label": "Divisional Round", "value": "2"},
                {"label": "Conference Championship", "value": "3"},
                {"label": "Super Bowl", "value": "4"}]},
            {"label": "Off Season", "value": "4", "entries": []}]
CAL_2025 = [{"label": "Postseason", "value": "3", "entries": [
    {"label": "Wild Card", "value": "1"}, {"label": "Divisional Round", "value": "2"},
    {"label": "Conference Championship", "value": "3"}, {"label": "Pro Bowl", "value": "4"},
    {"label": "Super Bowl", "value": "5"}]}]


def test_postseason_rounds_follow_the_calendar_and_skip_the_pro_bowl():
    assert games.postseason_rounds(CAL_2026, 2026) == {
        1: "Wild Card", 2: "Divisional Round", 3: "Conference Championship", 4: "Super Bowl"}
    assert games.postseason_rounds(CAL_2025, 2025) == {
        1: "Wild Card", 2: "Divisional Round", 3: "Conference Championship", 5: "Super Bowl"}
    # No calendar: the layout each season had.
    assert max(games.postseason_rounds(None, 2025)) == 5
    assert max(games.postseason_rounds([], 2026)) == 4


def _event(gid, home, away, when, state="pre", score=(None, None), odds=None):
    def side(tid, where, pts):
        return {"homeAway": where, "score": pts,
                "team": {"id": tid, "shortDisplayName": f"T{tid}", "abbreviation": f"A{tid}"}}
    return {"id": gid, "date": when, "competitions": [{
        "competitors": [side(home, "home", score[0]), side(away, "away", score[1])],
        "status": {"type": {"state": state, "completed": state == "post",
                            "shortDetail": "Final" if state == "post" else "Sun 6:30 PM"}},
        "odds": odds or [], "venue": {"fullName": "Stadium"}}]}


def test_the_2026_super_bowl_is_fetched_from_week_4(monkeypatch):
    asked = []

    def get(params):
        week, st = int(params["week"]), int(params["seasontype"])
        asked.append((st, week))
        events = []
        if (st, week) == (2, 1):
            events = [_event("r1", "12", "13", "2026-09-13T17:00Z")]
        if (st, week) == (3, 4):
            events = [_event("sb", "12", "21", "2027-02-14T23:30Z")]
        return {"events": events, "leagues": [{"calendar": CAL_2026}]}

    monkeypatch.setattr(games, "_get", get)
    monkeypatch.setattr(games, "_PAUSE", 0)
    frame = games.fetch_season(2026)
    assert (3, 4) in asked and (3, 5) not in asked
    sb = frame[frame["game_id"] == "sb"].iloc[0]
    assert (sb["week"], sb["seasontype"], sb["round"]) == (4, 3, "Super Bowl")
    assert frame.loc[frame["seasontype"] == 2, "round"].eq("").all()
    # And the pages name it, under either number.
    assert teams.week_label(4, 3) == "SB" and teams.week_label(5, 3) == "SB"
    assert schedule.week_label(schedule.week_key(4, 3)) == "Super Bowl"
    assert power.week_label(power.week_number(4, 3)) == "SB"
    block = pd.DataFrame([{"week": 4, "seasontype": 3}])
    assert predictions._week_label(block) == "Super Bowl"
    assert games.round_of(sb) == 4
    assert games.round_of(pd.Series({"week": 5, "seasontype": 3})) == 4     # 2025's, no label


# --------------------------------------------------------------------------- #
# 8 (with 1). A week with no line on any game
# --------------------------------------------------------------------------- #

def test_a_season_without_a_single_line_stores_numbers_and_the_card_stands(monkeypatch, tmp_path):
    def get(params):
        week, st = int(params["week"]), int(params["seasontype"])
        events = [_event(f"g{week}", "12", "13", f"2026-09-{10 + week}T17:00Z")] \
            if (st, week) in ((2, 1), (2, 2)) else []
        return {"events": events, "leagues": [{"calendar": CAL_2026}]}

    monkeypatch.setattr(games, "_get", get)
    monkeypatch.setattr(games, "_PAUSE", 0)
    frame = games.fetch_season(2026)
    # All None from ESPN: float NaN on file, not an object column.
    assert frame["book_spread"].dtype == float and frame["book_total"].dtype == float
    # The card's own guard: an object column of Nones (an older file) no longer
    # raises on `-games["spread"]`.
    cands = pd.DataFrame({"game_id": ["1"], "home": ["H"], "away": ["A"],
                          "date": [pd.Timestamp("2026-10-04T17:00Z")],
                          "spread": pd.Series([None], dtype=object),
                          "total": pd.Series([None], dtype=object),
                          "pred_margin": [3.0], "pred_total": [44.0]})
    edged = bets_card.with_edges(cands)
    assert edged["edge"].isna().all()
    assert bets_card.pick_week(edged, 4, 3, 6)["single"] is None

    monkeypatch.setattr(homecards, "BETS_DIR", tmp_path)
    season = _bets_frame(spread=pd.Series([None, None], dtype=object),
                         book_total=pd.Series([None, None], dtype=object))
    html = homecards.bets_html(datetime(2026, 9, 30, 12, tzinfo=TZ), season)
    assert "both our number and the book" in html and "agree" not in html


def _bets_frame(spread=(-3.0, -2.5), book_total=(44.0, 44.0), pred_total=(44.0, 44.0),
                margin=(3.5, 3.0)):
    kicks = [pd.Timestamp("2026-10-04T17:00Z"), pd.Timestamp("2026-10-04T20:25Z")]
    return pd.DataFrame({
        "game_id": ["1", "2"], "week": [4, 4], "seasontype": [2, 2], "date": kicks,
        "home": ["Giants", "Raiders"], "away": ["Cards", "Chiefs"],
        "home_id": ["19", "13"], "away_id": ["22", "12"],
        "pred_margin": list(margin), "pred_total": list(pred_total),
        "book_spread": spread, "book_total": book_total,
        "played": [False, False], "completed": [False, False], "state": ["pre", "pre"],
        "home_score": [None, None], "away_score": [None, None]})


# --------------------------------------------------------------------------- #
# 14. "Agree on every game" only when it is true
# --------------------------------------------------------------------------- #

def test_no_bet_says_why_from_the_weeks_numbers(monkeypatch, tmp_path):
    monkeypatch.setattr(homecards, "BETS_DIR", tmp_path)
    now = datetime(2026, 9, 30, 12, tzinfo=TZ)
    # Spreads within a point of the book's, a total 4.5 off: no single, and
    # the totals are not "agreement".
    totals_only = homecards.bets_html(now, _bets_frame(pred_total=(48.5, 44.0)))
    assert "on every spread this week" in totals_only and "every game" not in totals_only
    # The only wide spread is past the cap.
    too_wide = homecards.bets_html(now, _bets_frame(margin=(10.0, 3.0)))
    assert "between 3 and 6 points" in too_wide and "every game" not in too_wide
    # Truly agreeing everywhere keeps the old line.
    agree = homecards.bets_html(now, _bets_frame())
    assert "agree to within 3 points on every game" in agree
    # Nothing written: a week without a single never locks.
    assert not list(tmp_path.glob("*.json"))
    # The college card's call, without the week's games, is unchanged.
    assert "on every game" in bets_card.no_bet(4)


# --------------------------------------------------------------------------- #
# 2. Playoff odds once the regular season is over
# --------------------------------------------------------------------------- #

def test_a_finished_season_pins_one_field_where_the_coin_used_to_move_it():
    lg = _league(True)                  # ties everywhere: the coin decides seeds
    loose = playoff.simulate(lg, n=400, seed=3)
    assert ((loose.playoff > 0) & (loose.playoff < 1)).any()   # the bug's own picture
    lg.seeds = playoff.real_seeds(lg)
    assert lg.seeds is not None
    res = playoff.simulate(lg, n=400, seed=3)
    assert set(np.unique(res.playoff)) <= {0.0, 1.0}
    assert ((res.seed_count > 0).sum(axis=1) <= 1).all()        # one seed, every run
    for c, order in lg.seeds.items():
        for s, i in enumerate(order):
            assert res.seed_count[i, s] == 400
    # The same answer however many times it is asked.
    assert playoff.real_seeds(lg) == lg.seeds


def test_the_real_wild_card_pairings_override_our_tiebreaks():
    lg = _league(True)
    ours = playoff.real_seeds(lg)["AFC"]
    afc = [i for i in range(32) if lg.conf[i] == "AFC"]
    outsider = next(i for i in afc if i not in ours)
    # ESPN pairs our 2 seed with a team we left out; the rest as we had them.
    lg.wild_card = {"AFC": [(ours[3], ours[4]), (ours[1], outsider), (ours[2], ours[5])]}
    real = playoff.real_seeds(lg)["AFC"]
    assert real[0] == ours[0]
    assert real[1:4] == ours[1:4]                     # the hosts, in our order of them
    assert real[4:] == [ours[4], ours[5], outsider]   # 5 at the 4, 6 at the 3, 7 at the 2
    assert ours[6] not in real


class _Model:
    def __init__(self, rating):
        self.r = rating

    def rating(self, team):
        return self.r.get(str(team), 0.0)

    def predict(self, df):
        return pd.DataFrame({"pred_margin": [self.rating(h) - self.rating(a) + 1.0
                                             for h, a in zip(df["home_team"], df["away_team"])]},
                            index=df.index)


IDS = sorted(playoff.DIVISIONS, key=lambda t: (playoff.DIVISIONS[t], int(t)))


def _season_frame(post: list, cancelled: bool = False, sb_week: int = 4,
                  label: bool = True) -> tuple:
    """A finished round-robin regular season (each conference plays itself
    once, the better team always wins), then the postseason rows given as
    (round, home id, away id, winner id or None)."""
    ids = IDS
    rating = dict(zip(ids, np.linspace(30, -30, 32)))
    conf = {t: playoff.DIVISIONS[t].split()[0] for t in ids}
    kick = pd.Timestamp("2026-09-13T17:00Z")
    rows = []

    def row(week, st, h, a, winner, date, rnd=""):
        played = winner is not None
        hs, as_ = ((27.0, 20.0) if winner == h else (17.0, 24.0)) if played else (None, None)
        return {"week": week, "seasontype": st, "game_id": f"{st}-{week}-{h}-{a}",
                "home_team": h, "away_team": a, "home_id": h, "away_id": a,
                "neutral": False, "played": played, "state": "post" if played else "pre",
                "completed": played, "home_score": hs, "away_score": as_,
                "actual_margin": (hs - as_) if played else np.nan,
                "pred_margin": rating[h] - rating[a] + 1.0, "date": date, "round": rnd}

    n = 0
    for x in range(32):
        for y in range(x + 1, 32):
            if conf[ids[x]] == conf[ids[y]]:
                h, a = (ids[x], ids[y]) if (x + y) % 2 else (ids[y], ids[x])
                rows.append(row(1 + n % 18, 2, h, a, h if rating[h] > rating[a] else a,
                                kick + pd.Timedelta(days=7 * (n % 18))))
                n += 1
    if cancelled:
        # Called off, BUF-CIN style: post, not completed, 0-0.
        bad = row(17, 2, ids[0], ids[20], None, kick + pd.Timedelta(days=112))
        bad.update(state="post", completed=False, home_score=0.0, away_score=0.0,
                   game_id="cancelled")
        rows.append(bad)
    names = {1: "Wild Card", 2: "Divisional Round", 3: "Conference Championship",
             4: "Super Bowl"}
    for rnd, h, a, w in post:
        week = sb_week if rnd == 4 else rnd
        rows.append(row(week, 3, h, a, w, kick + pd.Timedelta(days=126 + 7 * rnd),
                        names[rnd] if label else ""))
    return pd.DataFrame(rows), _Model(rating), {t: (f"N{t}", f"A{t}") for t in ids}, ids


def _bracket(ids):
    """The 2026 seeds of the round-robin season (East's four first, then the
    other division winners), and a postseason with upsets in the AFC."""
    div = lambda c, d: [t for t in ids if playoff.DIVISIONS[t] == f"{c} {d}"]
    afc = {d: div("AFC", d) for d in ("East", "North", "South", "West")}
    nfc = {d: div("NFC", d) for d in ("East", "North", "South", "West")}
    e0, e1, e2, e3 = afc["East"]
    n0, s0, w0 = afc["North"][0], afc["South"][0], afc["West"][0]
    f0, f1, f2, f3 = nfc["East"]
    g0, h0, k0 = nfc["North"][0], nfc["South"][0], nfc["West"][0]
    post = [
        # AFC: the 7 beats the 2, then the 1, then the 5; NFC chalk.
        (1, n0, e3, e3), (1, s0, e2, s0), (1, w0, e1, e1),
        (2, e0, e3, e3), (2, s0, e1, e1),
        (3, e1, e3, e3),
        (1, g0, f3, g0), (1, h0, f2, h0), (1, k0, f1, k0),
        (2, f0, k0, f0), (2, g0, h0, g0),
        (3, f0, g0, f0),
        (4, e3, f0, e3),
    ]
    return post, e3, f0


def test_a_played_postseason_ends_at_100_percent_and_the_page_says_who_won(monkeypatch):
    post, champ_id, loser_id = _bracket(IDS)
    frame, model, names, ids = _season_frame(post)
    league = playoff.build(frame, model, names, 13.0, pd.Timestamp("2027-02-20T00:00Z"))
    champ, loser = ids.index(champ_id), ids.index(loser_id)
    assert league.final and league.champion == champ
    # The 1 seeds, read off the divisional round: the AFC East's and NFC
    # East's best, who played no Wild Card game.
    east = lambda c: next(i for i, t in enumerate(ids) if playoff.DIVISIONS[t] == f"{c} East")
    assert league.bye == {"AFC": east("AFC"), "NFC": east("NFC")}
    assert league.seeds["AFC"][0] == east("AFC") and league.seeds["AFC"][6] == champ
    res = playoff.simulate(league, n=300, seed=5)
    assert res.title[champ] == 1.0 and res.title.sum() == pytest.approx(1.0)
    assert res.conf_title[champ] == 1.0 and res.conf_title[loser] == 1.0
    # Everyone who lost a real playoff game is out of every run.
    for i, rnd in league.out.items():
        assert res.title[i] == 0.0
    monkeypatch.setattr(playoff_site.playoff, "project", lambda: (res, league))
    monkeypatch.setattr(playoff_site.fpi, "by_id", lambda: {})
    monkeypatch.setattr(playoff_site, "_BASE", {})
    html = playoff_site.body()
    assert f"The {names[champ_id][0]} won the Super Bowl." in html


def test_the_2025_super_bowl_week_still_ends_a_season():
    post, champ_id, _ = _bracket(IDS)
    frame, model, names, ids = _season_frame(post, sb_week=5, label=False)
    league = playoff.build(frame, model, names, 13.0, pd.Timestamp("2026-02-20T00:00Z"))
    assert league.final and league.champion == ids.index(champ_id)


# --------------------------------------------------------------------------- #
# 4. A game called off
# --------------------------------------------------------------------------- #

def test_a_called_off_game_closes_the_week_and_leaves_the_season():
    frame, model, names, ids = _season_frame([], cancelled=True)
    assert games.called_off(frame).sum() == 1
    league = playoff.build(frame, model, names, 13.0, pd.Timestamp("2027-01-20T00:00Z"))
    # Not in the simulation's season, so the season is over and seeds pin.
    assert len(league.games) == len(frame) - 1 and league.games["played"].all()
    assert league.seeds is not None
    # current_week moves past it to the next game still to play.
    nxt = pd.DataFrame([{**frame.iloc[0].to_dict(), "week": 18, "game_id": "next",
                         "state": "pre", "completed": False, "played": False,
                         "home_score": None, "away_score": None,
                         "date": pd.Timestamp("2027-01-10T18:00Z")}])
    assert predict.current_week(pd.concat([frame, nxt], ignore_index=True)) == (18, 2)


def test_a_called_off_game_settles_a_locked_pick_as_a_push():
    frame = _bets_frame()
    frame.loc[0, ["state", "home_score", "away_score"]] = ["post", 0.0, 0.0]
    finals = homecards._finals(frame)
    assert finals["1"] == bets_card.VOID and "2" not in finals
    pick = {"kind": "spread", "game_id": "1", "home": True, "line": -3.0}
    assert bets_card.grade(pick, finals) is None
    total = {"kind": "total", "game_id": "1", "side": "Over", "line": 44.0}
    assert bets_card.grade(total, finals) is None
    week = {"single": pick, "parlay": []}
    assert "0-0-1" in bets_card.season_record([week], finals, {})


# --------------------------------------------------------------------------- #
# 3. An ESPN outage
# --------------------------------------------------------------------------- #

def test_an_espn_outage_falls_back_to_the_cached_schedule(monkeypatch, tmp_path):
    path = tmp_path / "2026.parquet"
    monkeypatch.setattr(games, "season_path", lambda season: path)
    monkeypatch.setattr(games, "GAMES_DIR", tmp_path)

    def down(season, postseason=True):
        raise requests.ConnectionError("ESPN is down")

    monkeypatch.setattr(games, "fetch_season", down)
    with pytest.raises(requests.ConnectionError):
        games.schedule()                                 # nothing cached: nothing to show
    pd.DataFrame({"game_id": ["1"], "week": [1]}).to_parquet(path)
    old = path.stat().st_mtime - 24 * 3600
    os.utime(path, (old, old))
    assert list(games.schedule()["game_id"]) == ["1"]


# --------------------------------------------------------------------------- #
# 5. Playoff games are not the regular season's record
# --------------------------------------------------------------------------- #

def _two_games():
    kick = pd.Timestamp("2027-01-03T18:00Z")
    base = {"home_team": "12", "away_team": "13", "home_id": "12", "away_id": "13",
            "home": "Chiefs", "away": "Raiders", "played": True, "neutral": False,
            "home_score": 24.0, "away_score": 10.0, "actual_margin": 14.0,
            "home_win_prob": 0.7, "state": "post", "completed": True}
    return pd.DataFrame([
        {**base, "week": 18, "seasontype": 2, "game_id": "reg", "date": kick},
        {**base, "week": 1, "seasontype": 3, "game_id": "wc", "date": kick + pd.Timedelta(days=7)},
        {**base, "week": 2, "seasontype": 3, "game_id": "div", "played": False,
         "state": "pre", "completed": False, "home_score": None, "away_score": None,
         "actual_margin": np.nan, "date": kick + pd.Timedelta(days=14)},
    ])


def test_records_count_the_regular_season_only():
    frame = _two_games()

    class M:
        rating = staticmethod(lambda t: 0.0)
        pace = staticmethod(lambda t: 0.0)

    table = teams.standings(frame, M(), {"12": ("Chiefs", "KC"), "13": ("Raiders", "LV")})
    kc = table.set_index("team").loc["12"]
    assert (kc["wins"], kc["losses"]) == (1, 0)
    assert teams.expected_record(frame, "12") == (1.0, 0.0)
    # Records going in: the divisional game's is the regular season's 1-0.
    assert schedule._records(frame)["div"] == ("0-1", "1-0")
    season = previews._games_list(frame, {})
    assert previews._records_going_in(season)["div"] == ("0-1", "1-0")


# --------------------------------------------------------------------------- #
# 6. The watch guide and an untimed kickoff
# --------------------------------------------------------------------------- #

def _watch_frame():
    def g(gid, date, detail):
        return {"game_id": gid, "date": pd.Timestamp(date), "home": "Commanders",
                "away": "Cowboys", "home_id": "28", "away_id": "6", "home_abbr": "WSH",
                "away_abbr": "DAL", "home_record": "9-7", "away_record": "8-8",
                "home_score": None, "away_score": None, "pred_home": 24.0, "pred_away": 21.0,
                "pred_margin": 3.0, "home_win_prob": 0.6, "book_spread": -2.5,
                "neutral": False, "venue": "", "tv": "", "state": "pre", "detail": detail}
    return pd.DataFrame([g("tbd", "2027-01-10T05:00Z", "TBD"),
                         g("mnf", "2027-01-05T01:15Z", "Mon 8:15 PM")])


def test_an_untimed_week_18_game_is_on_its_own_day_in_the_tba_window(monkeypatch):
    monkeypatch.setattr(watch.predict, "season", lambda: (_watch_frame(), None, None))
    now = datetime(2027, 1, 4, 12, tzinfo=watch.ET)
    got = {g["id"]: g for g in watch.games(now, espn={})}
    tbd = got["tbd"]
    assert tbd["tk"] is False and tbd["slot"] == watch_page.TBA[0]
    assert tbd["day"] == "2027-01-10"                    # Sunday, not Saturday


def test_a_build_after_midnight_keeps_the_game_still_on(monkeypatch):
    """(A) Monday night's game kicked off at 8:15 ET; at 00:30 ET Tuesday it is
    still the guide's Monday, and the game is still in it."""
    monkeypatch.setattr(watch.predict, "season", lambda: (_watch_frame(), None, None))
    now = datetime(2027, 1, 5, 0, 30, tzinfo=watch.ET)
    got = {g["id"]: g for g in watch.games(now, espn={})}
    assert "mnf" in got and got["mnf"]["day"] == "2027-01-04"


# --------------------------------------------------------------------------- #
# 7. A tie has no winner to call
# --------------------------------------------------------------------------- #

def test_a_tie_is_out_of_the_winners_record():
    frame = pd.DataFrame({
        "pred_margin": [-2.0, 3.0, 4.0], "pred_total": [44.0] * 3,
        "market_spread": [1.5, -3.0, -3.5], "market_total": [44.5] * 3,
        "actual_margin": [0.0, 7.0, -3.0], "actual_total": [40.0, 41.0, 37.0],
        "kickoff": pd.to_datetime(["2026-09-13", "2026-09-14", "2026-09-15"], utc=True)})
    got = cfb_results.grade(frame)
    tie = got.iloc[0]
    # An away pick on a tie was graded right; the book's away favourite too.
    assert np.isnan(tie["correct"]) and np.isnan(tie["book_correct"])
    s = cfb_results.summary(got)
    assert (s["games"], s["correct"], s["book_games"]) == (2, 1, 2)
    assert s["winner_accuracy"] == 0.5 and s["correct_on_book_games"] == 1
    assert s["margin_mae"] == pytest.approx((2 + 4 + 7) / 3)    # the tie still has a miss


# --------------------------------------------------------------------------- #
# 9. A stakes game nobody ever lost
# --------------------------------------------------------------------------- #

def test_a_lopsided_stakes_game_is_left_out_whole():
    frame = pd.DataFrame({"roster_id": [1, 2, 3, 4], "manager": ["A", "B", "C", "D"],
                          "opponent": [2, 1, 4, 3], "playoff_odds": [.99, .2, .6, .4],
                          "win_prob": [1.0, 0.0, .55, .45],
                          "playoff_if_win": [.99, np.nan, .8, .6],
                          "playoff_if_loss": [np.nan, .2, .36, .24]})
    got = stakes.teams_from(frame, "roster_id", "manager")
    assert set(got) == {"3", "4"}
    assert "C vs D" in stakes.table(5, got)


# --------------------------------------------------------------------------- #
# 10, 11 and (B). The predictions page's cards
# --------------------------------------------------------------------------- #

def _card(**over):
    base = {"week": 1, "seasontype": 2, "game_id": "g1", "home_id": "26", "away_id": "8",
            "home": "Seahawks", "away": "Lions", "home_abbr": "SEA", "away_abbr": "DET",
            "home_score": 31.0, "away_score": 17.0, "played": True, "neutral": False,
            "pred_margin": 6.5, "pred_total": 47.0, "home_win_prob": 0.7,
            "book_spread": -3.0, "book_total": 45.5, "home_rating": 2.0, "away_rating": 1.0,
            "place": "Seattle, WA", "tv": "FOX", "detail": "Final",
            "date": pd.Timestamp("2026-09-13T20:25Z")}
    return pd.Series({**base, **over})


def test_a_final_with_no_call_on_record_shows_no_refit_as_a_call():
    html = predictions._card(_card(), {})
    assert "no call on record" in html
    assert "called" not in html and "proj" not in html and "-6.5" not in html
    assert "final 48" in html


def test_an_unset_playoff_game_and_an_untimed_kickoff_are_not_dressed_as_real():
    tbd = predictions._card(_card(seasontype=3, home_id="-1", away_id="-2", home="TBD",
                                  away="TBD", home_abbr="TBD", away_abbr="TBD", played=False,
                                  home_score=None, away_score=None, detail="TBD",
                                  date=pd.Timestamp("2027-01-17T05:00Z")), {})
    assert "Teams to be decided" in tbd
    assert "TBD -" not in tbd and "12:00 AM" not in tbd and "Sun, Jan 17, time TBD" in tbd
    assert "tbd.png" not in tbd                           # (B) no logo to 404
    untimed = predictions._card(_card(played=False, home_score=None, away_score=None,
                                      detail="TBD", date=pd.Timestamp("2027-01-10T05:00Z")), {})
    assert "time TBD" in untimed and "12:00 AM" not in untimed and "Seahawks -6.5" in untimed


def test_capture_archives_only_real_games(monkeypatch, tmp_path):
    monkeypatch.setattr(results, "PRED_DIR", tmp_path)
    future = pd.Timestamp("2030-01-06T18:00Z")
    board = pd.DataFrame([_card(game_id=gid, played=False, home_score=None, away_score=None,
                                date=future, **over)
                          for gid, over in (("real", {}),
                                            ("tbd", {"home_id": "-1", "away_id": "-2"}),
                                            ("untimed", {"detail": "TBD"}))])
    monkeypatch.setattr(results.predict, "season", lambda: (board, None, None))
    got = results.capture(2030)
    assert list(got["game_id"]) == ["real"]


def test_a_tbd_capture_already_on_file_is_never_the_call_on_record(monkeypatch, tmp_path):
    monkeypatch.setattr(results, "PRED_DIR", tmp_path)
    kick = "2027-01-17T18:00:00+00:00"
    pd.DataFrame([
        # Filed while the slot was TBD v TBD, then the same ESPN id with teams.
        {"captured": "2027-01-05T10:00:00+00:00", "game_id": "wc1", "kickoff": kick,
         "home_id": "-1", "away_id": "-2", "pred_margin": 2.1},
        {"captured": "2027-01-12T10:00:00+00:00", "game_id": "wc1", "kickoff": kick,
         "home_id": "12", "away_id": "13", "pred_margin": 6.0},
        # Teams never set before the archive's last look: nothing on record.
        {"captured": "2027-01-05T10:00:00+00:00", "game_id": "wc2", "kickoff": kick,
         "home_id": "-1", "away_id": "-2", "pred_margin": 2.1},
    ]).to_parquet(tmp_path / "2026.parquet")
    rec = results.on_record(2026).set_index("game_id")
    assert list(rec.index) == ["wc1"] and rec.loc["wc1", "pred_margin"] == 6.0


# --------------------------------------------------------------------------- #
# 12. "Through week N" is the last complete week
# --------------------------------------------------------------------------- #

def test_through_week_is_the_last_week_every_game_of_which_is_in():
    reg = pd.DataFrame({"week": [3, 3, 4], "game_id": ["a", "b", "c"]})
    sched = pd.DataFrame({"week": [3, 3, 4, 4, 4], "seasontype": [2] * 5,
                          "state": ["post", "post", "post", "pre", "post"],
                          "completed": [True, True, True, False, False],
                          "home_score": [20.0, 21.0, 24.0, None, 0.0],
                          "away_score": [10.0, 14.0, 17.0, None, 0.0]})
    # Thursday's game of week 4 is in; one is still to play (the third is
    # called off and owed by nobody).
    assert advanced.complete_through(reg, sched) == 3
    reg = pd.concat([reg, pd.DataFrame({"week": [4], "game_id": ["d"]})])
    assert advanced.complete_through(reg, sched) == 4
    assert advanced.complete_through(reg, None) == 4      # no schedule: the newest week
    assert advanced.complete_through(reg.iloc[:0], sched) == 0


# --------------------------------------------------------------------------- #
# 15. The playoff history survives a bad file and a killed write
# --------------------------------------------------------------------------- #

def test_a_history_that_will_not_parse_is_kept_aside(tmp_path):
    path = tmp_path / "2026.json"
    path.write_text('{"season": 2026, "snapshots": [{"at": "2026-10-01T21:55-04:00"', "utf-8")
    assert playoff_history.record(path, 2026, {"12": (0.7, 0.1)},
                                  now=datetime(2026, 10, 2, 12, tzinfo=playoff_history.ET))
    aside = list(tmp_path.glob("2026.json.bad-*"))
    assert len(aside) == 1 and aside[0].read_text("utf-8").startswith('{"season": 2026')
    assert len(json.loads(path.read_text("utf-8"))["snapshots"]) == 1
    assert not list(tmp_path.glob("*.tmp"))


def test_a_write_that_dies_leaves_the_last_good_file(tmp_path, monkeypatch):
    path = tmp_path / "2026.json"
    playoff_history.record(path, 2026, {"12": (0.7, 0.1)})
    before = path.read_text("utf-8")

    def killed(src, dst):
        raise OSError("power cut")

    monkeypatch.setattr(playoff_history.os, "replace", killed)
    with pytest.raises(OSError):
        playoff_history.record(path, 2026, {"12": (0.8, 0.2)})
    assert path.read_text("utf-8") == before


# --------------------------------------------------------------------------- #
# 16. Power-history windows in the zone, not today's offset
# --------------------------------------------------------------------------- #

def test_january_windows_are_in_eastern_standard_time():
    frame = pd.DataFrame({"week": [1, 2], "seasontype": [3, 2],
                          "date": pd.to_datetime(["2027-01-16T21:30Z", "2026-10-04T17:00Z"],
                                                 utc=True)})
    spans = {w: (a, b) for w, a, b in power.week_spans(frame)}
    assert spans[19][0] == datetime(2027, 1, 16, 16, 30)    # EST, -5
    assert spans[2][0] == datetime(2026, 10, 4, 13, 0)      # EDT, -4
