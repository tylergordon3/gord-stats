"""
The site's own daily ceiling on writes (functions/api/_lib/limits.js).

D1's free tier is 100,000 rows written a day for the whole database, and
sign-in writes too. Each account already had its own allowance (1,000 rows a
day), but about fifty accounts at theirs spent the whole quota, and then
nobody could sign in. Now one row, `site_writes`, counts what the metered
endpoints - favourites, leagues, Tweets of the week - write in a UTC day, and
over SITE_DAILY_WRITES they stop for everyone with a clean 503 and
Retry-After, while sign-in carries on.

Runs the Functions in headless Chromium against a real SQLite
(tests/functions_harness.py), so the counting SQL is exercised as written.
"""
import json
import sqlite3

import pytest

from functions_harness import (CHROME, FUNCTIONS, MIGRATION_006, SCHEMA, Worker,
                               before_004, before_006)
from test_auth_session import HELPERS, callback, good_claims, login, me

pytestmark = pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")

API = "https://www.gordstats.com/api"
LIMITS = FUNCTIONS / "api" / "_lib" / "limits.js"


@pytest.fixture
def worker():
    with Worker() as w:
        for path, name in [(FUNCTIONS / "api" / "favorites.js", "fav"),
                           (FUNCTIONS / "api" / "leagues.js", "leagues"),
                           (FUNCTIONS / "api" / "tweets.js", "tw"),
                           (FUNCTIONS / "api" / "tweets" / "[[route]].js", "twr"),
                           (FUNCTIONS / "api" / "auth" / "[[route]].js", "auth"),
                           (FUNCTIONS / "api" / "me.js", "me"),
                           (LIMITS, "limits")]:
            w.load(path, name)
        w.js(HELPERS)
        yield w


def constants(w):
    return w.js("return { ceiling: limits.SITE_DAILY_WRITES, perRow: limits.WRITES_PER_ROW,"
                " meter: limits.METER_WRITES, full: limits.SITE_FULL };")


def today(w):
    return w.js("return new Date().toISOString().slice(0, 10);")


def site(w):
    rows = w.sql.rows("SELECT day, written FROM site_writes")
    return rows[0] if rows else None


def fill(w, written, day=None):
    """The site's count for today (or `day`), as if readers had written it."""
    w.sql.execute("INSERT INTO site_writes (id, day, written) VALUES (1, ?, ?) "
                  "ON CONFLICT (id) DO UPDATE SET day = excluded.day, written = excluded.written",
                  day or today(w), written)


def put(w, who, keys):
    return w.call("fav.onRequestPut", f"{API}/favorites", method="PUT", headers=who,
                  body={"favorites": keys})


def favs(w, uid="u1"):
    return {f"{r['sport']}:{r['team_id']}" for r in w.sql.rows(
        "SELECT sport, team_id FROM favorites WHERE user_id = ?", uid)}


def write_count(w, uid="u1"):
    return w.sql.rows("SELECT write_count FROM users WHERE id = ?", uid)[0]["write_count"]


def approved_post(w, tweet_id="77"):
    w.sql.execute("INSERT INTO tweets (tweet_id, submitted_at, status, reviewed_at) "
                  "VALUES (?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), 'approved', "
                  "strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))", tweet_id)
    return w.sql.rows("SELECT id FROM tweets WHERE tweet_id = ?", tweet_id)[0]["id"]


def refused_by_the_site(got, c):
    assert got["status"] == 503, got["text"]
    body = got["json"]
    assert body["ok"] is False and body["site_limit"] is True and body["error"] == c["full"]
    wait = int(got["headers"]["retry-after"])
    assert 0 < wait <= 86400 and body["retry_after"] == wait
    assert got["headers"]["cache-control"] == "no-store"


# --------------------------------------------------------------------------- #
# Over the ceiling
# --------------------------------------------------------------------------- #

def test_over_the_ceiling_every_metered_write_is_refused_and_sign_in_still_works(worker):
    c = constants(worker)
    who = worker.user()
    put(worker, who, ["cfb:1"])
    before = write_count(worker)
    pid = approved_post(worker)
    fill(worker, c["ceiling"] - 1)          # not even the smallest write fits
    worker.sql.statements.clear()

    # Favourites: refused, nothing stored, and nothing written to refuse it -
    # not the account's allowance, not the site's count.
    refused_by_the_site(put(worker, who, ["cfb:1", "cfb:2"]), c)
    assert favs(worker) == {"cfb:1"} and write_count(worker) == before

    # Leagues: refused before Sleeper is asked anything or the refresh limit
    # is claimed.
    worker.js("T.fetches.length = 0;")
    for body in ({"provider": "sleeper", "league_id": "123456789"},
                 {"provider": "sleeper", "username": "tyler"},
                 {"provider": "espn", "league_id": "12345"}):
        got = worker.call("leagues.onRequestPost", f"{API}/leagues", method="POST",
                          headers=who, body=body)
        refused_by_the_site(got, c)
    assert worker.js("return T.fetches;") == []
    assert worker.sql.rows("SELECT last_league_sync FROM users")[0]["last_league_sync"] is None

    # Tweets of the week: a submission (before X is asked) and a vote.
    sent = worker.call("tw.onRequestPost", f"{API}/tweets", method="POST", headers=who,
                       body={"url": "https://x.com/a/status/1841234567890123456"})
    refused_by_the_site(sent, c)
    assert worker.js("return T.fetches;") == []
    voted = worker.call("twr.onRequestPost", f"{API}/tweets/{pid}/vote", method="POST",
                        headers=who, body={}, ctx="{ params: { route: [%s, 'vote'] } }"
                        % json.dumps(str(pid)))
    refused_by_the_site(voted, c)
    assert worker.sql.rows("SELECT * FROM tweets WHERE status = 'pending'") == []
    assert worker.sql.rows("SELECT * FROM tweet_votes") == []

    # Every refusal above cost reads only.
    assert all(s.lstrip().upper().startswith("SELECT") for s in worker.sql.statements), \
        worker.sql.statements
    assert site(worker)["written"] == c["ceiling"] - 1

    # Reading still works...
    got = worker.call("fav.onRequestGet", f"{API}/favorites", headers=who)
    assert got["status"] == 200 and got["json"] == {"favorites": ["cfb:1"]}
    # ...and so does signing in: a new account, and a returning one.
    state, stamp = login(worker)
    signed = callback(worker, state, stamp, good_claims(worker))
    assert signed["status"] == 302 and "signin=failed" not in signed["headers"]["location"]
    token = next(x for x in signed["cookies"] if x.startswith("__Host-gs_session="))
    assert me(worker, token.split(";")[0])["signedIn"] is True
    state, stamp = login(worker)
    again = callback(worker, state, stamp, good_claims(worker))
    assert any(x.startswith("__Host-gs_session=") for x in again["cookies"])
    assert len(worker.sql.rows("SELECT id FROM users WHERE provider_sub = 'g-123'")) == 1


def test_one_upsert_a_request_counted_in_d1_rows(worker):
    """Not a statement per row: one, whatever the size of the change. What it
    adds is D1's own measure - each row and its key's index - plus the two
    meter rows."""
    c = constants(worker)
    who = worker.user()
    assert site(worker) is None                              # the row makes itself
    worker.sql.statements.clear()
    assert put(worker, who, ["cfb:1", "cfb:2", "nfl:KC"])["status"] == 200
    counted = [s for s in worker.sql.statements if "site_writes" in s]
    assert len([s for s in counted if s.lstrip().startswith("INSERT")]) == 1
    assert site(worker) == {"day": today(worker), "written": 3 * c["perRow"] + c["meter"]}

    assert put(worker, who, ["cfb:1"])["status"] == 200      # two removed
    assert site(worker)["written"] == (3 + 2) * c["perRow"] + 2 * c["meter"]
    # A PUT that changes nothing writes nothing, the site's count included.
    worker.sql.statements.clear()
    assert put(worker, who, ["cfb:1"])["status"] == 200
    assert all(s.lstrip().upper().startswith("SELECT") for s in worker.sql.statements)


def test_parallel_requests_cannot_overshoot_the_ceiling(worker):
    """Twenty readers star five teams each at once, with room for three."""
    c = constants(worker)
    cost = 5 * c["perRow"] + c["meter"]
    start = c["ceiling"] - 3 * cost - (cost - 1)            # three fit; a fourth does not
    fill(worker, start)
    users = [worker.user(f"r{i}") for i in range(20)]
    statuses = worker.js(f"""
      const env = {worker.env()};
      const one = (who, i) => fav.onRequestPut({{ env, request: T.req({json.dumps(API + '/favorites')}, {{
        method: "PUT", headers: who,
        body: JSON.stringify({{ favorites: [0, 1, 2, 3, 4].map((j) => `cfb:${{i}}-${{j}}`) }}),
      }}) }});
      return (await Promise.all({json.dumps(users)}.map(one))).map((r) => r.status);
    """)
    assert statuses.count(200) == 3 and statuses.count(503) == 17, statuses
    assert site(worker)["written"] == start + 3 * cost <= c["ceiling"]
    assert len(worker.sql.rows("SELECT * FROM favorites")) == 15


def test_an_account_at_its_own_limit_cannot_run_down_the_sites(worker):
    """Its own allowance is checked before the site's is charged, so requests
    that write nothing cost the site nothing - one script cannot empty the
    day for everyone with refusals."""
    who = worker.user()
    worker.sql.execute("UPDATE users SET write_day = ?, write_count = 1000", today(worker))
    for i in range(10):
        got = put(worker, who, [f"cfb:{i}"])
        assert got["status"] == 429 and "site_limit" not in got["json"]
    assert site(worker) is None and favs(worker) == set()


def test_yesterdays_count_does_not_carry_over(worker):
    c = constants(worker)
    who = worker.user()
    fill(worker, c["ceiling"], day="2000-01-01")
    assert put(worker, who, ["cfb:1"])["status"] == 200
    assert site(worker) == {"day": today(worker), "written": c["perRow"] + c["meter"]}


def test_the_ceiling_leaves_sign_in_most_of_d1s_day(worker):
    c = constants(worker)
    assert c["ceiling"] <= 40_000, "D1's free tier is 100,000 rows written a day, all told"
    assert c["perRow"] >= 2, "a row and its primary key's index"
    # siteFull is the early answer: whether `n` more rows still fit today.
    got = worker.js(f"""
      const db = T.db(SQL);
      return [await limits.siteFull(db, 1), await limits.siteFull(db, {c['ceiling']})];""")
    assert got[0] is None and got[1]["site"] is True and got[1]["ok"] is False


# --------------------------------------------------------------------------- #
# Deployed ahead of migration 006
# --------------------------------------------------------------------------- #

def test_deployed_before_the_migration_the_site_is_unmetered():
    """Code first, migration later: nothing breaks, each account's own
    allowance still holds, and the site's ceiling is simply off."""
    with Worker(before_006()) as w:
        w.load(FUNCTIONS / "api" / "favorites.js", "fav")
        w.load(FUNCTIONS / "api" / "tweets" / "[[route]].js", "twr")
        w.load(LIMITS, "limits")
        who = w.user()
        assert put(w, who, ["cfb:1", "cfb:2"])["json"] == {"ok": True, "count": 2}
        assert write_count(w) == 2
        pid = approved_post(w)
        voted = w.call("twr.onRequestPost", f"{API}/tweets/{pid}/vote", method="POST",
                       headers=who, body={}, ctx="{ params: { route: [%s, 'vote'] } }"
                       % json.dumps(str(pid)))
        assert voted["status"] == 200 and voted["json"]["mine"] is True
        spent = w.js("return await limits.spend(T.db(SQL), 'u1', 1);")
        assert spent == {"ok": True, "siteUnmetered": True}
        today_ = today(w)
        w.sql.execute("UPDATE users SET write_day = ?, write_count = 1000", today_)
        assert put(w, who, ["cfb:3"])["status"] == 429


def test_before_both_migrations_nothing_is_metered_and_nothing_fails():
    """A database older than 004 and 006: the oldest the code can meet."""
    sql = before_004() + "\nDROP TABLE site_writes;\nALTER TABLE users DROP COLUMN session_epoch;"
    with Worker(sql) as w:
        w.load(FUNCTIONS / "api" / "favorites.js", "fav")
        w.load(LIMITS, "limits")
        who = w.user()
        assert put(w, who, ["cfb:1"])["status"] == 200
        assert w.js("return await limits.spend(T.db(SQL), 'u1', 1);") == {
            "ok": True, "unmetered": True, "siteUnmetered": True}


def _columns(db):
    tables = [r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
    # By name: 006 can only append session_epoch, where the schema declares it
    # ahead of 004's columns (see d1-schema.sql and before_004).
    return {t: sorted(tuple(c)[1:] for c in db.execute(f"PRAGMA table_xinfo({t})"))
            for t in tables}, sorted(r[0] for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"))


def test_migration_006_brings_a_database_to_the_schema():
    old = sqlite3.connect(":memory:")
    old.executescript(before_006())
    assert "site_writes" not in _columns(old)[0]
    old.executescript(MIGRATION_006.read_text())
    fresh = sqlite3.connect(":memory:")
    fresh.executescript(SCHEMA.read_text())
    assert _columns(old) == _columns(fresh)
    # One row, ever, and no index of its own to write.
    assert fresh.execute("SELECT name FROM sqlite_master WHERE type = 'index'"
                         " AND tbl_name = 'site_writes'").fetchall() == []
    with pytest.raises(sqlite3.IntegrityError):
        fresh.execute("INSERT INTO site_writes (id, day, written) VALUES (2, 'x', 0)")
    # Run-once like 002-005: a second run stops at the ALTER, harmlessly.
    with pytest.raises(sqlite3.OperationalError, match="duplicate column"):
        old.executescript(MIGRATION_006.read_text())
