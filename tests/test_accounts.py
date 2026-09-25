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

ENDPOINTS = ["me.js", "favorites.js", "account.js", "leagues.js"]


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


# --------------------------------------------------------------------------- #
# Synced leagues
#
# Same principle as the rest of this file: the endpoint cannot be run from
# pytest, so what is pinned here is the contract - above all that syncing a
# league never becomes a reason to hold someone's provider credentials.
# --------------------------------------------------------------------------- #

LEAGUES = (FUNCTIONS / "leagues.js").read_text()


def test_syncing_a_league_stores_no_provider_credentials():
    """The feature exists in this shape *because* neither provider needs one:
    Sleeper is keyless and Yahoo's public API serves a public league. If a
    token ever has to be stored, that is a different design and a different
    review, not a column quietly added here."""
    for word in ("access_token", "refresh_token", "client_secret", "password"):
        assert word not in LEAGUES, f"leagues.js mentions {word}"
    leagues_table = SCHEMA[SCHEMA.index("CREATE TABLE IF NOT EXISTS leagues"):]
    for word in ("token", "secret", "password"):
        assert word not in leagues_table.lower(), f"the leagues table has a {word} column"


def test_a_league_is_checked_with_the_provider_before_it_is_stored():
    """A typo should fail at the point of typing, not become a row that never
    resolves to anything."""
    assert "async function lookup(" in LEAGUES
    assert LEAGUES.index("await lookup(") < LEAGUES.index("INSERT INTO leagues")


def test_league_ids_are_shape_checked_before_they_are_used():
    assert "SHAPES" in LEAGUES and "SHAPES[provider].test(" in LEAGUES


def test_only_sleeper_can_be_synced():
    """Yahoo came out again: its public API serves only leagues set public, and
    a private one needs OAuth and stored refresh tokens - which would change
    what a leaked database costs, for leagues nobody has asked for.

    The `provider` column stays so a second platform needs no migration, but
    nothing should accept one until that decision is actually taken."""
    assert "SHAPES = { sleeper:" in LEAGUES
    assert "yahoo" not in LEAGUES.lower().replace("yahoo was here", "")
    page = (ROOT / "src" / "gordstats" / "league_sync.py").read_text()
    assert "ls-yahoo" not in page, "the sync page still offers a Yahoo box"


def test_the_refresh_limit_is_read_from_the_stored_timestamp():
    """A limit kept in the browser is no limit: it resets on reload and does
    not exist in a second tab."""
    assert "last_synced_at" in LEAGUES
    assert "REFRESH_SECONDS" in LEAGUES
    assert "429" in LEAGUES


def test_deleting_an_account_takes_the_leagues_with_it():
    table = SCHEMA[SCHEMA.index("CREATE TABLE IF NOT EXISTS leagues"):]
    assert "REFERENCES users(id) ON DELETE CASCADE" in table
