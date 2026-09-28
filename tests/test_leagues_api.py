"""
/api/leagues: what one POST can cost is bounded, and the bounds hold.

Four holes, each closed here and pinned by a test below:
  - a username sync fanned out to ~480 calls to Sleeper (history and a team
    name for every season of 20 leagues); Workers Free stops at 50;
  - the five-minute refresh limit was read-then-write on the leagues' own
    timestamps, so parallel POSTs all passed it and a DELETE reset it;
  - the 120-row cap applied per sync, so syncing a different public username
    every five minutes grew an account without bound;
  - the id path compared a row count with a limit on leagues, so four
    leagues with five seasons each could never add a fifth.

Runs the Function in headless Chromium against a real SQLite (see
tests/functions_harness.py), with Sleeper stubbed from a generated world.
"""
import json

import pytest

from functions_harness import CHROME, FUNCTIONS, Worker, before_004

pytestmark = pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")

LEAGUES = FUNCTIONS / "api" / "leagues.js"
URL = "https://www.gordstats.com/api/leagues"

# Answers every Sleeper path leagues.js asks for, from a world built in Python.
SLEEPER = r"""
window.sleeper = (W) => {
  T.routes = [["^https://api\\.sleeper\\.app/v1/", (url) => {
    const path = url.replace("https://api.sleeper.app/v1/", "");
    let m;
    if (path === "state/nfl") return { body: W.state };
    if ((m = path.match(/^user\/([^/]+)\/leagues\/nfl\/(\d+)$/))) return { body: W.lists[m[1]] || [] };
    if ((m = path.match(/^user\/([^/]+)$/))) return { body: W.users[decodeURIComponent(m[1])] || null };
    if ((m = path.match(/^league\/(\d+)\/users$/))) return { body: W.members[m[1]] || [] };
    if ((m = path.match(/^league\/(\d+)$/))) {
      return W.leagues[m[1]] ? { body: W.leagues[m[1]] } : { status: 404, body: null };
    }
    return { status: 404, body: null };
  }]];
};
"""


def lid(lg, s, u=0):
    """League lg of account u, season s (0 = the oldest)."""
    return f"9{u:02d}{lg:02d}{s:02d}000"


def world(accounts=None):
    """{username: (leagues, seasons)} -> a Sleeper that knows all of them.

    Ids come from lid(); each season links back to the one before it, and
    the reader's team is renamed every year.
    """
    accounts = accounts or {"tyler": (3, 4)}
    w = {"state": {"season": "2026"}, "users": {}, "lists": {}, "leagues": {}, "members": {}}
    for u, (name, (n_leagues, n_seasons)) in enumerate(accounts.items()):
        uid = f"U{u}"
        w["users"][name] = {"user_id": uid, "username": name}
        w["lists"][uid] = []
        for lg in range(n_leagues):
            prev = None
            for s in range(n_seasons):
                key = lid(lg, s, u)
                year = str(2026 - n_seasons + 1 + s)
                w["leagues"][key] = {"league_id": key, "name": f"{name} league {lg}",
                                     "season": year, "previous_league_id": prev}
                w["members"][key] = [
                    {"user_id": "someone", "display_name": "them",
                     "metadata": {"team_name": "Not mine"}},
                    {"user_id": uid, "display_name": name,
                     "metadata": {"team_name": f"{name} {lg} in {year}"}}]
                prev = key
            w["lists"][uid].append(w["leagues"][prev])
    return w


@pytest.fixture
def worker():
    with Worker() as w:
        w.load(LEAGUES, "leagues")
        w.js(SLEEPER)
        yield w


def sync(w, who, body, world_=None):
    if world_ is not None:
        w.js(f"sleeper({json.dumps(world_)}); T.fetches.length = 0;")
    return w.call("leagues.onRequestPost", URL, method="POST", headers=who, body=body)


def rows(w, uid="u1"):
    return w.sql.rows("SELECT * FROM leagues WHERE user_id = ? ORDER BY league_id", uid)


def fetched(w):
    return w.js("return T.fetches;")


def reopen(w, uid="u1"):
    """Let the next sync through, as if the refresh interval had passed."""
    w.sql.execute("UPDATE users SET last_league_sync = NULL WHERE id = ?", uid)


def test_a_username_sync_stores_every_season_with_its_team_name(worker):
    who = worker.user()
    got = sync(worker, who, {"provider": "sleeper", "username": "tyler"}, world())
    assert got["status"] == 200, got["text"]
    body = got["json"]
    assert body["ok"] and body["complete"] and "unfinished" not in body
    assert body["synced"] == 12 and body["leagues_found"] == 3
    # The list answers this season itself: 3 setup calls, a team name for each
    # of the 12 seasons, and one call per earlier season.
    assert body["sleeper_calls"] == len(fetched(worker)) == 3 + 12 + 9

    stored = rows(worker)
    assert len(stored) == 12
    for r in stored:
        lg, year = r["name"].split()[-1], r["season"]
        assert r["team_name"] == f"tyler {lg} in {year}"
        assert r["provider_user_id"] == "U0"
        assert r["lineage_id"] == lid(int(lg), 0)                 # the oldest season
    # The shape the sync page reads is unchanged.
    first = body["leagues"][0]
    assert set(first) >= {"provider", "sport", "league_id", "name", "season",
                          "team_name", "lineage_id", "last_synced_at"}


def test_a_big_account_stays_inside_the_fetch_budget_and_says_so(worker):
    """20 leagues x 12 seasons was ~480 calls; Workers Free allows 50."""
    who = worker.user()
    got = sync(worker, who, {"provider": "sleeper", "username": "big"},
               world({"big": (25, 12)}))
    body = got["json"]
    assert got["status"] == 200, got["text"]
    assert len(fetched(worker)) == body["sleeper_calls"] <= 40
    assert body["complete"] is False
    left = body["unfinished"]
    assert left["leagues_not_added"] == 5                  # 25 found, 20 is the most
    assert left["history_cut_short"] > 0 and "note" in left
    # What mattered most was bought first: this season of every league, named.
    current = [r for r in rows(worker) if r["season"] == "2026"]
    assert len(current) == 20 and all(r["team_name"] for r in current)
    assert len({r["lineage_id"] for r in rows(worker)}) == 20


def test_a_resync_rewrites_only_what_moved(worker):
    who = worker.user()
    w = world()
    sync(worker, who, {"provider": "sleeper", "username": "tyler"}, w)
    worker.sql.execute("UPDATE leagues SET last_synced_at = 'before'")
    spent = worker.sql.rows("SELECT write_count FROM users")[0]["write_count"]
    assert spent == 12

    reopen(worker)
    w["leagues"][lid(1, 0)]["name"] = "renamed long ago"          # one old season moved
    got = sync(worker, who, {"provider": "sleeper", "username": "tyler"}, w)
    assert got["json"]["complete"]
    touched = {r["league_id"] for r in rows(worker) if r["last_synced_at"] != "before"}
    # The three current seasons (their "synced" time is on the page) and the
    # one row that changed; nothing else was written.
    assert touched == {lid(0, 3), lid(1, 3), lid(2, 3), lid(1, 0)}
    assert worker.sql.rows("SELECT write_count FROM users")[0]["write_count"] == 12 + 4
    # A finished season's team name, once stored, is not asked for again.
    asked = [u for u in fetched(worker) if u.endswith("/users")]
    assert sorted(asked) == sorted(
        f"https://api.sleeper.app/v1/league/{lid(lg, 3)}/users" for lg in range(3))


def test_parallel_syncs_cannot_all_pass_the_refresh_limit(worker):
    who = worker.user()
    worker.js(f"sleeper({json.dumps(world())});")
    statuses = worker.js(f"""
      const env = {worker.env()};
      const one = () => leagues.onRequestPost({{ env, request: T.req({json.dumps(URL)}, {{
        method: "POST", headers: {json.dumps(who)},
        body: JSON.stringify({{ provider: "sleeper", username: "tyler" }}) }}) }});
      const out = await Promise.all([1, 2, 3, 4, 5, 6].map(one));
      return await Promise.all(out.map(async (r) => [r.status, await r.json()]));
    """)
    codes = [s for s, _ in statuses]
    assert codes.count(200) == 1 and codes.count(429) == 5, statuses
    for status, body in statuses:
        if status == 429:
            assert 0 < body["retry_after"] <= 300 and body["error"] == "just refreshed"


def test_removing_a_league_does_not_reset_the_refresh_limit(worker):
    who = worker.user()
    sync(worker, who, {"provider": "sleeper", "username": "tyler"}, world())
    for r in rows(worker):
        worker.call("leagues.onRequestDelete",
                    f"{URL}?provider=sleeper&league_id={r['league_id']}",
                    method="DELETE", headers=who)
    assert rows(worker) == []
    again = sync(worker, who, {"provider": "sleeper", "username": "tyler"})
    assert again["status"] == 429
    assert int(again["headers"]["retry-after"]) == again["json"]["retry_after"]


def test_a_mistyped_username_does_not_start_the_clock(worker):
    who = worker.user()
    miss = sync(worker, who, {"provider": "sleeper", "username": "tylr"}, world())
    assert miss["status"] == 404 and "tylr" in miss["json"]["error"]
    assert len(fetched(worker)) <= 3
    assert sync(worker, who, {"provider": "sleeper", "username": "tyler"})["status"] == 200


def test_the_row_cap_is_for_the_account_not_the_sync(worker):
    who = worker.user()
    # 110 rows already, in 10 leagues: room for 10 more rows.
    for lg in range(10):
        for s in range(11):
            worker.sql.execute(
                "INSERT INTO leagues (user_id, provider, sport, league_id, name, season, "
                "lineage_id, created_at, last_synced_at) VALUES "
                "('u1', 'sleeper', 'nfl', ?, 'old', ?, ?, 'x', 'x')",
                f"7{lg:02d}{s:02d}0000", str(2015 + s), f"7{lg:02d}000000")

    got = sync(worker, who, {"provider": "sleeper", "username": "tyler"}, world())
    assert got["status"] == 200, got["text"]
    assert len(rows(worker)) == 120
    assert got["json"]["complete"] is False
    assert got["json"]["unfinished"]["seasons_not_added"] == 2
    # This season of each league claimed room before any history did.
    assert {r["season"] for r in rows(worker) if r["name"].startswith("tyler")} >= {"2026"}
    assert len([r for r in rows(worker) if r["season"] == "2026"]) == 3

    # A second public username finds the account full rather than growing it.
    reopen(worker)
    full = sync(worker, who, {"provider": "sleeper", "username": "other"},
                world({"tyler": (3, 4), "other": (2, 2)}))
    assert full["status"] == 413 and full["json"]["error"] == "too many leagues"
    assert len(rows(worker)) == 120


def test_adding_by_id_counts_leagues_not_rows(worker):
    who = worker.user()
    w = world({"tyler": (5, 5)})
    worker.js(f"sleeper({json.dumps(w)});")
    # Four leagues with five seasons each: 20 rows, 4 leagues.
    for lg in range(4):
        got = sync(worker, who, {"provider": "sleeper", "league_id": lid(lg, 4)})
        assert got["status"] == 200, got["text"]
        reopen(worker)
    assert len(rows(worker)) == 20
    fifth = sync(worker, who, {"provider": "sleeper", "league_id": lid(4, 4)})
    assert fifth["status"] == 200, fifth["text"]
    assert fifth["json"]["synced"] == 5
    assert fifth["json"]["league"]["name"] == "tyler league 4"


def test_adding_by_id_refuses_a_twenty_first_league(worker):
    who = worker.user()
    for lg in range(20):
        worker.sql.execute(
            "INSERT INTO leagues (user_id, provider, sport, league_id, name, season, "
            "lineage_id, created_at, last_synced_at) VALUES "
            "('u1', 'sleeper', 'nfl', ?, 'old', '2025', ?, 'x', 'x')",
            f"7{lg:02d}000000", f"7{lg:02d}000000")
    w = world({"tyler": (1, 3)})
    got = sync(worker, who, {"provider": "sleeper", "league_id": lid(0, 2)}, w)
    assert got["status"] == 413 and got["json"]["error"] == "too many leagues"
    assert len(rows(worker)) == 20

    # This season of a league already held is not a twenty-first league.
    w["leagues"]["800000000"] = {"league_id": "800000000", "name": "old",
                                 "season": "2026", "previous_league_id": "700000000"}
    w["leagues"]["700000000"] = {"league_id": "700000000", "name": "old",
                                 "season": "2025", "previous_league_id": None}
    reopen(worker)
    same = sync(worker, who, {"provider": "sleeper", "league_id": "800000000"}, w)
    assert same["status"] == 200, same["text"]
    assert len(rows(worker)) == 21


def test_adding_by_id_keeps_its_contract(worker):
    who = worker.user()
    w = world()
    assert sync(worker, who, {"provider": "sleeper", "league_id": "12ab"}, w)["status"] == 400
    assert sync(worker, who, {"provider": "yahoo", "league_id": "123456"})["status"] == 400
    # An id Sleeper does not know costs one call and no wait.
    miss = sync(worker, who, {"provider": "sleeper", "league_id": "123456789"})
    assert miss["status"] == 404 and len(fetched(worker)) == 1

    got = sync(worker, who, {"provider": "sleeper", "league_id": lid(0, 3)})
    assert got["status"] == 200
    body = got["json"]
    assert body["synced"] == 4 and body["complete"]
    assert body["league"]["name"] == "tyler league 0" and body["league"]["season"] == "2026"
    # Straight away again: refused, with the wait the page shows.
    again = sync(worker, who, {"provider": "sleeper", "league_id": lid(1, 3)})
    assert again["status"] == 429 and 0 < again["json"]["retry_after"] <= 60

    listed = worker.call("leagues.onRequestGet", URL, headers=who)["json"]["leagues"]
    assert len(listed) == 4 and {r["lineage_id"] for r in listed} == {lid(0, 0)}


def test_deployed_before_the_migration_the_old_limit_still_holds():
    with Worker(before_004()) as w:
        w.load(LEAGUES, "leagues")
        w.js(SLEEPER)
        who = w.user()
        first = sync(w, who, {"provider": "sleeper", "username": "tyler"}, world())
        assert first["status"] == 200 and first["json"]["synced"] == 12
        again = sync(w, who, {"provider": "sleeper", "username": "tyler"})
        assert again["status"] == 429


def test_before_the_leagues_table_exists_it_says_so():
    with Worker(before_004() + "\nDROP TABLE leagues;") as w:
        w.load(LEAGUES, "leagues")
        w.js(SLEEPER)
        who = w.user()
        got = w.call("leagues.onRequestGet", URL, headers=who)
        assert got["status"] == 503 and got["json"]["migrating"] is True
        post = sync(w, who, {"provider": "sleeper", "username": "tyler"}, world())
        assert post["status"] == 503 and post["json"]["migrating"] is True
