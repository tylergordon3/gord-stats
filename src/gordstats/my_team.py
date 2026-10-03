"""
"Your team this week" on the NFL team dashboard (/fantasy/roster/).

The built page is this league's: its start/sit, its waiver adds, its projection
board. For a reader's own league the same questions have to be answered from
what Sleeper will hand a browser - their roster, their slots, their scoring -
against the projections this build publishes.

The lineup itself is `gordstats.lineup.plan` ported to JavaScript. Two
implementations of the same greedy selection is a real risk, so
`tests/test_my_team_planner.py` runs both over the same fixtures in a browser
and asserts they agree; if the Python changes and this does not, that test
fails rather than the page quietly recommending a different lineup.

What is exact and what is not: PPR, half-PPR and standard leagues are exact,
because Sleeper prices every player under all three and the league's own
`scoring_settings.rec` picks the column. A league further from the default -
six-point passing touchdowns, reception bonuses - is approximated by the
nearest of the three, and the page says so.
"""
from gordstats import js_assets

CSS = """<style>
.mt{margin:10px 0 18px}
.mt h2{margin:16px 0 6px;font-size:18px}
.mt-note{font-size:12.5px;color:#64748b;margin:0 0 10px;line-height:1.5}
.mt-warn{color:#b45309;font-weight:600}
.mt-pick{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:0 0 10px;font-size:13px}
.mt-pick select{font:inherit;font-size:13px;padding:6px 9px;border:1px solid #cbd5e1;
  border-radius:8px}
table.mt-t{width:100%;border-collapse:collapse;font-size:13.5px}
table.mt-t th{background:#eef2f7;color:#334155;padding:6px 9px;text-align:left;font-size:11.5px;
  text-transform:uppercase;letter-spacing:.03em;border:1px solid #e2e8f0;white-space:nowrap}
table.mt-t td{padding:6px 9px;border:1px solid #eef2f7;background:#fff;color:#0f172a}
table.mt-t td.n{text-align:right;font-variant-numeric:tabular-nums;font-weight:700}
table.mt-t tr.bench td{background:#f8fafc;color:#64748b}
table.mt-t tr.bench td.nm{font-weight:500}
.mt-slot{font-weight:800;font-size:11.5px;color:#475569;white-space:nowrap}
.mt-pos{font-size:10.5px;color:var(--gs-muted,#5d6b7e);font-weight:700;margin-left:5px}
.mt-lock{font-size:10.5px;color:var(--gs-muted,#5d6b7e);margin-left:5px}
table.mt-t tr.mt-move td{background:#ecfdf5;border-color:#a7f3d0}
table.mt-t tr.mt-out td{background:#fef2f2;border-color:#fecaca;color:#0f172a}
table.mt-t tr.mt-out td.nm{font-weight:600}
.mt-swap{margin:0 0 10px;padding:11px 13px;border:1px solid #a7f3d0;border-radius:10px;
  background:#ecfdf5;font-size:13.5px;line-height:1.6}
.mt-swap b{color:#15803d}
.mt-none{font-size:13.5px;color:#475569}
@media (prefers-color-scheme: dark){
  .mt-note,.mt-none{color:#aab7c9}
  table.mt-t th{background:#223052;color:#dde5ef;border-color:#2b3852}
  table.mt-t td{background:#16203a;border-color:#2b3852;color:#dde5ef}
  table.mt-t tr.bench td{background:#1b2540;color:#8fa0b8}
  .mt-slot{color:#aab7c9}
  .mt-swap{background:#14332a;border-color:#1f5f47}
  .mt-swap b{color:#6ee7b7}
  table.mt-t tr.mt-move td{background:#14332a;border-color:#1f5f47}
  table.mt-t tr.mt-out td{background:#3a1d1d;border-color:#7f1d1d;color:#dde5ef}
  .mt-pick select{background:#16203a;border-color:#2b3852;color:#dde5ef}
}
</style>"""

# The planner, ported from gordstats.lineup.plan. Kept deliberately close to
# the Python - same names, same order - so the two can be read side by side.
# The code is docs/assets/js/gs-plan.js (gordstats.js_assets): PLANNER_JS is it inline,
# for the browser tests; PLANNER_JS_TAG is what the pages carry.
PLANNER_JS = js_assets.inline("gs-plan.js")
PLANNER_JS_TAG = js_assets.tag("gs-plan.js")


# The code is docs/assets/js/gs-team.js (gordstats.js_assets): VIEW_JS is it inline,
# for the browser tests; VIEW_JS_TAG is what the pages carry.
VIEW_JS = js_assets.inline("gs-team.js")
VIEW_JS_TAG = js_assets.tag("gs-team.js")


def section() -> str:
    """The container the script fills."""
    return (CSS + "<div class='mt' id='mt-wrap'>"
            "<h2>Your team this week</h2>"
            "<div class='mt-pick' id='mt-bar'></div>"
            "<div id='mt-host'></div></div>")
