"""
Projected playoff pages for any sport (/cfb/playoff/, /nfl/playoff/): the
likeliest bracket as a stack of cards, then every contender's odds in one
sortable table, then a folded note on how it is worked out. The sport's
adapter (cfb.site.playoff, nfl.site.playoff) runs its simulation (cfb.playoff,
nfl.playoff) and hands over plain rows; everything drawn lives here once, as
gordstats.stats_page does for the stats pages.

A table row:

    {"id": "333", "name": "Alabama", "full": "Alabama Crimson Tide",
     "link": "/cfb/teams/alabama/", "logo": "<img ...>", "record": "4-0",
     "values": {"playoff": 0.85, "fpi": 0.73, "seed": 4.2, ...}}

A column: {"key", "label", "tip", "kind": "pct" | "seed"}. A pct column is
shaded by its own value - the chance itself, not a rank - so ours and ESPN's
read side by side; a value of None prints nothing (a team ESPN does not
list). The shade is an inset shadow rather than a background so a starred
row's tint (gordstats.favorites.table_css) and the shade both show.

A bracket is [{"title": "AFC", "cards": [[block, ...], ...]}], a block
{"label": "Wild card", "lines": [line, ...]}, a line {"seed": 2, "id",
"name", "link", "logo", "fig": "87%", "state": None | "won" | "lost"}.
On a phone the groups stack; wider, they sit side by side.
"""
from html import escape

from gordstats import favorites


def pct_text(v) -> str:
    """A chance as the table prints it: whole percents, "<1" and ">99" at the
    ends so a long shot is not rounded to nothing nor a near-lock to certain,
    and a dot for a true zero."""
    if v is None:
        return ""
    if v <= 0:
        return "<span class='po-zero'>&middot;</span>"
    if v >= 1:
        return "100"
    p = v * 100
    if p < 0.5:
        return "&lt;1"
    if p > 99.5:
        return "&gt;99"
    return f"{p:.0f}"


def _cell(value, kind: str) -> str:
    if kind == "seed":
        if value is None or value != value:
            return "<td class='po-seedavg'></td>"
        return f"<td class='po-seedavg' data-v='{value:.3f}'>{value:.1f}</td>"
    if value is None:
        return "<td></td>"
    return (f"<td class='h' style='--p:{min(max(value, 0.0), 1.0):.3f}' "
            f"data-v='{value:.5f}'>{pct_text(value)}</td>")


def _team(row: dict, sport: str) -> str:
    name = escape(str(row["name"]))
    label = (f"<a href='{escape(row['link'], quote=True)}'>{name}</a>" if row.get("link")
             else f"<span class='po-nm'>{name}</span>")
    rec = f"<span class='po-rec'>{escape(str(row['record']))}</span>" if row.get("record") else ""
    return (f"<td class='po-team'><span class='po-tn'>{row.get('logo') or ''}{label}{rec}</span>"
            + favorites.star(sport, row["id"], row.get("full") or row["name"]) + "</td>")


def odds_table(rows: list, columns: list, sport: str, sort_key: str = None) -> str:
    """The contenders' table, in the order given (the adapter sorts it); a
    tap on a figure's header re-sorts by it, best first."""
    head = "<th class='po-team'>Team</th>" + "".join(
        f"<th data-k='{c['key']}' data-t='{c['kind']}' title='{escape(c.get('tip', ''), quote=True)}'"
        f"{' aria-sort=descending' if c['key'] == sort_key else ''}>{escape(c['label'])}</th>"
        for c in columns)
    body = []
    for r in rows:
        cells = "".join(_cell(r["values"].get(c["key"]), c["kind"]) for c in columns)
        body.append(f"<tr{favorites.row_attr(sport, r['id'])}>{_team(r, sport)}{cells}</tr>")
    return (favorites.table_css("table.po-t")
            + "<div class='power-wrap po-wrap'><table class='po-t' data-sticky-head>"
            + f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>")


def _line(line: dict, sport: str) -> str:
    state = f" {line['state']}" if line.get("state") else ""
    name = escape(str(line["name"]))
    if line.get("link"):
        name = f"<a href='{escape(line['link'], quote=True)}'>{name}</a>"
    fav = favorites.row_attr(sport, line["id"]) if line.get("id") else ""
    rec = f"<span class='po-rec'>{escape(str(line['record']))}</span>" if line.get("record") else ""
    return (f"<div class='po-line{state}'{fav}><span class='po-seed'>{line.get('seed', '')}</span>"
            f"{line.get('logo') or ''}<span class='po-name'>{name}{rec}</span>"
            f"<span class='po-fig'>{line.get('fig', '')}</span></div>")


def bracket(groups: list, sport: str) -> str:
    out = []
    for g in groups:
        cards = []
        for card in g["cards"]:
            blocks = "".join(
                "<div class='po-block'>"
                + (f"<div class='po-label'>{escape(b['label'])}</div>" if b.get("label") else "")
                + "".join(_line(x, sport) for x in b["lines"]) + "</div>"
                for b in card)
            cards.append(f"<div class='po-card'>{blocks}</div>")
        title = f"<h3 class='po-gh'>{escape(g['title'])}</h3>" if g.get("title") else ""
        out.append(f"<div class='po-group'>{title}{''.join(cards)}</div>")
    return f"<div class='po-bracket'>{''.join(out)}</div>"


def method(paragraphs: list, summary: str = "How this works") -> str:
    """The folded note. Paragraphs are HTML the adapter wrote."""
    return (f"<details class='section po-method'><summary>{escape(summary)}</summary>"
            + "".join(f"<p>{p}</p>" for p in paragraphs) + "</details>")


def empty(text: str) -> str:
    return f"<p class='po-empty'>{text}</p>"


def page(*parts: str) -> str:
    return CSS + "<div class='po'>" + "".join(parts) + "</div>" + JS


CSS = """<style>
.po h2{margin:22px 0 4px}
.po .po-note{font-size:13.5px;color:var(--gs-muted,#5d6b7e);text-align:center;margin:0 0 10px}
.po-empty{text-align:center;font-size:15px;margin:24px 0}
.po-bracket{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:4px 16px;
  margin:6px 0 8px}
.po-gh{font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.06em;
  color:var(--gs-muted,#5d6b7e);text-align:left;margin:8px 2px 6px}
.po-card{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:4px 10px;
  margin:0 0 10px;box-shadow:0 1px 3px rgba(15,23,42,.05)}
.po-block+.po-block{border-top:1px solid #eef2f7;margin-top:2px;padding-top:2px}
.po-label{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;
  color:var(--gs-muted,#5d6b7e);margin:5px 0 0 30px}
.po-line{display:flex;align-items:center;gap:8px;min-height:36px;padding:0 4px;border-radius:6px}
.po-seed{flex:none;width:18px;text-align:right;font-weight:800;font-size:13px;
  color:var(--gs-muted,#5d6b7e);font-variant-numeric:tabular-nums}
.po-line img,table.po-t td.po-team img{flex:none;width:22px;height:22px;max-width:none;
  object-fit:contain;vertical-align:middle;margin:0;border:0;padding:0;box-shadow:none;
  background:none;border-radius:0}
.po-name{flex:1;min-width:0;font-weight:700;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;color:#0f172a}
.po-name a{color:inherit;text-decoration:none}
.po-rec{font-weight:400;font-size:12px;color:var(--gs-muted,#5d6b7e);margin-left:6px}
.po-fig{flex:none;font-size:13px;color:var(--gs-muted,#5d6b7e);font-variant-numeric:tabular-nums}
.po-line.won .po-name{color:#0f172a}
.po-line.lost{opacity:.5}
.po-line.lost .po-name{font-weight:500}
/* The theme boxes every cell in a dark 1px border and pads it 10px. */
table.po-t{width:100%;border:0;margin:0;border-collapse:separate;border-spacing:0;font-size:14px;
  font-variant-numeric:tabular-nums}
table.po-t th,table.po-t td{border:0}
table.po-t th{background:#eef2f7;color:#334155;font:inherit;font-size:11.5px;font-weight:700;
  text-transform:uppercase;letter-spacing:.03em;padding:8px 6px;border-bottom:1px solid #e2e8f0;
  white-space:nowrap;text-align:right;cursor:pointer;user-select:none}
table.po-t th[aria-sort]::after{content:" \\25BE";color:#2a78d6}
table.po-t th[aria-sort=ascending]::after{content:" \\25B4"}
table.po-t td{padding:8px 6px;border-bottom:1px solid #eef2f7;text-align:right;white-space:nowrap;
  color:#0f172a;background:#fff}
/* The shade is the chance itself, as an inset shadow: it layers over a
   starred row's tint instead of fighting it for the background. */
table.po-t td.h{box-shadow:inset 0 0 0 60px hsl(217 85% 52% / calc(var(--p) * .30))}
table.po-t .po-team{position:sticky;left:0;z-index:1;text-align:left;font-weight:700;cursor:default}
table.po-t th.po-team{z-index:2}
/* The name gives way (an ellipsis) before the figures are pushed off a phone. */
table.po-t .po-tn{display:inline-flex;align-items:center;max-width:200px;vertical-align:middle}
table.po-t .po-tn a,table.po-t .po-tn .po-nm{min-width:0;overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap;color:inherit;text-decoration:none;margin-left:7px}
table.po-t .po-tn .po-rec{flex:none}
table.po-t td.po-seedavg{color:var(--gs-muted,#5d6b7e)}
.po-zero{color:#64748b}
.po-wrap{overflow-x:auto;border:1px solid #e2e8f0;border-radius:12px}
.po-method p{font-size:14px;line-height:1.55;margin:8px 0}
@media (max-width:600px){
  table.po-t{font-size:13.5px}
  table.po-t th{padding:8px 3px;font-size:10.5px;letter-spacing:0}
  table.po-t th[aria-sort]::after{content:"\\25BE"}
  table.po-t th[aria-sort=ascending]::after{content:"\\25B4"}
  table.po-t td{padding:8px 3px}
  table.po-t th:first-child,table.po-t td:first-child{padding-left:6px}
  table.po-t th:last-child,table.po-t td:last-child{padding-right:7px}
  table.po-t .po-tn{max-width:108px}
  table.po-t .po-tn a,table.po-t .po-tn .po-nm{margin-left:6px}
  table.po-t .po-rec{display:none}
}
@media (prefers-color-scheme: dark){
  .po-card{background:#1b2540;border-color:#2b3852;box-shadow:none}
  .po-block+.po-block{border-color:#2b3852}
  .po-name,.po-line.won .po-name{color:#e6edf6}
  /* Ohio State's and Penn State's marks are near-black: a light disc. */
  .po-line img,table.po-t td.po-team img{background:#e8edf5;border-radius:50%;padding:2px;
    box-sizing:border-box}
  table.po-t th{background:#223052;color:#dde5ef;border-color:#2b3852}
  table.po-t td{background:#16203a;color:#e6edf6;border-color:#2b3852}
  table.po-t td.h{box-shadow:inset 0 0 0 60px hsl(213 90% 62% / calc(var(--p) * .30))}
  .po-wrap{border-color:#2b3852}
  .po-zero{color:#94a3b8}
}
</style>"""

JS = """<script>
(function(){
  var table=document.querySelector('table.po-t');
  if(!table) return;
  var body=table.tBodies[0];
  table.tHead.addEventListener('click',function(e){
    var th=e.target.closest('th[data-k]'); if(!th) return;
    var col=[].indexOf.call(th.parentNode.cells,th);
    // Best first: the highest chance, the lowest average seed.
    var first=th.getAttribute('data-t')==='seed'?'ascending':'descending';
    var dir=th.getAttribute('aria-sort')===first?(first==='ascending'?'descending':'ascending'):first;
    [].forEach.call(th.parentNode.cells,function(c){ c.removeAttribute('aria-sort'); });
    th.setAttribute('aria-sort',dir);
    var rows=[].slice.call(body.rows), sign=dir==='ascending'?1:-1;
    rows.sort(function(a,b){
      var x=a.cells[col].getAttribute('data-v'), y=b.cells[col].getAttribute('data-v');
      if(x===null&&y===null) return 0; if(x===null) return 1; if(y===null) return -1;
      return (parseFloat(x)-parseFloat(y))*sign;
    });
    rows.forEach(function(r){ body.appendChild(r); });
  });
})();
</script>"""
