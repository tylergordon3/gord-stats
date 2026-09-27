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
    """`next` arrives in the query string, so it is attacker-controlled. The
    check is behavioural - tests/test_safe_next.py runs it in a browser - since
    a pattern on the source is what let "/\\evil.com" through."""
    assert "function safeNext" in AUTH
    for start in (m.end() for m in re.finditer(r"(?<!function )safeNext\(", AUTH)):
        depth, i = 1, start
        while depth:
            depth += {"(": 1, ")": -1}.get(AUTH[i], 0)
            i += 1
        assert AUTH[start:i - 1].endswith(", url.origin"), \
            f"a safeNext call without the origin to resolve against: {AUTH[start:i - 1]}"


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
# What is pinned here is the contract - above all that syncing a league never
# becomes a reason to hold someone's provider credentials. The endpoint itself
# is run, against SQLite and a stubbed Sleeper, in tests/test_leagues_api.py.
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
    resolves to anything - nor start the refresh clock."""
    block = LEAGUES[LEAGUES.index("async function addOne("):]
    asked = block.index("await ask(`league/${leagueId}`)")
    assert asked < block.index("await claim(") < block.index("await store(")


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


def test_a_username_syncs_every_league_that_account_is_in():
    """The league-id flow asked people to dig a sixteen-digit number out of a
    URL, once per league, which is where it lost them. Sleeper will say which
    leagues an account is in, so the username is the way in."""
    assert "syncAll(" in LEAGUES
    assert "/leagues/nfl/" in LEAGUES, "it never asks Sleeper for the account's leagues"
    assert "USERNAME" in LEAGUES, "the username is not shape-checked"
    # Still no credentials: this works because Sleeper is keyless, not because
    # anyone signed in to it.
    for word in ("password", "access_token", "refresh_token"):
        assert word not in LEAGUES


def test_the_bulk_sync_is_rate_limited_on_the_account():
    """One button that fans out to every league is the one worth holding down,
    so the limit is the whole account rather than each league - claimed in one
    conditional UPDATE, since a read-then-write let parallel POSTs through."""
    block = LEAGUES[LEAGUES.index("async function syncAll("):]
    assert "claim(env.DB, session.uid, CLAIM, REFRESH_SECONDS)" in block
    assert 'const CLAIM = "last_league_sync"' in LEAGUES


def test_each_league_stores_the_team_in_it():
    """Two leagues named the same thing are one entry twice in a picker, and
    people do name them the same thing."""
    assert "team_name" in LEAGUES
    leagues_table = SCHEMA[SCHEMA.index("CREATE TABLE IF NOT EXISTS leagues"):]
    assert "team_name" in leagues_table
    picker = (ROOT / "src" / "gordstats" / "my_league.py").read_text()
    assert "leagueLabel" in picker and "team_name" in picker


def test_the_league_lookup_does_not_swallow_its_own_bugs():
    """An empty catch around the account lookup hid a TypeError - a function
    shadowed by a parameter - and the picker just silently never appeared."""
    picker = (ROOT / "src" / "gordstats" / "my_league.py").read_text()
    lookup = picker[picker.index("fetch('/api/leagues',{credentials:'same-origin'})"):]
    assert ".catch(function(){});" not in lookup, \
        "the account lookup swallows its own errors again"
    assert "console.error" in lookup


def test_syncing_a_league_takes_its_history_with_it():
    """Sleeper gives each season its own league id and links them backwards
    with previous_league_id, so one walk gets the lot - the site's own league
    chains 2026 back to 2023 that way."""
    assert "previous_league_id" in LEAGUES
    assert "async function walkBack(" in LEAGUES
    # Both ways in get it: a league added by id should not be a poorer relation.
    assert LEAGUES.count("walkBack(") >= 3


def test_the_history_walk_cannot_loop_or_run_away():
    """These ids come from an API. A cycle would be an endless one, and a long
    chain would be an unbounded row count on somebody's account - or, before
    the call budget, ~480 calls to Sleeper from one POST."""
    block = LEAGUES[LEAGUES.index("async function walkBack("):]
    assert "seen.has(" in block and "MAX_SEASONS" in block
    assert "MAX_ROWS" in LEAGUES and "asker(FETCH_BUDGET)" in LEAGUES


def test_seasons_group_under_their_league_everywhere_they_are_shown():
    """A league with four years of history is four rows. Listed raw that reads
    as four leagues, in a picker it is four near-identical entries."""
    for path in ("src/gordstats/my_league.py", "src/gordstats/league_sync.py"):
        src = (ROOT / path).read_text()
        assert "lineage_id" in src, f"{path} does not group seasons"


def test_removing_a_league_removes_its_seasons():
    """Otherwise "Remove" takes this year and leaves three older rows behind,
    which come back as a league the reader thought they had deleted."""
    block = LEAGUES[LEAGUES.index("export async function onRequestDelete"):]
    assert "lineage_id = ?" in block
