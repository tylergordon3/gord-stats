"""
The 2026-10-02 audit's college fixes, pinned. No network: ESPN's schedule, the
archive and the rating fit are stubbed, and the one browser check runs a
single JS function in headless Chromium.

- A cancelled or postponed game (ESPN: state=post, 0-0 or "Canceled") is no
  game still to play: not simulated for the playoff, not on a team's
  projected record, not priced - and its replay, a separate event, counts once.
- Bowl and CFP rows filed -1 against -2 ("TBD") build no previews.
- An untimed Saturday game is Saturday's, on the watch guide's tabs and on the
  home page's My teams card west of Eastern.
- The playoff page's records count title games, the CFP and the week after.
- Tempo counts every snap, not the garbage-time-free plays.
- Publishing the CBB lines record never loses a game the live file forgot.
- After midnight the watch guide still holds Saturday night's games.
- A failed Yahoo proxy is no points on the matchups page, not "0.0 final".
- The schedule's week switch shows the week picked last, and its live poll
  runs one loop and none in a hidden tab.
"""
import asyncio
import json
import re
import shutil
import subprocess
import time
import urllib.request
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from cfb import espn, games as games_mod, playoff, predict
from cfb.config import SEASON
from gordstats import watch_page

T0 = pd.Timestamp("2026-09-05T20:00Z")
IDS = [str(i) for i in range(1, 11)]


# --------------------------------------------------------------------------- #
# A ten-team season, through the real predict.season()
# --------------------------------------------------------------------------- #

def _round_robin(ids):
    """Nine rounds of five, every pair once (the circle method)."""
    ids = list(ids)
    out = []
    for _ in range(len(ids) - 1):
        out.append([(ids[k], ids[-1 - k]) for k in range(len(ids) // 2)])
        ids = [ids[0], ids[-1]] + ids[1:-1]
    return out


def _row(week, gid, home, away, state="pre", hs=np.nan, as_=np.nan, detail="", note="",
         when=None):
    kick = when if when is not None else T0 + pd.Timedelta(days=7 * (week - 1))
    return {"week": week, "game_id": gid, "date_utc": kick.strftime("%Y-%m-%dT%H:%MZ"),
            "time_valid": True, "home_id": home, "away_id": away, "home": f"T{home}",
            "away": f"T{away}", "home_rank": np.nan, "away_rank": np.nan,
            "home_score": hs, "away_score": as_, "neutral": False, "conference_game": True,
            "venue": "", "note": note, "place": "", "tv": "", "state": state,
            "detail": detail or ("Final" if state == "post" else "TBD")}


class _Model:
    """Just enough of cfb.ratings.Ratings: id 1 best, 10 worst."""

    def __init__(self, ids):
        self.teams = list(ids) + [games_mod.FCS]
        self._r = {t: 10.0 - i for i, t in enumerate(ids)}
        self._r[games_mod.FCS] = -20.0
        self.hfa = 2.5

    def rating(self, team):
        return self._r.get(team, -20.0)

    def pace(self, _team):
        return 0.0

    def predict(self, frame):
        home = frame["home_team"].map(self.rating).to_numpy(float)
        away = frame["away_team"].map(self.rating).to_numpy(float)
        margin = home - away + np.where(frame["neutral"].to_numpy(bool), 0.0, self.hfa)
        total = np.full(len(frame), 52.0)
        return pd.DataFrame({"pred_margin": margin, "pred_total": total,
                             "pred_home": (total + margin) / 2, "pred_away": (total - margin) / 2},
                            index=frame.index)


def _season(monkeypatch, rows):
    """predict.season() on `rows` as ESPN's schedule, the fit stubbed."""
    sched = pd.DataFrame(rows)
    past = pd.DataFrame([{"date_utc": "2025-11-01T20:00Z", "date": pd.Timestamp("2025-11-01T20:00Z"),
                          "home_id": "1", "away_id": "2", "home": "T1", "away": "T2",
                          "home_score": 30.0, "away_score": 20.0, "neutral": False,
                          "week": 10, "season": SEASON - 1}])
    model = _Model(IDS)
    monkeypatch.setattr(espn, "schedule", lambda *a, **k: sched.copy())
    monkeypatch.setattr(predict.games_mod, "load", lambda *a, **k: past.copy())
    monkeypatch.setattr(predict.ratings_mod, "fit", lambda *a, **k: model)
    monkeypatch.setattr(predict.efficiency, "corrected", lambda m, *a, **k: m)
    monkeypatch.setattr(predict, "margin_sd", lambda: 16.0)
    frame, model, names = predict.season(asof=pd.Timestamp("2026-10-01T12:00Z"))
    return frame, model, names, sched


def _league(frame, model, names, sched):
    conf = {t: "SEC" for t in IDS}
    return playoff.build(frame, model, names, conf, {}, sched, 16.0,
                         pd.Timestamp("2026-10-01T12:00Z"))


def _with_a_cancellation():
    """Weeks 1-4 played; in week 4, 1 v 2 called off (0-0, "Canceled") and
    replayed as a separate event in week 10."""
    rounds = _round_robin(IDS)
    week_12 = next(w for w, r in enumerate(rounds, 1) if ("1", "2") in r or ("2", "1") in r)
    # Put the 1-2 meeting in week 4, whichever round the circle gave it.
    rounds[3], rounds[week_12 - 1] = rounds[week_12 - 1], rounds[3]
    rows = []
    for week, pairs in enumerate(rounds, 1):
        for k, (h, a) in enumerate(pairs):
            gid = f"{week}{k}"
            if week <= 4:
                if {h, a} == {"1", "2"}:
                    rows.append(_row(week, gid, h, a, "post", 0.0, 0.0, detail="Canceled"))
                else:
                    rows.append(_row(week, gid, h, a, "post", 28.0, 21.0))
            else:
                rows.append(_row(week, gid, h, a))
    rows.append(_row(10, "replay", "2", "1"))
    return rows


def test_the_rule_is_post_with_no_score_or_a_status_that_says_so():
    s = pd.DataFrame([_row(1, "a", "1", "2", "post", 0.0, 0.0),
                      _row(1, "b", "1", "2", "post", 7.0, 3.0, detail="Canceled"),
                      _row(1, "c", "1", "2", "post", np.nan, np.nan, detail="Postponed"),
                      _row(1, "d", "1", "2", "post", 24.0, 17.0),
                      _row(1, "e", "1", "2", "pre", 0.0, 0.0),
                      _row(1, "f", "1", "2", "in", 0.0, 0.0, detail="1st 10:00")])
    assert predict.cancelled(s).tolist() == [True, True, True, False, False, False]


def test_a_cancelled_game_is_not_a_game_still_to_play(monkeypatch):
    rows = _with_a_cancellation()
    called_off = next(r["game_id"] for r in rows if r["detail"] == "Canceled")
    frame, model, names, sched = _season(monkeypatch, rows)
    assert called_off not in set(frame["game_id"]), "out of the season frame"
    replay = frame[frame["game_id"] == "replay"]
    assert len(replay) == 1 and not replay["played"].iloc[0]
    assert frame.loc[frame["state"] == "post", "played"].all(), "every final left is a real one"

    # The playoff simulation plays 1 v 2 once - the replay - and the season
    # has moved on to week 5 (the cancelled game held it at 4, the wander at 8).
    lg = _league(frame, model, names, sched)
    one, two = lg.teams.index("1"), lg.teams.index("2")
    g = lg.games
    meetings = g[((g.home == one) & (g.away == two)) | ((g.home == two) & (g.away == one))]
    assert len(meetings) == 1 and not meetings["played"].iloc[0]
    assert lg.next_week == 5

    # The team page: nine games, 1 v 2 once, three of them results.
    from cfb.site import teams
    w, l = teams._expected_record(frame, "1")
    assert round(w + l, 6) == 9
    assert teams._standings(frame, model, names).set_index("team").loc["1", "games"] == 9


def test_membership_counts_a_cancelled_game_before_it_is_dropped(monkeypatch):
    """A school with eight games on its schedule is FBS whether or not one of
    them was called off - and a "Canceled" final with a partial score never
    trains the ratings."""
    rows = [_row(w, f"x{w}", "X", f"Y{w}", "post", 21.0, 14.0) for w in range(1, 8)]
    rows.append(_row(8, "x8", "X", "Y8", "post", 7.0, 0.0, detail="Canceled"))
    sched = pd.DataFrame(rows)
    monkeypatch.setattr(espn, "schedule", lambda *a, **k: sched.copy())
    monkeypatch.setattr(predict.games_mod, "load", lambda *a, **k: pd.DataFrame(
        columns=["date_utc", "date", "home_id", "away_id", "home", "away",
                 "home_score", "away_score"]))
    _frame, schedule, _names = predict.history()
    assert "x8" not in set(schedule["game_id"])
    assert set(schedule["home_team"]) == {"X"}, "still rated as its own team"
    assert "x8" not in set(predict._current_season_games()["game_id"])


# --------------------------------------------------------------------------- #
# The playoff page's records
# --------------------------------------------------------------------------- #

def test_records_count_the_title_game_the_week_after_and_the_cfp(monkeypatch):
    rows = []
    for week, pairs in enumerate(_round_robin(IDS), 1):
        for k, (h, a) in enumerate(pairs):
            first = "1" in (h, a)
            hs, as_ = (35.0, 10.0) if (h == "1" or not first) else (10.0, 35.0)
            rows.append(_row(week, f"{week}{k}", h, a, "post", hs, as_))
    rows.append(_row(10, "title", "1", "2", "post", 31.0, 24.0, note="SEC Championship"))
    rows.append(_row(11, "after", "3", "1", "post", 14.0, 17.0))       # Army-Navy's Saturday
    rows.append(_row(espn.POSTSEASON_WEEK, "qf", "1", "4", "post", 27.0, 20.0,
                     note="College Football Playoff Quarterfinal",
                     when=pd.Timestamp("2027-01-01T20:00Z")))
    frame, model, names, sched = _season(monkeypatch, rows)
    lg = _league(frame, model, names, sched)
    rec = playoff.records(lg)
    assert rec[lg.teams.index("1")] == (12, 0), "9-0, the title, the week after, the CFP"
    two = lg.teams.index("2")
    assert sum(rec[two]) == 10 and rec[two][1] >= 2, "the title game lost is on it"
    assert sum(rec[lg.teams.index("4")]) == 10, "the CFP game lost is on it"


def test_a_hand_built_league_still_counts_titles_and_the_cfp():
    games = pd.DataFrame({"home": [0], "away": [1], "neutral": [False], "conf_game": [True],
                          "played": [True], "home_won": [1.0], "mean": [3.0], "ahead": [1]})
    lg = playoff.League(teams=["a", "b", "c"], names={}, conf=["SEC"] * 3, division=[""] * 3,
                        rating=np.zeros(4), home_edge=2.5, margin_sd=16.0, games=games,
                        title={"SEC": {"pair": (0, 1), "winner": 1}},
                        cfp_results={(1, 2): 2})
    assert playoff.records(lg) == {0: (1, 1), 1: (1, 2), 2: (1, 0)}


# --------------------------------------------------------------------------- #
# Previews: no "TBD at TBD"
# --------------------------------------------------------------------------- #

def test_placeholder_sides_are_not_fbs_and_get_no_preview():
    from cfb.site import previews
    rows = []
    for week, pairs in enumerate(_round_robin(IDS), 1):
        for k, (h, a) in enumerate(pairs):
            rows.append(_row(week, f"{week}{k}", h, a, "post", 28.0, 21.0))
    bowls = pd.Timestamp("2026-12-20T20:00Z")
    for k in range(40):                                  # every bowl until it is paired
        rows.append(_row(espn.POSTSEASON_WEEK, f"b{k}", "-1", "-2", when=bowls))
    rows.append(_row(espn.POSTSEASON_WEEK, "paired", "1", "2", when=bowls))
    rows.append(_row(espn.POSTSEASON_WEEK, "half", "3", "-2", when=bowls))
    frame = pd.DataFrame(rows)
    frame["dk_spread"] = np.nan
    fbs = previews._fbs(frame)
    assert "-1" not in fbs and "-2" not in fbs and set(IDS) <= fbs
    got = previews.window(frame, pd.Timestamp("2026-12-14T12:00Z"))
    bowls = got[got["week"] == espn.POSTSEASON_WEEK]
    assert set(bowls["game_id"]) == {"paired"}, "no TBD side, not even one"
    assert len(got) == len(bowls) + 5, "and the last regular week's five"


# --------------------------------------------------------------------------- #
# Untimed games keep their day
# --------------------------------------------------------------------------- #

def test_game_day_rolls_back_only_a_real_small_hours_kickoff():
    midnight = pd.Timestamp("2026-10-10T04:00:00Z")          # 12:00 AM EDT, Saturday
    assert watch_page.game_day(midnight, False) == "2026-10-10", "untimed: its own day"
    assert watch_page.game_day(midnight, True) == "2026-10-09", "a real 12 AM: the night before"
    assert watch_page.game_day(midnight) == "2026-10-09", "the old call still means a real time"
    assert watch_page.game_day(pd.Timestamp("2026-10-10T16:00Z"), False) == "2026-10-10"


def _watch_games(monkeypatch, rows, now):
    """cfb.site.watch.games() on these model rows, nothing else read."""
    from cfb.site import watch
    base = {"week": 7, "tv": "", "note": "", "neutral": False, "home_rank": np.nan,
            "away_rank": np.nan, "home_score": np.nan, "away_score": np.nan,
            "pred_home": 30.0, "pred_away": 20.0, "pred_margin": 10.0, "home_win_prob": 0.7,
            "state": "pre", "time_valid": True}
    frame = pd.DataFrame([dict(base, **r) for r in rows])
    monkeypatch.setattr(watch.predict, "season", lambda *a, **k: (frame.copy(), None, {}))
    monkeypatch.setattr(watch.odds_mod, "latest", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(watch.gameinfo, "load", lambda *a, **k: {})
    monkeypatch.setattr(watch, "_playoff_odds", lambda: {})
    monkeypatch.setattr(watch.preview_page, "href", lambda *a, **k: None)
    return {g["id"]: g for g in watch.games(now)}


def test_the_cfb_guide_files_an_untimed_saturday_game_on_saturday(monkeypatch):
    got = _watch_games(monkeypatch, [
        dict(game_id="tba", date=pd.Timestamp("2026-10-10T04:00Z"), time_valid=False,
             home_id="1", home="Florida", away_id="2", away="South Carolina"),
        dict(game_id="late", date=pd.Timestamp("2026-10-10T04:30Z"),
             home_id="3", home="Hawaii", away_id="4", away="Fresno St")],
        datetime(2026, 10, 9, 12, 0, tzinfo=watch_page.ET))
    assert (got["tba"]["day"], got["tba"]["slot"]) == ("2026-10-10", "tba")
    assert (got["late"]["day"], got["late"]["slot"]) == ("2026-10-09", "late")


def test_after_midnight_the_guide_still_holds_saturday_night(monkeypatch):
    """The live tick at 12:30 AM Sunday: Saturday's 10:30 PM kickoff is still
    on, and still Saturday's - not dropped because the clock passed midnight."""
    got = _watch_games(monkeypatch, [
        dict(game_id="sat-late", date=pd.Timestamp("2026-10-11T02:30Z"), state="in",
             home_id="1", home="Hawaii", away_id="2", away="UNLV"),
        dict(game_id="sat-noon", date=pd.Timestamp("2026-10-10T16:00Z"), state="post",
             home_id="3", home="Ohio State", away_id="4", away="Iowa"),
        dict(game_id="fri", date=pd.Timestamp("2026-10-09T23:00Z"), state="post",
             home_id="5", home="Tulane", away_id="6", away="Memphis")],
        datetime(2026, 10, 11, 0, 30, tzinfo=watch_page.ET))
    assert got["sat-late"]["day"] == "2026-10-10"
    assert set(got) == {"sat-late", "sat-noon"}, "the guide's day is Saturday's, Friday is gone"


CHROME = next((p for p in ("/usr/bin/chromium-browser", "/usr/bin/chromium",
                           "/usr/bin/google-chrome") if shutil.which(p)), None)
CDP = 9539


def _in_chromium(steps, tz: str = None):
    """[(expression, seconds to wait after it)] in one headless Chromium page,
    the reader's clock in `tz`; the last expression's value."""
    import websockets
    from browser_util import launch, reap
    subprocess.run(["fuser", "-k", f"{CDP}/tcp"], capture_output=True)
    proc = launch(CHROME, CDP)
    try:
        ws_url = None
        for _ in range(60):
            try:
                ws_url = next(t["webSocketDebuggerUrl"] for t in json.load(
                    urllib.request.urlopen(f"http://127.0.0.1:{CDP}/json")) if t["type"] == "page")
                break
            except Exception:                               # noqa: BLE001
                time.sleep(0.5)

        async def go():
            async with websockets.connect(ws_url, max_size=None) as ws:
                n = 0

                async def send(method, params):
                    nonlocal n
                    n += 1
                    await ws.send(json.dumps({"id": n, "method": method, "params": params}))
                    while True:
                        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
                        if msg.get("id") == n:
                            return msg.get("result", {})
                if tz:
                    await send("Emulation.setTimezoneOverride", {"timezoneId": tz})
                value = None
                for expression, wait in steps:
                    got = await send("Runtime.evaluate", {"expression": expression,
                                                          "returnByValue": True,
                                                          "awaitPromise": True})
                    if got.get("exceptionDetails"):
                        raise AssertionError(got["exceptionDetails"])
                    value = got["result"].get("value")
                    await asyncio.sleep(wait)
                return value
        return asyncio.run(go())
    finally:
        proc.terminate()
        reap(proc)
        subprocess.run(["fuser", "-k", f"{CDP}/tcp"], capture_output=True)


needs_chrome = pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")


@needs_chrome
def test_my_teams_names_an_untimed_games_day_in_eastern():
    from gordstats import my_teams_today
    fn = re.search(r"function day\(t, known\)\{.*?\n  \}", my_teams_today.JS, re.S).group(0)
    got = _in_chromium([("(function(){" + fn + "; return [day('2026-10-10T04:00:00Z', false),"
                         " day('2026-10-10T04:00:00Z', true), day(null, true)];})()", 0)],
                       tz="America/Los_Angeles")
    assert got[0].startswith("Sat") and got[0].endswith("TBA"), got
    assert got[1].startswith("Fri") and "9:00" in got[1], "a real time stays the reader's own"
    assert got[2] == "TBA", "no time at all is not 1970"


@needs_chrome
def test_a_failed_matchups_proxy_is_no_points():
    """A 502 or an ok:false from the Yahoo proxy reaches the live updater as
    nothing, not as a payload that reads every started player "0.0 final"."""
    from cfb.site import matchups
    answers = {"502": {"ok": False, "status": 502, "body": {"ok": False, "error": "yahoo 500"}},
               "false": {"ok": True, "status": 200, "body": {"ok": False, "error": "bad"}},
               "good": {"ok": True, "status": 200, "body": {"ok": True, "teams": {"t1": {"points": 9}}}},
               "html": {"ok": True, "status": 200, "body": None}}
    stub = ("window.A=" + json.dumps(answers) + ";window.fetch=function(u){"
            "var k=u.match(/week=(\\w+)/)[1],a=A[k];"
            "return Promise.resolve({ok:a.ok,status:a.status,json:function(){"
            "return a.body===null?Promise.reject(new SyntaxError('<html>')):Promise.resolve(a.body);}});};")
    got = _in_chromium([(stub + matchups.API_JS + ";true", 0),
                        ("Promise.all(['502','false','good','html'].map(muCfbApi))"
                         ".then(function(x){return JSON.stringify(x);})", 0)])
    assert json.loads(got) == [{"teams": {}}, {"teams": {}}, answers["good"]["body"], {"teams": {}}]


# --------------------------------------------------------------------------- #
# The schedule page's week switch and live poll
# --------------------------------------------------------------------------- #

@needs_chrome
def test_a_slow_week_never_lands_over_the_one_picked_after_it_and_one_poll_loop():
    from cfb.site import schedule
    html = schedule._switcher([5, 6, 7], 6, {6: "<p>six</p>"}, controls=schedule._controls({}))
    js = schedule._JS % {"upset": "0.3", "current": 6, "cols": schedule._COLS,
                         "url": json.dumps("/api/cfb-scores?week=6")}
    js = re.sub(r"</?script>", "", js)
    boot = (
        "window.HIDDEN=true;Object.defineProperty(document,'hidden',{configurable:true,"
        "get:function(){return window.HIDDEN;}});"
        "window.ASKED=[];window.fetch=function(u){ASKED.push(u);"
        "if(u.indexOf('/api/cfb-scores')===0)return new Promise(function(res){"
        "window.RELEASE=function(){res({ok:true,json:function(){return Promise.resolve({events:[]});}});};});"
        "var w=u.match(/week-(\\d+)/)[1];"
        "return new Promise(function(res){setTimeout(function(){res({ok:true,text:function(){"
        "return Promise.resolve('<p>week '+w+'</p>');}});},w==='7'?800:20);});};"
        "document.body.innerHTML=" + json.dumps(html) + ";(0,eval)(" + json.dumps(js) + ");true")
    polls = "ASKED.filter(function(u){return u.indexOf('/api/cfb-scores')===0;}).length"
    got = _in_chromium([
        (boot, 0.2),
        ("window.BOOT=" + polls + ";true", 0),             # hidden at boot: no poll
        ("HIDDEN=false;document.dispatchEvent(new Event('visibilitychange'));"
         "document.dispatchEvent(new Event('visibilitychange'));"
         "document.dispatchEvent(new Event('visibilitychange'));true", 0.2),
        ("window.POLLS=" + polls + ";RELEASE();show_wk('7');show_wk('5');true", 1.5),
        ("JSON.stringify({boot:BOOT,polls:POLLS,five:document.getElementById('wk-view-5').style.display,"
         "seven:document.getElementById('wk-view-7').style.display,"
         "tab:document.querySelector('.wk-btn.active').id,hash:location.hash})", 0)])
    got = json.loads(got)
    assert got["boot"] == 0, "a tab opened in the background does not poll"
    assert got["polls"] == 1, "one loop, however often the tab comes back"
    assert (got["five"], got["seven"], got["tab"]) == ("", "none", "wk-tab-5")
    assert "w=5" in got["hash"]


# --------------------------------------------------------------------------- #
# Tempo
# --------------------------------------------------------------------------- #

def test_plays_a_game_counts_every_snap(tmp_path, monkeypatch):
    from cfb import advanced, efficiency
    from cfb.site import previews
    pd.DataFrame({"team": ["Georgia"] * 4 + ["Toledo"] * 2,
                  "offense_plays": [61, 62, 66, 53, 80, 0]}).to_parquet(
        tmp_path / f"{SEASON}.parquet")
    monkeypatch.setattr(efficiency, "ARCHIVE", tmp_path)
    caches = {"wepa": {n: {"id": i, "conf": "", **{k: None for k in (
                  "off", "off_pass", "off_rush", "def", "def_pass", "def_rush", "sr", "sr_sd",
                  "sr_pd", "sr_a", "sr_sd_a", "sr_pd_a", "line", "line_a", "expl", "expl_a")}}
                       for n, i in (("Georgia", "61"), ("Toledo", "2649"), ("Akron", "2006"))},
              # The garbage-time-free count: 150 over four games read "38 a game".
              "advanced": {"Georgia": {"off": {"plays": 150}, "def": {}}},
              "season_stats": {"Georgia": {"games": 4}}, "talent": {}}
    monkeypatch.setattr(advanced, "_load", lambda name: caches[name])
    rows = {r["name"]: r for r in advanced.teams()}
    assert rows["Georgia"]["plays_pg"] == 60.5
    assert rows["Toledo"]["plays_pg"] == 80.0, "a zero-play row is a hole, not a game"
    assert rows["Akron"]["plays_pg"] is None
    ranks = {"plays_pg": (60.5, 2, 2)}
    assert previews._style(ranks, {}) == "60 plays a game (2nd most)"

    monkeypatch.setattr(efficiency, "ARCHIVE", tmp_path / "missing")
    assert advanced._plays_per_game() == {}


# --------------------------------------------------------------------------- #
# The CBB lines record
# --------------------------------------------------------------------------- #

def test_publishing_never_drops_a_game_the_live_file_forgot(tmp_path, monkeypatch):
    from cbb import lines
    monkeypatch.setattr(lines, "LIVE_DIR", tmp_path / "live")
    monkeypatch.setattr(lines, "RECORD_DIR", tmp_path / "record")
    record = {"men:1": {"league": "men", "spread": "DUKE -3", "home_score": 80, "final": True},
              "men:2": {"league": "men", "spread": "UNC -1", "total": 140.5}}
    lines._write(tmp_path / "record" / "2027.json", record)
    # The live file started again from nothing (a fresh clone): game 2 seen
    # only after tipoff, game 3 new.
    lines._write(tmp_path / "live" / "2027.json",
                 {"men:2": {"league": "men", "home_score": 70, "away_score": 66, "final": True},
                  "men:3": {"league": "men", "spread": "KU -7"}})
    assert lines.publish(2027) == 3
    got = json.loads((tmp_path / "record" / "2027.json").read_text())
    assert got["men:1"] == record["men:1"], "a game only the record has is kept"
    assert got["men:2"] == {"league": "men", "spread": "UNC -1", "total": 140.5,
                            "home_score": 70, "away_score": 66, "final": True}
    assert got["men:3"]["spread"] == "KU -7"
    before = (tmp_path / "record" / "2027.json").stat().st_mtime_ns
    lines.publish(2027)
    assert (tmp_path / "record" / "2027.json").stat().st_mtime_ns == before, "unchanged, unwritten"
