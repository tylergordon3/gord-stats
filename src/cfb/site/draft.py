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
from gordstats.frontmatter import liquid

POSITIONS = ["QB", "RB", "WR", "TE", "DEF"]

# Row layout of the embedded JSON (arrays, not objects, to keep the page small).
# Movement columns are appended after these, one per (window, metric) pair the
# history can support (see yahoo.WINDOWS and yahoo.METRICS) - their indices ride
# in the CFG.moves map, and the controls decide which one is live.
_FIELDS = ["player", "pos", "team", "team_full", "bye", "adp", "avg_round",
           "pct_drafted", "rank", "pos_rank"]

# How long a movers card is, and the lengths offered above it.
MOVERS_SHOWN = 8
MOVERS_COUNTS = [5, 8, 15, 25]

# Which slice of the board a movers card is drawn from. "adp" is the drafted
# pool (everyone Yahoo publishes an average pick for); a number is a board-rank
# depth; 0 is the whole 450-deep pull. Depth matters most for the rank measure,
# where the undrafted tail shuffles by dozens of spots on noise alone.
MOVER_POOLS = [("adp", "Drafted pool"), ("100", "Top 100"),
               ("200", "Top 200"), ("0", "Everyone")]

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
.adp-up{color:#1a7f4b;font-weight:700}
.adp-down{color:#b3382c;font-weight:700}
.adp-flat{color:#93a1ad}
.adp-controls button.mv-win.active{background:#334155;border-color:#334155}
.movers{display:flex;flex-wrap:wrap;gap:12px;margin:10px 0 4px}
.movers .mover-card{flex:1 1 260px;min-width:0;border:1px solid #e5e7eb;border-radius:12px;
  overflow:hidden;background:#fff;box-shadow:0 2px 8px rgba(15,23,42,.05)}
.movers .mover-head{padding:6px 10px;font-size:13px;font-weight:700;letter-spacing:.03em;
  text-transform:uppercase;background:#eef2f7;color:#334155}
.movers ol,.movers li,.mover-none{color:#0f172a}
.movers ol{margin:0;padding:6px 10px 8px 26px;font-size:13px}
.movers li{padding:2px 0;line-height:1.45}
.movers .mv-pos{color:#4a5a68;font-size:12px}
.movers .mv-num{font-family:monospace;white-space:nowrap}
.movers .mv-ctx{color:#4a5a68;font-size:12px;font-family:monospace;white-space:nowrap}
.movers .mover-none{padding:10px;font-size:13px;color:#4a5a68}
.movers .mover-head .mv-what{float:right;font-weight:400;text-transform:none;
  letter-spacing:0;color:#4a5a68}
.mv-since{font-size:12px;color:#4a5a68;margin:0 0 6px}
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
  .adp-up{color:#6ee7b7}
  .adp-down{color:#ff9b91}
  .movers .mover-card{background:#1b2540;border-color:#2b3852}
  .movers .mover-head{background:#223052;color:#dde5ef}
  .movers ol,.movers li{color:#dde5ef}
  .movers .mover-none,.movers .mv-pos,.movers .mv-ctx,.mv-since{color:#aab7c9}
  .movers .mover-head .mv-what{color:#aab7c9}
}
@media (max-width:600px){
  .movers{gap:8px}
  .movers .mover-card{flex:1 1 100%}
}
</style>"""


def _cell(v):
    if isinstance(v, str):
        return v
    return None if pd.isna(v) else float(v)


def _controls(has_movement: bool) -> str:
    buttons = "".join(
        f'<button class="adp-pos{" active" if p == "ALL" else ""}" data-pos="{p}">{p}</button>'
        for p in ["ALL"] + POSITIONS)
    limits = "".join(
        f'<option value="{v}"{" selected" if v == 100 else ""}>{label}</option>'
        for v, label in [(50, "Top 50"), (100, "Top 100"), (200, "Top 200"), (0, "All")])
    # Only offered once there is a baseline to measure against - otherwise the
    # filter would empty the board.
    movers_btn = ('<button id="adp-movers" class="adp-toggle" '
                  'title="Only players who moved over the selected window">'
                  "Movers only</button>" if has_movement else "")
    return (f'<div class="adp-controls"><span class="adp-label">Position:</span>{buttons}'
            f"{movers_btn}</div>"
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


def _header(move_col: int | None) -> str:
    """The board's header. The Move column's label and tooltip are rewritten by
    the script whenever the measure changes, so they start blank-ish here."""
    cells = "".join(
        f'<th{" class=" + chr(34) + cls + chr(34) if cls else ""} data-col="{col}" '
        f'title="{tip}">{label}</th>'
        for cls, label, col, tip in _HEADERS)
    if move_col is not None:
        cells += f'<th id="adp-move" data-col="{move_col}">Move</th>'
    return f'<thead id="adp-head"><tr>{cells}</tr></thead>'


def _table_js(rows: list, cfg: dict) -> str:
    payload = json.dumps({"rows": rows, "teams": LEAGUE_TEAMS, **cfg},
                         separators=(",", ":")).replace("</", "<\\/")
    return """{% raw %}<script>
(function(){
var CFG=""" + payload + """;
var D=CFG.rows, TEAMS=CFG.teams, MOVES=CFG.moves, MET=CFG.metrics;
var ADP=5, RD=6, PCT=7, RANK=8, POSRK=9;
var HEADS=document.querySelectorAll('#adp-head th');
var MOVEHEAD=document.getElementById('adp-move');
var sortCol=RANK, asc=true, pos='ALL', query='', limit=100, moversOnly=false;
// Exactly one movement column is live at a time: the (window, measure) pair the
// buttons above the cards have selected. The cards and the table's Move column
// both read it, so the two halves of the page can never disagree.
var win=CFG.defaultWin, metric=CFG.defaultMetric;
var mvPos='ALL', mvPool=CFG.pool, mvCount=CFG.count;

function spec(){return MET[metric];}
function moveCol(){
  var m=win?MOVES[win]:null;
  return m&&m[metric]!==undefined?m[metric]:-1;
}
function stampFor(k){
  for(var i=0;i<CFG.wins.length;i++) if(CFG.wins[i].key===k) return CFG.wins[i].stamp;
  return '';
}

function fmt(v){return v===null||v===undefined?'-':v.toFixed(1);}
function pct(v){return v===null||v===undefined?'-':Math.round(v*100)+'%';}
function slot(rank){
  var rd=Math.floor((rank-1)/TEAMS)+1, pk=(rank-1)%TEAMS+1;
  return rd+'.'+(pk<10?'0':'')+pk+' <span class="slot-ovr">('+rank+')</span>';
}

// Every measure is signed the same way: positive = rising, whichever way the
// underlying number happens to run.
function mvNum(v){var s=spec(); return Math.abs(v).toFixed(s.dec)+s.suffix;}
function moveCell(v){
  var s=spec();
  if(v===null||v===undefined) return '<td class="adp-flat">-</td>';
  if(Math.abs(v)<s.min) return '<td class="adp-flat">&ndash;</td>';
  return '<td class="'+(v>0?'adp-up':'adp-down')+'">'
        +(v>0?'\u25B2 ':'\u25BC ')+mvNum(v)+'</td>';
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
  var q=query.toLowerCase(), col=moveCol(), s=spec();
  return D.filter(function(r){
    if(pos!=='ALL'&&r[1]!==pos) return false;
    if(q&&(r[0]+' '+(r[2]||'')+' '+(r[3]||'')).toLowerCase().indexOf(q)<0) return false;
    if(moversOnly&&(col<0||r[col]===null||Math.abs(r[col])<s.min)) return false;
    return true;
  }).sort(compare);
}

function cells(r){
  var col=moveCol();
  var html='<td class="pick">'+slot(r[8])+'</td>'
    +'<td class="name">'+r[0]+'</td>'
    +'<td><span class="pos-tag pos-'+r[1]+'">'+r[1]+r[9]+'</span></td>'
    +'<td title="'+(r[3]||'')+'">'+(r[2]||'-')+'</td>'
    +'<td>'+(r[4]===null?'-':r[4])+'</td>'
    +'<td class="avg">'+fmt(r[5])+'</td>'
    +'<td>'+fmt(r[6])+'</td>'
    +'<td>'+pct(r[7])+'</td>';
  if(col>=0) html+=moveCell(r[col]);
  return html;
}

function draw(){
  var rows=filtered(), shown=limit>0?rows.slice(0,limit):rows;
  document.getElementById('adp-body').innerHTML = shown.length
    ? shown.map(function(r){return '<tr>'+cells(r)+'</tr>';}).join('')
    : '<tr><td class="adp-empty" colspan="'+HEADS.length+'">No players match.</td></tr>';
  document.getElementById('adp-count').textContent =
    'Showing '+shown.length+' of '+rows.length+(moversOnly?' movers':' players')
    +(pos==='ALL'?'':' at '+pos)+'.';
  HEADS.forEach(function(th){
    var on = +th.dataset.col===sortCol;
    th.classList.toggle('sorted',on);
    th.classList.toggle('asc',on&&asc);
  });
}

// --- movers cards ---------------------------------------------------------
// Drawn here rather than baked in at build time, because the pair of cards is
// now one cell of a window x measure x position x pool x length grid, and
// shipping every combination as HTML would be most of the page.

function inPool(r){
  if(mvPool==='adp') return r[ADP]!==null;
  var depth=+mvPool;
  return depth?r[RANK]<=depth:true;
}

// What the number moved from and to, in the measure's own units.
function ctx(r,v){
  if(metric==='adp'){
    if(r[ADP]===null) return '';
    return 'ADP '+r[ADP].toFixed(1)+' \u2190 '+(r[ADP]+v).toFixed(1);
  }
  if(metric==='rank') return '#'+r[RANK]+' \u2190 #'+Math.round(r[RANK]+v);
  if(r[PCT]===null) return '';
  return Math.round(r[PCT]*100)+'% \u2190 '+Math.round(r[PCT]*100-v)+'%';
}

function moverList(rising){
  var col=moveCol(), s=spec();
  if(col<0) return '<div class="mover-none">No baseline for this window yet.</div>';
  var mv=D.filter(function(r){
    if(mvPos!=='ALL'&&r[1]!==mvPos) return false;
    if(!inPool(r)) return false;
    var v=r[col];
    return v!==null&&v!==undefined&&(rising?v>=s.min:v<=-s.min);
  }).sort(function(a,b){return rising?b[col]-a[col]:a[col]-b[col];}).slice(0,mvCount);
  if(!mv.length){
    return '<div class="mover-none">No one has '+(rising?'risen':'fallen')+' '
      +s.min+'+ '+s.unit+' here over this window.</div>';
  }
  return '<ol>'+mv.map(function(r){
    var v=r[col], cls=rising?'adp-up':'adp-down', arrow=rising?'\u25B2':'\u25BC';
    var c=ctx(r,v);
    return '<li>'+r[0]+' <span class="mv-pos">('+r[1]+' \u00b7 '+(r[2]||'?')+')</span> '
      +'<span class="mv-num '+cls+'">'+arrow+' '+mvNum(v)+'</span>'
      +(c?' <span class="mv-ctx">'+c+'</span>':'')+'</li>';
  }).join('')+'</ol>';
}

function drawMovers(){
  var s=spec(), up=document.getElementById('mv-up');
  if(!up) return;
  up.innerHTML=moverList(true);
  document.getElementById('mv-down').innerHTML=moverList(false);
  document.querySelectorAll('.mv-what').forEach(function(e){e.textContent=s.label;});
  document.getElementById('mv-since').innerHTML=
    'Against the board pulled <b>'+stampFor(win)+'</b>. '+s.tip+'.';
}

// --- wiring ---------------------------------------------------------------

HEADS.forEach(function(th){
  th.addEventListener('click',function(){
    var c=+th.dataset.col;
    // Drafted and Move read best biggest-first.
    if(c===sortCol){asc=!asc;} else {sortCol=c; asc=(c!==PCT&&c!==moveCol());}
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
var moversBtn=document.getElementById('adp-movers');
if(moversBtn) moversBtn.addEventListener('click',function(){
  moversOnly=!moversOnly;
  moversBtn.classList.toggle('active',moversOnly);
  if(moversOnly&&moveCol()>=0){sortCol=moveCol(); asc=false;}   // biggest risers first
  draw();
});

// Re-point the Move column - header, tooltip, numbers, and any sort already
// running on it - after the window or the measure changes underneath it.
function repoint(was){
  var col=moveCol(), s=spec();
  if(MOVEHEAD){
    MOVEHEAD.dataset.col=col;
    MOVEHEAD.textContent=s.short;
    MOVEHEAD.title=s.tip;
  }
  if(sortCol===was) sortCol=col>=0?col:RANK;
  draw(); drawMovers();
}
function pick(group,attr,value){
  document.querySelectorAll(group).forEach(function(x){
    x.classList.toggle('active',x.dataset[attr]===value);
  });
}
document.querySelectorAll('.mv-win').forEach(function(b){
  b.addEventListener('click',function(){
    var was=moveCol(); win=b.dataset.win; pick('.mv-win','win',win); repoint(was);
  });
});
document.querySelectorAll('.mv-metric').forEach(function(b){
  b.addEventListener('click',function(){
    var was=moveCol(); metric=b.dataset.metric; pick('.mv-metric','metric',metric);
    repoint(was);
  });
});
// The card filters exist only when there is movement to show at all.
function onSelect(id,fn){
  var el=document.getElementById(id);
  if(el) el.addEventListener('change',function(e){fn(e.target.value); drawMovers();});
}
onSelect('mv-pos',function(v){mvPos=v;});
onSelect('mv-pool',function(v){mvPool=v;});
onSelect('mv-count',function(v){mvCount=+v;});

if(MOVEHEAD){MOVEHEAD.textContent=spec().short; MOVEHEAD.title=spec().tip;}
draw();
drawMovers();
})();
</script>{% endraw %}"""


# --------------------------------------------------------------------------- #
# Movement tracker
# --------------------------------------------------------------------------- #

def _buttons(cls: str, attr: str, items: list[tuple[str, str]], first: str) -> str:
    return "".join(
        f'<button class="{cls}{" active" if key == first else ""}" '
        f'data-{attr}="{key}">{label}</button>'
        for key, label in items)


def _select(sid: str, label: str, items: list[tuple[str, str]], chosen: str) -> str:
    opts = "".join(f'<option value="{v}"{" selected" if v == chosen else ""}>{t}</option>'
                   for v, t in items)
    return (f'<span class="adp-label">{label}</span>'
            f'<select id="{sid}">{opts}</select>')


def _tracker(win_keys: list[str], default_metric: str) -> str:
    """The movement section's controls and its two empty cards. Every list the
    cards can hold is a filter of the same embedded rows, so the markup here is
    a shell and _table_js fills it - see the note above moverList()."""
    windows = _buttons("mv-win", "win",
                       [(k, yahoo.WINDOWS[k]["label"]) for k in win_keys], win_keys[0])
    measures = _buttons("mv-metric", "metric",
                        [(k, m["label"]) for k, m in yahoo.METRICS.items()],
                        default_metric)
    filters = (_select("mv-pos", "Position:",
                       [("ALL", "All positions")] + [(p, p) for p in POSITIONS], "ALL")
               + _select("mv-pool", "Pool:", MOVER_POOLS, MOVER_POOLS[0][0])
               + _select("mv-count", "Show:",
                         [(str(n), f"Top {n}") for n in MOVERS_COUNTS],
                         str(MOVERS_SHOWN)))
    card = ('<div class="mover-card"><div class="mover-head">{head}'
            '<span class="mv-what"></span></div><div id="{cid}"></div></div>')
    return (
        f'<div class="adp-controls"><span class="adp-label">Window:</span>{windows}</div>'
        f'<div class="adp-controls"><span class="adp-label">Measure:</span>{measures}</div>'
        f'<div class="adp-controls">{filters}</div>'
        '<p class="mv-since" id="mv-since"></p>'
        '<div class="movers">'
        + card.format(head="Risers", cid="mv-up")
        + card.format(head="Fallers", cid="mv-down")
        + "</div>")


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
    """Modifier values by display name, first occurrence winning: Yahoo names
    both the passing and the team-defense interception "Int", and the card
    means the offensive one, which sorts first."""
    out = {}
    for m in lg["modifiers"]:
        if m["name"] and m["name"] not in out:
            out[m["name"]] = m["value"]
    return out


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
        'would suggest. On the night, the '
        '<a href="/cfb/live/"><b>live draft board</b></a> prices all of this in '
        'points and picks for you.</p>'
        '</div>')


def _scoring_table(lg: dict) -> str:
    rows = "".join(f"<tr><td>{m['name']}</td><td>{m['value']:+g}</td></tr>"
                   for m in lg["modifiers"] if m["name"])
    return ('<table class="sticky-table"><thead><tr><th>Stat</th><th>Points</th></tr></thead>'
            f"<tbody>{rows}</tbody></table>")


def _teams_table(lg: dict) -> str:
    # Yahoo masks manager nicknames on signed-out reads; skip the column then.
    named = any(t.get("manager") for t in lg["teams"])
    rows = "".join(
        f"<tr><td>{t['name']}</td>"
        + (f"<td>{t['manager'] or '—'}</td>" if named else "") + "</tr>"
        for t in lg["teams"])
    head = "<th>Team</th>" + ("<th>Manager</th>" if named else "")
    return (f'<table class="sticky-table"><thead><tr>{head}</tr></thead>'
            f"<tbody>{rows}</tbody></table>")


def _details(summary: str, body: str) -> str:
    return f'<details class="section"><summary>{summary}</summary>{body}</details>'


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #

def body() -> str:
    lg = yahoo.league()
    df = yahoo.board()

    movement = yahoo.movement(df)
    win_keys = [k for k in yahoo.WINDOWS if k in movement]
    metric_keys = list(yahoo.METRICS)
    default_metric = metric_keys[0]

    # One embedded column per (window, measure) the archive can support; the
    # controls only ever light up one of them at a time.
    frame = df.copy()
    fields = list(_FIELDS)
    moves_idx: dict[str, dict[str, int]] = {}
    for k in win_keys:
        moves_idx[k] = {}
        for m in metric_keys:
            col = f"mv_{k}_{m}"
            frame[col] = frame["yahoo_id"].map(movement[k]["moves"][m])
            moves_idx[k][m] = len(fields)
            fields.append(col)
    rows = [[_cell(v) for v in row]
            for row in frame[fields].itertuples(index=False, name=None)]

    wins = [{"key": k, "label": yahoo.WINDOWS[k]["label"],
             "stamp": movement[k]["stamp"].astimezone(LEAGUE_TZ)
             .strftime("%b %-d, %-I:%M %p %Z")}
            for k in win_keys]
    # Only the display half of METRICS crosses into the page; how a delta is
    # computed is the data module's business.
    shown = ("label", "short", "min", "dec", "suffix", "unit", "tip")
    metrics = {k: {f: m[f] for f in shown} for k, m in yahoo.METRICS.items()}
    cfg = {"moves": moves_idx, "wins": wins, "metrics": metrics,
           "defaultWin": win_keys[0] if win_keys else None,
           "defaultMetric": default_metric,
           "pool": MOVER_POOLS[0][0], "count": MOVERS_SHOWN}

    if win_keys:
        tracker = ("<h2>Board Movement</h2>"
                   "<p>Who is climbing and sliding on Yahoo's board. Pick a "
                   "window and what to measure &mdash; the <strong>ADP</strong> "
                   "itself, Yahoo's <strong>rank order</strong> (which covers "
                   "the undrafted tail too), or the <strong>share of leagues</strong> "
                   "drafting him &mdash; then narrow the cards by position, board "
                   "depth, and length. The same choice drives the "
                   "<strong>Move</strong> column in the table below.</p>"
                   + _tracker(win_keys, default_metric))
    else:
        tracker = ("<h2>Board Movement</h2>"
                   "<p>The tracker compares the board with its archived pulls; "
                   "it appears once the history is more than a day deep.</p>")

    stamp = yahoo.board_updated()
    when = (stamp.astimezone(LEAGUE_TZ).strftime("%b %-d, %-I:%M %p %Z")
            if stamp else "an earlier build")
    with_adp = int(df["adp"].notna().sum())

    return (
        _CSS
        + liquid('{% include cfb_countdown.html %}')
        + _league_card(lg)
        + tracker
        + "<h2>Draft Board</h2>"
        f"<p>Yahoo's college board, in Yahoo's own rank order (pulled {when}). "
        f"<strong>ADP</strong> is Yahoo's average pick across live drafts — the only "
        f"site running a college game, so there is one column of it. {with_adp} of "
        f"{len(df)} players carry one; the rest are ranked but going undrafted. "
        "<strong>Pick</strong> is where that board slot lands in this league's "
        f"{LEAGUE_TEAMS}-team snake. Click a header to sort; the position chips "
        "and search filter the pool.</p>"
        + _controls(bool(win_keys))
        + '<div class="adp-wrap"><table class="adp-table">'
        + _header(moves_idx[win_keys[0]][default_metric] if win_keys else None)
        + '<tbody id="adp-body"></tbody></table></div>'
        + _table_js(rows, cfg)
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
