"""
"Your league this week" on the NFL matchups page.

The built page is this league's: its scoreboard, its median tracker, its four
projection sources scored against each other, all of it out of an archive the
Pi writes. None of that exists for someone else's league, and pretending
otherwise would mean rebuilding the archive per reader.

What does exist, keyless and CORS-open, is Sleeper's own view of any league:
who plays whom this week, both full rosters, and every player's points as they
land. So the reader's league is rendered *in the built page's own layout* -
the scoreboard, then a section per matchup with the two-column header, the win
bar, the paired phone view and the two roster tables - because a reader
looking at his own league should be reading the same page, not a plainer one
beside it.

Names come from /fantasy/players-index.json and the week's numbers from
/fantasy/week-context.json and /fantasy/week-projections.json, all written by
the build; `gordstats.my_week` holds the cells, so a row here is the row the
built page emits.

Three honest differences from the built league, all of them stated on the
page rather than papered over:

  * **Two projection columns, not four.** This site collects ESPN's and
    FantasyPros' weekly numbers for its own league's rosters only, so a
    reader gets GordStats and Sleeper. The blend the Pts cell runs on is the
    mean of what exists, which is the built page's rule with fewer inputs.
  * **The win bars' spread is the fallback one.** The built bars read each
    player's week-to-week standard deviation off the projection board, which
    is not published; every player here takes the share-of-projection
    fallback the built page uses for a player it has no figure for.
  * **No best-lineup swap line.** It needs kickoffs and lock rules that the
    reader's own dashboard (/fantasy/roster/) already does properly, and
    guessing at the opponent's lineup is not worth a wrong answer.
"""

from html import escape

from gordstats import js_assets

CSS = """<style>
.mm{margin:10px 0 18px}
.mm-head{display:flex;flex-wrap:wrap;gap:9px;align-items:baseline;margin:0 0 10px}
.mm-head h2{margin:0;font-size:18px}
.mm-note{font-size:12.5px;color:#64748b;margin:0 0 11px;line-height:1.5}
/* The reader's own matchup is first and says so - on the scoreboard, on the
   phone card and on the section itself. Every other matchup in the league is
   worth reading; this is the one they came for. */
.mm-tag{font-size:10.5px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;
  color:#1a7f4b;background:#d5efdd;border-radius:999px;padding:1px 7px;margin-left:8px;
  vertical-align:1px}
tr.mm-yours td{box-shadow:inset 0 2px 0 #1a7f4b,inset 0 -2px 0 #1a7f4b}
tr.mm-yours td:first-child{box-shadow:inset 4px 0 0 #1a7f4b,inset 0 2px 0 #1a7f4b,
  inset 0 -2px 0 #1a7f4b}
a.mu-card.mm-yours{border-color:#1a7f4b;box-shadow:inset 3px 0 0 #1a7f4b}
details.section.mm-yours>summary{color:#1a7f4b}
@media (prefers-color-scheme: dark){
  .mm-note{color:#8fa0b8}
  .mm-tag{color:#8ff0bd;background:#123c2e}
  tr.mm-yours td{box-shadow:inset 0 2px 0 #6ee7b7,inset 0 -2px 0 #6ee7b7}
  tr.mm-yours td:first-child{box-shadow:inset 4px 0 0 #6ee7b7,inset 0 2px 0 #6ee7b7,
    inset 0 -2px 0 #6ee7b7}
  a.mu-card.mm-yours{border-color:#6ee7b7;box-shadow:inset 3px 0 0 #6ee7b7}
  details.section.mm-yours>summary{color:#8ff0bd}
}
</style>"""

# The code is docs/assets/js/gs-matchups.js (gordstats.js_assets): JS is it inline,
# for the browser tests; JS_TAG is what the pages carry.
JS = js_assets.inline("gs-matchups.js")
JS_TAG = js_assets.tag("gs-matchups.js")


def section(week: int, year: int, scoreboard: str = "") -> str:
    """The container the script fills, and the note explaining what it is.
    `scoreboard` is ESPN's for the week, which the live poll reads clocks from."""
    espn = f" data-espn='{escape(scoreboard, quote=True)}'" if scoreboard else ""
    return (CSS + f"<div class='mm' id='mm-wrap'>"
            f"<div class='mm-head' id='mm-bar'></div>"
            f"<div id='mm-host' data-week='{int(week)}' data-year='{int(year)}'{espn}></div>"
            "</div>")
