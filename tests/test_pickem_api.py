"""
/api/pickem: readers' picks with confidence points, locked at kickoff by the
server, graded against the pipeline's published finals, with a GordStats entry.

The Function runs in headless Chromium against a real SQLite built from
deploy/d1-schema.sql (tests/functions_harness.py). The published files it
reads (/pickem/season.json and the week files) come from a stub env.ASSETS
built here from Python dicts - the shapes gordstats.pickem writes - with lock
times set against the real clock, since the Function judges locks by its own.
"""
import json
import re
import sqlite3
import time

import pytest

from functions_harness import CHROME, FUNCTIONS, SCHEMA, Worker

pytestmark = pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")

PICKEM = FUNCTIONS / "api" / "pickem.js"
ROUTE = FUNCTIONS / "api" / "pickem" / "[[route]].js"
MIGRATION_007 = SCHEMA.parent / "d1-migrate-007-pickem.sql"
URL = "https://www.gordstats.com/api/pickem"
SEASON = 2026
HOUR = 3600


def game(gid, lock_in, res=None, gs=None):
    """One game of the season file: [id, lock epoch s, result, GS side, GS value]."""
    side, conf = gs or (None, None)
    return [gid, int(time.time()) + lock_in, res, side, conf]


def slate_for(week, games):
    """The week file the page shows, matching the season file's games."""
    return {"season": SEASON, "week": week, "label": f"Week {week}", "sub": "NFL Week 5",
            "start": "2026-10-06T00:00:00-04:00", "end": "2026-10-13T00:00:00-04:00",
            "n": len(games),
            "games": [{"id": g[0], "sp": g[0][:3], "ko": "2026-10-10T19:30:00Z", "tk": True,
                       "lock": "2026-10-10T19:30:00Z", "h": {"nm": "Home"}, "a": {"nm": "Away"},
                       "st": "pre", "res": g[2],
                       "gs": {"s": g[3], "c": g[4], "p": 0.7} if g[3] else None}
                      for g in games]}


# Week 5 is this week: two games locked (one final, one in progress), three open.
WEEK5 = [game("nfl:1", -5 * HOUR, "h", ("h", 5)),
         game("cfb:2", -1 * HOUR, None, ("a", 4)),
         game("nfl:3", 6 * HOUR, None, ("h", 3)),
         game("cfb:4", 30 * HOUR, None, ("a", 2)),
         game("nfl:5", 50 * HOUR, None, ("h", 1))]
# Week 4 is over: a winner each way, a tie (void) and a cancelled game (void).
WEEK4 = [game("nfl:11", -200 * HOUR, "h", ("h", 4)),
         game("nfl:12", -199 * HOUR, "a", ("h", 3)),
         game("nfl:13", -198 * HOUR, "v", ("a", 2)),
         game("cfb:14", -197 * HOUR, "v", ("h", 1))]


def files(weeks=None, current=5):
    weeks = weeks or {4: WEEK4, 5: WEEK5}
    index = {"season": SEASON, "current": current,
             "weeks": [{"w": w, "label": f"Week {w}", "sub": "", "n": len(g),
                        "done": all(x[2] is not None for x in g), "g": g}
                       for w, g in sorted(weeks.items())]}
    out = {"/pickem/season.json": index}
    for w, g in weeks.items():
        out[f"/pickem/{SEASON}/week_{w:02d}.json"] = slate_for(w, g)
    return out


def install(w, published):
    """env.ASSETS answering from `published` ({path: json}); 404 for anything else."""
    w.js("""
      window.FILES = %s;
      window.ASSETS = { calls: [], async fetch(u) {
        const path = new URL(u).pathname;
        ASSETS.calls.push(path);
        const f = FILES[path];
        return f === undefined ? new Response("not found", { status: 404 })
                               : new Response(JSON.stringify(f), { status: 200 });
      } };""" % json.dumps(published))


def env(w, **extra):
    base = {"SESSION_SECRET": "test-secret", "GOOGLE_CLIENT_ID": "cid",
            "GOOGLE_CLIENT_SECRET": "csecret"}
    base.update(extra)
    return f"Object.assign({{ DB: T.db(SQL), ASSETS: window.ASSETS }}, {json.dumps(base)})"


@pytest.fixture
def worker():
    with Worker() as w:
        w.load(PICKEM, "pk")
        w.load(ROUTE, "pkr")
        install(w, files())
        yield w


def get(w, who=None, week=None, e=None):
    url = URL + (f"?week={week}" if week is not None else "")
    return w.call("pk.onRequestGet", url, headers=who or {}, env=e or env(w))


def post(w, who, action, body, e=None):
    return w.call("pkr.onRequestPost", f"{URL}/{action}", method="POST", headers=who,
                  body=body, env=e or env(w), ctx="{ params: { route: [%s] } }" % json.dumps(action))


def join(w, who, name):
    return post(w, who, "name", {"name": name})


def save(w, who, picks, week=5, season=SEASON):
    return post(w, who, "picks", {"season": season, "week": week, "picks": picks})


def reader(w, uid="u1", name="Reader One"):
    who = w.user(uid)
    assert join(w, who, name)["status"] == 200
    return who


def stored(w, uid="u1", week=5):
    rows = w.sql.rows("SELECT picks FROM pickem_entries WHERE user_id = ? AND week = ?", uid, week)
    return {k: v[:2] for k, v in json.loads(rows[0]["picks"]).items()} if rows else None


def no_email(*answers):
    for a in answers:
        assert "@example.com" not in a["text"], a["text"][:300]
        assert "email" not in a["text"]


# --------------------------------------------------------------------------- #
# Display names
# --------------------------------------------------------------------------- #

GOOD_NAMES = ["Big Ten Bob", "  Roll   Tide  ", "o'neil", "J.R._Smith-2", "Spicy Takes",
              "Raccoon Nation", "Tycoon", "Scunthorpe Utd", "Nigeria Fan", "Dykes Era", "abc",
              "Twenty Characters Ok"]
BAD_NAMES = ["ab", "x" * 21, "", "   ", None, 7, "-Lead", "Trail.", "under score!", "<b>hi</b>",
             "émile", "123", "GordStats", "gord stats", "Gord.Stats Fan", "GORDSTATS2",
             "Admin", "you", "Mod"]


def test_names_are_checked(worker):
    got = worker.js("return %s.map((n) => pk.validName(n));" % json.dumps(GOOD_NAMES))
    assert all(g["ok"] for g in got), [n for n, g in zip(GOOD_NAMES, got) if not g["ok"]]
    assert got[1]["name"] == "Roll Tide" and got[1]["key"] == "rolltide"
    assert got[3]["key"] == "jrsmith2"
    bad = worker.js("return %s.map((n) => pk.validName(n));" % json.dumps(BAD_NAMES))
    assert not any(b["ok"] for b in bad), [n for n, b in zip(BAD_NAMES, bad) if b["ok"]]
    assert all(b["error"] for b in bad)


def test_slurs_are_refused_including_dressed_up(worker):
    # The list is base64 in the source; check a few from it, spelled around.
    words = worker.js("""
      const src = %s;
      const b64 = src.match(/atob\\(\\s*((?:"[^"]*"\\s*\\+?\\s*)+)\\)/)[1]
        .replace(/[\\s+"]/g, "");
      return JSON.parse(atob(b64));""" % json.dumps(PICKEM.read_text()))
    stems, whole = words
    assert len(stems) >= 15 and len(whole) >= 10
    tries = [stems[0].capitalize(), f"Big {stems[0]} 99", stems[4].replace("o", "0"),
             f"the {whole[0]}", f"{whole[2]} fan", stems[6].upper()]
    got = worker.js("return %s.map((n) => pk.validName(n));" % json.dumps(tries))
    assert not any(g["ok"] for g in got), [t for t, g in zip(tries, got) if g["ok"]]
    assert {g["error"] for g in got} == {"Please choose a different name."}


def test_joining_takes_a_unique_name_and_never_shows_the_email(worker):
    a, b = worker.user("u1"), worker.user("u2")
    assert join(worker, {}, "Nobody")["status"] == 401
    first = join(worker, a, "  Roll   Tide ")
    assert first["status"] == 200 and first["json"] == {"ok": True, "saved": True,
                                                        "name": "Roll Tide"}
    assert first["headers"]["cache-control"] == "no-store"
    # Case and punctuation do not make a different name.
    for clash in ("roll tide", "ROLLTIDE", "Roll-Tide", "roll.tide"):
        got = join(worker, b, clash)
        assert got["status"] == 409 and got["json"]["taken"] is True, clash
    assert join(worker, b, "Hook Em")["status"] == 200
    bad = join(worker, b, "GordStats")
    assert bad["status"] == 400 and "reserved" in bad["json"]["error"]
    assert join(worker, b, "x")["status"] == 400

    # Renaming frees the old name; the same name again writes nothing.
    assert join(worker, a, "Bama Fan")["json"]["name"] == "Bama Fan"
    again = join(worker, a, "Bama Fan")
    assert again["json"] == {"ok": True, "saved": False, "name": "Bama Fan"}
    assert join(worker, b, "Roll Tide")["status"] == 200
    rows = worker.sql.rows("SELECT user_id, name, name_key FROM pickem_players ORDER BY user_id")
    assert rows == [{"user_id": "u1", "name": "Bama Fan", "name_key": "bamafan"},
                    {"user_id": "u2", "name": "Roll Tide", "name_key": "rolltide"}]
    # Each change is one row of the reader's allowance.
    assert worker.sql.rows("SELECT write_count FROM users WHERE id = 'u1'")[0]["write_count"] == 2

    save(worker, a, {"nfl:3": ["h", 3]})
    pub, mine = get(worker), get(worker, a)
    no_email(first, again, pub, mine)
    assert mine["json"]["me"] == {"name": "Bama Fan"}
    assert [r["name"] for r in pub["json"]["board"]["week"]] == ["GordStats", "Bama Fan"]


def test_a_name_is_needed_before_picks(worker):
    who = worker.user()
    got = save(worker, who, {"nfl:3": ["h", 3]})
    assert got["status"] == 409 and got["json"]["need_name"] is True
    assert worker.sql.rows("SELECT * FROM pickem_entries") == []
    mine = get(worker, who)
    assert mine["json"]["signedIn"] is True and mine["json"]["me"] is None


# --------------------------------------------------------------------------- #
# Picks, confidence and locks
# --------------------------------------------------------------------------- #

def test_picks_save_and_come_back(worker):
    who = reader(worker)
    got = save(worker, who, {"nfl:3": ["h", 3], "cfb:4": ["a", 5], "nfl:5": ["a", 1]})
    assert got["status"] == 200 and got["json"]["saved"] is True
    assert got["json"]["picks"] == {"nfl:3": ["h", 3], "cfb:4": ["a", 5], "nfl:5": ["a", 1]}
    assert stored(worker) == got["json"]["picks"]
    # Each pick carries when it was set.
    raw = json.loads(worker.sql.rows("SELECT picks FROM pickem_entries")[0]["picks"])
    assert all(abs(p[2] - time.time()) < 120 for p in raw.values())

    mine = get(worker, who)
    assert mine["status"] == 200 and mine["json"]["mine"] == got["json"]["picks"]
    assert mine["json"]["week"] == 5 and mine["json"]["slate"]["week"] == 5
    # The same picks again: no write, no allowance spent.
    before = worker.sql.rows("SELECT write_count FROM users WHERE id = 'u1'")[0]["write_count"]
    again = save(worker, who, {"nfl:3": ["h", 3], "cfb:4": ["a", 5], "nfl:5": ["a", 1]})
    assert again["json"]["saved"] is False
    assert worker.sql.rows("SELECT write_count FROM users WHERE id = 'u1'")[0]["write_count"] == before
    # Leaving a game out of an open week takes its pick away.
    out = save(worker, who, {"nfl:3": ["h", 3]})
    assert out["json"]["picks"] == {"nfl:3": ["h", 3]}
    assert stored(worker) == {"nfl:3": ["h", 3]}
    assert worker.sql.rows("SELECT rev FROM pickem_entries")[0]["rev"] == 2


def test_a_body_bigger_than_a_week_is_refused_before_it_is_read(worker):
    who = reader(worker)
    big = post(worker, who, "picks", {"season": SEASON, "week": 5,
                                      "picks": {"nfl:3": ["h", 3]}, "pad": "x" * 5000})
    assert big["status"] == 413 and stored(worker) is None
    assert post(worker, who, "name", {"name": "Reader Two", "pad": "y" * 5000})["status"] == 413
    assert post(worker, who, "picks", "not json at all")["status"] == 400
    assert post(worker, who, "picks", [1, 2])["status"] == 400


def test_each_value_once_and_in_range_and_swaps_go_through(worker):
    who = reader(worker)
    assert save(worker, who, {"nfl:3": ["h", 3], "cfb:4": ["a", 2]})["status"] == 200
    dup = save(worker, who, {"nfl:3": ["h", 3], "cfb:4": ["a", 3]})
    assert dup["status"] == 400 and "once" in dup["json"]["error"]
    assert dup["json"]["picks"] == {"nfl:3": ["h", 3], "cfb:4": ["a", 2]}, "the page resyncs"
    for bad in ({"nfl:3": ["h", 6]}, {"nfl:3": ["h", 0]}, {"nfl:3": ["h", 2.5]},
                {"nfl:3": ["x", 2]}, {"nfl:99": ["h", 2]}, {"nfl:3": ["h"]},
                {"nfl:3": "h"}, ["nfl:3"], "picks"):
        got = save(worker, who, bad)
        assert got["status"] == 400, bad
    # A swap is one save: both values move at once.
    swap = save(worker, who, {"nfl:3": ["h", 2], "cfb:4": ["a", 3]})
    assert swap["status"] == 200 and stored(worker) == {"nfl:3": ["h", 2], "cfb:4": ["a", 3]}
    assert worker.sql.rows("SELECT COUNT(*) AS n FROM pickem_entries")[0]["n"] == 1
    assert save(worker, who, {"nfl:3": ["h", 2]}, week=9)["status"] == 404
    assert save(worker, who, {"nfl:3": ["h", 2]}, season=2025)["status"] == 409
    assert post(worker, who, "picks", "not json")["status"] == 400


def test_locks_are_the_servers_and_locked_picks_hold_their_values(worker):
    who = reader(worker)
    # Before the lock: worker's game 2 locked an hour ago, so seed its pick
    # the way an earlier save would have, in time.
    worker.sql.execute(
        "INSERT INTO pickem_entries (season, user_id, week, picks, rev, updated_at) "
        "VALUES (?, 'u1', 5, ?, 1, '2026-10-10T00:00:00Z')",
        SEASON, json.dumps({"cfb:2": ["a", 5, 1], "nfl:3": ["h", 1, 1]}))

    # A locked game cannot be added, changed or given another value...
    for change in ({"nfl:1": ["h", 4]},                       # no pick before its lock
                   {"cfb:2": ["h", 5]},                        # other side
                   {"cfb:2": ["a", 4]}):                       # other value
        got = save(worker, who, {"nfl:3": ["h", 1], **change})
        assert got["status"] == 409 and "locked" in got["json"]["error"], change
        assert got["json"]["picks"] == {"cfb:2": ["a", 5], "nfl:3": ["h", 1]}
    # ...and its value is not free for an open game.
    taken = save(worker, who, {"cfb:2": ["a", 5], "nfl:3": ["h", 5]})
    assert taken["status"] == 400
    # Leaving the locked pick out keeps it; the open ones move around it.
    ok = save(worker, who, {"nfl:3": ["a", 4], "cfb:4": ["h", 3], "nfl:5": ["h", 2]})
    assert ok["status"] == 200
    assert ok["json"]["picks"] == {"cfb:2": ["a", 5], "nfl:3": ["a", 4], "cfb:4": ["h", 3],
                                   "nfl:5": ["h", 2]}
    raw = json.loads(worker.sql.rows("SELECT picks FROM pickem_entries")[0]["picks"])
    assert raw["cfb:2"] == ["a", 5, 1], "a locked pick keeps when it was set"

    # Locks are judged on the server's clock alone: a lock a second ago is
    # locked whatever the request says about time.
    install(worker, files({5: [game("nfl:3", -1), game("cfb:4", HOUR)]}))
    late = post(worker, who, "picks", {"season": SEASON, "week": 5, "now": 0,
                                       "picks": {"nfl:3": ["h", 1], "cfb:4": ["h", 2]}})
    assert late["status"] == 409


def test_a_whole_week_locked_changes_nothing(worker):
    who = reader(worker)
    got = save(worker, who, {"nfl:11": ["h", 4]}, week=4)
    assert got["status"] == 409
    assert save(worker, who, {}, week=4)["json"]["saved"] is False
    assert worker.sql.rows("SELECT * FROM pickem_entries") == []


def test_parallel_saves_never_leave_a_value_twice(worker):
    who = reader(worker)
    sets = [{"nfl:3": ["h", a], "cfb:4": ["a", b], "nfl:5": ["h", c]}
            for a, b, c in ((3, 2, 1), (1, 3, 2), (2, 1, 3), (3, 1, 2), (2, 3, 1), (1, 2, 3))]
    statuses = worker.js(f"""
      const env = {env(worker)};
      const one = (picks) => pkr.onRequestPost({{ env, params: {{ route: ["picks"] }},
        request: T.req({json.dumps(URL + "/picks")}, {{ method: "POST",
          headers: {json.dumps(who)},
          body: JSON.stringify({{ season: {SEASON}, week: 5, picks }}) }}) }});
      return (await Promise.all({json.dumps(sets)}.map(one))).map((r) => r.status);""")
    assert all(s in (200, 409) for s in statuses) and 200 in statuses
    final = stored(worker)
    assert final in sets, final
    assert sorted(v[1] for v in final.values()) == [1, 2, 3]


def test_the_allowance_and_the_site_ceiling_cover_saves(worker):
    who = reader(worker)
    today = worker.js("return new Date().toISOString().slice(0, 10);")
    worker.sql.execute("UPDATE users SET write_day = ?, write_count = 1000", today)
    got = save(worker, who, {"nfl:3": ["h", 3]})
    assert got["status"] == 429 and int(got["headers"]["retry-after"]) > 0
    assert join(worker, who, "Other Name")["status"] == 429
    worker.sql.execute("UPDATE users SET write_count = 0")
    worker.sql.execute("INSERT OR REPLACE INTO site_writes (id, day, written) VALUES (1, ?, 40000)",
                       today)
    full = save(worker, who, {"nfl:3": ["h", 3]})
    assert full["status"] == 503 and full["json"]["site_limit"] is True
    assert worker.sql.rows("SELECT * FROM pickem_entries") == []


# --------------------------------------------------------------------------- #
# Grading and the leaderboards
# --------------------------------------------------------------------------- #

def test_grading_counts_winners_and_nothing_for_void_games(worker):
    games = worker.js("""return [...new Map(FILES['/pickem/season.json'].weeks[0].g
                                  .map((g) => [g[0], g]))];""")
    picks = {"nfl:11": ["h", 4, 0], "nfl:12": ["h", 3, 0], "nfl:13": ["a", 2, 0],
             "cfb:14": ["h", 1, 0]}
    got = worker.js(f"return pk.grade({json.dumps(picks)}, new Map({json.dumps(games)}));")
    # Right on 11 (4); wrong on 12; 13 a tie and 14 cancelled score nothing.
    assert got == {"pts": 4, "right": 1, "of": 2, "max": 4, "n": 4}
    open_ = worker.js("""const g = new Map(FILES['/pickem/season.json'].weeks[1].g.map((x) => [x[0], x]));
      return pk.grade({"nfl:1": ["h", 5, 0], "cfb:2": ["h", 4, 0], "nfl:3": ["a", 3, 0]}, g);""")
    assert open_ == {"pts": 5, "right": 1, "of": 1, "max": 12, "n": 3}


def test_the_boards_rank_readers_with_gordstats_and_sum_the_season(worker):
    a, b, c = (reader(worker, f"u{i}", n) for i, n in ((1, "Alpha"), (2, "Bravo"), (3, "Charlie")))
    # Week 4 is over: seed entries as saved before it locked.
    for uid, picks in (("u1", {"nfl:11": ["h", 4, 1], "nfl:12": ["a", 3, 1]}),      # 7
                       ("u2", {"nfl:11": ["h", 3, 1], "nfl:12": ["a", 4, 1],
                               "nfl:13": ["h", 2, 1]}),                             # 7, void 2
                       ("u3", {"nfl:11": ["a", 4, 1]})):                            # 0
        worker.sql.execute("INSERT INTO pickem_entries (season, user_id, week, picks, rev, "
                           "updated_at) VALUES (?, ?, 4, ?, 1, 'x')", SEASON, uid,
                           json.dumps(picks))
    worker.sql.execute("INSERT INTO pickem_entries (season, user_id, week, picks, rev, "
                       "updated_at) VALUES (?, 'u3', 5, ?, 1, 'x')", SEASON,
                       json.dumps({"nfl:1": ["h", 5, 1], "cfb:2": ["a", 4, 1]}))     # 5 so far
    got = get(worker, week=4)
    assert got["status"] == 200 and got["headers"]["cache-control"] == "no-store"
    body = got["json"]
    assert body["signedIn"] is False and abs(body["now"] - time.time() * 1000) < 60_000
    wk = body["board"]["week"]
    # GordStats week 4: right on 11 (4), wrong on 12, 13/14 void -> 4.
    assert [(r["r"], r["name"], r["pts"], r["right"]) for r in wk] == [
        (1, "Alpha", 7, 2), (1, "Bravo", 7, 2), (3, "GordStats", 4, 1), (4, "Charlie", 0, 0)]
    assert [r.get("gs", False) for r in wk] == [False, False, True, False]
    assert wk[0]["of"] == 2 and wk[0]["max"] == 7
    season = body["board"]["season"]
    # Season: Alpha 7, Bravo 7, Charlie 0+5, GordStats 4 + 5 (week 5's final game).
    assert [(r["name"], r["pts"], r["wk"]) for r in season] == [
        ("GordStats", 9, 2), ("Alpha", 7, 1), ("Bravo", 7, 1), ("Charlie", 5, 2)]
    weeks = {w["w"]: w for w in body["weeks"]}
    assert weeks[4]["done"] is True and weeks[4]["players"] == 3 and weeks[4]["gs"] == 4
    assert weeks[4]["top"] == [{"name": "Alpha", "pts": 7}, {"name": "Bravo", "pts": 7}]
    assert weeks[5]["done"] is False and weeks[5]["players"] == 1
    assert body["slate"]["week"] == 4
    assert body["current"] == 5 and body["week"] == 4
    no_email(got)
    # Nobody's picks are in the public answer - only points.
    assert '"picks"' not in got["text"] and "mine" not in body


def test_the_public_answer_is_shared_for_a_minute_and_a_readers_is_their_own(worker):
    worker.js("""window.edge = T.cache();
      Object.defineProperty(window, "caches", { value: { default: edge }, configurable: true });""")
    who = reader(worker)
    save(worker, who, {"nfl:3": ["h", 3]})
    first = get(worker)
    worker.js("await T.settle();")
    assert worker.js("return [...edge.store.keys()];") == [URL + "?public=1&week=current"]
    calls = worker.js("return ASSETS.calls.length;")
    worker.sql.execute("DELETE FROM pickem_entries")
    again = get(worker)
    assert again["json"]["board"] == first["json"]["board"], "served from the cache"
    assert worker.js("return ASSETS.calls.length;") == calls
    assert again["json"]["now"] >= first["json"]["now"], "the clock is never cached"
    # Signed in, the reader's own picks come fresh from the database.
    mine = get(worker, who)
    assert mine["json"]["mine"] == {} and mine["headers"]["cache-control"] == "no-store"


def test_signed_out_is_read_only_and_works_without_accounts(worker):
    got = get(worker, e="({ ASSETS: window.ASSETS })")
    assert got["status"] == 200 and got["json"]["configured"] is False
    assert [r["name"] for r in got["json"]["board"]["week"]] == ["GordStats"]
    assert got["json"]["slate"]["games"][0]["id"] == "nfl:1"
    assert save(worker, {}, {"nfl:3": ["h", 3]})["status"] == 401
    off = post(worker, {}, "picks", {"season": SEASON, "week": 5, "picks": {}},
               e="({ ASSETS: window.ASSETS })")
    assert off["status"] == 503
    assert worker.sql.rows("SELECT * FROM pickem_entries") == []


def test_weeks_that_do_not_exist_and_a_season_not_yet_published(worker):
    assert get(worker, week=9)["status"] == 404
    for bad in ("0", "x", "100", "-1", "5.0"):
        assert worker.call("pk.onRequestGet", f"{URL}?week={bad}", env=env(worker))["status"] == 400
    install(worker, {})
    empty = get(worker)
    assert empty["status"] == 200 and empty["json"]["season"] is None
    assert empty["json"]["weeks"] == [] and empty["json"]["slate"] is None
    # Published but unreadable is a failure, not "nothing yet" - and never cached.
    install(worker, {"/pickem/season.json": {"season": SEASON, "current": 5, "weeks": [
        {"w": 5, "g": WEEK5}]}})
    assert get(worker)["status"] == 503


def test_routes_that_are_not_actions_are_not_found(worker):
    who = reader(worker)
    for route in (["vote"], ["picks", "x"], ["name", "picks"]):
        got = worker.call("pkr.onRequestPost", f"{URL}/{'/'.join(route)}", method="POST",
                          headers=who, body={}, env=env(worker),
                          ctx="{ params: { route: %s } }" % json.dumps(route))
        assert got["status"] == 404, route
    bare = worker.call("pkr.onRequestGet", URL, env=env(worker), ctx="{ params: {} }")
    assert bare["status"] == 200 and bare["json"]["week"] == 5


def test_deleting_an_account_takes_its_name_and_picks(worker):
    who = reader(worker)
    save(worker, who, {"nfl:3": ["h", 3]})
    worker.load(FUNCTIONS / "api" / "account.js", "acct")
    assert worker.call("acct.onRequestDelete", "https://www.gordstats.com/api/account",
                       method="DELETE", headers=who)["status"] == 200
    assert worker.sql.rows("SELECT * FROM pickem_entries") == []
    assert worker.sql.rows("SELECT * FROM pickem_players") == []
    assert save(worker, who, {"nfl:3": ["h", 3]})["status"] == 401


# --------------------------------------------------------------------------- #
# Deployed ahead of migration 007, and the migration itself
# --------------------------------------------------------------------------- #

def _before_007() -> str:
    sql = re.sub(r"--[^\n]*", "", SCHEMA.read_text())
    return re.sub(r"CREATE TABLE IF NOT EXISTS pickem_\w+ \(.*?\) WITHOUT ROWID;", "", sql,
                  flags=re.S)


def _shape(db):
    tables = [r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
    return ({t: sorted(tuple(c)[1:] for c in db.execute(f"PRAGMA table_xinfo({t})"))
             for t in tables},
            sorted(r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'index'")))


def test_migration_007_brings_a_database_to_the_schema_and_can_run_again():
    old = sqlite3.connect(":memory:")
    old.executescript(_before_007())
    assert "pickem_entries" not in _shape(old)[0]
    old.executescript(MIGRATION_007.read_text())
    fresh = sqlite3.connect(":memory:")
    fresh.executescript(SCHEMA.read_text())
    assert _shape(old) == _shape(fresh)
    old.executescript(MIGRATION_007.read_text())            # no ALTER: harmless again
    assert _shape(old) == _shape(fresh)


def test_a_save_is_one_row_and_the_reads_use_the_keys():
    db = sqlite3.connect(":memory:")
    db.executescript(SCHEMA.read_text())
    for sql in ("SELECT e.week, e.picks, p.name FROM pickem_entries e JOIN pickem_players p "
                "ON p.user_id = e.user_id WHERE e.season = 1",
                "SELECT picks FROM pickem_entries WHERE season = 1 AND user_id = 'u' AND week = 5",
                "SELECT user_id FROM pickem_players WHERE name_key = 'x'"):
        plan = " ".join(r[-1] for r in db.execute("EXPLAIN QUERY PLAN " + sql))
        assert "SCAN e" not in plan and "SCAN pickem_entries" not in plan, plan
    text = re.sub(r"--[^\n]*", "", MIGRATION_007.read_text())
    assert text.count("WITHOUT ROWID") == 2 and "ALTER" not in text
    assert "CREATE INDEX" not in text, "an index is a write on every save"


def test_deployed_before_the_migration_it_answers_rather_than_failing():
    with Worker(_before_007()) as w:
        w.load(PICKEM, "pk")
        w.load(ROUTE, "pkr")
        install(w, files())
        who = w.user()
        got = get(w)
        assert got["status"] == 200 and got["json"]["migrating"] is True
        assert [r["name"] for r in got["json"]["board"]["week"]] == ["GordStats"]
        mine = get(w, who)
        assert mine["status"] == 200 and mine["json"]["me"] is None
        assert join(w, who, "Early Bird")["status"] == 503
        assert save(w, who, {"nfl:3": ["h", 3]})["status"] == 503


# --------------------------------------------------------------------------- #
# The pipeline's files, as the Function reads them
# --------------------------------------------------------------------------- #

def test_the_pipelines_files_are_what_the_function_grades():
    """gordstats.pickem's own output - not a hand-made fixture - locked and
    graded by the Function: the published shapes are one contract."""
    from datetime import datetime, timedelta, timezone

    from gordstats import pickem
    from test_pickem import nfl_row

    now = datetime.now(timezone.utc).replace(microsecond=0)
    start, end = now - timedelta(days=3), now + timedelta(days=4)
    done_at, later = now - timedelta(hours=5), now + timedelta(days=2)
    pre = {"1": nfl_row(1, done_at), "2": nfl_row(2, later, "NYJ", "NE")}
    probs = {"nfl:1": 0.7, "nfl:2": 0.4}
    slate = pickem.update_week(None, season=SEASON, week=5, start=start, end=end,
                               now=now - timedelta(hours=6), cfb={}, nfl=pre, watch=[],
                               probs=probs)
    final = {"1": nfl_row(1, done_at, state="post", hs=24, as_=10),
             "2": nfl_row(2, later, "NYJ", "NE")}
    slate = pickem.update_week(slate, season=SEASON, week=5, start=start, end=end, now=now,
                               cfb={}, nfl=final, watch=[], probs=probs)
    idx = pickem.index(SEASON, {5: slate}, now, pickem.first_window(now - timedelta(days=30)))
    assert idx["weeks"][0]["g"][0][2:] == ["h", "h", 2]

    with Worker() as w:
        w.load(PICKEM, "pk")
        w.load(ROUTE, "pkr")
        install(w, {"/pickem/season.json": json.loads(json.dumps(idx)),
                    f"/pickem/{SEASON}/week_05.json": json.loads(json.dumps(slate))})
        who = reader(w)
        assert save(w, who, {"nfl:1": ["h", 2], "nfl:2": ["a", 1]})["status"] == 409
        assert save(w, who, {"nfl:2": ["a", 2]})["status"] == 200
        w.sql.execute("UPDATE pickem_entries SET picks = ?",
                      json.dumps({"nfl:1": ["h", 1, 1], "nfl:2": ["a", 2, 1]}))
        body = get(w, who)["json"]
        assert body["slate"]["games"][0]["res"] == "h" and body["week"] == 5
        assert [(r["name"], r["pts"], r["max"]) for r in body["board"]["week"]] == [
            ("GordStats", 2, 3), ("Reader One", 1, 3)]
        assert body["mine"] == {"nfl:1": ["h", 1], "nfl:2": ["a", 2]}
