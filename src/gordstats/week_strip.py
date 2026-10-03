"""
"This week" at the top of League Home: every matchup with its score, and the
standings.

League Home was all history - all-time metrics and the team profiles - so the
page a manager opens on a Sunday said nothing about the Sunday. This puts the
week first. It is drawn in the browser from Sleeper for whichever league is on
screen - this site's own is a Sleeper league too - so the built page and a
reader's league get the same strip, from the same code, with live points:

  * every matchup of the week, the reader's own first; Sleeper's projected
    totals before kickoff (the league's scoring basis, from the week's
    projection file), points once games are on, marked live or final by the
    kickoffs of the starters involved;
  * the standings - Sleeper's records, which in a league playing the median
    count two results a week - with points for, the reader's team marked.

It polls once a minute only while a game is on, and never on a hidden tab.
"""
from gordstats import js_assets

CSS = """<style>
.ws{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(0,1fr);gap:14px;margin:12px 0 22px}
@media (max-width:760px){.ws{grid-template-columns:minmax(0,1fr)}}
/* In season the card's height is held until it draws: drawn into an empty div,
   it pushed League Home down 432px a moment after it painted (Cloudflare's
   layout-shift score 0.31 there, 2026-10-02). The script drops the hold
   whichever way it finishes, so the offseason leaves no gap. */
.ws-wait:empty{min-height:432px}
@media (max-width:760px){.ws-wait:empty{min-height:1000px}}
.ws-card{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:12px 14px;min-width:0}
.ws-head{display:flex;align-items:baseline;justify-content:space-between;gap:8px;margin:0 0 8px}
.ws-head h2{margin:0;font-size:17px;border:0;padding:0}
.ws-head a{font-size:13px;font-weight:700;white-space:nowrap}
.ws-sub{font-size:12px;color:#64748b}
/* A matchup: side by side on a wide screen (name, score - score, name,
   the state under the scores); on a phone one team a line, so the names
   keep their width, with the state on the right. */
.ws-mu{display:grid;grid-template-columns:minmax(0,1fr) auto auto auto minmax(0,1fr);
  grid-template-areas:"a pa dash pb b" ". st st st .";align-items:center;column-gap:8px;
  padding:7px 6px;border-top:1px solid #eef2f7;text-decoration:none;color:inherit;border-radius:8px}
.ws-mu .a{grid-area:a}.ws-mu .b{grid-area:b}.ws-mu .pa{grid-area:pa;text-align:right}
.ws-mu .pb{grid-area:pb}.ws-mu .dash{grid-area:dash;color:#64748b}.ws-mu .st{grid-area:st;text-align:center}
@media (max-width:600px){
  .ws-mu{grid-template-columns:minmax(0,1fr) auto auto;grid-template-areas:"a pa st" "b pb st";
    row-gap:4px}
  .ws-mu .dash{display:none}
  .ws-mu .pb{text-align:right}
  .ws-mu .ws-side.r{flex-direction:row;text-align:left}
  .ws-mu .st{text-align:right;min-width:62px}
}
.ws-mu:first-of-type{border-top:0}
.ws-mu.me{background:#f0fdf4;box-shadow:inset 3px 0 0 #1a7f4b}
.ws-side{display:flex;align-items:center;gap:7px;min-width:0}
.ws-side.r{flex-direction:row-reverse;text-align:right}
.ws-side img{width:24px;height:24px;border-radius:50%;flex:none;border:0;padding:0;box-shadow:none;
  background:none;object-fit:cover}
.ws-nm{font-size:13.5px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ws-mu b{font-size:15px;font-variant-numeric:tabular-nums;white-space:nowrap}
.ws-mu b.lead{color:#1a7f4b}
.ws-mu b.proj{color:#64748b;font-weight:600;font-style:italic}
.ws-mu small{font-size:10.5px;color:#64748b;text-transform:uppercase;letter-spacing:.04em;white-space:nowrap}
.ws-mu small.live{color:#b3382c;font-weight:700}
table.ws-st{width:100%;border-collapse:collapse;font-size:13px}
table.ws-st th{font-size:11px;text-transform:uppercase;letter-spacing:.03em;color:#64748b;
  text-align:right;padding:4px 6px;border-bottom:1px solid #e2e8f0;background:transparent}
table.ws-st th:nth-child(2){text-align:left}
table.ws-st td{padding:5px 6px;border-bottom:1px solid #eef2f7;text-align:right;
  font-variant-numeric:tabular-nums;background:transparent;color:inherit}
table.ws-st td.t{text-align:left;max-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  font-weight:600;width:60%}
table.ws-st td.rk{color:#64748b;width:1%}
table.ws-st tr.me td{background:#f0fdf4}
.ws-load{font-size:13px;color:#64748b}
@media (prefers-color-scheme: dark){
  .ws-card{background:#16203a;border-color:#2b3852}
  .ws-sub,.ws-mu small,.ws-mu .dash,.ws-load,table.ws-st th,table.ws-st td.rk{color:#aab7c9}
  .ws-mu{border-top-color:#2b3852}
  .ws-mu.me{background:#123c2e;box-shadow:inset 3px 0 0 #6ee7b7}
  .ws-mu b.lead{color:#8ff0bd}
  .ws-mu b.proj{color:#aab7c9}
  .ws-mu small.live{color:#ffb4ab}
  table.ws-st th{border-bottom-color:#2b3852}
  table.ws-st td{border-bottom-color:#2b3852}
  table.ws-st tr.me td{background:#123c2e}
}
</style>"""


def _site_league() -> str:
    from fantasy.config import UPCOMING_LEAGUE_ID
    return str(UPCOMING_LEAGUE_ID)


# The code is docs/assets/js/gs-week-strip.js (gordstats.js_assets): JS is it inline,
# for the browser tests; JS_TAG is what the pages carry.
# This site's league reaches it through GSCFG.
_CFG = {"siteLeague": _site_league()}
JS = js_assets.inline("gs-week-strip.js", _CFG)
JS_TAG = js_assets.tag("gs-week-strip.js", _CFG)


def section(today=None) -> str:
    """The container the script fills; empty in the offseason. From September
    to mid-February (the NFL season, fantasy playoffs and all) it holds the
    card's height while the script draws it."""
    from datetime import date
    today = today or date.today()
    held = today.month in (9, 10, 11, 12, 1) or (today.month == 2 and today.day <= 15)
    return CSS + ("<div id='ws-host' class='ws-wait'></div>" if held else "<div id='ws-host'></div>")
