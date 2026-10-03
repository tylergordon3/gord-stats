"""
The built pages' table cells, in the browser, for a reader's own league.

/fantasy/roster/ and /fantasy/matchups/ render this site's league on the Pi,
where the whole of `fantasy.site.roster.Week` is available: every projection,
every line, every forecast, and how each defence has been treating the
position. A reader's league is rendered at view time from Sleeper, which has
none of that, so those tables were four columns beside the built twelve - the
same information, laid out as if it were a different feature.

`fantasy.site.week_context` publishes the numbers; this holds the cells, so
there is one description of what a row looks like rather than a Python one and
a drifting JavaScript one. The classes are the built page's own (`rd-*`,
`mu-*`), which are already in the stylesheet on these pages - so matching the
format is a matter of emitting the same markup, not restyling anything.

Two honest differences from the built page, both stated on the page rather
than papered over:

  * **Proj** is the mean of the sources that have the player. This site
    collects ESPN's and FantasyPros' weekly numbers only for its own league's
    rosters, so for somebody else's league that mean is over GordStats and
    Sleeper. `roster.Week.blend` already averages whatever it has; the rule is
    the same, the inputs are fewer.
  * A **defence** with no finished week to rate yet shows a dash, exactly as
    the built page does.
"""
from gordstats import js_assets, logos

# The code is docs/assets/js/gs-week.js (gordstats.js_assets): JS is it inline,
# for the browser tests; JS_TAG is what the pages carry.
_CFG = {"nflLogo": logos.url("nfl", "{abbr}")}
JS = js_assets.inline("gs-week.js", _CFG)
JS_TAG = js_assets.tag("gs-week.js", _CFG)
