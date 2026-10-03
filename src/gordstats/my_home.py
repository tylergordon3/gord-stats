"""
League Home for whichever league the reader has picked, in the built page's
own format.

The built League Home is two things: All-Time Metrics (record, points, strength
of schedule and of victory, expected wins) and a profile per manager (the two
books, rival, nemesis and favourite, every game by margin, every opponent,
season by season) - fantasy.site.homepage and fantasy.site.team_profiles, out
of this league's archive. A reader's league used to get something else
entirely: champions, a table per season, an all-time table and a
head-to-head grid, one after another - longer, plainer, and a different page
from the one everybody else was looking at.

Everything the built page computes is there in Sleeper's history - every
season through `previous_league_id`, every week's matchups, the winners
bracket - and gordstats.my_history already reads it (window.GSHist). So this
draws the built page's two sections from it, with the built page's markup
(team_profiles.CSS applies to both) and the built page's arithmetic:

  * Record, PF and PA are Sleeper's season records summed - a league playing a
    weekly median counts two results a week, as the built table does.
  * SOS is (2 x opponents' win % + opponents' opponents' win %) / 3 over every
    regular-season meeting; SOV the win % of the opponents beaten; Exp W the
    Pythagorean share of the head-to-head games (constant EXPW_RATIO), with
    the actual head-to-head wins in brackets.
  * Profiles are team_profiles.profile, rule for rule: regular season is head
    to head only, playoffs are winners-bracket games, a nemesis needs three
    meetings.

The full history (champions, season tables, the head-to-head grid) and the
drafts keep pages of their own, linked underneath.
"""
from fantasy.config import EXPW_RATIO
from gordstats import js_assets

CSS = """<style>
#lh-mine table.sticky-table td.n{text-align:right;font-variant-numeric:tabular-nums}
#lh-mine .mh-load{font-size:12.5px;color:#64748b}
@media (prefers-color-scheme: dark){ #lh-mine .mh-load{color:#aab7c9} }
</style>"""

# The code is docs/assets/js/gs-home.js (gordstats.js_assets): JS is it inline,
# for the browser tests; JS_TAG is what the pages carry.
_CFG = {"expwRatio": EXPW_RATIO}
JS = js_assets.inline("gs-home.js", _CFG)
JS_TAG = js_assets.tag("gs-home.js", _CFG)


def section(nav: str, links: str) -> str:
    """The two built sections, filled in the browser, and the links to the
    pages the rest of a league's history lives on."""
    return (CSS + nav
            + '<h2 id="mh-metrics-h">All-Time Metrics</h2><div id="mh-metrics"></div>'
            + '<h2 id="mh-teams-h">Teams</h2><div id="mh-teams"></div>' + links)
