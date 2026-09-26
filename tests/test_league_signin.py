"""
What the league control offers depends on whether there is an account.

Three states, and the difference between two of them is the bug worth
guarding: 401 from /api/leagues means nobody is signed in, and 503 means this
deploy has no accounts at all. Treating the second as the first puts a "Sign
in" button on a site with nowhere to sign in to.

Finding every league from a username is a sync - it writes to an account - so
signed out that is a sign-in prompt. A league id needs nobody and lives in the
browser, so it stays open to everyone.
"""
import re

from gordstats import my_league

JS = my_league.JS


def test_the_api_status_is_the_signal_not_a_failure():
    """One request already being made answers this; a second one to /api/me
    would be a round trip for something we are told anyway."""
    assert "if(r.status===401) signedIn=false;" in JS
    assert "else if(r.ok) signedIn=true;" in JS


def test_a_deploy_without_accounts_is_not_a_signed_out_reader():
    """503 must leave signedIn null, so the control keeps the behaviour it had
    before accounts existed rather than offering a sign-in that goes nowhere."""
    assert re.search(r"var signedIn=null;", JS), "unknown until the API answers"
    # Every place the state is set, comments stripped so prose about 503
    # cannot pass for code that handles it.
    code = re.sub(r"//[^\n]*", "", JS)
    sets = re.findall(r"signedIn\s*=\s*(\w+)", code)
    assert sorted(set(sets)) == ["false", "null", "true"], sets
    # ...and the only conditions that set it are 401 and ok. A 503 falls
    # through both and leaves it null, which is what keeps the control as it
    # was before accounts existed.
    assert re.search(r"if\(r\.status===401\)\s*signedIn=false;", code)
    assert re.search(r"else if\(r\.ok\)\s*signedIn=true;", code)
    assert "503" not in code, "no code path should branch on 503"


def test_signed_out_offers_a_sign_in_and_a_league_id():
    assert "ml-in" in JS and "/api/auth/login?next=" in JS
    assert "'league id'" in JS, "the field takes an id, not a username"
    assert "or paste a league id" in JS


def test_signed_out_cannot_sync_a_username():
    """The endpoint already answers 401; this is so the reader is told why
    instead of watching it fail silently."""
    body = JS[JS.index("function connect(username)"):]
    guard = body[:body.index("msg('Asking Sleeper")]
    assert "signedIn===false" in guard
    assert "Sign in first" in guard


def test_the_sign_in_link_comes_back_to_this_page():
    assert "encodeURIComponent(location.pathname+location.search)" in JS


def test_the_empty_state_is_redrawn_once_the_answer_arrives():
    """It is drawn before the API answers, so a signed-out reader would
    otherwise keep the username box they cannot use."""
    assert "if(!(saved()||{}).id && !mine) draw(null);" in JS


def test_a_signed_in_reader_gets_their_leagues_without_a_username():
    """The whole point: the account already knows, so asking again is asking
    twice."""
    assert "ml-pick" in JS
    assert "fromAccount.length" in JS and "saveList(SYNCED)" in JS


def test_every_fantasy_page_with_a_league_carries_the_control():
    """A page offering a league it has no way to choose is the bug that
    shipped on the roster page once already."""
    import pathlib

    from conftest import ROOT

    for name in ("waivers", "history", "draft_review", "power", "usage",
                 "matchups", "roster"):
        src = (ROOT / "src" / "fantasy" / "site" / f"{name}.py").read_text()
        assert "my_league.bar()" in src, f"{name} has no league control"
        assert "my_league.JS" in src, f"{name} has the control but not its script"
