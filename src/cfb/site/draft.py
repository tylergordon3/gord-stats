"""
The CFB draft board (docs/cfb/draft/) - the pre-draft preview.

The same idea as the NFL homepage's ADP board, sized to what college fantasy
actually has: Yahoo is the only site running a college game, so there is one
ADP column instead of five, and the board's spine is Yahoo's own average rank
(cfb.yahoo.board). Sortable / filterable / searchable, all client-side vanilla
JS baked in at build time, since the site is a static Jekyll build.

Above the board: the league's own shape (from cfb.yahoo.league) - the numbers
that decide draft strategy, led by the 2-QB roster - and below it the scoring
table and the ten teams.

    python -m cfb.site.draft        # rebuild the page
"""
import json
from datetime import datetime

import pandas as pd

from cfb import yahoo
from cfb.config import LEAGUE_TEAMS, LEAGUE_TZ, LEAGUE_URL, SEASON, WEB_DIR
from cfb.site import write_page

POSITIONS = ["QB", "RB", "WR", "TE", "DEF"]

# Row layout of the embedded JSON (arrays, not objects, to keep the page small).
_FIELDS = ["player", "pos", "team", "team_full", "bye", "adp", "avg_round",
           "pct_drafted", "rank", "pos_rank"]

# The board CSS is a slimmed copy of the NFL board's (fantasy.site.upcoming):
# same class names, so the chips / search / pills pick up their shared styling
# from docs/assets/css/custom.css, and the same sticky-header approach.
_CSS = """<style>
.adp-wrap{max-height:calc(100vh - 150px);min-height:320px;overflow:auto;
  overscroll-behavior:contain;scroll-margin-top:120px;
  border:1px solid #e5e7eb;border-radius:12px;
  background:#fff;box-shadow:0 2px 8px rgba(15,23,42,.05)}
table.adp-table{width:100%;border-collapse:separate;border-spacing:0;font-size:14px;font-family:monospace}
table.adp-table th{position:sticky;top:0;z-index:2;background:#eef2f7;color:#334155;
  padding:8px 10px;text-align:center;cursor:pointer;white-space:nowrap;font-size:12px;
  text-transform:uppercase;letter-spacing:.03em;
  border-right:1px solid #e2e8f0;border-bottom:1px solid #e2e8f0;
  -webkit-user-select:none;user-select:none}
table.adp-table th:hover{background:#e2e8f0}
table.adp-table th.sorted::after{content:' \\25BE';font-size:11px}
table.adp-table th.sorted.asc::after{content:' \\25B4'}
table.adp-table td{border-right:1px solid #eef2f7;border-bottom:1px solid #eef2f7;
  padding:5px 10px;text-align:center;white-space:nowrap;background:#fff;color:#0f172a}
table.adp-table td.name{text-align:left;font-family:inherit}
table.adp-table tbody tr:nth-child(even) td{background:#f8fafc}
table.adp-table tbody tr:hover td{background:#eef2f6}
table.adp-table td.pick{color:#4a5a68}
table.adp-table td.avg{font-weight:700}
.slot-ovr{color:#5d6b7e;font-size:12px}
.adp-meta{font-size:13px;color:#4a5a68;margin:6px 0 0}
.adp-empty{padding:14px;text-align:center;color:#666}
.cfb-league{font-size:14px;color:#334155;border:1px solid #e5e7eb;border-radius:12px;
  padding:10px 14px;background:#f8fafc;margin:10px 0}
.cfb-league b{color:#0f172a}
@media (max-width:600px){
  .adp-wrap{max-height:70vh}
  .slot-ovr{display:none}
  table.adp-table td,table.adp-table th{padding:5px 7px}
  table.adp-table td.name,table.adp-table th.name{position:sticky;left:0;
    max-width:118px;overflow:hidden;text-overflow:ellipsis;
    box-shadow:2px 0 4px -2px rgba(0,0,0,.3)}
  table.adp-table td.name{z-index:1;background:#fff}
  table.adp-table th.name{z-index:4;background:#eef2f7}
  table.adp-table tbody tr:nth-child(even) td.name{background:#f8fafc}
}
@media (prefers-color-scheme: dark){
  .adp-wrap{background:#16203a;border-color:#2b3852}
  table.adp-table th{background:#223052;color:#dde5ef}
  table.adp-table th:hover{background:#26365c}
  table.adp-table td{background:#16203a;border-color:#2b3852;color:#dde5ef}
  table.adp-table tbody tr:nth-child(even) td{background:#1b2540}
  table.adp-table tbody tr:hover td{background:#26365c}
  table.adp-table td.name{background:#16203a}
  table.adp-table th.name{background:#223052}
  table.adp-table tbody tr:nth-child(even) td.name{background:#1b2540}
  table.adp-table td.pick{color:#dde5ef}
  .slot-ovr{color:#aab7c9}
  .adp-meta,.adp-empty{color:#aab7c9}
  .cfb-league{background:#1b2540;border-color:#2b3852;color:#dde5ef}
  .cfb-league b{color:#fff}
}
</style>"""


def _cell(v):
    if isinstance(v, str):
        return v
    return None if pd.isna(v) else float(v)


def _controls() -> str:
    buttons = "".join(
        f'<button class="adp-pos{" active" if p == "ALL" else ""}" data-pos="{p}">{p}</button>'
        for p in ["ALL"] + POSITIONS)
    limits = "".join(
        f'<option value="{v}"{" selected" if v == 100 else ""}>{label}</option>'
        for v, label in [(50, "Top 50"), (100, "Top 100"), (200, "Top 200"), (0, "All")])
    return (f'<div class="adp-controls"><span class="adp-label">Position:</span>{buttons}</div>'
            '<div class="adp-controls">'
            '<input id="adp-search" type="search" placeholder="Search player or school...">'
            f'<select id="adp-limit">{limits}</select>'
            '<span class="adp-label adp-count" id="adp-count"></span></div>')


_HEADERS = [
    ("pick", "Pick", 8, f"Round and pick this board slot lands on in a "
                        f"{LEAGUE_TEAMS}-team draft, with the overall slot in brackets"),
    ("name", "Player", 0, "Player"),
    ("", "Pos", 9, "Position, and where he ranks in it on this board"),
    ("", "School", 2, "School"),
    ("", "Bye", 4, "Bye week"),
    ("avg", "ADP", 5, "Yahoo average draft pick across live drafts"),
    ("", "Avg Rd", 6, "Yahoo average round taken"),
    ("", "Drafted", 7, "Share of Yahoo leagues drafting him"),
]


def _header() -> str:
    cells = "".join(
        f'<th{" class=" + chr(34) + cls + chr(34) if cls else ""} data-col="{col}" '
        f'title="{tip}">{label}</th>'
        for cls, label, col, tip in _HEADERS)
    return f'<thead id="adp-head"><tr>{cells}</tr></thead>'


def _table_js(rows: list) -> str:
    cfg = json.dumps({"rows": rows, "teams": LEAGUE_TEAMS}, separators=(",", ":"))
    return """{% raw %}<script>
(function(){
var CFG=""" + cfg + """;
var D=CFG.rows, TEAMS=CFG.teams;
var ADP=5, RD=6, PCT=7, RANK=8, POSRK=9;
var HEADS=document.querySelectorAll('#adp-head th');
var sortCol=RANK, asc=true, pos='ALL', query='', limit=100;

function fmt(v){return v===null||v===undefined?'-':v.toFixed(1);}
function pct(v){return v===null||v===undefined?'-':Math.round(v*100)+'%';}
function slot(rank){
  var rd=Math.floor((rank-1)/TEAMS)+1, pk=(rank-1)%TEAMS+1;
  return rd+'.'+(pk<10?'0':'')+pk+' <span class="slot-ovr">('+rank+')</span>';
}

function compare(a,b){
  // Pos sorts as a draft board reads it - QB1..QB20, then RB1..
  if(sortCol===POSRK&&a[1]!==b[1]) return a[1]<b[1]?-1:1;
  var x=a[sortCol], y=b[sortCol];
  if(typeof x==='string'||typeof y==='string'){
    x=(x||'').toLowerCase(); y=(y||'').toLowerCase();
    return asc?(x<y?-1:x>y?1:0):(x>y?-1:x<y?1:0);
  }
  if(x===null&&y===null) return 0;
  if(x===null) return 1;             // missing values always sink to the bottom
  if(y===null) return -1;
  return asc?x-y:y-x;
}

function filtered(){
  var q=query.toLowerCase();
  return D.filter(function(r){
    if(pos!=='ALL'&&r[1]!==pos) return false;
    if(q&&(r[0]+' '+(r[2]||'')+' '+(r[3]||'')).toLowerCase().indexOf(q)<0) return false;
    return true;
  }).sort(compare);
}

function cells(r){
  return '<td class="pick">'+slot(r[8])+'</td>'
    +'<td class="name">'+r[0]+'</td>'
    +'<td><span class="pos-tag pos-'+r[1]+'">'+r[1]+r[9]+'</span></td>'
    +'<td title="'+(r[3]||'')+'">'+(r[2]||'-')+'</td>'
    +'<td>'+(r[4]===null?'-':r[4])+'</td>'
    +'<td class="avg">'+fmt(r[5])+'</td>'
    +'<td>'+fmt(r[6])+'</td>'
    +'<td>'+pct(r[7])+'</td>';
}

function draw(){
  var rows=filtered(), shown=limit>0?rows.slice(0,limit):rows;
  document.getElementById('adp-body').innerHTML = shown.length
    ? shown.map(function(r){return '<tr>'+cells(r)+'</tr>';}).join('')
    : '<tr><td class="adp-empty" colspan="'+HEADS.length+'">No players match.</td></tr>';
  document.getElementById('adp-count').textContent =
    'Showing '+shown.length+' of '+rows.length+' players'+(pos==='ALL'?'':' at '+pos)+'.';
  HEADS.forEach(function(th){
    var on = +th.dataset.col===sortCol;
    th.classList.toggle('sorted',on);
    th.classList.toggle('asc',on&&asc);
  });
}

HEADS.forEach(function(th){
  th.addEventListener('click',function(){
    var c=+th.dataset.col;
    if(c===sortCol){asc=!asc;} else {sortCol=c; asc=(c!==PCT);}
    draw();
  });
});
document.querySelectorAll('.adp-pos').forEach(function(b){
  b.addEventListener('click',function(){
    pos=b.dataset.pos;
    document.querySelectorAll('.adp-pos').forEach(function(x){x.classList.toggle('active',x===b);});
    draw();
  });
});
document.getElementById('adp-search').addEventListener('input',function(e){
  query=e.target.value; draw();
});
document.getElementById('adp-limit').addEventListener('change',function(e){
  limit=+e.target.value; draw();
});
draw();
})();
</script>{% endraw %}"""


# --------------------------------------------------------------------------- #
# League shape
# --------------------------------------------------------------------------- #

def _roster_line(lg: dict) -> str:
    parts = [f"{r['count']} {r['position']}" for r in lg["roster"]
             if r["position"] not in ("BN", "IL")]
    bench = next((r["count"] for r in lg["roster"] if r["position"] == "BN"), 0)
    return " · ".join(parts) + f" · {bench} bench"


def _draft_when(lg: dict) -> str | None:
    if not lg.get("draft_time"):
        return None
    dt = datetime.fromtimestamp(lg["draft_time"], tz=LEAGUE_TZ)
    return dt.strftime("%A, %B %-d · %-I:%M %p %Z")


def _mods(lg: dict) -> dict:
    return {m["name"]: m["value"] for m in lg["modifiers"] if m["name"]}


def _league_card(lg: dict) -> str:
    rounds = sum(r["count"] for r in lg["roster"] if r["position"] != "IL")
    when = _draft_when(lg)
    draft_line = (f"Draft: <b>{when}</b> — live snake, "
                  f"{int(lg['draft_pick_seconds'] or 0)}s per pick. "
                  if when and lg.get("draft_status") == "predraft" else "")
    mods = _mods(lg)
    rec = mods.get("Rec", 0)
    ppr = {1.0: "full-PPR", 0.5: "half-PPR", 0.0: "non-PPR"}.get(rec, f"{rec}/reception")
    return (
        '<div class="cfb-league">'
        f'<p><a href="{lg["url"]}"><b>{lg["name"]}</b></a> — {lg["num_teams"]} teams, '
        f'{lg["scoring_label"]}, weeks {lg["start_week"]}–{lg["end_week"]} '
        f'(playoffs from week {lg["playoff_start_week"]}).</p>'
        f'<p>{draft_line}Rosters: <b>{_roster_line(lg)}</b> — {rounds} rounds. '
        f'Scoring: <b>{ppr}</b>, {mods.get("Pass TD", 4):.0f}-pt passing TDs, '
        f'{mods.get("Int", -1):+.0f} INT.</p>'
        '<p>Two starting QBs and two flexes on a 10-team board: quarterbacks '
        'and three-down college workhorses go far earlier than an NFL board '
        'would suggest.</p>'
        '</div>')


def _scoring_table(lg: dict) -> str:
    rows = "".join(f"<tr><td>{m['name']}</td><td>{m['value']:+g}</td></tr>"
                   for m in lg["modifiers"] if m["name"])
    return ('<table class="sticky-table"><thead><tr><th>Stat</th><th>Points</th></tr></thead>'
            f"<tbody>{rows}</tbody></table>")


def _teams_table(lg: dict) -> str:
    rows = "".join(f"<tr><td>{t['name']}</td><td>{t['manager'] or '—'}</td></tr>"
                   for t in lg["teams"])
    return ('<table class="sticky-table"><thead><tr><th>Team</th><th>Manager</th></tr></thead>'
            f"<tbody>{rows}</tbody></table>")


def _details(summary: str, body: str) -> str:
    return f'<details class="section"><summary>{summary}</summary>{body}</details>'


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #

def body() -> str:
    lg = yahoo.league()
    df = yahoo.board()
    rows = [[_cell(v) for v in row]
            for row in df[_FIELDS].itertuples(index=False, name=None)]

    stamp = yahoo.board_updated()
    when = (stamp.astimezone(LEAGUE_TZ).strftime("%b %-d, %-I:%M %p %Z")
            if stamp else "an earlier build")
    with_adp = int(df["adp"].notna().sum())

    return (
        _CSS
        + '{% include countdown.html key="cfb" %}'
        + _league_card(lg)
        + "<h2>Draft Board</h2>"
        f"<p>Yahoo's college board, in Yahoo's own rank order (pulled {when}). "
        f"<strong>ADP</strong> is Yahoo's average pick across live drafts — the only "
        f"site running a college game, so there is one column of it. {with_adp} of "
        f"{len(df)} players carry one; the rest are ranked but going undrafted. "
        "<strong>Pick</strong> is where that board slot lands in this league's "
        f"{LEAGUE_TEAMS}-team snake. Click a header to sort; the position chips "
        "and search filter the pool.</p>"
        + _controls()
        + '<div class="adp-wrap"><table class="adp-table">'
        + _header()
        + '<tbody id="adp-body"></tbody></table></div>'
        + _table_js(rows)
        + _details("League Scoring", '<div class="table-scroll">'
                   + _scoring_table(lg) + "</div>")
        + _details("The Ten Teams", '<div class="table-scroll">'
                   + _teams_table(lg) + "</div>")
    )


def generate():
    write_page(WEB_DIR / "draft" / "index.html",
               f"CFB Draft Board {SEASON}", body())


if __name__ == "__main__":
    generate()
