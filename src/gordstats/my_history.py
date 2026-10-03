"""
League history for whichever league the reader has picked (/fantasy/history/).

Everything here comes from Sleeper, keylessly, in the browser: a league's
seasons chain backwards through `previous_league_id`, and each season gives up
its final records (one call), its champion (one call at the winners bracket)
and, walked week by week, who played whom.

Managers are identified by `owner_id`, which is stable across seasons; team
names are not - people rename their team most years - so the all-time table
aggregates on the owner and shows the name they go by now.

Records here are Sleeper's own, which in a league playing a weekly median
counts two results a week. That is why a fourteen-week season shows a 28-game
record, and the page says so rather than leaving it to be puzzled out.

The cheap half (records, champions) renders first; head-to-head needs every
week of every season and fills in behind it.
"""
from gordstats import js_assets


CSS = """<style>
.hi{margin:8px 0 20px}
.hi h2{margin:20px 0 6px;font-size:18px}
.hi-note{font-size:12.5px;color:#64748b;margin:0 0 10px;line-height:1.5}
.hi-none{font-size:14px;color:#475569}
.hi-crown{color:#b45309;font-weight:800}
.hi-sub{font-size:11px;color:var(--gs-muted,#5d6b7e);margin-left:5px}
table.hi-h2h td,table.hi-h2h th{text-align:center;font-size:12.5px;padding:5px 7px}
table.hi-h2h th.row,table.hi-h2h td.row{text-align:left;font-weight:700;white-space:nowrap;
  position:sticky;left:0;background:#eef2f7;z-index:1}
table.hi-h2h td.self{background:#f1f5f9;color:var(--gs-muted,#5d6b7e)}
.hi-w{color:#15803d;font-weight:700}
.hi-l{color:#b91c1c}
.hi-load{font-size:12.5px;color:#64748b}
/* The controls over the grid: a season, a book, a manager. */
.hi-bar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:0 0 10px;
  font-size:13px;color:#475569}
.hi-bar label{display:inline-flex;align-items:center;gap:7px;min-width:0}
.hi-bar select{font:inherit;font-size:13px;padding:6px 10px;border:1px solid #cbd5e1;
  border-radius:8px;background:#fff;color:#0f172a;cursor:pointer;max-width:min(100%,320px)}
.hi-seg{display:inline-flex;background:#e2e8f0;border-radius:999px;padding:3px}
.hi-seg button{font:inherit;font-size:12.5px;font-weight:700;border:0;border-radius:999px;
  padding:5px 12px;background:transparent;color:#475569;cursor:pointer}
.hi-seg button.on{background:#fff;color:#0f172a;box-shadow:0 1px 3px rgba(15,23,42,.2)}
/* One manager's season: the two books, then what he scores and gives up. */
.hi-tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));
  gap:8px;margin:0 0 12px}
.hi-tile{border:1px solid #e2e8f0;border-radius:8px;background:#fff;padding:8px 11px;
  text-align:center}
.hi-tile b{display:block;font-size:18px;font-weight:800;color:#0f172a;line-height:1.2}
.hi-tile span{font-size:11px;color:#64748b}
/* Rival, nemesis, favourite - the three relationships worth naming. */
.hi-rivals{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));
  gap:8px;margin:0 0 14px}
.hi-rival{border-left:4px solid #cbd5e1;background:#f8fafc;border-radius:6px;padding:8px 11px}
.hi-rival.rival{border-color:#2a78d6}
.hi-rival.nemesis{border-color:#b91c1c}
.hi-rival.victim{border-color:#15803d}
.hi-rival .k{display:block;font-size:11px;text-transform:uppercase;letter-spacing:.04em;
  color:#64748b;font-weight:700}
.hi-rival .v{display:block;font-size:17px;font-weight:800;color:#0f172a}
.hi-rival .s{display:block;font-size:12px;color:#64748b}
/* Every game on one margin axis. The playoff ring is the table's own ink, so
   it reads as an outline in both themes rather than a second colour. */
.hi-strip{margin:0 0 14px}
.hi-strip svg{width:100%;height:auto;overflow:visible}
.hi-strip svg text{fill:#64748b}
.hi-strip svg .axis{stroke:#cbd5e1}
.hi-strip svg .zero{stroke:#94a3b8;stroke-dasharray:3 3}
.hi-strip svg circle.w{fill:#15803d}
.hi-strip svg circle.l{fill:#b91c1c}
.hi-strip svg circle.po{stroke:#0f172a;stroke-width:2}
.hi-key{font-size:12px;color:#64748b;margin:4px 0 0}
.hi-key b.w{color:#15803d}
.hi-key b.l{color:#b91c1c}
.hi-strip .strip-narrow{display:none}
@media (max-width:560px){
  .hi-strip .strip-wide{display:none}
  .hi-strip .strip-narrow{display:block}
  .hi-bar{gap:7px}
  .hi-bar select{flex:1;min-width:0;max-width:none}
  .hi-seg button{padding:5px 11px;font-size:13px;min-height:38px}
}
@media (prefers-color-scheme: dark){
  .hi-note,.hi-none,.hi-load{color:#aab7c9}
  .hi-bar{color:#aab7c9}
  .hi-bar select{background:#16203a;border-color:#2b3852;color:#dde5ef}
  .hi-bar select option{background:#16203a;color:#dde5ef}
  .hi-seg{background:#223052}
  .hi-seg button{color:#aab7c9}
  .hi-seg button.on{background:#0b1220;color:#e8eef7}
  .hi-tile{background:#16203a;border-color:#2b3852}
  .hi-tile b{color:#e8eef7}
  .hi-tile span{color:#aab7c9}
  .hi-rival{background:#16203a;border-left-color:#2b3852}
  .hi-rival .k,.hi-rival .s{color:#aab7c9}
  .hi-rival .v{color:#f1f5f9}
  .hi-strip svg text{fill:#aab7c9}
  .hi-strip svg .axis{stroke:#2b3852}
  .hi-strip svg .zero{stroke:#64748b}
  .hi-strip svg circle.w{fill:#34d399}
  .hi-strip svg circle.l{fill:#f87171}
  /* The ring is the page's own light ink here, which is what makes a playoff
     dot read as outlined rather than as a third colour. */
  .hi-strip svg circle.po{stroke:#e8eef7}
  .hi-key{color:#aab7c9}
  .hi-key b.w{color:#6ee7b7}
  .hi-key b.l{color:#ff9b91}
  table.hi-h2h th.row,table.hi-h2h td.row{background:#223052}
  table.hi-h2h td.self{background:#1b2540;color:#64748b}
  .hi-crown{color:#e0a92a}
  .hi-w{color:#6ee7b7}
  .hi-l{color:#ff9b91}
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
    return CSS + "<div class='hi' id='hi-host'></div>"


def _site_league() -> str:
    from fantasy.config import UPCOMING_LEAGUE_ID
    return str(UPCOMING_LEAGUE_ID)


# The code is docs/assets/js/gs-history.js (gordstats.js_assets): JS is it inline,
# for the browser tests; JS_TAG is what the pages carry.
# This site's league reaches it through GSCFG.
_CFG = {"siteLeague": _site_league()}
JS = js_assets.inline("gs-history.js", _CFG)
JS_TAG = js_assets.tag("gs-history.js", _CFG)
