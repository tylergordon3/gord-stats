"""
/api/favorites writes what changed, and one account cannot empty D1's day.

Each PUT used to delete the reader's whole list and insert it again - up to
500 rows, three writes apiece with the old user_id index - so a few dozen
scripted PUTs spent the free tier's 100,000 daily row writes, and with them
everybody's ability to sign in. A PUT now writes only the difference, and the
rows an account may change in a day are capped with one atomic UPDATE.

The Function runs in headless Chromium with env.DB backed by a real SQLite
built from deploy/d1-schema.sql (tests/functions_harness.py), so the SQL is
exercised as written.
"""
import json

import pytest

from functions_harness import CHROME, FUNCTIONS, Worker, before_004

pytestmark = pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")

FAV = FUNCTIONS / "api" / "favorites.js"
URL = "https://www.gordstats.com/api/favorites"


@pytest.fixture
def worker():
    with Worker() as w:
        w.load(FAV, "fav")
        yield w


def put(w, who, keys, env=None):
    return w.call("fav.onRequestPut", URL, method="PUT", headers=who,
                  body={"favorites": keys}, env=env)


def stored(w, uid="u1"):
    return {f"{r['sport']}:{r['team_id']}": r["created_at"] for r in w.sql.rows(
        "SELECT sport, team_id, created_at FROM favorites WHERE user_id = ?", uid)}


def test_a_put_writes_only_the_rows_that_changed(worker):
    who = worker.user()
    assert put(worker, who, ["cfb:1", "cfb:2", "nfl:KC"])["json"] == {"ok": True, "count": 3}
    before = stored(worker)
    worker.sql.execute("UPDATE favorites SET created_at = 'kept' WHERE team_id = '1'")

    got = put(worker, who, ["cfb:1", "nfl:KC", "wnba:LV:x"])
    assert got["json"] == {"ok": True, "count": 3}
    after = stored(worker)
    assert set(after) == {"cfb:1", "nfl:KC", "wnba:LV:x"}
    # Untouched rows were not deleted and re-inserted.
    assert after["cfb:1"] == "kept"
    assert after["nfl:KC"] == before["nfl:KC"]
    # A team id may itself hold a ':' - the key splits at the first one.
    assert worker.sql.rows("SELECT sport, team_id FROM favorites WHERE sport = 'wnba'") == [
        {"sport": "wnba", "team_id": "LV:x"}]
    assert worker.sql.rows("SELECT write_count FROM users")[0]["write_count"] == 3 + 2


def test_a_put_that_changes_nothing_writes_nothing(worker):
    who = worker.user()
    put(worker, who, ["cfb:1", "cfb:2"])
    worker.sql.statements.clear()
    got = put(worker, who, ["cfb:2", "cfb:1", "cfb:1", "not a key"])
    assert got["json"] == {"ok": True, "count": 2}
    assert all(s.lstrip().upper().startswith("SELECT") for s in worker.sql.statements)


def test_emptying_the_list_and_the_request_contract(worker):
    who = worker.user()
    put(worker, who, ["cfb:1", "cfb:2"])
    assert put(worker, who, [])["json"] == {"ok": True, "count": 0}
    assert stored(worker) == {}

    got = worker.call("fav.onRequestGet", URL, headers=who)
    assert got["status"] == 200 and got["json"] == {"favorites": []}
    assert got["headers"]["cache-control"] == "no-store"

    assert put(worker, {}, ["cfb:1"])["status"] == 401
    bad = worker.call("fav.onRequestPut", URL, method="PUT", headers=who, body="{nope")
    assert bad["status"] == 400
    assert worker.call("fav.onRequestPut", URL, method="PUT", headers=who,
                       body={"teams": []})["status"] == 400
    assert put(worker, who, [f"cfb:{i}" for i in range(501)])["status"] == 413
    # Malformed and duplicate keys are dropped, not fatal.
    got = put(worker, who, ["cfb:1", "CFB:2", "cfb:<b>", 7, None, "cfb:1", "nfl:SF"])
    assert got["json"] == {"ok": True, "count": 2}
    assert set(stored(worker)) == {"cfb:1", "nfl:SF"}


def test_the_daily_allowance_refuses_a_put_that_does_not_fit(worker):
    who = worker.user()
    today = worker.js("return new Date().toISOString().slice(0, 10);")
    worker.sql.execute("UPDATE users SET write_day = ?, write_count = 999", today)

    got = put(worker, who, ["cfb:1", "cfb:2"])
    assert got["status"] == 429
    wait = int(got["headers"]["retry-after"])
    assert 0 < wait <= 86400 and got["json"]["retry_after"] == wait
    assert stored(worker) == {}                                # nothing written

    assert put(worker, who, ["cfb:1"])["status"] == 200       # one still fits
    assert worker.sql.rows("SELECT write_count FROM users")[0]["write_count"] == 1000


def test_yesterdays_count_does_not_carry_over(worker):
    who = worker.user()
    worker.sql.execute("UPDATE users SET write_day = '2000-01-01', write_count = 1000")
    assert put(worker, who, ["cfb:1", "cfb:2"])["status"] == 200
    row = worker.sql.rows("SELECT write_day, write_count FROM users")[0]
    assert row["write_day"] != "2000-01-01" and row["write_count"] == 2


def test_parallel_puts_cannot_overspend_the_allowance(worker):
    """Twenty PUTs at once, five new teams each, with room left for two."""
    who = worker.user()
    today = worker.js("return new Date().toISOString().slice(0, 10);")
    worker.sql.execute("UPDATE users SET write_day = ?, write_count = 990", today)
    statuses = worker.js(f"""
      const env = {worker.env()};
      const one = (i) => fav.onRequestPut({{ env, request: T.req({json.dumps(URL)}, {{
        method: "PUT", headers: {json.dumps(who)},
        body: JSON.stringify({{ favorites: [0, 1, 2, 3, 4].map((j) => `cfb:${{i}}-${{j}}`) }}),
      }}) }});
      return (await Promise.all([...Array(20).keys()].map(one))).map((r) => r.status);
    """)
    assert statuses.count(200) == 2 and statuses.count(429) == 18
    assert worker.sql.rows("SELECT write_count FROM users")[0]["write_count"] == 1000
    assert len(stored(worker)) == 10


def test_deployed_before_the_migration_it_still_saves():
    """Code first, migration later must not break starring a team."""
    with Worker(before_004()) as w:
        w.load(FAV, "fav")
        who = w.user()
        assert put(w, who, ["cfb:1", "cfb:2"])["json"] == {"ok": True, "count": 2}
        assert put(w, who, ["cfb:2"])["json"] == {"ok": True, "count": 1}
        assert set(stored(w)) == {"cfb:2"}
