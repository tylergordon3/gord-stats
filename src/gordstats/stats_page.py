"""
Team stats pages for any sport: one sortable table of every team, in tabs,
each figure shaded by where it ranks, and player leaderboards beside it - the
nerd pages (/cfb/stats/, /nfl/stats/). Each sport's adapter builds the rows
and says what the columns are; everything drawn lives here once (the pattern
of gordstats.watch_page).

A column:

    {"key": "off_epa", "label": "EPA/play", "tip": "what it is, one line",
     "fmt": "epa" | "pct" | "num1" | "num2" | "int" | "text" | "rec" (a W-L
            record, sorted by winning share),
     "better": "high" | "low" | None, "views": ("overview", "offense")}

A row is a dict with the columns' keys plus `name`, and optionally `link`,
`logo`, `group` (what the filter selects on: a conference, a division) and
`tags` (extra filter memberships, e.g. "Power 4"). Missing figures are None
and shade nothing.

Shading is the row's percentile among the teams on the page for that column,
turned the right way ("better": low means low is good - points allowed, stuff
rate on offence), drawn as a translucent red-to-green behind the figure so it
reads in both themes. A column with no "better" is not shaded.

The table sits in a sideways scroller with its header copied under the pinned
bar as it scrolls (assets/js/stickyhead.js, `data-sticky-head`); a tap on a
header sorts by it, best first, a second tap reverses; the # column numbers
the rows as they stand after sorting and filtering.
"""
import json
from html import escape

import pandas as pd

VIEWS = [("overview", "Overview"), ("offense", "Offense"), ("defense", "Defense"),
         ("situational", "Situational")]


def fmt(value, kind: str) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "&mdash;"
    if kind == "text" or kind == "rec":
        return escape(str(value))
    v = float(value)
    # A figure that rounds to nothing is nothing, not "-0.00".
    if kind in ("epa", "num2") and round(v, 2) == 0:
        v = 0.0
    elif kind == "num1" and round(v, 1) == 0:
        v = 0.0
    if kind == "pct":
        return f"{v * 100:.1f}%"
    if kind == "epa":
        return f"{v:+.2f}"
    if kind == "num2":
        return f"{v:.2f}"
    if kind == "int":
        return f"{v:,.0f}"
    return f"{v:.1f}"


def _win_pct(record) -> float | None:
    """"3-1" or "3-1-1" as a winning share, so a record column sorts."""
    try:
        parts = [int(x) for x in str(record).split("-")]
    except ValueError:
        return None
    w, l, t = (parts + [0, 0, 0])[:3]
    return None if w + l + t == 0 else (w + t / 2) / (w + l + t)


def percentiles(rows: list, columns: list) -> dict:
    """{(row index, column key): 0-1, 1 best} for every shaded column."""
    out = {}
    for c in columns:
        if not c.get("better"):
            continue
        vals = pd.Series([r.get(c["key"]) for r in rows], dtype="float64")
        ranked = vals.rank(pct=True, ascending=c["better"] == "high")
        n = vals.notna().sum()
        for i, p in ranked.items():
            if pd.notna(p) and n > 1:
                # rank(pct) runs 1/n..1; stretch it to 0..1 so the worst is red.
                out[(i, c["key"])] = round((p * n - 1) / (n - 1), 3)
    return out


def table(rows: list, columns: list, views=VIEWS, filters: list = None,
          filter_label: str = "Show", entity: str = "Team", default_view: str = "overview",
          sort_key: str = None) -> str:
    """The team table with its tab buttons and filter. `filters` is
    [(value, label)] - a value matches a row's group or one of its tags;
    "" is everyone. `sort_key` is the column the table opens sorted by."""
    pct = percentiles(rows, columns)
    by = next((c for c in columns if c["key"] == sort_key), None)
    order = list(range(len(rows)))
    if by is not None:
        sign = -1 if by.get("better", "high") != "low" else 1
        order.sort(key=lambda i: (rows[i].get(by["key"]) is None,
                                  sign * float(rows[i].get(by["key"]) or 0)))

    def cls(c):
        return " ".join(f"v-{v}" for v in c.get("views", ()))

    head = ("<th class='st-rk'>#</th>"
            f"<th class='st-team' data-k='name' data-t='text'>{escape(entity)}</th>"
            + "".join(
                f"<th class='{cls(c)}' data-k='{c['key']}' data-b='{c.get('better') or ''}'"
                f" data-t='{c['fmt']}' title='{escape(c.get('tip', ''), quote=True)}'"
                f"{' aria-sort=descending' if by is c else ''}>{escape(c['label'])}</th>"
                for c in columns))
    body = []
    for n, i in enumerate(order, 1):
        r = rows[i]
        tags = " ".join([str(r.get("group") or "")] + list(r.get("tags") or []))
        name = escape(str(r["name"]))
        logo = (f"<img src='{escape(r['logo'], quote=True)}' alt='' width='20' height='20' "
                f"loading='lazy'>" if r.get("logo") else "")
        team = f"<a href='{escape(r['link'], quote=True)}'>{logo}{name}</a>" if r.get("link") \
            else f"{logo}{name}"
        sub = f"<span class='st-sub'>{escape(str(r['sub']))}</span>" if r.get("sub") else ""
        cells = []
        for c in columns:
            v = r.get(c["key"])
            p = pct.get((i, c["key"]))
            if c["fmt"] == "rec":
                wp = _win_pct(v)
                data = "" if wp is None else f" data-v='{wp:.4f}'"
            else:
                data = "" if v is None or (isinstance(v, float) and pd.isna(v)) or c["fmt"] == "text" \
                    else f" data-v='{float(v):.6g}'"
            shade = f" class='{cls(c)} h' style='--p:{p}'" if p is not None else f" class='{cls(c)}'"
            cells.append(f"<td{shade}{data}>{fmt(v, c['fmt'])}</td>")
        body.append(f"<tr data-f='{escape(tags, quote=True)}'><td class='st-rk'>{n}</td>"
                    f"<td class='st-team' data-v='{name}'>{team}{sub}</td>{''.join(cells)}</tr>")

    tabs = "".join(f"<button type='button' data-view='{k}' aria-pressed='{str(k == default_view).lower()}'>"
                   f"{escape(label)}</button>" for k, label in views)
    flt = ""
    if filters:
        opts = "".join(f"<option value='{escape(v, quote=True)}'>{escape(label)}</option>"
                       for v, label in filters)
        flt = (f"<label class='st-flt'><span>{escape(filter_label)}</span>"
               f"<select>{opts}</select></label>")
    view_css = "".join(
        f"table.st-t.view-{k} td:not(.st-rk):not(.st-team):not(.v-{k}),"
        f"table.st-t.view-{k} th:not(.st-rk):not(.st-team):not(.v-{k}){{display:none}}"
        for k, _ in views)
    return (CSS + f"<style>{view_css}</style>"
            + f"<div class='st' data-st>"
            + f"<div class='pin-bar st-bar'><div class='st-tabs' role='group'>{tabs}</div>{flt}</div>"
            + f"<div class='power-wrap st-wrap'><table class='st-t view-{default_view}' data-sticky-head>"
            + f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
            + "</div>" + JS)


def glossary(columns: list, extra: str = "") -> str:
    """Every column's one line, folded - what a nerd page owes its reader.
    Any list of {label, tip} will do, not only the table's columns."""
    items = "".join(f"<dt>{escape(c['label'])}</dt><dd>{escape(c['tip'])}</dd>"
                    for c in columns if c.get("tip"))
    return ("<details class='section st-gloss'><summary>What the columns mean</summary>"
            f"{extra}<dl>{items}</dl></details>")


def leaders(groups: list, top: int = 15) -> str:
    """Player leaderboards in tabs. `groups` is [{key, label, metric, volume,
    rows: [{name, team, value, fmt, vol, sub}]}], rows best first."""
    if not groups:
        return ""
    tabs = "".join(f"<button type='button' data-lb='{escape(g['key'])}' aria-pressed='{str(i == 0).lower()}'>"
                   f"{escape(g['label'])}</button>" for i, g in enumerate(groups))
    lists = []
    for i, g in enumerate(groups):
        items = "".join(
            f"<li><span class='lb-n'>{n}</span><span class='lb-who'><b>{escape(str(r['name']))}</b>"
            f"<small>{escape(str(r.get('team') or ''))}{(' &middot; ' + escape(str(r['sub']))) if r.get('sub') else ''}</small></span>"
            f"<span class='lb-v'>{fmt(r['value'], r.get('fmt', g.get('fmt', 'num2')))}"
            f"<small>{escape(str(r.get('vol') or ''))}</small></span></li>"
            for n, r in enumerate(g["rows"][:top], 1))
        lists.append(f"<div class='lb-list' data-lb='{escape(g['key'])}'{'' if i == 0 else ' hidden'}>"
                     f"<p class='lb-head'>{escape(g['metric'])}"
                     f"{(' &middot; ' + escape(g['volume'])) if g.get('volume') else ''}</p>"
                     f"<ol>{items}</ol></div>")
    return (f"<div class='lb' data-lbs><div class='st-tabs lb-tabs' role='group'>{tabs}</div>"
            + "".join(lists) + "</div>" + LB_JS)


CSS = """<style>
.st-bar{display:flex;flex-wrap:wrap;align-items:center;gap:8px 14px}
.st-tabs{display:flex;gap:6px;overflow-x:auto}
.st-tabs button{flex:none;min-height:40px;padding:0 14px;border-radius:999px;font:inherit;
  font-size:14px;font-weight:700;border:1px solid #cbd5e1;background:#fff;color:#334155;cursor:pointer}
.st-tabs button[aria-pressed=true]{background:#1e293b;border-color:#1e293b;color:#fff}
.st-flt{display:flex;align-items:center;gap:6px;font-size:13px;color:#475569}
.st-flt select{min-height:40px;font:inherit;font-size:14px;border-radius:8px;border:1px solid #cbd5e1;
  background:#fff;color:#0f172a;padding:0 8px;max-width:200px}
table.st-t{border-collapse:collapse;font-size:14px;width:100%;min-width:560px;
  font-variant-numeric:tabular-nums}
table.st-t th{font-size:11.5px;text-transform:uppercase;letter-spacing:.03em;color:#334155;
  background:#eef2f7;padding:8px 8px;border-bottom:1px solid #e2e8f0;white-space:nowrap;
  cursor:pointer;user-select:none;text-align:right}
table.st-t th[aria-sort]::after{content:" \\25BE";color:#2a78d6}
table.st-t th[aria-sort=ascending]::after{content:" \\25B4"}
table.st-t td{padding:7px 8px;border-bottom:1px solid #eef2f7;text-align:right;white-space:nowrap;
  color:#0f172a}
table.st-t .st-rk{width:28px;text-align:right;color:#64748b;font-weight:700;font-size:12.5px;cursor:default}
table.st-t .st-team{text-align:left;font-weight:700;position:sticky;left:0;background:#fff;z-index:1;
  max-width:180px;overflow:hidden;text-overflow:ellipsis}
table.st-t th.st-team{background:#eef2f7;z-index:2}
table.st-t .st-team a{color:inherit;text-decoration:none;padding:8px 0}
table.st-t .st-team img{width:20px;height:20px;object-fit:contain;vertical-align:-4px;margin:0 6px 0 0;
  border:0;padding:0;box-shadow:none;background:none}
table.st-t .st-sub{font-weight:500;font-size:12px;color:#64748b;margin-left:6px}
/* Where a figure ranks: red (worst) through amber to green (best), faint
   enough that the number stays the thing read. */
table.st-t td.h{background:hsl(calc(var(--p) * 120) 70% 45% / .17)}
.st-gloss dl{margin:6px 0 0;font-size:13.5px;line-height:1.5}
.st-gloss dt{font-weight:700;margin-top:8px}
.st-gloss dd{margin:0;color:#475569}
.lb-tabs{margin:4px 0 10px}
.lb-head{font-size:13px;color:#475569;margin:0 0 6px}
.lb ol{list-style:none;margin:0;padding:0}
.lb li{display:grid;grid-template-columns:26px minmax(0,1fr) auto;gap:4px 10px;align-items:center;
  padding:8px 4px;border-bottom:1px solid #eef2f7}
.lb .lb-n{color:#64748b;font-weight:700;font-size:13px;text-align:right}
.lb .lb-who{min-width:0}
.lb .lb-who b{display:block;font-size:15px;font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.lb small{display:block;font-size:12.5px;color:#64748b}
.lb .lb-v{text-align:right;font-weight:800;font-size:16px;font-variant-numeric:tabular-nums}
@media (max-width:600px){
  table.st-t{font-size:13.5px}
  table.st-t .st-team{max-width:142px}
  table.st-t .st-sub{display:none}
  /* Four tabs in 358px: "Situational" was cut off at the edge. */
  .st-tabs button{padding:0 10px;font-size:13px}
}
@media (prefers-color-scheme: dark){
  .st-tabs button{background:#16203a;border-color:#2b3852;color:#dde5ef}
  .st-tabs button[aria-pressed=true]{background:#e2e8f0;border-color:#e2e8f0;color:#0f172a}
  .st-flt{color:#aab7c9}
  .st-flt select{background:#16203a;border-color:#2b3852;color:#dde5ef}
  table.st-t th,table.st-t th.st-team{background:#223052;color:#dde5ef;border-color:#2b3852}
  table.st-t td{border-color:#2b3852;color:#e6edf6}
  table.st-t .st-team{background:#0f172a}
  /* Ohio State's and Penn State's marks are near-black: the site's light disc. */
  table.st-t .st-team img{background:#e8edf5;border-radius:50%;padding:2px;box-sizing:border-box}
  table.st-t td.h{background:hsl(calc(var(--p) * 120) 70% 45% / .28)}
  table.st-t .st-rk,table.st-t .st-sub,.lb small,.lb .lb-n,.lb-head,.st-gloss dd{color:#aab7c9}
  .lb li{border-color:#2b3852}
}
</style>"""

JS = """<script>
(function(){
  var root=document.currentScript&&document.currentScript.previousElementSibling;
  if(!root||!root.matches('[data-st]')) return;
  var table=root.querySelector('table.st-t'), body=table.tBodies[0];
  function renumber(){
    var n=0;
    [].forEach.call(body.rows,function(tr){ if(!tr.hidden) tr.cells[0].textContent=++n; });
  }
  root.querySelector('.st-tabs').addEventListener('click',function(e){
    var b=e.target.closest('button[data-view]'); if(!b) return;
    [].forEach.call(this.querySelectorAll('button'),function(x){ x.setAttribute('aria-pressed',String(x===b)); });
    table.className=table.className.replace(/\\bview-[a-z]+/,'view-'+b.getAttribute('data-view'));
  });
  var sel=root.querySelector('.st-flt select');
  if(sel) sel.addEventListener('change',function(){
    var want=sel.value;
    [].forEach.call(body.rows,function(tr){
      tr.hidden=!!want&&(' '+tr.getAttribute('data-f')+' ').indexOf(' '+want+' ')<0;
    });
    renumber();
  });
  table.tHead.addEventListener('click',function(e){
    var th=e.target.closest('th[data-k]'); if(!th) return;
    var col=[].indexOf.call(th.parentNode.cells,th), text=th.getAttribute('data-t')==='text';
    // Best first on the first tap: high for most figures, low where low is good.
    var first=text||th.getAttribute('data-b')==='low'?'ascending':'descending';
    var dir=th.getAttribute('aria-sort')===first?(first==='ascending'?'descending':'ascending'):first;
    [].forEach.call(th.parentNode.cells,function(c){ c.removeAttribute('aria-sort'); });
    th.setAttribute('aria-sort',dir);
    var rows=[].slice.call(body.rows), sign=dir==='ascending'?1:-1;
    rows.sort(function(a,b){
      var x=a.cells[col].getAttribute('data-v'), y=b.cells[col].getAttribute('data-v');
      if(x===null&&y===null) return 0; if(x===null) return 1; if(y===null) return -1;
      return (text?x.localeCompare(y):(parseFloat(x)-parseFloat(y)))*sign;
    });
    rows.forEach(function(r){ body.appendChild(r); });
    renumber();
  });
})();
</script>"""

LB_JS = """<script>
(function(){
  var lb=document.currentScript&&document.currentScript.previousElementSibling;
  if(!lb||!lb.matches('[data-lbs]')) return;
  lb.querySelector('.lb-tabs').addEventListener('click',function(e){
    var b=e.target.closest('button[data-lb]'); if(!b) return;
    [].forEach.call(this.querySelectorAll('button'),function(x){ x.setAttribute('aria-pressed',String(x===b)); });
    [].forEach.call(lb.querySelectorAll('.lb-list'),function(l){ l.hidden=l.getAttribute('data-lb')!==b.getAttribute('data-lb'); });
  });
})();
</script>"""
