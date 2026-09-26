"""
Structural checks on the generated site.

Covers the navigation failures: links that pointed nowhere, and a layout script
that rewrote them at click time so they only broke in a browser.
"""

import json
import re
from datetime import datetime

import pytest
import yaml

from conftest import DOCS, needs_built_site, ROOT

NAV = yaml.safe_load((DOCS / "_data" / "nav.yml").read_text())
LAYOUT = (DOCS / "_layouts" / "default.html").read_text()
REDIRECTS = (DOCS / "_redirects").read_text() if (DOCS / "_redirects").exists() else ""


def _targets():
    """(where it came from, url) for every link in nav.yml."""
    for section, items in NAV.items():
        for item in items:
            if item.get("url"):
                yield section, item["url"]


def _resolves(url: str) -> bool:
    """Does this URL correspond to a file that will exist in the built site?"""
    path = url.split("#")[0].lstrip("/")
    if not path or path.endswith("/"):
        path += "index.html"
    if (DOCS / path).exists():
        return True
    # a redirect rule counts as resolving
    return any(line.split()[0].rstrip("*").rstrip("/") == "/" + url.rstrip("/").lstrip("/")
               for line in REDIRECTS.splitlines() if line and not line.startswith("#"))


@pytest.mark.parametrize("section,url", list(_targets()))
@needs_built_site
def test_nav_links_point_at_real_pages(section, url):
    assert _resolves(url), f"nav.yml [{section}] -> {url} has no page behind it"


def test_no_script_rewrites_nav_hrefs():
    """The bug: a 'league-aware nav rewrite' prepended /men to every
    root-relative nav href without .no-rewrite, turning /fantasy/adp/ into
    /men/fantasy/adp/. It only fired on click, so fetching the URLs directly
    always returned 200 and hid it."""
    assert "LEAGUE-AWARE NAV REWRITE" not in LAYOUT
    assert not re.search(r"a\.href\s*=\s*[`'\"]\s*/\$\{league\}", LAYOUT), \
        "something in the layout is rewriting nav hrefs at runtime"


@needs_built_site
def test_every_section_in_the_bar_has_a_landing_page():
    for item in NAV["sections"]:
        assert _resolves(item["url"]), f"section {item['title']} -> {item['url']} is missing"


#: Sub-nav lists kept in nav.yml but not reachable from anywhere right now.
#: WNBA was taken out of the Fantasy switcher on 2026-09-25 with its regular
#: season over; its pages stay defined so putting it back is uncommenting four
#: lines. Naming them here rather than loosening the check keeps a genuinely
#: orphaned list from appearing unnoticed.
PARKED_SUB_NAVS = {"wnba"}


@needs_built_site
def test_sub_nav_sections_match_the_bar():
    """A section listed in the bar, or a league under Fantasy, must have a
    sub-nav key - without one its pages have no navigation at all. The reverse
    is a tidiness check, so a deliberately parked list is allowed for it."""
    bar = {i["section"] for i in NAV["sections"] if i.get("section")}
    leagues = {lg["pages"] for lg in NAV["fantasy_leagues"]}
    subs = set(NAV) - {"sections", "fantasy_leagues"}
    missing = (bar | leagues) - subs
    assert not missing, f"{missing} are in the bar with no sub-nav"
    orphans = subs - (bar | leagues) - PARKED_SUB_NAVS
    assert not orphans, f"{orphans} are sub-navs nothing links to"
    # A parked list that turns out to be reachable is a stale exception - and
    # it is how a nav edit can be reverted without anything noticing, which is
    # exactly what happened to the WNBA one on 2026-09-25.
    live = PARKED_SUB_NAVS & (bar | leagues)
    assert not live, (
        f"{live} are in PARKED_SUB_NAVS but are linked from the bar or the "
        "Fantasy switcher - put them back or take them out of the parked set")
    for lg in NAV["fantasy_leagues"]:
        assert _resolves(lg["url"]), f"league {lg['title']} -> {lg['url']} is missing"


def test_retired_draft_pages_are_gone_and_redirected():
    """Pages serves a matching asset before consulting _redirects, so the old
    directories had to be deleted for the 301s to fire at all."""
    for old in ("draft-recap", "draft-report", "draft-dna", "adp"):
        assert not (DOCS / "fantasy" / old).exists(), f"docs/fantasy/{old} still shadows its redirect"
        assert f"/fantasy/{old}/" in REDIRECTS, f"no redirect for /fantasy/{old}/"
    # The CFB scoreboard folded into the schedule page the same way.
    assert not (DOCS / "cfb" / "scoreboard").exists(), "docs/cfb/scoreboard still shadows its redirect"
    assert "/cfb/scoreboard/" in REDIRECTS, "no redirect for /cfb/scoreboard/"


# --------------------------------------------------------------------------- #
# Countdown clocks
# --------------------------------------------------------------------------- #

# Tracked source, but read defensively: this is also read at collection time by
# a parametrize, and a missing file there is a collection error rather than a
# skip - which is a bad way to find out about a mistake.
def _countdowns():
    path = DOCS / "_data" / "countdowns.yml"
    return yaml.safe_load(path.read_text()) if path.exists() else {}
_COUNTDOWN_KEY = re.compile(r'include\s+countdown\.html\s+key="([^"]+)"')


def _countdown_uses():
    """(where it was written, key) for every countdown placed on a page.

    The generators are read as well as the pages: docs/index.html is written by
    src/cbb/render/render_home.py and docs/fantasy/index.html by the fantasy
    site build, so a bad key added there would only surface on the next daily
    rebuild.
    """
    for path in sorted(DOCS.rglob("*.html")):
        if "_site" in path.parts:
            continue
        for key in _COUNTDOWN_KEY.findall(path.read_text(encoding="utf-8")):
            yield path.relative_to(ROOT), key
    for path in sorted((ROOT / "src").rglob("*.py")):
        for key in _COUNTDOWN_KEY.findall(path.read_text(encoding="utf-8")):
            yield path.relative_to(ROOT), key


@needs_built_site
def test_every_countdown_on_a_page_has_data_behind_it():
    """A key with no entry renders nothing at all — the include is silent about
    it, so the clock just quietly stops appearing."""
    missing = [f"{where} -> {key!r}" for where, key in _countdown_uses()
               if key not in _countdowns()]
    assert not missing, ("countdowns.yml has no entry for:\n  " + "\n  ".join(missing))


@needs_built_site
def test_the_homepage_carries_both_countdowns():
    """They live inside the preview boxes; two clocks on one page is the case
    the old per-page includes could not do, since each hardcoded id="days"."""
    keys = _COUNTDOWN_KEY.findall((DOCS / "index.html").read_text(encoding="utf-8"))
    assert "cbb" in keys and "fantasy" in keys, f"homepage countdowns: {keys}"


@pytest.mark.parametrize("key", sorted(_countdowns()))
def test_countdown_entries_are_complete_and_parseable(key):
    entry = _countdowns()[key]
    for field in ("eyebrow", "title", "target", "expired"):
        assert entry.get(field), f"countdowns.yml [{key}] is missing {field}"
    # Naive on purpose: the browser reads it as the reader's local time, so a
    # trailing Z or an offset would move the clock for everyone but the author.
    datetime.fromisoformat(entry["target"])
    assert not entry["target"].endswith("Z") and "+" not in entry["target"], \
        f"countdowns.yml [{key}] target must be local, not zoned"


def test_the_old_per_page_countdowns_are_gone():
    """Three copies of one clock, two of them hand-written, is how the styles
    drifted apart in the first place."""
    assert not (DOCS / "_includes" / "cbb_countdown.html").exists()
    stale = [p.relative_to(ROOT) for p in DOCS.rglob("*.html")
             if "_site" not in p.parts and "cbb_countdown.html" in p.read_text(encoding="utf-8")]
    assert not stale, f"still including the retired countdown: {stale}"


def test_brand_icons_exist():
    for name in ("icon-32.png", "icon-180.png", "icon-192.png", "icon-512.png"):
        assert (DOCS / "assets" / "images" / "brand" / name).exists(), f"missing {name}"
    assert (DOCS / "favicon.ico").exists()
    assert (DOCS / "site.webmanifest").exists()


def test_lang_attribute_has_no_nested_quotes():
    """It rendered as lang=" en-US" — a double quote inside the Liquid closed
    the attribute early, leaving a leading space in the tag.

    Checked structurally rather than by capturing the value: a naive
    `lang="([^"]*)"` stops at the inner quote and happily matches the broken
    form, which is how an earlier version of this test passed either way.
    """
    m = re.search(r'<html lang=(.*?)>', LAYOUT)
    assert m, "no lang attribute"
    attr = m.group(1)
    assert attr.count('"') == 2, f"nested quotes in the lang attribute: {attr}"


def test_local_assets_are_cache_busted():
    """Cloudflare serves JS and CSS with max-age=14400.

    Without a version in the URL, a reader who visited in the last four hours
    runs the previous build's JavaScript against the current build's HTML. That
    shipped once: the sign-in control was in the markup and invisible on a
    phone that had loaded the site earlier the same day.
    """
    for asset in re.findall(r"'(/assets/(?:js|css)/[^']+)' \| relative_url }}(\?v=\{\{ v \}\})?",
                            LAYOUT):
        path, version = asset
        assert version, f"{path} is served without ?v= and will be cached stale"


# --------------------------------------------------------------------------- #
# Usage tables: a column is hidden by class, so the header and the body have to
# agree about which classes a column carries.
# --------------------------------------------------------------------------- #

USAGE_PAGES = ["fantasy/usage/index.html", "cfb/usage/index.html"]


def _usage_table(path):
    doc = (DOCS / path).read_text()
    head = re.search(r"<thead>(.*?)</thead>", doc, re.S)
    body = re.search(r"<tbody>(.*?)</tbody>", doc, re.S)
    assert head and body, f"{path} has no usage table"
    ths = re.findall(r"<th[^>]*>", head.group(1))
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", body.group(1), re.S)
    return ths, rows


@pytest.mark.parametrize("path", USAGE_PAGES)
@needs_built_site
def test_usage_rows_have_one_cell_per_column(path):
    ths, rows = _usage_table(path)
    for i, row in enumerate(rows):
        tds = re.findall(r"<td[^>]*>", row)
        assert len(tds) == len(ths), f"{path} row {i}: {len(tds)} cells for {len(ths)} columns"


@pytest.mark.parametrize("path", USAGE_PAGES)
@needs_built_site
def test_usage_headers_hide_with_their_column(path):
    """Every class that hides a cell - the position views and the two the phone
    layout drops - has to be on the header too.

    A header without its column's class stays visible when the cells go, and
    every column right of it reads under the wrong heading. That shipped once:
    on a phone the owner cell was hidden and its "Fantasy" header was not, so
    games sat under Fantasy and carries under G.
    """
    ths, rows = _usage_table(path)
    hiders = re.compile(r"\b(v-overall|v-rb|v-wr|v-te|us-own|us-lead)\b")

    def marks(tag):
        cls = re.search(r"class=[\"']([^\"']*)[\"']", tag)
        return set(hiders.findall(cls.group(1))) if cls else set()

    head_marks = [marks(t) for t in ths]
    for i, row in enumerate(rows):
        for col, td in enumerate(re.findall(r"<td[^>]*>", row)):
            assert marks(td) == head_marks[col], (
                f"{path} row {i} column {col}: cell has {marks(td) or '{}'}, "
                f"header has {head_marks[col] or '{}'}")


# --------------------------------------------------------------------------- #
# The two fantasy leagues are navigated the same way
# --------------------------------------------------------------------------- #

def test_both_fantasy_leagues_offer_the_same_tabs():
    """The league switcher keeps the reader on their tab by matching `key`
    across the two lists, so a key on one side with no twin on the other
    silently drops them back at a league home."""
    nfl = [i.get("key") for i in NAV["fantasy"]]
    cfb = [i.get("key") for i in NAV["cfb_fantasy"]]
    assert None not in nfl and None not in cfb, "every fantasy tab needs a key"
    assert nfl == cfb, f"tab keys differ: NFL {nfl} vs CFB {cfb}"


@needs_built_site
def test_pages_behind_a_hub_are_still_reachable():
    """Moving a page out of the sub-nav and behind Analytics must not strand
    it: every url a chip `covers` has to exist, and be linked from the hub."""
    for section in ("fantasy", "cfb_fantasy"):
        for item in NAV[section]:
            if not item.get("covers"):
                continue
            hub = (DOCS / item["url"].strip("/") / "index.html")
            assert hub.exists(), f"{section}: hub page {item['url']} is missing"
            # Reachable from the hub, or from a page the hub links to: the
            # draft sub-pages hang off Draft Analytics rather than sitting on
            # the hub itself, and the chip stays lit for them all the same.
            reach = hub.read_text()
            for linked in set(re.findall(r'href=[\'"](/[^\'"#?]*)', reach)):
                child = DOCS / linked.strip("/") / "index.html"
                if child.exists():
                    reach += child.read_text()
            for url in item["covers"].split():
                assert _resolves(url), f"{section}: {url} is covered but does not exist"
                assert url in reach, (
                    f"{section}: {url} is covered by {item['url']} but nothing "
                    "on or one hop from the hub links to it")


# --------------------------------------------------------------------------- #
# "Show my league" on the usage page
# --------------------------------------------------------------------------- #

MY_LEAGUE = (ROOT / "src" / "gordstats" / "my_league.py").read_text()


def test_the_league_override_works_without_an_account():
    """Local first, like the stars: a league id typed on the page is kept in
    this browser and works signed out. The account only carries it to another
    device, and must never become the gate."""
    assert "localStorage" in MY_LEAGUE
    # The account lookup is a later refinement, not a precondition: it runs
    # after the saved league has already been drawn. Anchored on the call
    # itself - /api/leagues is also named inside connect(), which is a
    # definition rather than a step in the order things happen.
    assert (MY_LEAGUE.index("var have=saved();")
            < MY_LEAGUE.index("fetch('/api/leagues',{credentials:'same-origin'})"))


def test_asking_for_the_sites_own_league_sticks_but_the_picker_stays():
    """Two halves, and pinning only the first cost a real bug.

    The account lookup must not re-apply the synced league a moment after the
    reader asked for this one, or the button looks broken. But it must still
    *draw*: the version that simply returned left the bar as a username box,
    so somebody signed in with three leagues synced had no way back to them
    (2026-09-25)."""
    assert "save({site:true})" in MY_LEAGUE
    assert "if(have&&have.site){ draw(null); return; }" in MY_LEAGUE
    # The return comes before the load, so their league is not pulled back in.
    after = MY_LEAGUE[MY_LEAGUE.index("if(have&&have.site)"):]
    assert after.index("return;") < after.index("load(chosen.league_id")


def test_only_ownership_is_re_pointed():
    """Snaps, carries and targets are properties of the NFL, not of anyone's
    league. If this ever starts rewriting them, the page is lying."""
    for cell in ("snap_share", "car_share", "tgt_share", "data-v"):
        assert cell not in MY_LEAGUE, f"the override touches {cell}"


@needs_built_site
def test_usage_rows_carry_the_player_id_the_override_needs():
    doc = (DOCS / "fantasy" / "usage" / "index.html").read_text()
    body = re.search(r"<tbody>(.*?)</tbody>", doc, re.S).group(1)
    rows = re.findall(r"<tr[^>]*>", body)
    assert rows, "no usage rows"
    assert all("data-pid=" in r for r in rows), "a row has no Sleeper id to match on"


# --------------------------------------------------------------------------- #
# "Your league this week" on the matchups page
# --------------------------------------------------------------------------- #

MY_MATCHUPS = (ROOT / "src" / "gordstats" / "my_matchups.py").read_text()


@needs_built_site
def test_the_files_the_browser_needs_are_built():
    """Both are fetched at view time, so a missing one is a silently empty
    scoreboard rather than a build error."""
    index = DOCS / "fantasy" / "players-index.json"
    proj = DOCS / "fantasy" / "week-projections.json"
    assert index.exists() and proj.exists()
    names = json.loads(index.read_text())
    week = json.loads(proj.read_text())
    assert len(names) > 500, "the player index looks truncated"
    # Name, position and team. The team is what gives a player with no
    # projection this week - a bench back on a bye - a logo and a game; it
    # was added third so the two existing readers keep their indexes.
    assert all(isinstance(v, list) and len(v) == 3 for v in names.values())
    assert any(v[2] for v in names.values()), "no player carries a team"

    assert len(week["proj"]) > 100, "the week projections look truncated"
    assert week["kick"], "no kickoffs, so no lineup can lock"
    # Three scoring bases and the player's team, in that order: a half-PPR
    # league reads the second number, and reading the wrong one is silent.
    for pid, row in list(week["proj"].items())[:50]:
        assert len(row) == 5, f"{pid} does not carry three bases, a team and a status"
        ppr, half, std, team, injury = row
        assert ppr >= half >= std, f"{pid}: the bases are out of order"


def test_projections_are_served_from_here_not_from_sleeper():
    """Sleeper answers a cross-origin request to its projections endpoint with
    every player mapped to an empty object - the stats are stripped - so the
    numbers have to come off our own build. If this ever points back at
    api.sleeper.app for projections, the page silently loses them."""
    assert "/fantasy/week-projections.json" in MY_MATCHUPS
    assert "api.sleeper.app/v1/projections" not in MY_MATCHUPS


def test_a_readers_league_does_not_borrow_this_leagues_numbers():
    """The built page's median tracker and four-source scoring come out of an
    archive that exists only for this league. The reader's view is rendered
    separately and the built one is hidden, rather than the two being mixed."""
    assert "mm-built" in MY_MATCHUPS and "built.hidden=true" in MY_MATCHUPS
    page = (ROOT / "src" / "fantasy" / "site" / "matchups.py").read_text()
    assert '<div id="mm-built">' in page


def test_the_matchups_page_and_the_usage_page_share_one_league():
    """Two controls that each remembered their own league would be a bug you
    only notice on the second page."""
    assert "gsSleeperLeague" in MY_MATCHUPS
    assert "gsSleeperLeague" in MY_LEAGUE


# --------------------------------------------------------------------------- #
# "Your team this week" on the dashboard
# --------------------------------------------------------------------------- #

MY_TEAM = (ROOT / "src" / "gordstats" / "my_team.py").read_text()


def test_the_reader_s_team_is_rendered_apart_from_the_built_one():
    """The built page's projections, defence-vs-position and weather are this
    league's sources for this league's players. Mixing a reader's roster into
    them would attribute numbers to players they were never computed for."""
    assert "mt-built" in MY_TEAM and "built.hidden=true" in MY_TEAM
    page = (ROOT / "src" / "fantasy" / "site" / "roster.py").read_text()
    assert '<div id="mt-built">' in page


def test_the_scoring_basis_comes_from_the_league_not_from_us():
    """This site plays PPR. A half-PPR league reading PPR numbers is wrong on
    every row and says nothing about it, which is the worst way to be wrong."""
    data = (ROOT / "src" / "gordstats" / "my_league_data.py").read_text()
    assert "scoring_settings" in data
    assert "['PPR','half-PPR','standard']" in data
    # And a league further off than that is told, rather than quietly rounded.
    assert "custom" in data and "custom" in MY_TEAM


def test_every_league_shares_one_stored_league():
    """Usage, matchups and the dashboard all read the same key - three pages
    each remembering their own league is a bug you meet on the second one."""
    for src in (MY_TEAM, MY_LEAGUE, MY_MATCHUPS):
        assert "gsSleeperLeague" in src or "GSL.saved()" in src


LEAGUE_PAGES = {
    "usage": "fantasy/usage/index.html",
    "matchups": "fantasy/matchups/index.html",
    "My Team": "fantasy/roster/index.html",
}


@pytest.mark.parametrize("name,path", sorted(LEAGUE_PAGES.items()))
@needs_built_site
def test_the_league_control_has_its_script_on_every_page(name, path):
    """The container and the behaviour are two separate things to wire, and
    wiring only the first leaves a control that renders nothing.

    That shipped: the dashboard had the bar and no script, so there was no way
    to choose a league from the page that most needed one. It only looked fine
    in testing because the league had been put into localStorage by hand.
    """
    doc = (DOCS / path).read_text()
    assert "ml-bar" in doc, f"{name} has no league control"
    assert "function restore()" in doc, f"{name} has the control but not its script"
    assert "SYNCED" in doc, f"{name} cannot offer a synced league"


@pytest.mark.parametrize("name,path", sorted(LEAGUE_PAGES.items()))
@needs_built_site
def test_a_reader_in_two_leagues_can_reach_both(name, path):
    """Picking the first synced league and ignoring the rest is invisible until
    somebody syncs a second one - which is the normal case for anyone in two."""
    doc = (DOCS / path).read_text()
    assert "ml-pick" in doc, f"{name} offers no way to switch between synced leagues"


# --------------------------------------------------------------------------- #
# The season being played
# --------------------------------------------------------------------------- #

def test_the_season_being_played_is_in_the_keyed_maps():
    """LEAGUE_IDS drives every per-season page. While the live season sat only
    in UPCOMING_*, the schedule, draft and waiver pages silently showed last
    season and nothing said so."""
    from fantasy.config import (DRAFT_IDS, FORMAL_SEASON, LEAGUE_IDS,
                                SEASON_YEAR, UPCOMING_LEAGUE_ID)
    from fantasy import util

    now = util.year_str()
    assert now in LEAGUE_IDS, f"{now} is being played but is not in LEAGUE_IDS"
    assert LEAGUE_IDS[now] == UPCOMING_LEAGUE_ID, "the two names disagree about the league"
    for name, m in (("DRAFT_IDS", DRAFT_IDS), ("FORMAL_SEASON", FORMAL_SEASON),
                    ("SEASON_YEAR", SEASON_YEAR)):
        assert now in m, f"{now} is missing from {name}"


def test_the_season_rolls_over_at_kickoff_not_in_october():
    """The old rule was `month > 9`, so through September - weeks one to four -
    the site believed it was still in last season. It also anchored the week
    count to the first Thursday of September rather than the Thursday after
    Labor Day, which in 2026 is a week out.
    """
    from datetime import date
    from fantasy import util

    assert util.opening_thursday(2026) == date(2026, 9, 10)
    assert util.opening_thursday(2025) == date(2025, 9, 4)
    assert util.opening_thursday(2024) == date(2024, 9, 5)


def test_every_keyed_season_has_its_data_file():
    """A season in LEAGUE_IDS without a season file is a page that raises."""
    from fantasy.config import LEAGUE_IDS
    for code in LEAGUE_IDS:
        assert (ROOT / "data" / "fantasy" / "season" / f"{code}.json").exists(), \
            f"no season file for {code}"


# --------------------------------------------------------------------------- #
# League history
# --------------------------------------------------------------------------- #

MY_HISTORY = (ROOT / "src" / "gordstats" / "my_history.py").read_text()


@needs_built_site
def test_history_reads_the_readers_league_not_this_one():
    doc = (DOCS / "fantasy" / "history" / "index.html").read_text()
    assert "hi-host" in doc and "previous_league_id" in doc, \
        "the history page does not walk the reader's own seasons"
    assert "ml-bar" in doc and "function restore()" in doc, \
        "the history page has no league control"


def test_managers_are_tracked_by_owner_not_by_team_name():
    """People rename their team most years - in this league 2023's "Matt" is
    later "padgett". Aggregating on the name would split one manager into
    several and hand out their titles twice."""
    assert "t.owner" in MY_HISTORY
    assert "owner_id" in MY_HISTORY


def test_the_champion_is_the_winner_of_the_placing_game():
    """Sleeper's bracket marks the championship game with p == 1. Taking the
    last round's winner instead picks up third-place games."""
    assert "m.p===1" in MY_HISTORY.replace(" ", "")


def test_a_season_still_being_played_has_no_champion():
    """The live season is in the chain and has no bracket; it must not crown
    anybody, and must not drop out of the season-by-season table either."""
    assert "championRoster=final?final.w:null" in MY_HISTORY.replace(" ", "")


def test_the_history_walk_is_bounded():
    """Same reason as the server's: these ids come from an API."""
    assert "MAX_SEASONS" in MY_HISTORY and "seen[lid]" in MY_HISTORY


# --------------------------------------------------------------------------- #
# Waivers and trades, and connecting a league
# --------------------------------------------------------------------------- #

MY_WAIVERS = (ROOT / "src" / "gordstats" / "my_waivers.py").read_text()


@needs_built_site
def test_waivers_reads_the_readers_league():
    doc = (DOCS / "fantasy" / "waivers" / "index.html").read_text()
    assert "wv-host" in doc and "previous_league_id" in doc
    assert "ml-bar" in doc and "function restore()" in doc, "no league control"


def test_failed_claims_are_kept():
    """Being outbid is half the story of a waiver wire. A log that silently
    drops failed claims makes every claim look uncontested."""
    assert "failed" in MY_WAIVERS
    assert "t.status!=='complete'" in MY_WAIVERS.replace(" ", "")


@needs_built_site
def test_defences_resolve_like_players():
    """Sleeper keys a defence by team code ("GB") where everyone else is a
    number, so a naive lookup prints "GB" in the log."""
    index = json.loads((DOCS / "fantasy" / "players-index.json").read_text())
    for code in ("GB", "SEA", "KC"):
        assert code in index, f"{code} defence missing from the player index"
        assert index[code][1] == "DEF"


def test_a_league_can_be_connected_without_leaving_the_page():
    """It used to mean finding the Analytics hub and then a settings page. The
    reader is already looking at a page that would show their league."""
    picker = (ROOT / "src" / "gordstats" / "my_league.py").read_text()
    assert "function connect(" in picker
    assert "/user/" in picker and "/leagues/nfl/" in picker
    # And it works signed out, so the account stays a convenience.
    assert "gsSleeperLeagues" in picker, "the found leagues are not kept locally"


MY_DRAFT = (ROOT / "src" / "gordstats" / "my_draft.py").read_text()


def test_draft_value_is_measured_against_results_not_our_adp():
    """This site's ADP is its own league's and says nothing about a stranger's,
    so a pick is set against where its player finished among everyone drafted -
    the same question, answered from results rather than somebody's market."""
    assert "_finish" in MY_DRAFT and "pick_no-p._finish" in MY_DRAFT.replace(" ", "")
    assert "adp" not in MY_DRAFT.lower().replace("this site’s adp", "") \
        or "not measured against ADP" in MY_DRAFT


def test_season_points_are_shipped_not_fetched_from_sleeper():
    """Sleeper's season endpoint is 2.3 MB a year; four seasons of drafts would
    be nine megabytes to find out how the picks did."""
    assert "/fantasy/season-points/" in MY_DRAFT
    assert "api.sleeper.app/v1/stats" not in MY_DRAFT
    points = DOCS / "fantasy" / "season-points"
    assert points.is_dir(), "no season points shipped"
    files = sorted(points.glob("*.json"))
    assert len(files) >= 4, f"only {len(files)} seasons of points"
    for f in files:
        rows = json.loads(f.read_text())
        assert len(rows) > 300, f"{f.name} looks truncated"
        ppr, half, std = next(iter(rows.values()))
        assert ppr >= half >= std, f"{f.name}: scoring bases out of order"


def test_draft_value_uses_the_leagues_own_scoring():
    """A half-PPR league reading PPR totals would rate every receiver wrong."""
    assert "state.basis" in MY_DRAFT and "basis.index" in MY_DRAFT


# --------------------------------------------------------------------------- #
# The profile page
# --------------------------------------------------------------------------- #

@needs_built_site
def test_the_profile_page_gathers_the_account_things():
    doc = (DOCS / "profile" / "index.html").read_text()
    for want in ("pf-who", "pf-favs", "ls-user-go"):
        assert want in doc, f"the profile page has no {want}"


@needs_built_site
def test_followed_teams_have_names_not_keys():
    """They are stored as sport:id, which is no use to read. The names come off
    the stars the rest of the site has already rendered."""
    index = json.loads((DOCS / "assets" / "favourite-teams.json").read_text())
    assert index, "no team-name index"
    total = sum(len(v) for v in index.values())
    assert total > 100, f"only {total} names indexed"
    assert "cfb" in index and index["cfb"].get("194")


def test_the_profile_page_does_not_own_the_favourites_list():
    """favorites.js holds the list in a variable, its storage event only fires
    for other documents, and its next push would put back anything removed
    behind its back. One owner, and everybody else asks it."""
    page = (ROOT / "src" / "gordstats" / "profile_page.py").read_text()
    assert "window.GSFavorites" in page
    js = (DOCS / "assets" / "js" / "favorites.js").read_text()
    assert "window.GSFavorites" in js, "favorites.js exposes no API to ask"


def test_two_leagues_named_the_same_are_never_the_same_entry():
    """An option list with the same words twice is a choice nobody can make."""
    picker = (ROOT / "src" / "gordstats" / "my_league.py").read_text()
    assert "function labelsFor(" in picker
    assert "team_name" in picker


@needs_built_site
def test_no_phone_rule_shrinks_text_below_the_floor():
    """This site is read standing in a car park, and the schedule page was
    actively shrinking its labels *further* on phones to fit more in - a tag
    from 10.5px down to 9.5px, form badges to 9.5px. That is the wrong trade on
    the device where reading is hardest, and it is the complaint this site
    started from.

    Only rules inside a phone media query are checked: a 10px label on a
    desktop table is fine, and several are deliberately raised for phones by a
    later query rather than changed outright.

    Swept in a browser at 390px afterwards: 41 pages, nothing under 10.5px and
    no horizontal scroll anywhere.
    """
    import re

    FLOOR = 10.5
    offenders = []
    for path in sorted(ROOT.joinpath("src").rglob("*.py")):
        text = path.read_text(errors="ignore")
        for block in re.finditer(r"@media\s*\(max-width:\s*([0-9]+)px\)\s*\{", text):
            if int(block.group(1)) > 700:
                continue                       # a tablet rule, not a phone one
            # The body of the query, to its matching brace.
            depth, i = 1, block.end()
            while i < len(text) and depth:
                depth += (text[i] == "{") - (text[i] == "}")
                i += 1
            body = text[block.end():i]
            for rule in re.finditer(r"([^{};\n]+)\{([^}]*)\}", body):
                for size in re.findall(r"font-size:\s*([0-9.]+)px", rule.group(2)):
                    if float(size) < FLOOR:
                        sel = " ".join(rule.group(1).split())[-40:]
                        offenders.append(f"{path.name}: {sel} -> {size}px")
    assert not offenders, (
        "phone rules below the floor:\n  " + "\n  ".join(sorted(offenders)))
