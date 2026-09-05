"""
Google sign-in, so a reader's stars follow them between devices.

The endpoints cannot be exercised from pytest - they are Cloudflare Pages
Functions and need a real Google client, a D1 binding and an edge to run on.
What is checked here is the contract around them, and above all the property
that matters while the credentials do not yet exist: **all of this is inert
until it is configured**, so shipping it changes nothing on the live site.
"""
import re

import pytest

from conftest import DOCS, ROOT

FUNCTIONS = ROOT / "functions" / "api"
SCHEMA = (ROOT / "deploy" / "d1-schema.sql").read_text()
SESSION = (FUNCTIONS / "_lib" / "session.js").read_text()
AUTH = (FUNCTIONS / "auth" / "[[route]].js").read_text()
JS = (DOCS / "assets" / "js" / "favorites.js").read_text()

ENDPOINTS = ["me.js", "favorites.js", "account.js"]


@pytest.mark.parametrize("name", ENDPOINTS)
def test_every_endpoint_refuses_to_run_unconfigured(name):
    """Deploying before the bindings exist must not 500 anybody."""
    src = (FUNCTIONS / name).read_text()
    assert "configured(env)" in src, f"{name} does not check configuration"


def test_the_auth_route_refuses_to_run_unconfigured():
    assert "configured(env)" in AUTH


def test_the_page_offers_no_sign_in_until_it_is_configured():
    """The one that keeps today's site unchanged: no control, no dead link."""
    assert "if (!account.configured)" in JS
    assert "slot.hidden = true" in JS


def test_the_session_cookie_is_httponly_secure_and_lax():
    for flag in ("HttpOnly", "Secure", "SameSite=Lax"):
        assert flag in SESSION, f"session cookie missing {flag}"


def test_the_session_expiry_is_inside_the_signature():
    """An expiry beside the signature is an expiry the holder can edit."""
    assert "payload.exp" in SESSION
    assert "crypto.subtle.verify" in SESSION, "signature compared by hand"


def test_the_callback_checks_audience_and_issuer():
    """A valid Google token issued to somebody else's client is not a sign-in."""
    assert "claims.aud !== env.GOOGLE_CLIENT_ID" in AUTH
    assert "ISSUERS.has(claims.iss)" in AUTH


def test_the_callback_checks_state_against_its_own_cookie():
    assert "stamp.state !== state" in AUTH


def test_redirects_cannot_leave_the_site():
    """`next` arrives in the query string, so it is attacker-controlled."""
    assert "function safeNext" in AUTH
    assert re.search(r"\^\\/\(\?!\\/\)", AUTH), "safeNext does not reject //host"


def test_no_google_token_is_ever_stored():
    """The schema is the enforcement: there is nowhere to put one."""
    assert "access_token" not in SCHEMA
    assert "refresh_token" not in SCHEMA
    assert "id_token" not in SCHEMA


def test_users_are_keyed_on_the_google_subject_not_the_email():
    """A reassigned address must not inherit the previous holder's favourites."""
    assert "provider_sub  TEXT NOT NULL UNIQUE" in SCHEMA


def test_deleting_an_account_takes_the_favourites_with_it():
    assert "ON DELETE CASCADE" in SCHEMA
    assert "onRequestDelete" in (FUNCTIONS / "account.js").read_text()


def test_a_synced_write_is_one_batch():
    """A delete that lands without its inserts would empty a reader's list."""
    assert "DB.batch(" in (FUNCTIONS / "favorites.js").read_text()


def test_favorite_keys_are_shape_checked_before_they_reach_the_table():
    src = (FUNCTIONS / "favorites.js").read_text()
    assert "KEY.test(key)" in src
    assert "MAX" in src, "no ceiling on rows per user"


def test_local_favourites_paint_before_the_network_is_asked():
    """A reader's own stars must never wait on a round trip."""
    boot = JS.split("function boot()")[1]
    assert boot.index("paint()") < boot.index("sync()")


def test_first_sign_in_merges_and_afterwards_the_server_wins():
    """Merging forever would make un-starring impossible to make stick."""
    assert "union(favorites, remote)" in JS
    assert "favorites = remote" in JS
    assert "readSyncedAs() !== account.email" in JS
