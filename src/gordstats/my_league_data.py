"""
Shared browser-side loading for "your own league": the player index, this
week's projections, and the scoring basis a league actually plays.

Both the matchups view and the team dashboard need the same three things, and
they must agree about them - a lineup recommended on PPR numbers beside a
scoreboard totalled on half-PPR would be its own bug. So it lives here once and
hangs off `window.GSL`.

The scoring basis is the part worth stating. This site plays PPR, and every
projection it publishes is PPR. Sleeper prices each player under PPR, half-PPR
and standard, so those three leagues are exact; `scoring_settings.rec` says
which. Anything further from the default - six-point passing touchdowns,
reception bonuses - is approximated by the nearest of the three, and the page
says so rather than quietly being wrong.
"""
from gordstats import js_assets

# The code is docs/assets/js/gs-league-data.js (gordstats.js_assets): JS is it inline,
# for the browser tests; JS_TAG is what the pages carry.
JS = js_assets.inline("gs-league-data.js")
JS_TAG = js_assets.tag("gs-league-data.js")
