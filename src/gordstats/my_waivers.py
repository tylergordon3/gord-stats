"""
Waivers and trades for whichever league the reader has picked
(/fantasy/waivers/).

Sleeper keeps transactions per week, so this walks every week of every season
in the league's chain. Each one carries who added whom, who was dropped, and
what it cost: a waiver claim has its FAAB bid in `settings.waiver_bid`, and a
trade can move budget as well as players.

Player ids are numeric except for defences, which Sleeper keys by team code
("GB"). The player index carries all thirty-two, so both resolve the same way.

Failed claims are kept and shown separately: being outbid is half the story of
a waiver wire, and a log that silently drops them makes every claim look
uncontested.
"""
from gordstats import js_assets


CSS = """<style>
.wv{margin:8px 0 20px}
.wv h2{margin:20px 0 6px;font-size:18px}
.wv-note{font-size:12.5px;color:#64748b;margin:0 0 10px;line-height:1.5}
.wv-none{font-size:14px;color:#475569}
.wv-bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:0 0 10px;
  font-size:13px;color:#475569}
.wv-bar select{font:inherit;font-size:13px;padding:5px 9px;border:1px solid #cbd5e1;
  border-radius:8px}
.wv-in{color:#15803d;font-weight:600}
.wv-out{color:#b91c1c}
.wv-pos{font-size:10.5px;color:var(--gs-muted,#5d6b7e);font-weight:700;margin-left:4px}
.wv-how{font-size:11.5px;color:#64748b;white-space:nowrap}
.wv-bid{font-weight:800;color:#0f172a}
.wv-when{font-size:11.5px;color:#64748b;white-space:nowrap}
.wv-failed td{background:#fdf6f6;color:var(--gs-muted,#5d6b7e)}
.wv-more{font:inherit;font-size:12.5px;padding:6px 14px;border-radius:999px;
  border:1px solid #cbd5e1;background:#fff;color:#334155;cursor:pointer;margin:10px 0 0}
.wv-load{font-size:12.5px;color:#64748b}
@media (prefers-color-scheme: dark){
  .wv-note,.wv-none,.wv-how,.wv-when,.wv-load,.wv-bar{color:#aab7c9}
  .wv-in{color:#6ee7b7}
  .wv-out{color:#ff9b91}
  .wv-bid{color:#f1f5f9}
  .wv-failed td{background:#2a1e1e;color:#7f8ea3}
  .wv-bar select,.wv-more{background:#16203a;border-color:#2b3852;color:#dde5ef}
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

# The code is docs/assets/js/gs-waivers.js (gordstats.js_assets): JS is it inline,
# for the browser tests; JS_TAG is what the pages carry.
JS = js_assets.inline("gs-waivers.js")
JS_TAG = js_assets.tag("gs-waivers.js")


def section() -> str:
    return CSS + "<div class='wv' id='wv-host'></div>"
