"""
The weekly recap for whichever league the reader has picked (/fantasy/recap/).

The built recap (gordstats.recap, over fantasy.site.recap's week archive) is
this site's league. A reader's league has no archive, but a recap needs very
little that Sleeper will not hand a browser: a week's matchup rows carry every
rostered player's points and who started in which slot, and the league carries
its slots. So the week is put together here, the awards and lineup accuracy
are the built page's own rules ported to JavaScript, and it is drawn in the
built page's markup and stylesheet (gordstats.recap.CSS) - a reader looking at
his own league should be reading the same page.

What is read, and when:

    the week     the league, its rosters and users, that week's matchups and
                 the player index (names and positions) - drawn from these
    the season   every earlier week's matchups, and the transactions of this
                 week and the one before (for the pickup award), read once
                 the week is on screen; the season columns fill in after

Everything read is kept for the page view, so moving between weeks costs a
request only for a week not yet seen.

An ESPN league goes through GSAPI like any other: each week is asked for with
its lineups (`{lineups: true}` - GSAPI otherwise has them for this week and
last only), and ESPN's rows say who sat on injured reserve that week. Its team
names come from GSAPI.teams, because ESPN's rosters carry every player's
stats and nothing here needs them.

The best lineup is `GSPlan` (gordstats.my_team's port of lineup.plan) run on
the points each player actually scored, with the league's own slots - every
flex it has, not only FLEX. Two ports are two chances to drift, so
tests/test_my_recap.py compares the awards, headline, season table and markup
with the Python over the same weeks, and runs the best lineup over the
committed NFL weeks, where it must reproduce Sleeper's own "max points".

What the browser cannot have, and so is not here:

  * Beat / Missed the projection. They set a score against GordStats'
    projection as it stood before kickoff, which is archived for this site's
    league's rosters only (fantasy.pregame). Today's projection for a past
    week would be hindsight.
  * Power riser / faller. A move is read off this site's power-rankings
    history, which exists for its own league only; the reader's power page
    (gordstats.my_power) simulates now and keeps nothing.
  * Who was on injured reserve in a past week, on Sleeper: its matchup rows
    do not say, and the roster says who is on it now. So a player on it now is
    left out of a past week's best lineup only if he scored nothing that week
    - one who scored was plainly playing. ESPN's lineups say, week by week.
  * A position for a player the index does not carry (defensive players,
    mostly). One who started is held where he started, so the rest of the
    lineup is still judged; one on the bench cannot be placed at all.
"""

from gordstats import js_assets, recap, share_button

CSS = """<style>
/* The rest is the built recap's own (gordstats.recap.CSS): only what the
   reader's version adds is here, and scoped to it, so the built page beside
   it looks as it always did. */
/* Their own team: an edge and a heavier name. A tag beside the name cost it
   half the room a phone gives the column, and "Charlie's" read "Charl...". */
.rc-acc tr.rc-me td:first-child{box-shadow:inset 3px 0 0 #1a7f4b}
.rc-acc tr.rc-me .tmw span{font-weight:800}
.rc-acc td.rc-wait{color:#5d6b7e}
.rc-src{margin-top:14px}
/* A league with no pictures at all (every ESPN league) is a column of blank
   discs otherwise. */
#rc-host.rc-noav .rc-av{display:none}
/* A team without a picture, beside teams with one: its initial on the disc,
   as Sleeper draws a missing avatar - a blank disc read as a hole, most of
   all in dark mode. The page puts the letter in (initials()). */
#rc-host span.rc-av{display:inline-flex;align-items:center;justify-content:center;
  font-size:11px;font-weight:800;line-height:1;color:#475569;background:#e2e8f0}
@media (prefers-color-scheme: dark){
  #rc-host .rc-av{background:#2b3852}
  #rc-host span.rc-av{background:#334363;color:#dde5ef}
  .rc-acc tr.rc-me td:first-child{box-shadow:inset 3px 0 0 #6ee7b7}
  .rc-acc td.rc-wait{color:#94a3b8}
}
</style>"""


# The recap itself, with no page around it: the Python's rules and markup,
# kept close enough to gordstats.recap to be read side by side, and apart
# from the page so the tests can run it against the Python.
# The code is docs/assets/js/gs-recap.js (gordstats.js_assets): CORE_JS is it inline,
# for the browser tests; CORE_JS_TAG is what the pages carry.
CORE_JS = js_assets.inline("gs-recap.js")
CORE_JS_TAG = js_assets.tag("gs-recap.js")


# The code is docs/assets/js/gs-recap-view.js (gordstats.js_assets): JS is it inline,
# for the browser tests; JS_TAG is what the pages carry.
_CFG = {"recapShare": share_button.row("", "", league=True)}
JS = js_assets.inline("gs-recap-view.js", _CFG)
JS_TAG = js_assets.tag("gs-recap-view.js", _CFG)


def section(week: int = 0, css: bool = True) -> str:
    """The container the script fills. `week` is the week this address is
    for, which the reader's league opens on too (0: its latest); `css` is
    False where the built recap beside it already carries recap.CSS."""
    return ((recap.CSS if css else "") + CSS
            + f"<div class='rc' id='rc-host' data-week='{int(week)}'></div>")
