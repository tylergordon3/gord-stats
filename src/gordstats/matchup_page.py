"""
The look shared by the weekly matchup pages (cfb.site.matchups,
fantasy.site.matchups): the scoreboard table, the matchup header, the
roster tables and the week switcher. Each section renders its own rows -
the leagues score different things - but a matchup should read the same
way on both pages, so the classes and the styling live here once.
"""
import pandas as pd

CSS = """<style>
.mu-wrap{margin:8px 0 18px}
/* The fantasy section's stylesheet sizes tables inside .table-scroll to their
   content; the scoreboard should span the page on both sections. */
table.mu-board,.table-scroll table.mu-board{width:100%;border-collapse:collapse;font-size:14px}
table.mu-board th{background:#eef2f7;color:#334155;padding:7px 10px;text-align:center;
  font-size:12px;text-transform:uppercase;letter-spacing:.03em;white-space:nowrap;
  border:1px solid #e2e8f0}
table.mu-board td{padding:6px 10px;border:1px solid #eef2f7;color:#0f172a;background:#fff;
  text-align:center;white-space:nowrap;font-variant-numeric:tabular-nums}
table.mu-board td.mu-t{text-align:left}
table.mu-board td.mu-t.r{text-align:right}
table.mu-board td.mu-vs{color:#94a3b8;font-size:11px}
table.mu-board tbody tr:nth-child(even) td{background:#f8fafc}
table.mu-board td b.lead{color:#1a7f4b}
.mu-head{display:grid;grid-template-columns:1fr auto 1fr;gap:12px;align-items:center;
  margin:6px 0 10px}
.mu-side{display:flex;align-items:center;gap:10px;min-width:0}
.mu-side.r{flex-direction:row-reverse;text-align:right}
.mu-side .nm{font-weight:700;font-size:16px;overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap}
.mu-side .rec{font-size:12px;color:#64748b;margin-left:6px;font-weight:400}
.mu-side .num{font-size:26px;font-weight:700;line-height:1.1;font-variant-numeric:tabular-nums}
.mu-side .num.lead{color:#1a7f4b}
.mu-side .sub{font-size:12px;color:#64748b;white-space:nowrap}
.mu-side .sub b{color:#334155}
.mu-mid{text-align:center;color:#94a3b8;font-size:12px;text-transform:uppercase;
  letter-spacing:.06em;white-space:nowrap}
.mu-wp{height:6px;border-radius:3px;background:#e2e8f0;overflow:hidden;margin:6px 0 2px;
  display:flex}
.mu-wp i{display:block;height:100%;background:#2f6db5}
.mu-wp i.b{background:#c0392b}
.mu-wp-lbl{display:flex;justify-content:space-between;font-size:11px;color:#64748b;
  margin-bottom:8px}
.mu-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;align-items:start}
/* min-width:0 on the grid items, or a wide roster table sets the column width
   and the right-hand roster runs off the page instead of scrolling. */
.mu-grid>div{min-width:0}
@media (max-width:860px){.mu-grid{grid-template-columns:1fr}
  .mu-head{grid-template-columns:1fr}.mu-mid{display:none}
  .mu-side.r{flex-direction:row;text-align:left}}
table.mu-roster{width:100%;border-collapse:collapse;font-size:13px}
table.mu-roster th{background:#eef2f7;color:#334155;padding:5px 7px;text-align:center;
  font-size:11px;text-transform:uppercase;letter-spacing:.03em;white-space:nowrap;
  border:1px solid #e2e8f0}
table.mu-roster td{padding:4px 7px;border:1px solid #eef2f7;color:#0f172a;background:#fff;
  text-align:center;white-space:nowrap;font-variant-numeric:tabular-nums;vertical-align:middle}
table.mu-roster td.mu-p,table.mu-roster td.mu-g,table.mu-roster td.mu-s{text-align:left}
table.mu-roster td.mu-slot{font-weight:700;color:#64748b;font-size:11px}
table.mu-roster td.mu-s{color:#64748b;font-size:12px;white-space:normal;min-width:120px}
table.mu-roster td.mu-g{font-size:12px;color:#334155}
table.mu-roster td.mu-g .live{color:#b3382c;font-weight:700}
table.mu-roster td.mu-g .fin{color:#64748b}
table.mu-roster td.mu-g .bye{color:#94a3b8;font-style:italic}
table.mu-roster tr.bench td{background:#f8fafc;color:#475569}
table.mu-roster tr.bench td.mu-slot{color:#94a3b8}
table.mu-roster tr.sep td{background:#f1f5f9;color:#475569;font-weight:700;font-size:11px;
  text-align:left;text-transform:uppercase;letter-spacing:.04em;padding:3px 7px}
table.mu-roster tr.total td{background:#eef2f7;font-weight:700}
table.mu-roster td.mu-p .nm{font-weight:600}
/* Own names for the small labels: custom.css has a global .meta that styles
   any element carrying it as a block. */
table.mu-roster td.mu-p .mu-meta{font-size:11px;color:#64748b;margin-left:4px}
table.mu-roster td.mu-p .inj{font-size:10px;font-weight:700;color:#b3382c;margin-left:4px}
table.mu-roster td.mu-p .mu-hint{font-size:10px;font-weight:700;margin-left:4px;
  border-radius:3px;padding:0 4px}
table.mu-roster td.mu-p .mu-hint.in{background:#d5efdd;color:#1a7f4b}
table.mu-roster td.mu-p .mu-hint.out{background:#fde2dd;color:#b3382c}
table.mu-roster img.mu-logo{width:18px;height:18px;object-fit:contain;vertical-align:middle;
  margin:0 5px 0 0;border:none;padding:0;box-shadow:none;background:none;border-radius:0;
  filter:drop-shadow(0 0 1px rgba(255,255,255,.7))}
img.mu-tlogo{width:34px;height:34px;border-radius:50%;flex:none;border:none;padding:0;
  box-shadow:none;margin:0}
table.mu-board img.mu-tlogo{width:20px;height:20px;vertical-align:middle;margin:0 6px 0 0}
table.mu-board td.mu-t.r img.mu-tlogo{margin:0 0 0 6px}
.mu-note{font-size:13px;color:#4a5a68;margin:4px 0 10px}
.mu-swap{font-size:12px;color:#334155;margin:4px 0 0}
.mu-swap b{color:#1a7f4b}
.mu-wrap details.section>summary{font-size:15px}
@media (prefers-color-scheme: dark){
  table.mu-board th,table.mu-roster th{background:#223052;color:#dde5ef;border-color:#2b3852}
  table.mu-board td,table.mu-roster td{background:#16203a;border-color:#2b3852;color:#dde5ef}
  table.mu-board tbody tr:nth-child(even) td{background:#1b2540}
  table.mu-board td b.lead,.mu-side .num.lead,.mu-swap b{color:#8ff0bd}
  table.mu-roster tr.bench td{background:#1b2540;color:#aab7c9}
  table.mu-roster tr.sep td{background:#223052;color:#aab7c9}
  table.mu-roster tr.total td{background:#223052}
  table.mu-roster td.mu-slot,table.mu-roster td.mu-s,table.mu-roster td.mu-p .mu-meta{color:#aab7c9}
  table.mu-roster td.mu-g{color:#dde5ef}
  table.mu-roster td.mu-g .live{color:#ffb4ab}
  table.mu-roster td.mu-g .fin,table.mu-roster td.mu-g .bye{color:#aab7c9}
  table.mu-roster td.mu-p .inj{color:#ffb4ab}
  table.mu-roster td.mu-p .mu-hint.in{background:#123c2e;color:#8ff0bd}
  table.mu-roster td.mu-p .mu-hint.out{background:#4a1f1a;color:#ffb4ab}
  .mu-side .rec,.mu-side .sub,.mu-wp-lbl,.mu-mid{color:#aab7c9}
  .mu-side .sub b{color:#dde5ef}
  .mu-wp{background:#2b3852}
  .mu-note{color:#aab7c9}
  .mu-swap{color:#dde5ef}
}
</style>"""

JS = """<script>
(function(){
  function show(w){
    var views=document.querySelectorAll('.wk-view');
    for(var i=0;i<views.length;i++){views[i].style.display='none';}
    var v=document.getElementById('wk-view-'+w);if(!v)return;
    v.style.display='';
    var btns=document.querySelectorAll('.wk-btn');
    for(var j=0;j<btns.length;j++){btns[j].classList.remove('active');}
    var b=document.getElementById('wk-tab-'+w);if(b)b.classList.add('active');
    if(history.replaceState){history.replaceState(null,'','#wk-'+w);}
  }
  window.show_wk=show;
  var m=(location.hash||'').match(/^#wk-(\\d+)$/);
  if(m&&document.getElementById('wk-view-'+m[1]))show(m[1]);
})();
</script>"""


def fmt(v, dec: int = 1) -> str:
    """A number, or an em dash for nothing."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{float(v):.{dec}f}"


def week_switch(weeks: list, current: int, views: dict) -> str:
    """The week buttons and one view per week, the current one showing.
    `.view-switch` styling is the site's (custom.css)."""
    buttons = "".join(
        f'<button class="wk-btn{" active" if w == current else ""}" '
        f"onclick=\"show_wk('{w}')\" id=\"wk-tab-{w}\">{w}</button>" for w in weeks)
    divs = "".join(
        f'<div id="wk-view-{w}" class="wk-view"'
        f'{"" if w == current else " style=\'display:none\'"}>{views[w]}</div>' for w in weeks)
    switch = ("" if len(weeks) == 1 else
              f'<div class="view-switch"><span class="switch-label">Week:</span>{buttons}</div>')
    return f'<div class="mu-wrap">{switch}<div id="mu-weeks">{divs}</div></div>' + JS


def win_bar(wp_a: float, wp_b: float, source: str) -> str:
    """Two-colour probability bar with the percentages under it."""
    return (f'<div class="mu-wp"><i style="width:{wp_a * 100:.0f}%"></i>'
            f'<i class="b" style="width:{wp_b * 100:.0f}%"></i></div>'
            f'<div class="mu-wp-lbl"><span>{wp_a * 100:.0f}% ({source})</span>'
            f'<span>{wp_b * 100:.0f}%</span></div>')
