"""
Revocable sessions (functions/api/_lib/session.js), and the cookie's new name.

A session used to be a signed bearer token good for its whole 90 days: signing
out cleared only the browser it was pressed in, deleting the account left the
reader's other devices holding "valid" sessions that then failed every save,
and a leaked cookie could only be stopped by rotating SESSION_SECRET for
everybody. Now each session carries the account's `session_epoch` (`ep`) and
is accepted only while the account's row still holds that number: "Sign out
everywhere" (POST /api/auth/logout-everywhere, a button on /profile/) moves it
on, and deleting the account removes the row.

The cookie is `__Host-gs_session` now; the old `gs_session` is still read and
moved across by /api/me, so the switch signs nobody out.

Functions in headless Chromium against a real SQLite (tests/functions_harness.py);
the profile button in the same browser against a small local server.
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from functions_harness import CHROME, FUNCTIONS, SECRET, Worker, before_006
from gordstats import profile_page
from test_auth_session import HELPERS, callback, good_claims, login

pytestmark = pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")

API = "https://www.gordstats.com/api"
NEW, OLD = "__Host-gs_session", "gs_session"


def load_all(w):
    for path, name in [(FUNCTIONS / "api" / "me.js", "me"),
                       (FUNCTIONS / "api" / "account.js", "acct"),
                       (FUNCTIONS / "api" / "favorites.js", "fav"),
                       (FUNCTIONS / "api" / "leagues.js", "leagues"),
                       (FUNCTIONS / "api" / "tweets.js", "tw"),
                       (FUNCTIONS / "api" / "tweets" / "[[route]].js", "twr"),
                       (FUNCTIONS / "api" / "auth" / "[[route]].js", "auth"),
                       (FUNCTIONS / "api" / "_middleware.js", "mw")]:
        w.load(path, name)
    w.js(HELPERS)


@pytest.fixture
def worker():
    with Worker() as w:
        load_all(w)
        yield w


def token(w, uid="u1", name=NEW, **extra):
    """A session cookie for `uid`, signed with whatever `extra` says (ep=...)."""
    payload = {"uid": uid, "email": f"{uid}@example.com", **extra}
    t = w.js("return await session.sign(Object.assign(%s, { exp: Math.floor(Date.now() / 1000)"
             " + 3600 }), %s, 'session');" % (json.dumps(payload), json.dumps(SECRET)))
    return {"cookie": f"{name}={t}"}


def me(w, who):
    got = w.call("me.onRequestGet", f"{API}/me", headers=who)
    assert got["status"] == 200, got["text"]
    return got


def signed_in(w, who):
    return me(w, who)["json"]["signedIn"]


def everywhere(w, who, **headers):
    return w.call("auth.onRequestPost", f"{API}/auth/logout-everywhere", method="POST",
                  headers={**who, **headers}, ctx="{ params: { route: ['logout-everywhere'] } }")


def epoch(w, uid="u1"):
    return w.sql.rows("SELECT session_epoch FROM users WHERE id = ?", uid)[0]["session_epoch"]


def cleared(got):
    """The cookie names a response clears."""
    return {c.split("=", 1)[0] for c in got["cookies"] if "Max-Age=0" in c}


def approved_post(w):
    w.sql.execute("INSERT INTO tweets (tweet_id, submitted_at, status, reviewed_at) "
                  "VALUES ('77', '2026-10-01T00:00:00.000Z', 'approved', "
                  "strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))")
    return w.sql.rows("SELECT id FROM tweets")[0]["id"]


def writes_refused(w, who, pid):
    """Every endpoint a session opens, asked with `who` -> their statuses."""
    put = w.call("fav.onRequestPut", f"{API}/favorites", method="PUT", headers=who,
                 body={"favorites": ["cfb:9"]})
    get = w.call("fav.onRequestGet", f"{API}/favorites", headers=who)
    lg = w.call("leagues.onRequestGet", f"{API}/leagues", headers=who)
    add = w.call("leagues.onRequestPost", f"{API}/leagues", method="POST", headers=who,
                 body={"provider": "sleeper", "league_id": "123456789"})
    vote = w.call("twr.onRequestPost", f"{API}/tweets/{pid}/vote", method="POST", headers=who,
                  body={}, ctx="{ params: { route: [%s, 'vote'] } }" % json.dumps(str(pid)))
    tws = w.call("tw.onRequestGet", f"{API}/tweets", headers=who)
    gone = w.call("acct.onRequestDelete", f"{API}/account", method="DELETE", headers=who)
    return {"put": put["status"], "get": get["status"], "add": add["status"],
            "vote": vote["status"], "delete": gone["status"],
            "leagues_signed_in": lg["json"].get("signedIn", True),
            "tweets_signed_in": tws["json"]["signedIn"]}


DEAD = {"put": 401, "get": 401, "add": 401, "vote": 401, "delete": 401,
        "leagues_signed_in": False, "tweets_signed_in": False}


# --------------------------------------------------------------------------- #
# Sign out everywhere
# --------------------------------------------------------------------------- #

def test_signing_out_everywhere_ends_every_session_of_that_account_only(worker):
    phone = worker.user()                                   # no epoch: from before
    laptop = token(worker, ep=0)
    other = worker.user("u2")
    pid = approved_post(worker)
    assert signed_in(worker, phone) and signed_in(worker, laptop)

    got = everywhere(worker, laptop)
    assert got["status"] == 200 and got["json"] == {"ok": True}
    assert cleared(got) == {NEW, OLD}                       # this browser too
    assert epoch(worker) == 1 and epoch(worker, "u2") == 0

    for who in (phone, laptop):
        answer = me(worker, who)
        assert answer["json"] == {"signedIn": False, "configured": True}
        assert cleared(answer) == {NEW, OLD}, "a dead cookie is cleared, not kept"
        assert writes_refused(worker, who, pid) == DEAD
    assert worker.sql.rows("SELECT id FROM users WHERE id = 'u1'"), "nothing deleted"
    assert signed_in(worker, other)
    assert everywhere(worker, laptop)["status"] == 401 and epoch(worker) == 1


def test_a_sign_in_after_it_carries_the_new_epoch(worker):
    state, stamp = login(worker)
    first = callback(worker, state, stamp, good_claims(worker))
    old = next(c for c in first["cookies"] if c.startswith(NEW + "=")).split(";")[0]
    assert everywhere(worker, {"cookie": old})["status"] == 200

    state, stamp = login(worker)
    again = callback(worker, state, stamp, good_claims(worker))
    new = next(c for c in again["cookies"] if c.startswith(NEW + "=")).split(";")[0]
    body = new.split("=", 1)[1].split(".")[0]
    payload = worker.js(f"return JSON.parse(atob({json.dumps(body)}"
                        ".replace(/-/g, '+').replace(/_/g, '/')));")
    assert payload["ep"] == 1
    assert signed_in(worker, {"cookie": new}) and not signed_in(worker, {"cookie": old})


def test_the_same_request_twice_at_once_moves_the_epoch_once(worker):
    who = worker.user()
    statuses = worker.js(f"""
      const env = {worker.env()};
      const one = () => auth.onRequestPost({{ env, params: {{ route: ["logout-everywhere"] }},
        request: T.req({json.dumps(API + '/auth/logout-everywhere')},
                       {{ method: "POST", headers: {json.dumps(who)} }}) }});
      return (await Promise.all([1, 2, 3, 4, 5].map(one))).map((r) => r.status);
    """)
    assert 200 in statuses and set(statuses) <= {200, 401}
    assert epoch(worker) == 1


def test_another_site_cannot_sign_a_reader_out_everywhere(worker):
    who = worker.user()
    assert everywhere(worker, who, **{"sec-fetch-site": "cross-site"})["status"] == 403
    blocked = worker.js(f"""
      const res = await mw.onRequest({{ env: {worker.env()},
        request: T.req({json.dumps(API + '/auth/logout-everywhere')}, {{ method: "POST",
          headers: Object.assign({{ origin: "https://evil.example" }}, {json.dumps(who)}) }}),
        next: async () => new Response("{{}}", {{ status: 200 }}) }});
      return res.status;""")
    assert blocked == 403
    assert epoch(worker) == 0 and signed_in(worker, who)
    # And it is a POST: a GET (an <img src> on any site) is not a route.
    got = worker.call("auth.onRequestGet", f"{API}/auth/logout-everywhere", headers=who,
                      ctx="{ params: { route: ['logout-everywhere'] } }")
    assert got["status"] == 404 and epoch(worker) == 0


# --------------------------------------------------------------------------- #
# Old tokens, odd tokens, deleted accounts
# --------------------------------------------------------------------------- #

def test_old_tokens_without_an_epoch_last_until_the_first_bump(worker):
    untyped = worker.js("return await untyped({ uid: 'u1', email: 'u1@example.com',"
                        " exp: Math.floor(Date.now() / 1000) + 3600 });")
    worker.user()
    for who in ({"cookie": f"{OLD}={untyped}"}, token(worker, name=OLD), token(worker)):
        assert signed_in(worker, who)
    everywhere(worker, token(worker))
    for who in ({"cookie": f"{OLD}={untyped}"}, token(worker, name=OLD), token(worker)):
        assert not signed_in(worker, who)


@pytest.mark.parametrize("ep", [1, 7, -1, 1.5, "0", None, True])
def test_an_epoch_that_is_not_the_accounts_opens_nothing(worker, ep):
    worker.user()
    assert not signed_in(worker, token(worker, ep=ep))
    assert signed_in(worker, token(worker, ep=0))
    worker.sql.execute("UPDATE users SET session_epoch = 1")
    # Once the account is at 1, only a whole-number 1 opens it (JSON's true
    # is not 1, however Python compares them).
    assert signed_in(worker, token(worker, ep=ep)) == (ep == 1 and ep is not True)


def test_a_deleted_accounts_sessions_are_refused_cleanly(worker):
    here, elsewhere = worker.user(), token(worker, ep=0)
    pid = approved_post(worker)
    gone = worker.call("acct.onRequestDelete", f"{API}/account", method="DELETE", headers=here)
    assert gone["status"] == 200 and cleared(gone) == {NEW, OLD}
    assert worker.sql.rows("SELECT * FROM users") == []
    # The other device: signed out, cookie cleared, every write a 401 - not a
    # foreign-key 500 and not a "too many changes" 429.
    answer = me(worker, elsewhere)
    assert answer["json"]["signedIn"] is False and cleared(answer) == {NEW, OLD}
    assert writes_refused(worker, elsewhere, pid) == DEAD
    assert everywhere(worker, elsewhere)["status"] == 401
    assert worker.sql.rows("SELECT * FROM favorites") == []


# --------------------------------------------------------------------------- #
# The cookie's name
# --------------------------------------------------------------------------- #

def test_the_old_cookie_name_is_moved_to_the_new_one_by_api_me(worker):
    worker.user()
    old = token(worker, name=OLD, ep=0)
    got = me(worker, old)
    assert got["json"]["signedIn"] is True
    moved = next(c for c in got["cookies"] if c.startswith(NEW + "="))
    assert moved.split(";")[0] == f"{NEW}={old['cookie'].split('=', 1)[1]}", "same token"
    max_age = int(moved.split("Max-Age=")[1].split(";")[0])
    assert 3500 < max_age <= 3600, "what is left of its life, not a fresh 90 days"
    assert "Secure" in moved and "Path=/" in moved and "Domain" not in moved
    assert cleared(got) == {OLD}
    # A session already under the new name is left alone.
    assert me(worker, token(worker, ep=0))["cookies"] == []


def test_the_new_name_wins_and_a_bad_one_falls_back(worker):
    worker.user()
    worker.user("u2")
    both = {"cookie": f"{token(worker, 'u2')['cookie']}; {token(worker, name=OLD)['cookie']}"}
    assert me(worker, both)["json"]["email"] == "u2@example.com"
    broken = {"cookie": f"{NEW}=not.a-token; {token(worker, name=OLD)['cookie']}"}
    assert me(worker, broken)["json"]["email"] == "u1@example.com"


# --------------------------------------------------------------------------- #
# What it costs
# --------------------------------------------------------------------------- #

def test_a_reader_who_is_not_signed_in_costs_no_read_and_one_who_is_costs_one(worker):
    worker.user()
    for cookie in ({}, {"cookie": f"{NEW}=junk"}, {"cookie": "gs_oauth=x"}):
        worker.sql.statements.clear()
        assert me(worker, cookie)["json"]["signedIn"] is False
        assert worker.sql.statements == []
    worker.sql.statements.clear()
    assert signed_in(worker, token(worker))
    assert worker.sql.statements == ["SELECT * FROM users WHERE id = ?"]


def test_endpoints_read_the_account_row_once(worker):
    """The session check reads the row, so the endpoints that used to read it
    themselves (owner flag, league refresh stamp) take it from there."""
    who = worker.user()
    worker.sql.statements.clear()
    worker.call("leagues.onRequestGet", f"{API}/leagues", headers=who)
    assert sum("FROM users" in s for s in worker.sql.statements) == 1
    worker.sql.statements.clear()
    got = worker.call("tw.onRequestGet", f"{API}/tweets", headers=who)
    assert got["json"]["admin"] is False
    assert sum("FROM users" in s for s in worker.sql.statements) == 1
    worker.sql.execute("UPDATE users SET is_admin = 1")
    assert worker.call("tw.onRequestGet", f"{API}/tweets", headers=who)["json"]["admin"] is True
    # The refresh limit still holds, read off the same row.
    worker.sql.execute("UPDATE users SET last_league_sync = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')")
    worker.sql.statements.clear()
    soon = worker.call("leagues.onRequestPost", f"{API}/leagues", method="POST", headers=who,
                       body={"provider": "sleeper", "username": "tyler"})
    assert soon["status"] == 429 and 0 < soon["json"]["retry_after"] <= 300
    assert sum("FROM users" in s for s in worker.sql.statements) == 1


def test_api_me_says_unavailable_rather_than_signed_out_when_d1_fails(worker):
    worker.user()
    who = token(worker)
    got = worker.call("me.onRequestGet", f"{API}/me", headers=who,
                      env="Object.assign({ DB: { prepare() { throw new Error('D1 down'); } } },"
                          " %s)" % json.dumps({"SESSION_SECRET": SECRET, "GOOGLE_CLIENT_ID": "c",
                                               "GOOGLE_CLIENT_SECRET": "s"}))
    assert got["status"] == 503 and got["json"]["unavailable"] is True
    assert got["cookies"] == [], "a database outage clears nobody's cookie"


# --------------------------------------------------------------------------- #
# Deployed ahead of migration 006
# --------------------------------------------------------------------------- #

def test_before_the_migration_every_session_is_epoch_0_and_nothing_breaks():
    with Worker(before_006()) as w:
        load_all(w)
        who = w.user()
        assert signed_in(w, who) and signed_in(w, token(w, ep=0))
        assert not signed_in(w, token(w, ep=1))
        state, stamp = login(w)
        signed = callback(w, state, stamp, good_claims(w))
        new = next(c for c in signed["cookies"] if c.startswith(NEW + "=")).split(";")[0]
        assert signed_in(w, {"cookie": new})
        got = everywhere(w, who)
        assert got["status"] == 503 and got["json"]["migrating"] is True
        assert got["cookies"] == [] and signed_in(w, who), "nothing changed"
        put = w.call("fav.onRequestPut", f"{API}/favorites", method="PUT", headers=who,
                     body={"favorites": ["cfb:1"]})
        assert put["status"] == 200


# --------------------------------------------------------------------------- #
# The button on /profile/
# --------------------------------------------------------------------------- #

class _Site:
    """/profile/ built from the real markup, and /api/* from the test."""

    def __init__(self):
        body = profile_page.body("").replace("{% raw %}", "").replace("{% endraw %}", "")
        self.page = ("<!doctype html><html><head><meta charset='utf-8'><style>[hidden]"
                     "{display:none!important}</style></head><body>" + body + "</body></html>")
        self.signed_in = True
        self.everywhere = (200, {"ok": True})
        self.log = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _send(self, status, text, ctype="application/json"):
                data = text.encode()
                self.send_response(status)
                self.send_header("content-type", ctype)
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):                                   # noqa: N802
                outer.log.append(("GET", self.path))
                if self.path.split("?")[0] == "/profile/":
                    return self._send(200, outer.page, "text/html; charset=utf-8")
                if self.path == "/api/me":
                    return self._send(200, json.dumps(
                        {"configured": True, "signedIn": outer.signed_in, "email": "r@x.com"}))
                return self._send(404, "{}")

            def do_POST(self):                                  # noqa: N802
                outer.log.append(("POST", self.path))
                if self.path == "/api/auth/logout-everywhere":
                    status, body = outer.everywhere
                    if status == 200:
                        outer.signed_in = False
                    return self._send(status, json.dumps(body))
                return self._send(404, "{}")

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.origin = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def _until(w, expression, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if w.evaluate(expression):
                return
        except Exception:                                       # noqa: BLE001 - mid-navigation
            pass
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {expression}")


def test_the_profile_button_signs_out_everywhere_and_says_so():
    site = _Site()
    try:
        with Worker() as w:
            w._cdp("Page.navigate", {"url": site.origin + "/profile/"})
            _until(w, "!!document.getElementById('pf-everywhere')")
            assert w.evaluate("document.getElementById('pf-everywhere').textContent") \
                == "Sign out everywhere"

            # Refused: the reason is shown and the button can be pressed again.
            site.everywhere = (503, {"ok": False, "migrating": True,
                                     "error": "Signing out everywhere is not switched on yet."})
            w.evaluate("document.getElementById('pf-everywhere').click()")
            _until(w, "!document.getElementById('pf-everywhere-msg').hidden")
            assert "not switched on" in w.evaluate(
                "document.getElementById('pf-everywhere-msg').textContent")
            assert w.evaluate("document.getElementById('pf-everywhere').disabled") is False

            site.everywhere = (200, {"ok": True})
            w.evaluate("document.getElementById('pf-everywhere').click()")
            _until(w, "/Signed out on every device/.test(document.getElementById('pf-who')"
                      ".textContent)")
            assert w.evaluate("!!document.querySelector('#pf-who a[href^=\"/api/auth/login\"]')")
            # Said once: the marker is off the address already.
            assert w.evaluate("location.search") == ""
            assert [p for m, p in site.log if m == "POST"] == ["/api/auth/logout-everywhere"] * 2
    finally:
        site.close()
