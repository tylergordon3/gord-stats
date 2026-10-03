"""
Power rankings for whichever league the reader has picked (/fantasy/power/).

The page beside this one ranks *this* site's league by playing its season ten
thousand times (`fantasy.league.power`). Doing the same for a reader's league
has to happen in the browser, because the rosters, the slots and the rules only
exist at Sleeper. So the simulation is ported here, and the numbers it draws
from are fetched: `fantasy.site.season_board` publishes the projection board,
which is the one part no browser could ever compute.

What the port has to add, and the built page never needed, is that every league
is different:

  * **Scoring.** The board is PPR, because this league plays PPR. The only
    difference between Sleeper's three bases is what a catch is worth, so the
    board ships each player's catch rate and half-PPR is `mu - rec/2`,
    standard `mu - rec`. `sd` and `mu_se` are scaled by the same ratio: a
    receiver's week-to-week swing comes partly from his catches, so a standard
    league's scores vary less as well as averaging less, and holding the
    coefficient of variation is closer than holding the spread.

  * **Slots.** The built page hardcodes QB/RB/RB/WR/WR/TE/FLEX/FLEX/K/DEF.
    Sleeper leagues have superflex, two kinds of half-flex, three receivers.
    So slots are filled narrowest-first from `roster_positions`, which is the
    order that does not strand an eligible player: a flex can take what a
    dedicated slot cannot, so it must choose after it.

  * **The bracket.** Six teams over three weeks with two byes is this league.
    The bracket here is built for whatever `playoff_teams` says, seeded the
    standard way, with byes for the top seeds when the field is not a power of
    two, and redrawn each round (best seed left against worst left) where
    `playoff_seed_type` says the league reseeds - this one does. Once the
    regular season is in, the playoff weeks played and the rounds Sleeper's
    winners bracket has decided are taken as they happened.

  * **The median win.** This league awards one every week and most do not.
    It is `settings.league_average_match`, and quietly assuming it doubles
    everybody's projected record.

One thing the port deliberately leaves out: the published page's headline
Rating is our simulation averaged with the FantasyPros League Analyzer, and
that is keyed to this league specifically. A reader's league has no such key,
so this shows the simulation alone - and says so, rather than printing a
smaller number beside a bigger one with no explanation.

The fast part of the port is an accident worth keeping: the lineup a manager
sets is chosen on *projection*, never on the scores about to happen, and the
projection does not change during a season. So each team's starting order at
each slot is fixed before the first simulated week, and the inner loop is a
walk rather than a sort. Ten thousand seasons of a twelve-team league run in
under three seconds.
"""
from gordstats import js_assets


CSS = """<style>
.mp{margin:8px 0 22px}
.mp h2{margin:18px 0 6px;font-size:18px}
.mp-note{font-size:12.5px;color:#64748b;margin:8px 0 10px;line-height:1.5}
.mp-none{font-size:14px;color:#475569}
.mp-load{font-size:13px;color:#64748b}
.mp-warn{font-size:12.5px;color:#92400e;background:#fffbeb;border:1px solid #fde68a;
  border-radius:8px;padding:8px 11px;margin:0 0 12px;line-height:1.5}
/* The table itself is the site's `sticky-table pw-table` inside
   `.table-scroll`, the classes the built ranking beside it wears - a reader's
   league should not be a second look. Its rules are restated here rather
   than borrowed from the <style> inside #pw-built (fantasy.site.power
   _TABLE_CSS and styles.GRID_*): --heat is how strong the shading's ends get
   per theme, the grid and centring are pandas', and on a phone each column
   takes what its header needs, so Record, Playoffs and Title sit beside the
   name at 390px. */
.mp .pw-table{--heat:.35;font-size:14px}
.mp .pw-table td{border:1px solid #eef2f7;text-align:center}
.mp .pw-table th{text-align:center}
.mp .pw-table td:first-child,.mp .pw-table th:first-child{text-align:left}
@media (max-width:600px){
  .mp .pw-table th,.mp .pw-table td{min-width:0;padding:6px 7px}
  .mp .pw-table td:first-child,.mp .pw-table th:first-child{min-width:0;max-width:122px}
  .mp .pw-table .row-rank{min-width:1.5em;font-size:12px}
}
@media (prefers-color-scheme: dark){
  .mp .pw-table{--heat:.6}
  .mp-note,.mp-none,.mp-load{color:#aab7c9}
  .mp-warn{color:#fcd34d;background:#2a2410;border-color:#4a3c13}
}
</style>"""


# The simulation itself, kept apart from the page so it can be run against the
# Python it was ported from without a page around it.
# The code is docs/assets/js/gs-power-sim.js (gordstats.js_assets): SIM_JS is it inline,
# for the browser tests; SIM_JS_TAG is what the pages carry.
SIM_JS = js_assets.inline("gs-power-sim.js", attrs=' id="gs-power-sim"')
SIM_JS_TAG = js_assets.tag("gs-power-sim.js", attrs=' id="gs-power-sim"')


# Reading a league into the simulation's terms, and running it off the main
# thread: shared by the reader's power table and the trade page (gordstats.
# trade_page), which runs one league twice.
# The code is docs/assets/js/gs-power-league.js (gordstats.js_assets): LEAGUE_JS is it inline,
# for the browser tests; LEAGUE_JS_TAG is what the pages carry.
LEAGUE_JS = js_assets.inline("gs-power-league.js")
LEAGUE_JS_TAG = js_assets.tag("gs-power-league.js")


# The page script needs the shared loader first; a page that carries the
# trade analyzer as well defines it twice, harmlessly.
# The code is docs/assets/js/gs-power.js (gordstats.js_assets): JS is it inline,
# for the browser tests; JS_TAG is what the pages carry.
JS = LEAGUE_JS + js_assets.inline("gs-power.js")
JS_TAG = LEAGUE_JS_TAG + js_assets.tag("gs-power.js")


def section(year: int = 0) -> str:
    """The host the script fills. `year` is the season the page ranks
    (fantasy UPCOMING_YEAR): a reader's league saved in another season says
    so instead of being simulated on this season's board."""
    attr = f" data-year='{int(year)}'" if year else ""
    return CSS + f"<div class='mp' id='mp-host'{attr}></div>"
