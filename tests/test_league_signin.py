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

from conftest import ROOT
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
    assert "'or paste a league id'" in JS, "the field takes an id, not a username"
    assert "or paste a Sleeper or ESPN league id" in JS


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
    """The bar is drawn before /api/leagues answers, and it reads differently
    once it has: a signed-out reader gets a sign-in rather than a username box
    they cannot use, and this site's league goes back in the picker. So the
    no-leagues path has to redraw, not just return."""
    branch = JS[JS.index("var mine=d&&d.leagues"):]
    branch = branch[:branch.index("var fromAccount")]
    assert "draw(" in branch, "the answer arrives and nothing is redrawn"
    assert branch.index("draw(") < branch.index("return;"), \
        "it returns before redrawing"


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


def test_the_four_sections_share_one_empty_state():
    """They were four copies of the same sentence, which is how three came to
    say "connect yours" and one "sync yours"."""
    from gordstats import my_draft, my_history, my_power, my_waivers

    for mod in (my_waivers, my_power):
        assert "GSLeague.empty(" in mod.JS, f"{mod.__name__} still rolls its own"
        # Drawn twice, because the account state is not known at first paint.
        assert "GSLeague.ready" in mod.JS, f"{mod.__name__} never redraws"
    # History and drafts are Sleeper's for any league, this site's included:
    # with none picked they show this one rather than an empty state.
    from fantasy.config import UPCOMING_LEAGUE_ID
    for mod in (my_history, my_draft):
        assert f"if(!have||!have.id) have={{id:'{UPCOMING_LEAGUE_ID}'" in mod.JS, mod.__name__


def test_the_empty_state_asks_a_signed_out_reader_to_sign_in():
    assert "Paste a league id above, or sign in, to see your" in JS
    assert "Pick a league above" in JS, "and still guides a signed-in one"


def test_one_sign_in_offer_a_screen():
    """The league bar has its Sign in button; the site-wide invite stays off
    pages that carry the bar, and the empty state under it names no second
    button."""
    fav = (ROOT / "docs" / "assets" / "js" / "favorites.js").read_text()
    assert '!document.getElementById("ml-bar")' in fav
    empty = JS[JS.index("empty: function"):JS.index("Pick a league above")]
    assert "ml-in" not in empty


def test_a_section_without_the_control_still_says_something():
    """my_league.JS could be missing from a page by mistake - that has
    happened - and a blank panel is a worse way to find out than a sentence
    that is merely less helpful."""
    from gordstats import my_history

    # It no longer needs one: with no league picked it reads this site's.
    assert "have={id:'" in my_history.JS


def test_the_picker_survives_showing_this_sites_league():
    """The bug behind "still can't have teams auto here even though signed in".

    Pressing "Show this site's league" stored {site:true}, and the account
    handler then returned before drawing anything - so the bar fell back to a
    username box and stayed there. Signed in, three leagues synced, and the
    only way back to them was typing the name in again.

    Reproduced with the real six rows from D1 and fixed: the picker is drawn
    whenever there are leagues to pick between, and this site's league is one
    of the options rather than a door that only opens one way.
    """
    assert "if(SYNCED.length){" in JS, "the picker must not depend on one already showing"
    assert "if(want==='site'){ restore(); return; }" in JS
    assert "if(have&&have.site) return;" not in JS, "the early return is back"


def test_a_league_entered_by_id_is_still_named():
    """One the account has never heard of: nothing to pick between, so it is
    named with a way back rather than dropped into a picker of one."""
    assert "Showing <span class=\"ml-who\"></span>" in JS
    assert "ml-clear" in JS


def test_a_signed_in_reader_with_leagues_is_not_offered_this_sites_league():
    """"If a user is signed in and has at least one league synced, they should
    not even be able to see the site's main league. Just to keep things
    clear."

    So the option is drawn only once the account has answered that nobody is
    signed in - not on the way there, where `signedIn` is still null - and a
    stored {site:true} from before is not honoured for a reader who now has
    leagues of their own.
    """
    assert "var offerSite=(signedIn===false);" in JS, \
        "the site option is offered on something other than being signed out"
    site = JS[JS.index("var offerSite"):]
    site = site[:site.index("SYNCED.map(")]
    assert "offerSite" in site and 'value="site"' in site, \
        "the option is not behind the check"
    # An old choice is cleared rather than acted on (this site's own league,
    # picked by id, is theirs and stays).
    assert "if(have&&have.site&&!isSite(have.id)) have=null;" in JS
    # ...and then the first of their leagues is what the menu shows, or the
    # select sits on nothing and the page looks broken.
    assert "!offerSite && !here && i===0" in JS


def test_a_reader_with_nothing_synced_can_still_reach_this_sites_league():
    """It is the whole site for them. The ask was to hide it from somebody
    who has a league of their own, not to make it unreachable."""
    # The way back for a league entered by id, which is the case that has no
    # picker to put the option in.
    assert "ml-clear" in JS and "Show this site" in JS
    assert "addEventListener('click',restore)" in JS


def test_a_signed_out_answer_in_the_body_counts_too():
    """GET /api/leagues answers a signed-out reader 200 {signedIn: false} (a
    401 was a console error on every fantasy page); the 401 check stays for a
    deploy from before."""
    assert "if(d && d.signedIn===false) signedIn=false;" in JS
