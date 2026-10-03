"""
One door to a reader's league, whichever site it lives on: `window.GSAPI`.

Every page that shows a reader's own league was written against Sleeper, and
asks Sleeper's questions in Sleeper's words - `/league/<id>/rosters`,
`/league/<id>/matchups/4`, `/draft/<id>/picks`. `GSAPI.get(path)` takes those
same paths. A Sleeper league goes straight to Sleeper, as it always did; an
ESPN league is read from ESPN's fantasy API and answered in Sleeper's shapes,
so no page has to know which site the league is on.

An ESPN league's id here is `espn:<season>:<league id>` - ESPN keeps one id
for a league across seasons where Sleeper issues a new one each year, so the
season is carried in the id and "the season before" is the same league id a
year earlier. That keeps every page's one-id-per-season assumptions true.

**Public leagues only.** ESPN answers a league its commissioner has set
viewable to the public and refuses the rest (401). Requests go out with
`credentials: 'omit'`, so a reader who happens to be signed in to ESPN in the
same browser is never read with that session: nothing here ever acts as
anybody's ESPN account, and nothing is stored but the id.

What is fetched, and why it is split (sizes from a real league, uncompressed;
ESPN gzips them to about a tenth):

    base      mSettings mTeam mStatus      ~30 KB   league, users, records
    rosters   + mRoster                    ~100 KB a team - every player's
                                           stats ride along, so only asked
                                           for a season still being played
    schedule  mMatchupScore                ~40 KB   every week's scores and
                                           pairings: history, brackets, power
    week      mMatchupScore mScoreboard    lineups and player points for one
              + scoringPeriodId            week, one request a week: last
                                           week, this week and next always (a
                                           live page polls them); any other
                                           week played only for a caller that
                                           asks, `get(path, {lineups: true})`
                                           - the recap, which judges every
                                           week's lineup. History and power
                                           want scores and pairings alone,
                                           which the one schedule request has
                                           for every week at once
    draft     mDraftDetail;  transactions  mTransactions2 + scoringPeriodId

An ESPN week read with its lineups also says who sat on injured reserve that
week (`reserve` on each row, which Sleeper's rows do not carry).

GSAPI.teams(id) is a league's team names by roster id, for a page that wants
nothing else of the rosters: ESPN's come from the base request.

Every answer is kept for the page view, so the league, its rosters and users,
asked by the bar, the page and the planner in turn, are fetched once; a second
ask while the first is still on its way shares it. What changes while a page
is open is kept briefly instead - Sleeper's matchups and transactions for 30
seconds, ESPN's weeks around this one for 45 - so a live page's poll still
reads new points. A failure is never kept: the next ask tries again. Each
caller gets its own copy of a Sleeper answer, as it did when each ask was a
fetch.

Players: ESPN ids become Sleeper ids through /fantasy/espn-ids.json (written
by fantasy.site.players_index from the player registry), then by name and
position against the player index; a defence is its team code, as on
Sleeper. A player neither can place keeps an `e<espn id>` id and the name
ESPN gave, added to the shared player index so the pages can still name the player.
"""
from gordstats import js_assets

# The code is docs/assets/js/gs-league-api.js (gordstats.js_assets): JS is it inline,
# for the browser tests; JS_TAG is what the pages carry. ESPN's team and
# position codes are written into the file - they are ESPN's, the same on every
# page and in every season - and tests/test_shared_js_assets.py holds them equal
# to fantasy.league.ext_projections' ESPN_TEAMS and ESPN_POSITIONS.
JS = js_assets.inline("gs-league-api.js")
JS_TAG = js_assets.tag("gs-league-api.js")

