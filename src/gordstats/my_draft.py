"""
Draft analytics for whichever league the reader has picked
(/fantasy/draft-review/).

The board is free: Sleeper's picks carry the player's name, position and team
inline, so no lookup is needed to draw who took whom.

What a pick was *worth* is the harder half, and it is answered here without
ADP. This site's ADP is its own league's and means nothing for a stranger's,
so instead each pick is set against what it returned: every drafted player is
ranked by the points he actually scored that season, and a pick taken 40th
whose player finished 12th among those drafted is +28. That is the same
question "value against ADP" asks - did this cost less than it gave back -
answered from results rather than from somebody else's market.

Season totals come from /fantasy/season-points/<year>.json, written by
fantasy.site.players_index: Sleeper's own season endpoint is 2.3 MB a year,
and a reader looking at four drafts should not pull nine megabytes to find out
how they did.
"""
from gordstats import js_assets


CSS = """<style>
.dr{margin:8px 0 20px}
.dr h2{margin:20px 0 6px;font-size:18px}
.dr-note{font-size:12.5px;color:#64748b;margin:0 0 10px;line-height:1.5}
.dr-none{font-size:14px;color:#475569}
.dr-bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:0 0 10px;
  font-size:13px;color:#475569}
.dr-bar select{font:inherit;font-size:13px;padding:5px 9px;border:1px solid #cbd5e1;
  border-radius:8px;min-height:40px}
.dr-up{color:#15803d;font-weight:700}
.dr-down{color:#b91c1c;font-weight:700}
.dr-pos{font-size:11.5px;color:var(--gs-muted,#5d6b7e);font-weight:700;margin-left:4px}
table.dr-b{border-collapse:collapse;font-size:13px;width:100%}
table.dr-b th{background:#eef2f7;color:#334155;padding:4px 6px;font-size:11.5px;
  text-transform:uppercase;letter-spacing:.03em;border:1px solid #e2e8f0;
  white-space:nowrap;text-align:left}
table.dr-b th.rd{position:sticky;left:0;z-index:1}
table.dr-b td{padding:4px 6px;border:1px solid #eef2f7;background:#fff;
  color:#0f172a;white-space:nowrap}
/* A pick is name, position and what it returned. Only the name gives way in
   a narrow column - the +/- is the point of the board, so it is never the
   part an ellipsis eats. */
.dr-cell{display:flex;align-items:baseline;max-width:150px}
.dr-cell .dr-nm{min-width:0;overflow:hidden;text-overflow:ellipsis}
.dr-cell .dr-pos,.dr-cell .dr-v{flex:none}
/* A manager's whole team name, on two lines at most, rather than its first
   fourteen letters ("STRICTLY DICKL"). */
.dr-h{display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden;
  white-space:normal;max-width:150px}
table.dr-b td.rd{position:sticky;left:0;background:#eef2f7;font-weight:800;z-index:1}
.dr-nm{font-weight:600}
.dr-v{font-variant-numeric:tabular-nums;font-size:11.5px;margin-left:4px}
@media (prefers-color-scheme: dark){
  .dr-note,.dr-none,.dr-bar{color:#aab7c9}
  .dr-up{color:#6ee7b7}
  .dr-down{color:#ff9b91}
  .dr-bar select{background:#16203a;border-color:#2b3852;color:#dde5ef}
  /* The draft board is its own table - too many narrow columns for the
     site's - and its dark rules used to share a selector with the summary
     table that has now become a `sticky-table`. */
  table.dr-b th,table.dr-b td.rd{background:#223052;color:#dde5ef;
    border-color:#2b3852}
  table.dr-b td{background:#16203a;border-color:#2b3852;color:#dde5ef}
}
/* The tables are the site's `sticky-table` inside `.table-scroll` - the pair
   every built table on these pages uses. This section now sits beside them on
   League Home and Analytics, and two table styles on one page reads as two
   different features. `.n` stays: it right-aligns the figures these tables
   put in text columns. */
table.sticky-table td.n{text-align:right;font-variant-numeric:tabular-nums}
table.sticky-table tr.me td{background:#fffbeb}
@media (prefers-color-scheme: dark){
  table.sticky-table tr.me td{background:#33301a}
}
</style>"""


def section() -> str:
    return CSS + "<div class='dr' id='dr-host'></div>"


def _site_league() -> str:
    from fantasy.config import UPCOMING_LEAGUE_ID
    return str(UPCOMING_LEAGUE_ID)


# The code is docs/assets/js/gs-draft.js (gordstats.js_assets): JS is it inline,
# for the browser tests; JS_TAG is what the pages carry.
# This site's league reaches it through GSCFG.
_CFG = {"siteLeague": _site_league()}
JS = js_assets.inline("gs-draft.js", _CFG)
JS_TAG = js_assets.tag("gs-draft.js", _CFG)
