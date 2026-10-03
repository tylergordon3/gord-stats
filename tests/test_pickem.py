"""
gordstats.pickem: the contest's weeks, the frozen slate, locks, grading and
the GordStats entry - everything the pipeline decides before a reader picks.

All from synthetic schedules (the shapes of data/nfl/games/<season>.parquet,
data/cfb/schedule_<season>.parquet and the CFB watch guide's games.json), so
nothing here reads the network or the real data/.
"""
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from gordstats import pickem

ET = ZoneInfo("America/New_York")
UTC = timezone.utc


def iso(dt):
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%MZ")


def nfl_row(gid, kick, home="BUF", away="MIA", state="pre", hs=None, as_=None, week=5,
            seasontype=2, completed=None, detail="", **extra):
    row = {"week": week, "seasontype": seasontype, "game_id": str(gid), "date_utc": iso(kick),
           "home_id": str(sum(map(ord, home))), "away_id": str(sum(map(ord, away))),
           "home": home.title(), "away": away.title(), "home_abbr": home, "away_abbr": away,
           "home_score": hs, "away_score": as_, "home_record": "3-1", "away_record": "1-3",
           "neutral": False, "venue": "", "place": "", "indoor": False, "tv": "CBS",
           "state": state, "completed": bool(completed if completed is not None
                                              else state == "post"),
           "detail": detail or ("Final" if state == "post" else ""), "round": None,
           "book_spread": None, "book_total": None, "odds_detail": "", "season": 2026}
    row.update(extra)
    return row


def cfb_row(gid, kick, home="Iowa", away="Ohio State", state="pre", hs=None, as_=None, week=6,
            detail="", time_valid=True, home_id=None, away_id=None, **extra):
    row = {"week": week, "game_id": str(gid), "date_utc": iso(kick), "time_valid": time_valid,
           "home_id": home_id or str(1000 + int(gid) % 997), "away_id": away_id or str(2000 + int(gid) % 997),
           "home": home, "home_abbr": home[:4].upper(), "home_rank": None, "home_score": hs,
           "away": away, "away_abbr": away[:4].upper(), "away_rank": 3.0, "away_score": as_,
           "neutral": False, "note": "", "tv": "FOX", "state": state, "detail": detail}
    row.update(extra)
    return row


def frame(rows):
    return pd.DataFrame(rows)


def rows(*rs):
    return {r["game_id"]: r for r in rs}


def watch(gid, score):
    return {"id": str(gid), "score": score,
            "h": {"lg": f"https://a.espncdn.com/h/{gid}.png", "rk": None},
            "a": {"lg": f"https://a.espncdn.com/a/{gid}.png", "rk": 3}}


# 2026: the opener is Wednesday Sep 9, 8:20 PM ET (as ESPN has it).
OPENER = datetime(2026, 9, 9, 20, 20, tzinfo=ET)
FIRST = pickem.first_window(OPENER)
W5_START, W5_END = pickem.window(FIRST, 5)
SAT = datetime(2026, 10, 10, 12, 0, tzinfo=ET)        # week 5's Saturday
SUN = datetime(2026, 10, 11, 13, 0, tzinfo=ET)
TUE = datetime(2026, 10, 6, 6, 0, tzinfo=ET)          # the week's first run


def week5(slate=None, now=TUE, cfb=None, nfl=None, watch_list=None, probs=None):
    return pickem.update_week(slate, season=2026, week=5, start=W5_START, end=W5_END, now=now,
                              cfb=cfb or {}, nfl=nfl or {}, watch=watch_list or [],
                              probs=probs or {})


# --------------------------------------------------------------------------- #
# Weeks
# --------------------------------------------------------------------------- #

def test_week_one_starts_the_tuesday_before_the_opener_and_weeks_run_tuesday_to_monday():
    assert FIRST == datetime(2026, 9, 8, tzinfo=ET)
    assert pickem.first_window(datetime(2026, 9, 10, 20, 20, tzinfo=ET)) == FIRST   # a Thursday
    assert pickem.first_window(datetime(2026, 9, 8, 21, 0, tzinfo=ET)) == FIRST     # a Tuesday
    assert (W5_START, W5_END) == (datetime(2026, 10, 6, tzinfo=ET), datetime(2026, 10, 13, tzinfo=ET))
    assert pickem.week_of(FIRST, OPENER) == 1
    assert pickem.week_of(FIRST, datetime(2026, 10, 12, 23, 59, tzinfo=ET)) == 5     # Monday night
    assert pickem.week_of(FIRST, datetime(2026, 10, 13, 0, 0, tzinfo=ET)) == 6       # Tuesday
    # A Monday night game's kickoff, in UTC already Tuesday, is still week 5.
    assert pickem.week_of(FIRST, pd.Timestamp("2026-10-13T00:15Z")) == 5
    assert pickem.week_of(FIRST, datetime(2026, 8, 29, 15, 0, tzinfo=ET)) <= 0       # CFB week 0


def test_the_window_keeps_to_midnight_across_the_clock_change():
    start, end = pickem.window(FIRST, 8)          # Oct 27 - Nov 3; clocks go back Nov 1
    assert start.isoformat() == "2026-10-27T00:00:00-04:00"
    assert end.isoformat() == "2026-11-03T00:00:00-05:00"
    assert pickem.week_of(FIRST, datetime(2026, 11, 2, 23, 0, tzinfo=ET)) == 8
    assert pickem.week_of(FIRST, datetime(2026, 11, 3, 0, 30, tzinfo=ET)) == 9


def test_the_season_runs_from_the_nfl_opener_to_the_super_bowl():
    nfl = frame([nfl_row(1, OPENER, week=1),
                 nfl_row(2, datetime(2026, 9, 13, 13, 0, tzinfo=ET), week=1),
                 nfl_row(3, datetime(2027, 1, 16, 0, 0, tzinfo=ET), "TBD", "TBD", week=1,
                         seasontype=3),
                 nfl_row(4, datetime(2027, 2, 14, 18, 30, tzinfo=ET), "TBD", "TBD", week=4,
                         seasontype=3)])
    first, last = pickem.season_bounds(nfl)
    assert first == FIRST
    assert last == 23                             # Feb 9-15: the Super Bowl's week
    assert pickem.week_of(first, datetime(2027, 1, 17, 13, 0, tzinfo=ET)) == 19   # wild card
    assert pickem.season_bounds(pd.DataFrame()) is None


# --------------------------------------------------------------------------- #
# The slate
# --------------------------------------------------------------------------- #

def _cfb_week(n=14):
    """n college games on week 5's Saturday, the watch guide scoring them 90, 85, ..."""
    games = [cfb_row(100 + i, SAT + timedelta(minutes=30 * (i % 4)), home=f"Home{i}",
                     away=f"Away{i}") for i in range(n)]
    return rows(*games), [watch(100 + i, 90 - 5 * i) for i in range(n)]


def test_a_new_week_is_every_nfl_game_and_the_ten_best_college_games():
    cfb, w = _cfb_week()
    nfl = rows(nfl_row(1, datetime(2026, 10, 8, 20, 15, tzinfo=ET)),            # Thursday
               nfl_row(2, SUN), nfl_row(3, SUN, "NYJ", "NE"),
               nfl_row(4, datetime(2026, 10, 12, 20, 15, tzinfo=ET)),           # Monday
               nfl_row(5, datetime(2026, 10, 13, 20, 0, tzinfo=ET)),            # next week
               nfl_row(6, datetime(2026, 10, 3, 13, 0, tzinfo=ET)),             # last week
               nfl_row(7, SUN, "TBD", "TBD"),                                   # unknown teams
               nfl_row(8, SUN, "AFC", "NFC"))                                   # the Pro Bowl
    # A college game outside the window, one with no teams yet and one with
    # no watch score are not candidates, however they would rank.
    cfb["900"] = cfb_row(900, datetime(2026, 10, 14, 19, 0, tzinfo=ET))
    cfb["901"] = cfb_row(901, SAT, home="TBD", away="TBD", home_id="-1", away_id="-2")
    cfb["902"] = cfb_row(902, SAT)
    w = [watch(900, 99), watch(901, 98), {"id": "902", "score": None}] + w
    s = week5(cfb=cfb, nfl=nfl, watch_list=w)
    ids = [g["id"] for g in s["games"]]
    assert ids[:4] == ["nfl:1", "nfl:2", "nfl:3", "nfl:4"]
    assert ids[4:] == [f"cfb:{100 + i}" for i in range(pickem.FEATURED)]
    assert s["n"] == 14 and s["label"] == "Week 5" and s["sub"] == "NFL Week 5 · CFB Week 6"
    top = s["games"][4]
    assert top["gotw"] is True and sum(1 for g in s["games"] if g.get("gotw")) == 1
    assert top["watch"] == 90.0 and top["h"]["lg"] == "https://a.espncdn.com/h/100.png"
    assert top["a"]["rk"] == 3 and top["lock"] == top["ko"] == iso(SAT).replace("Z", ":00Z")
    nfl_game = s["games"][1]
    assert nfl_game["h"]["lg"].endswith("/nfl/500/buf.png&w=80&h=80")
    assert nfl_game["h"]["rec"] == "3-1" and nfl_game["res"] is None and nfl_game["st"] == "pre"
    assert s["opened"] == "2026-10-06T10:00:00Z"
    # Nothing at all in a window: no slate.
    assert week5() is None


def test_the_slate_is_frozen_added_to_never_dropped_or_reordered():
    cfb, w = _cfb_week()
    nfl = rows(nfl_row(2, SUN))
    first = week5(cfb=cfb, nfl=nfl, watch_list=w)
    ids = [g["id"] for g in first["games"]]

    # The guide changes its mind completely: the slate does not.
    flipped = [watch(100 + i, 10 + 5 * i) for i in range(14)]
    nfl["7"] = nfl_row(7, SUN, "TBD", "TBD")
    again = week5(first, now=TUE + timedelta(days=1), cfb=cfb, nfl=nfl, watch_list=flipped)
    assert [g["id"] for g in again["games"]] == ids
    assert again["opened"] == first["opened"]
    assert again["games"][1]["watch"] == 90.0, "the score it was picked on"

    # A game whose teams are now known joins at the end; one already locked never does.
    nfl["7"] = nfl_row(7, SUN, "DAL", "PHI")
    nfl["8"] = nfl_row(8, datetime(2026, 10, 8, 20, 15, tzinfo=ET), "KC", "LV")
    later = week5(again, now=datetime(2026, 10, 9, 9, 0, tzinfo=ET), cfb=cfb, nfl=nfl,
                  watch_list=flipped)
    assert [g["id"] for g in later["games"]] == ids + ["nfl:7"]

    # Ten college games is the most: a top-up only fills an empty place.
    short = {k: v for k, v in list(cfb.items())[:7]}
    few = week5(cfb=short, nfl=nfl, watch_list=w)
    assert sum(g["sp"] == "cfb" for g in few["games"]) == 7
    more = week5(few, now=TUE + timedelta(hours=5), cfb=cfb, nfl=nfl, watch_list=w)
    got = [g["id"] for g in more["games"]]
    assert got[:len(few["games"])] == [g["id"] for g in few["games"]]
    assert sum(g["sp"] == "cfb" for g in more["games"]) == pickem.FEATURED
    assert got[-3:] == ["cfb:107", "cfb:108", "cfb:109"]


def test_a_game_on_the_slate_keeps_its_place_when_espn_drops_it_and_is_void_after_the_week():
    cfb, w = _cfb_week(2)
    s = week5(cfb=cfb, watch_list=w)
    gone = week5(s, now=SAT - timedelta(hours=1), cfb={"100": cfb["100"]}, watch_list=w)
    assert [g["id"] for g in gone["games"]] == ["cfb:100", "cfb:101"]
    assert gone["games"][1]["res"] is None
    late = week5(gone, now=W5_END + pickem.GRACE + timedelta(hours=1), cfb={"100": cfb["100"]})
    assert late["games"][1]["res"] == "v"
    # The game still listed but never played (state pre) is void too.
    assert late["games"][0]["res"] == "v"
    assert pickem.done(late)


# --------------------------------------------------------------------------- #
# Locks
# --------------------------------------------------------------------------- #

def _one(kick, **kw):
    return rows(nfl_row(2, kick, **kw))


def test_a_lock_follows_a_moved_kickoff_until_it_passes_then_never_moves():
    s = week5(nfl=_one(SUN))
    lock = s["games"][0]["lock"]
    # Flexed later, before the lock: the lock follows.
    later = SUN + timedelta(hours=7, minutes=20)
    s = week5(s, now=SAT, nfl=_one(later))
    assert s["games"][0]["lock"] == s["games"][0]["ko"] == later.astimezone(UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    # Moved earlier: so does the lock.
    s = week5(s, now=SAT, nfl=_one(SUN))
    assert s["games"][0]["lock"] == lock
    # Kicked off, then postponed to next week: the lock stays where it was.
    after = SUN + timedelta(hours=1)
    s = week5(s, now=after, nfl=_one(SUN + timedelta(days=3), state="post", completed=False,
                                      detail="Postponed", hs=0, as_=0))
    assert s["games"][0]["lock"] == lock and s["games"][0]["res"] == "v"


def test_a_game_shown_started_locks_at_once_and_one_called_off_never_locks_later():
    s = week5(nfl=_one(SUN))
    early = SAT + timedelta(hours=2)
    started = week5(s, now=early, nfl=_one(SUN, state="in", hs=7, as_=0))
    assert started["games"][0]["lock"] == early.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    off = week5(s, now=SAT, nfl=_one(SUN + timedelta(days=2), state="post", completed=False,
                                     detail="Postponed", hs=0, as_=0))
    assert off["games"][0]["lock"] == s["games"][0]["lock"]
    assert off["games"][0]["res"] == "v"


def test_an_untimed_game_locks_at_its_midnight():
    midnight = datetime(2026, 10, 10, 0, 0, tzinfo=ET)
    cfb = rows(cfb_row(100, midnight, time_valid=False))
    s = week5(cfb=cfb, watch_list=[watch(100, 80)])
    g = s["games"][0]
    assert g["tk"] is False and g["lock"] == "2026-10-10T04:00:00Z"


# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #

def test_results_winners_and_the_games_that_score_nothing():
    kick = SAT
    cfb = rows(cfb_row(100, kick), cfb_row(101, kick), cfb_row(102, kick), cfb_row(103, kick))
    nfl = rows(nfl_row(1, SUN), nfl_row(2, SUN), nfl_row(3, SUN), nfl_row(4, SUN))
    w = [watch(100 + i, 80 - i) for i in range(4)]
    s = week5(cfb=cfb, nfl=nfl, watch_list=w)
    final = {
        "100": cfb_row(100, kick, state="post", hs=31, as_=17, detail="Final"),
        "101": cfb_row(101, kick, state="post", hs=10, as_=24, detail="Final/OT"),
        "102": cfb_row(102, kick, state="post", hs=0, as_=0, detail="Canceled"),
        "103": cfb_row(103, kick, state="post", hs=None, as_=None, detail="Postponed"),
    }
    nfl_final = {
        "1": nfl_row(1, SUN, state="post", hs=20, as_=20, detail="Final/OT"),          # a tie
        "2": nfl_row(2, SUN, state="post", hs=0, as_=0, completed=False, detail="Canceled"),
        "3": nfl_row(3, SUN + timedelta(days=4)),                                       # moved out
        "4": nfl_row(4, SUN, state="in", hs=3, as_=0, detail="2nd Quarter"),
    }
    after = SUN + timedelta(hours=5)
    got = {g["id"]: g for g in week5(s, now=after, cfb=final, nfl=nfl_final)["games"]}
    assert got["cfb:100"]["res"] == "h" and got["cfb:100"]["score"] == {"h": 31, "a": 17}
    assert got["cfb:101"]["res"] == "a"
    assert got["cfb:102"]["res"] == "v" and got["cfb:103"]["res"] == "v"
    assert got["nfl:1"]["res"] == "v" and got["nfl:2"]["res"] == "v" and got["nfl:3"]["res"] == "v"
    assert got["nfl:4"]["res"] is None and got["nfl:4"]["st"] == "in"
    assert got["nfl:4"]["score"] == {"h": 3, "a": 0}


# --------------------------------------------------------------------------- #
# The GordStats entry
# --------------------------------------------------------------------------- #

def test_gordstats_picks_favorites_ranked_by_win_chance():
    nfl = rows(nfl_row(1, SUN), nfl_row(2, SUN), nfl_row(3, SUN), nfl_row(4, SUN))
    probs = {"nfl:1": 0.55, "nfl:2": 0.2, "nfl:3": 0.9, "nfl:4": 0.5}
    s = week5(nfl=nfl, probs=probs)
    gs = {g["id"]: g["gs"] for g in s["games"]}
    assert gs == {"nfl:3": {"s": "h", "c": 4, "p": 0.9}, "nfl:2": {"s": "a", "c": 3, "p": 0.2},
                  "nfl:1": {"s": "h", "c": 2, "p": 0.55}, "nfl:4": {"s": "h", "c": 1, "p": 0.5}}
    # No chance on file: no pick, and its value is left for the rest.
    s2 = week5(nfl=nfl, probs={"nfl:1": 0.6})
    assert [g["gs"] for g in s2["games"]][1:] == [None, None, None]
    assert s2["games"][0]["gs"] == {"s": "h", "c": 4, "p": 0.6}


def test_a_locked_gordstats_pick_never_changes_and_the_open_ones_rerank_around_it():
    nfl = rows(nfl_row(1, datetime(2026, 10, 8, 20, 15, tzinfo=ET)), nfl_row(2, SUN),
               nfl_row(3, SUN))
    s = week5(nfl=nfl, probs={"nfl:1": 0.95, "nfl:2": 0.6, "nfl:3": 0.7})
    assert s["games"][0]["gs"]["c"] == 3
    # Thursday's game has kicked off; the model now loves game 2 most - and
    # Thursday's chance has moved since. Its pick stays as it locked.
    friday = datetime(2026, 10, 9, 9, 0, tzinfo=ET)
    s = week5(s, now=friday, nfl=nfl, probs={"nfl:1": 0.1, "nfl:2": 0.99, "nfl:3": 0.7})
    gs = {g["id"]: g["gs"] for g in s["games"]}
    assert gs["nfl:1"] == {"s": "h", "c": 3, "p": 0.95}
    assert gs["nfl:2"] == {"s": "h", "c": 2, "p": 0.99} and gs["nfl:3"]["c"] == 1
    # A game added later makes N bigger; the new top value goes to the surest open game.
    nfl["4"] = nfl_row(4, SUN, "DAL", "PHI")
    s = week5(s, now=friday, nfl=nfl, probs={"nfl:2": 0.99, "nfl:3": 0.7, "nfl:4": 0.8})
    gs = {g["id"]: g["gs"]["c"] for g in s["games"]}
    assert gs == {"nfl:1": 3, "nfl:2": 4, "nfl:4": 2, "nfl:3": 1}
    # An archive that has lost a game's chance keeps the last one it had.
    s = week5(s, now=friday, nfl=nfl, probs={"nfl:3": 0.7, "nfl:4": 0.8})
    assert {g["id"]: g["gs"]["c"] for g in s["games"]} == gs
    values = sorted(g["gs"]["c"] for g in s["games"])
    assert values == [1, 2, 3, 4], "each value once"


# --------------------------------------------------------------------------- #
# Building and publishing
# --------------------------------------------------------------------------- #

@pytest.fixture
def dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(pickem, "DATA", tmp_path / "data" / "pickem")
    monkeypatch.setattr(pickem, "OUT", tmp_path / "docs" / "pickem")
    monkeypatch.delenv("GS_PREGAME_SIDECAR", raising=False)
    monkeypatch.setattr(pickem.paths, "DATA", tmp_path / "data")
    return tmp_path


def _inputs():
    cfb, w = _cfb_week(3)
    nfl = frame([nfl_row(1, OPENER, week=1), nfl_row(2, SUN), nfl_row(3, SUN, "NYJ", "NE"),
                 nfl_row(9, datetime(2027, 2, 14, 18, 30, tzinfo=ET), "TBD", "TBD", week=4,
                         seasontype=3)])
    return {"nfl": nfl, "cfb": frame(list(cfb.values())), "watch": w,
            "probs": {"nfl:2": 0.7, "nfl:3": 0.4, "cfb:100": 0.8}}


def test_build_writes_the_record_and_the_published_files(dirs):
    idx = pickem.build(TUE, 2026, _inputs())
    record = dirs / "data" / "pickem" / "2026" / "week_05.json"
    slate = json.loads(record.read_text())
    assert slate["week"] == 5 and slate["v"] == 1 and len(slate["games"]) == 5
    published = json.loads((dirs / "docs" / "pickem" / "2026" / "week_05.json").read_text())
    assert published == slate
    season = json.loads((dirs / "docs" / "pickem" / "season.json").read_text())
    assert season == idx and season["season"] == 2026 and season["current"] == 5
    [wk] = season["weeks"]
    assert wk["w"] == 5 and wk["n"] == 5 and wk["done"] is False
    first = wk["g"][0]
    assert first[0] == "nfl:2" and first[1] == int(SUN.timestamp()) and first[2] is None
    assert first[3:] == ["h", 4]                  # cfb:100 (0.8) has 5
    # A second run that changes nothing changes no file.
    before = record.read_text()
    pickem.build(TUE + timedelta(minutes=10), 2026, _inputs())
    assert record.read_text() == before
    # A run that changes something counts it.
    later = _inputs()
    later["probs"]["nfl:3"] = 0.1
    pickem.build(TUE + timedelta(hours=6), 2026, later)
    assert json.loads(record.read_text())["v"] == 2


def test_build_finishes_old_weeks_and_moves_on(dirs):
    pickem.build(TUE, 2026, _inputs())
    # The next Tuesday: week 5's games are final, week 6 has none on file.
    finals = _inputs()
    nfl = finals["nfl"]
    nfl.loc[nfl.game_id.isin(["2", "3"]), ["state", "completed", "home_score", "away_score"]] = \
        ["post", True, 24, 10]
    cfb = finals["cfb"]
    cfb[["state", "home_score", "away_score"]] = ["post", 30, 20]
    idx = pickem.build(datetime(2026, 10, 13, 6, 0, tzinfo=ET), 2026, finals)
    assert idx["weeks"][0]["done"] is True and idx["current"] == 5
    assert [g[2] for g in idx["weeks"][0]["g"]] == ["h"] * 5


def test_the_untracked_copy_survives_a_checkout(dirs, monkeypatch):
    monkeypatch.setenv("GS_PREGAME_SIDECAR", "1")
    pickem.build(TUE, 2026, _inputs())
    side = dirs / "data" / "pickem_live" / "2026" / "week_05.json"
    record = dirs / "data" / "pickem" / "2026" / "week_05.json"
    assert side.read_text() == record.read_text()
    # A tick adds a game (v 2), then the next tick's checkout puts the tracked file back.
    old = record.read_text()
    more = _inputs()
    more["nfl"] = pd.concat([more["nfl"], frame([nfl_row(4, SUN, "DAL", "PHI")])])
    pickem.build(TUE + timedelta(hours=1), 2026, more)
    assert json.loads(side.read_text())["v"] == 2
    record.write_text(old)
    slates = pickem.load(2026)
    assert slates[5]["v"] == 2 and "nfl:4" in [g["id"] for g in slates[5]["games"]]
    # Without the switch only the tracked file is read.
    monkeypatch.delenv("GS_PREGAME_SIDECAR")
    assert pickem.load(2026)[5]["v"] == 1


def test_nothing_to_build_outside_a_season(dirs):
    assert pickem.build(TUE, 2026, {"nfl": pd.DataFrame(), "cfb": pd.DataFrame(),
                                    "watch": [], "probs": {}}) is None
    assert not (dirs / "docs" / "pickem" / "season.json").exists()


def test_the_index_points_at_the_next_week_between_weeks():
    slates = {5: {"label": "Week 5", "start": "", "end": "", "games": []},
              7: {"label": "Week 7", "start": "", "end": "", "games": []}}
    assert pickem.index(2026, slates, datetime(2026, 10, 15, tzinfo=ET), FIRST)["current"] == 7
    assert pickem.index(2026, slates, datetime(2026, 12, 1, tzinfo=ET), FIRST)["current"] == 7
    assert pickem.index(2026, slates, datetime(2026, 10, 7, tzinfo=ET), FIRST)["current"] == 5


def test_probabilities_take_the_last_archived_chance_over_the_guides(tmp_path, monkeypatch):
    from cfb import results as cfb_results
    from nfl import results as nfl_results

    docs = tmp_path / "docs"
    (docs / "nfl" / "watch").mkdir(parents=True)
    (docs / "nfl" / "watch" / "games.json").write_text(json.dumps(
        {"games": [{"id": "1", "hw": 0.3}, {"id": "2", "hw": 0.6}]}))
    monkeypatch.setattr(pickem.paths, "DOCS", docs)
    monkeypatch.setattr(nfl_results, "on_record",
                        lambda: pd.DataFrame({"game_id": ["1"], "home_win_prob": [0.71]}))
    monkeypatch.setattr(cfb_results, "on_record", lambda: (_ for _ in ()).throw(OSError("none")))
    got = pickem.probabilities([{"id": "100", "hw": 0.8}])
    assert got == {"nfl:1": 0.71, "nfl:2": 0.6, "cfb:100": 0.8}
