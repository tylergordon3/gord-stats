"""
Sessions and sign-in: the token kinds cannot stand in for each other, the ID
token's expiry and verified flag are checked, a bad cookie is no session
rather than a 500, and another site cannot sign a reader out.

  - The OAuth state stamp and the session were signed with one key in one
    format, so the gs_oauth cookie anyone gets from /api/auth/login, replayed
    as gs_session, made /api/me report a signed-in reader. Tokens now carry
    a signed `typ`; untyped sessions from before still pass if they hold a
    uid, which a state stamp never does.
  - The auth file's comment said the ID token's `exp` was checked; it was
    not, and neither was `email_verified`.
  - decodeURIComponent threw on a malformed cookie, outside any try.
  - Logout is a GET, so an <img> on any site could sign a reader out.

The Functions run in headless Chromium (tests/functions_harness.py), with
Google's token endpoint stubbed.
"""
import json
from urllib.parse import parse_qs, urlparse

import pytest

from functions_harness import CHROME, FUNCTIONS, SECRET, Worker

pytestmark = pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")

AUTH = "https://www.gordstats.com/api/auth"
ME = "https://www.gordstats.com/api/me"

# A token signed the way sessions were before `typ`: this is written out
# independently of session.js on purpose, so the test does not share its bugs.
HELPERS = r"""
window.b64 = (bytes) => btoa(String.fromCharCode(...bytes))
  .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
window.untyped = async (payload) => {
  const enc = new TextEncoder();
  const body = b64(enc.encode(JSON.stringify(payload)));
  const key = await crypto.subtle.importKey("raw", enc.encode(%s),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return body + "." + b64(new Uint8Array(await crypto.subtle.sign("HMAC", key, enc.encode(body))));
};
window.claims = {};
T.routes = [["oauth2\\.googleapis\\.com/token", () => ({ body: {
  id_token: "h." + b64(new TextEncoder().encode(JSON.stringify(window.claims))) + ".s" } })]];
""" % json.dumps(SECRET)


@pytest.fixture
def worker():
    with Worker() as w:
        w.load(FUNCTIONS / "api" / "auth" / "[[route]].js", "auth")
        w.load(FUNCTIONS / "api" / "me.js", "me")
        w.load(FUNCTIONS / "api" / "favorites.js", "fav")
        w.js(HELPERS)
        yield w


def route(name):
    return "{ params: { route: [%s] } }" % json.dumps(name)


def me(w, cookie):
    got = w.call("me.onRequestGet", ME, headers={"cookie": cookie})
    assert got["status"] == 200, got["text"]
    return got["json"]


def login(w):
    """-> (state, the gs_oauth cookie) from a real /login."""
    got = w.call("auth.onRequestGet", f"{AUTH}/login?next=/profile/", ctx=route("login"))
    assert got["status"] == 302
    state = parse_qs(urlparse(got["headers"]["location"]).query)["state"][0]
    stamp = got["cookies"][0].split(";")[0]
    assert stamp.startswith("gs_oauth=")
    return state, stamp


def callback(w, state, stamp, claims):
    w.js(f"window.claims = {json.dumps(claims)};")
    return w.call("auth.onRequestGet", f"{AUTH}/callback?code=c0de&state={state}",
                  headers={"cookie": stamp}, ctx=route("callback"))


def good_claims(w, **over):
    now = w.js("return Math.floor(Date.now() / 1000);")
    claims = {"iss": "https://accounts.google.com", "aud": "cid", "sub": "g-123",
              "email": "reader@example.com", "email_verified": True, "exp": now + 3600}
    claims.update(over)
    return claims


def test_a_malformed_cookie_is_no_session_not_a_500(worker):
    who = worker.user()
    assert me(worker, "gs_session=%E0%A4%A") == {"signedIn": False, "configured": True}
    # A bad cookie beside a good one costs only itself.
    assert me(worker, "junk=%zz; " + who["cookie"])["signedIn"] is True
    assert worker.call("fav.onRequestGet", "https://www.gordstats.com/api/favorites",
                       headers={"cookie": "gs_session=%"})["status"] == 401


def test_the_state_stamp_is_not_a_session(worker):
    _, stamp = login(worker)
    replayed = "gs_session=" + stamp.split("=", 1)[1]
    assert me(worker, replayed)["signedIn"] is False
    assert worker.call("fav.onRequestGet", "https://www.gordstats.com/api/favorites",
                       headers={"cookie": replayed})["status"] == 401


def test_a_session_is_not_a_state_stamp(worker):
    state, _ = login(worker)
    forged = worker.js(f"""return await session.sign({{ state: {json.dumps(state)}, next: "/",
      exp: Math.floor(Date.now() / 1000) + 600 }}, {json.dumps(SECRET)}, "session");""")
    got = callback(worker, state, "gs_oauth=" + forged, good_claims(worker))
    assert "signin=failed" in got["headers"]["location"]
    assert not any(c.startswith("gs_session=") and "Max-Age=0" not in c for c in got["cookies"])


def test_sessions_signed_before_typ_still_work_if_they_are_sessions(worker):
    worker.user()
    exp = worker.js("return Math.floor(Date.now() / 1000) + 3600;")
    old = worker.js(f"return await untyped({{ uid: 'u1', email: 'u1@example.com', exp: {exp} }});")
    assert me(worker, "gs_session=" + old) == {
        "signedIn": True, "configured": True, "email": "u1@example.com"}
    stampish = worker.js(f"return await untyped({{ state: 's', next: '/', exp: {exp} }});")
    assert me(worker, "gs_session=" + stampish)["signedIn"] is False
    # And an untyped token is never a state stamp.
    got = callback(worker, "s", "gs_oauth=" + stampish, good_claims(worker))
    assert "signin=failed" in got["headers"]["location"]


def test_a_good_callback_signs_in_with_a_typed_session(worker):
    state, stamp = login(worker)
    got = callback(worker, state, stamp, good_claims(worker))
    assert got["status"] == 302 and got["headers"]["location"] == "/profile/"
    session = next(c for c in got["cookies"] if c.startswith("gs_session="))
    token = session.split(";")[0].split("=", 1)[1]
    payload = worker.js(f"return JSON.parse(atob({json.dumps(token.split('.')[0])}"
                        ".replace(/-/g, '+').replace(/_/g, '/')));")
    assert payload["typ"] == "session" and payload["email"] == "reader@example.com"
    assert me(worker, f"gs_session={token}")["signedIn"] is True
    assert worker.sql.rows("SELECT email, provider_sub FROM users") == [
        {"email": "reader@example.com", "provider_sub": "g-123"}]


@pytest.mark.parametrize("over, why", [
    ({"exp": 1}, "did not verify"),                           # expired
    ({"exp": None}, "did not verify"),                        # no expiry at all
    ({"aud": "someone-else"}, "did not verify"),
    ({"iss": "https://evil.example"}, "did not verify"),
    ({"email_verified": False}, "not verified"),
    ({"email_verified": None}, "not verified"),               # not said
    ({"email": None}, "did not return an email"),
])
def test_a_callback_with_bad_claims_signs_nobody_in(worker, over, why):
    state, stamp = login(worker)
    claims = {k: v for k, v in good_claims(worker, **over).items() if v is not None}
    got = callback(worker, state, stamp, claims)
    where = urlparse(got["headers"]["location"])
    assert parse_qs(where.query)["signin"] == ["failed"]
    assert why in parse_qs(where.query)["why"][0]
    assert not any(c.startswith("gs_session=") for c in got["cookies"])
    assert worker.sql.rows("SELECT id FROM users") == []


@pytest.mark.parametrize("site, signed_out", [
    ("same-origin", True), ("same-site", True), ("none", True), (None, True),
    ("cross-site", False),
])
def test_logout_refuses_other_sites(worker, site, signed_out):
    headers = {"sec-fetch-site": site} if site else {}
    got = worker.call("auth.onRequestGet", f"{AUTH}/logout?next=/profile/",
                      headers=headers, ctx=route("logout"))
    if signed_out:
        assert got["status"] == 302 and got["headers"]["location"] == "/profile/"
        assert got["cookies"][0].startswith("gs_session=;") and "Max-Age=0" in got["cookies"][0]
    else:
        assert got["status"] == 403 and got["cookies"] == []
