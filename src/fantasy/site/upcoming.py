"""
Upcoming-draft block for the homepage.

Two pieces, both rendered by fantasy.site.homepage:

  * countdown_banner() - live JS countdown to config.DRAFT_DATETIME.
  * adp_board_section() - the multi-site ADP board (fantasy.league.adp_board) as a
    sortable / filterable / searchable table, plus the movement tracker: how far
    each player has climbed or slid over each window in adp_board.WINDOWS. The
    window buttons above the table drive both halves of that tracker - the risers
    / fallers cards and the table's single Move column, which re-reads whichever
    window is selected. Every window's numbers are baked into the page as JSON at
    build time; all the interaction is vanilla JS, since the site is a static
    Jekyll build with no JS dependencies.

    python -m fantasy.site.upcoming     # rebuilds the homepage
"""
import json
from datetime import datetime

import pandas as pd

from fantasy.config import (
    DRAFT_DATETIME, DRAFT_LABEL, LEAGUE_TEAMS, LEAGUE_TZ, UPCOMING_SEASON,
    UPCOMING_YEAR,
)
from fantasy.league.adp_board import (
    COMPARABLE_MAX, SOURCES, TRACKED_MAX, WINDOWS, baseline_times, board,
    last_updated, movers,
)

# Row layout for the embedded JSON (arrays, not objects - keeps the page small).
# player / pos / team lead so the JS can address them by index. Every window's
# movement ships, even though the table shows one column: the buttons switch
# between them client-side.
_MOVE_FIELDS = [w["move"] for w in WINDOWS.values()]
# Derived from SOURCES rather than listed, so adding a site to the board is one
# edit in adp_board.SOURCES and the table, its headers and the sort indices all
# follow. This list used to name the sites and silently omitted new ones.
_FIELDS = (["player", "pos", "team"] + list(SOURCES) + ["Avg"]
           + _MOVE_FIELDS + ["Spread", "Ovr", "Pick", "PosRk"])
POSITIONS = ["QB", "RB", "WR", "TE", "K", "DST"]
MOVERS_SHOWN = 8            # risers / fallers listed in the movement strip
MIN_MOVE = 0.5              # picks of drift before a player counts as "moved"


# --------------------------------------------------------------------------- #
# Countdown
# --------------------------------------------------------------------------- #

_COUNTDOWN_CSS = """<style>
.draft-banner{margin:14px 0 18px;padding:16px 18px;border-radius:14px;
  background:linear-gradient(135deg,#064e3b,#047857);color:#fff;text-align:center;
  box-shadow:0 2px 8px rgba(5,150,105,.25)}
.draft-banner .draft-when{font-size:15px;letter-spacing:.04em;opacity:.85;margin:0 0 4px}
.draft-banner .draft-title{font-size:20px;font-weight:700;margin:0 0 12px}
.countdown{display:flex;flex-wrap:wrap;gap:10px;justify-content:center}
.countdown .unit{min-width:74px;padding:8px 10px;border-radius:6px;background:rgba(255,255,255,.12)}
.countdown .num{font-size:28px;font-weight:700;font-family:monospace;line-height:1.1}
.countdown .lbl{font-size:11px;text-transform:uppercase;letter-spacing:.09em;opacity:.8}
.draft-banner .draft-note{margin:10px 0 0;font-size:13px;opacity:.8}
@media (max-width:600px){
  .draft-banner{margin:10px 0 14px;padding:14px 10px}
  .draft-banner .draft-title{font-size:18px;margin-bottom:10px}
  .draft-banner .draft-when{font-size:13px}
  .countdown{gap:6px}
  .countdown .unit{min-width:64px;padding:6px 4px}
  .countdown .num{font-size:24px}
  .draft-banner .draft-note{font-size:12px}
}
@media (max-width:360px){.countdown .unit{min-width:56px}.countdown .num{font-size:20px}}
</style>"""


def countdown_banner() -> str:
    """The draft-day countdown card that sits at the top of the homepage."""
    units = "".join(
        f'<div class="unit"><div class="num" id="cd-{key}">--</div><div class="lbl">{label}</div></div>'
        for key, label in [("d", "Days"), ("h", "Hours"), ("m", "Minutes"), ("s", "Seconds")]
    )
    js = f"""<script>
(function(){{
  var target=new Date("{DRAFT_DATETIME}").getTime();
  var box=document.getElementById('draft-countdown');
  function pad(n){{return n<10?'0'+n:''+n;}}
  function tick(){{
    var left=target-Date.now();
    if(left<=0){{
      box.innerHTML='<div class="num" style="font-size:22px">The draft is here. Good luck.</div>';
      clearInterval(timer); return;
    }}
    var s=Math.floor(left/1000);
    document.getElementById('cd-d').textContent=Math.floor(s/86400);
    document.getElementById('cd-h').textContent=pad(Math.floor(s/3600)%24);
    document.getElementById('cd-m').textContent=pad(Math.floor(s/60)%60);
    document.getElementById('cd-s').textContent=pad(s%60);
  }}
  var timer=setInterval(tick,1000); tick();
}})();
</script>"""
    return (_COUNTDOWN_CSS + '<div class="draft-banner">'
            f'<p class="draft-when">{UPCOMING_SEASON} DRAFT</p>'
            f'<p class="draft-title">{DRAFT_LABEL}</p>'
            f'<div class="countdown" id="draft-countdown">{units}</div>'
            '<p class="draft-note">Countdown shown in your local time.</p>'
            '</div>' + js)


# --------------------------------------------------------------------------- #
# ADP board
# --------------------------------------------------------------------------- #

_BOARD_CSS = """<style>
.adp-controls{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:10px 0}
.adp-controls .adp-label{font-weight:bold;font-size:14px}
.adp-controls button{padding:6px 14px;cursor:pointer;border:1px solid #e2e8f0;background:#fff;
  border-radius:999px;font-size:14px;font-weight:600;color:#334155;
  box-shadow:0 1px 2px rgba(15,23,42,.04)}
.adp-controls button:hover{background:#f1f5f9}
.adp-controls button.active{background:#059669;color:#fff;font-weight:700;border-color:#047857}
.adp-controls input,.adp-controls select{padding:6px 10px;border:1px solid #e2e8f0;
  border-radius:8px;font-size:14px;background:#fff;color:#0f172a}
.adp-controls input{min-width:170px}
.adp-wrap{max-height:620px;overflow:auto;border:1px solid #e5e7eb;border-radius:12px;
  background:#fff;box-shadow:0 2px 8px rgba(15,23,42,.05)}
/* border-collapse:separate, not collapse: collapsed borders are painted as
   part of the table's own border grid rather than with the cell, so rows
   scrolled under a position:sticky header show through its edges. Spacing is
   zeroed and the grid drawn with per-cell right/bottom borders instead. */
table.adp-table{width:100%;border-collapse:separate;border-spacing:0;font-size:14px;font-family:monospace}
table.adp-table th{position:sticky;top:0;z-index:2;background:#eef2f7;color:#334155;
  padding:8px 10px;text-align:center;cursor:pointer;white-space:nowrap;font-size:12px;
  text-transform:uppercase;letter-spacing:.03em;
  border-right:1px solid #e2e8f0;border-bottom:1px solid #e2e8f0;
  -webkit-user-select:none;user-select:none}
table.adp-table th:hover{background:#e2e8f0}
table.adp-table th.sorted::after{content:' \\25BE';font-size:11px}
table.adp-table th.sorted.asc::after{content:' \\25B4'}
table.adp-table td{border-right:1px solid #eef2f7;border-bottom:1px solid #eef2f7;padding:5px 10px;text-align:center;white-space:nowrap;
  background:#fff;color:#0f172a}
table.adp-table td.name{text-align:left;font-family:inherit}
table.adp-table tbody tr:nth-child(even) td{background:#f8fafc}
table.adp-table tbody tr:hover td{background:#eef2f6}
.pos-tag{display:inline-block;min-width:44px;padding:1px 6px;border-radius:4px;color:#fff;
  font-size:12px;font-weight:700}
.pos-QB{background:#c1436b}.pos-RB{background:#278259}.pos-WR{background:#2b7ba8}
.pos-TE{background:#946e22}.pos-K{background:#7a6bbd}.pos-DST{background:#6b7785}
/* The overall pick rides along in the slot cell, quieter than the round.pick
   it sits beside. */
.slot-ovr{color:#5d6b7e;font-size:12px}
/* Avg leads the site columns and is what the board sorts on, so it carries a
   little more weight than the working beside it. */
table.adp-table td.avg{font-weight:700}
.adp-early{background:#d8f0dd!important;color:#14532d!important}
.adp-late{background:#fadddd!important;color:#7f1d1d!important}
.adp-meta{font-size:13px;color:#4a5a68;margin:6px 0 0}
.adp-empty{padding:14px;text-align:center;color:#666}
.adp-up{color:#1a7f4b;font-weight:700}
.adp-down{color:#b3382c;font-weight:700}
.adp-flat{color:#93a1ad}
.adp-controls button.adp-toggle.active{background:#334155;border-color:#334155}
table.adp-table td.pick{color:#4a5a68}
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
.movers .mover-none{padding:10px;font-size:13px;color:#4a5a68}
.movers-window[hidden]{display:none}
.mv-since{font-size:12px;color:#4a5a68;margin:0 0 6px}
@media (max-width:600px){
  .adp-controls{gap:6px;margin:8px 0}
  /* Narrower, but still a thumb-sized target — shrinking these to 28px
     made them hard to hit on the screen they exist for. */
  .adp-controls button{padding:5px 9px;min-height:44px}
  .adp-controls input{min-width:0;flex:1 1 100%}
  .adp-controls select{flex:0 0 auto}
  .adp-controls .adp-label#adp-count{flex:1 1 100%;font-weight:normal}
  .adp-wrap{max-height:70vh}
  .movers{gap:8px}
  .movers .mover-card{flex:1 1 100%}
  /* Ovr used to be dropped here to save a column; it now rides inside the
     slot cell instead. The name stays pinned so the numbers keep a player
     attached to them while the table scrolls sideways. */
  .slot-ovr{display:none}
  table.adp-table td,table.adp-table th{padding:5px 7px}
  table.adp-table td.name,table.adp-table th.name{position:sticky;left:0;
    max-width:118px;overflow:hidden;text-overflow:ellipsis;
    box-shadow:2px 0 4px -2px rgba(0,0,0,.3)}
  table.adp-table td.name{z-index:1;background:#fff}
  table.adp-table th.name{z-index:4;background:#eef2f7}
  table.adp-table tbody tr:nth-child(even) td.name{background:#f8fafc}
}
@media (prefers-color-scheme: dark) {
  /* Every surface in this section is painted light by the rules above, so each
     one needs a dark counterpart or the dark theme's light text lands on it.
     The table cell background is the important one: setting only the even-row
     colour left the odd rows falling through to a white container, which read
     as ghost text on white. */
  .adp-wrap{background:#16203a;border-color:#2b3852}
  table.adp-table th{background:#223052;color:#dde5ef}
  table.adp-table th:hover{background:#26365c}
  table.adp-table td{background:#16203a;border-color:#2b3852;color:#dde5ef}
  table.adp-table tbody tr:nth-child(even) td{background:#1b2540}
  table.adp-table tbody tr:hover td{background:#26365c}
  table.adp-table td.name{background:#16203a}
  table.adp-table th.name{background:#223052}
  table.adp-table tbody tr:nth-child(even) td.name{background:#1b2540}

  /* Cheapest / dearest site for a row: dark tints, so they read as a highlight
     on this table rather than two light patches punched out of it. */
  .adp-early{background:#123c2e!important;color:#8ff0bd!important}
  .adp-late{background:#4a1d1d!important;color:#ffb4ae!important}

  /* Filter controls */
  .adp-controls button{background:#1b2540;border-color:#2b3852;color:#dde5ef}
  .adp-controls button:hover{background:#26365c}
  .adp-controls button.active{background:#047857;border-color:#065f46;color:#fff}
  .adp-controls input,.adp-controls select{background:#1b2540;border-color:#2b3852;color:#dde5ef}
  .adp-controls input::placeholder{color:#8b99ad}

  /* Risers / fallers cards */
  .movers .mover-card{background:#1b2540;border-color:#2b3852}
  .movers .mover-head{background:#223052;color:#dde5ef}
  /* Matching the light rules' specificity — `.movers li` is (0,2,0) and would
     otherwise keep its near-black colour on the now-dark card, which is how
     darkening these cards could have blanked the list text entirely. */
  /* Muted greys that read fine on white and vanish on dark. .adp-empty only
     appears when a filter matches nothing, so it is guarded here rather than
     found later by someone searching for a player who isn't on the board. */
  table.adp-table td.pick{color:#dde5ef}
  .slot-ovr{color:#aab7c9}
  .adp-meta,.adp-empty{color:#aab7c9}
  .movers ol,.movers li{color:#dde5ef}
  .movers .mover-none{color:#aab7c9}
  .movers .mv-pos{color:#aab7c9}
  .mv-since{color:#aab7c9}
  .adp-up{color:#6ee7b7}
  .adp-down{color:#ff9b91}
}
</style>"""


def _cell(v):
    """One JSON value: strings as-is, missing as null, everything else a number."""
    if isinstance(v, str):
        return v
    return None if pd.isna(v) else float(v)


def _rows(df: pd.DataFrame) -> list:
    """Board frame -> compact JSON rows (None for missing numbers)."""
    return [[_cell(v) for v in row]
            for row in df[_FIELDS].itertuples(index=False, name=None)]


def _table_js(rows) -> str:
    """The board's data + renderer. Wrapped in {% raw %} so Liquid leaves it alone."""
    cfg = json.dumps({
        "rows": rows,
        "sites": [_FIELDS.index(s) for s in SOURCES],
        "avg": _FIELDS.index("Avg"),
        "spread": _FIELDS.index("Spread"),
        "ovr": _FIELDS.index("Ovr"),
        "pick": _FIELDS.index("Pick"),
        "posRk": _FIELDS.index("PosRk"),
        # Window key -> its column in each row, plus the header the Move column
        # wears while that window is selected.
        "moves": {key: _FIELDS.index(spec["move"]) for key, spec in WINDOWS.items()},
        "moveHeads": {key: [spec["short"], _TIPS[spec["move"]]] for key, spec in WINDOWS.items()},
        "minMove": MIN_MOVE,
    }, separators=(",", ":"))
    return """{% raw %}<script>
(function(){
var CFG=""" + cfg + """;
var D=CFG.rows, SITES=CFG.sites, AVG=CFG.avg, SPREAD=CFG.spread;
var OVR=CFG.ovr, PICK=CFG.pick, POSRK=CFG.posRk, MOVES=CFG.moves, HEADS_MV=CFG.moveHeads;
var MINMOVE=CFG.minMove;
var HEADS=document.querySelectorAll('#adp-head th');
var MOVEHEAD=document.getElementById('adp-move');
var sortCol=AVG, asc=true, pos='ALL', query='', limit=100, moversOnly=false;
// One Move column, pointed at whichever window the buttons above have selected.
var window_='last', MOVE=MOVES[window_];

function fmt(v){return v===null||v===undefined?'-':v.toFixed(1);}

// Move is baseline ADP minus current: positive = going earlier = rising.
function moveCell(v){
  if(v===null||v===undefined) return '<td class="adp-flat">-</td>';
  if(Math.abs(v)<MINMOVE) return '<td class="adp-flat">&ndash;</td>';
  return '<td class="'+(v>0?'adp-up':'adp-down')+'">'
        +(v>0?'\\u25B2 ':'\\u25BC ')+Math.abs(v).toFixed(1)+'</td>';
}

function compare(a,b){
  // Pos sorts as a draft board reads it - QB1..QB40, then RB1.. - so the rank
  // alone (every position has a 1) is not the whole key.
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
    if(moversOnly&&(r[MOVE]===null||Math.abs(r[MOVE])<MINMOVE)) return false;
    if(q&&(r[0]+' '+(r[2]||'')).toLowerCase().indexOf(q)<0) return false;
    return true;
  }).sort(compare);
}

function cells(r){
  var best=null,worst=null;
  SITES.forEach(function(i){
    if(r[i]===null) return;
    if(best===null||r[i]<r[best]) best=i;
    if(worst===null||r[i]>r[worst]) worst=i;
  });
  // Pos carries the position and the rank in it on one tag: a green RB1.
  // Slot reads "1.1 (1)": the round.pick you actually draft at, with the
  // overall pick beside it, so the two former columns cost one.
  var slot = (r[PICK]||'-') + (r[OVR]===null?'':' <span class="slot-ovr">('+r[OVR]+')</span>');
  var html='<td class="pick">'+slot+'</td>'
          +'<td class="name">'+r[0]+'</td>'
          +'<td><span class="pos-tag pos-'+r[1]+'">'+r[1]+(r[POSRK]===null?'':r[POSRK])+'</span></td>'
          +'<td>'+(r[2]||'-')+'</td>'
          // Avg leads the sites: it is the number the board is sorted and
          // drafted on, and the per-site columns are the working behind it.
          +'<td class="avg">'+fmt(r[AVG])+'</td>';
  SITES.forEach(function(i){
    var cls = (best!==null&&worst!==null&&best!==worst)
      ? (i===best?' class="adp-early"':i===worst?' class="adp-late"':'') : '';
    html+='<td'+cls+'>'+fmt(r[i])+'</td>';
  });
  return html+moveCell(r[MOVE])+'<td>'+fmt(r[SPREAD])+'</td>';
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

HEADS.forEach(function(th){
  th.addEventListener('click',function(){
    var c=+th.dataset.col;
    if(c<0) return;                                    // Pick isn't sortable
    // Spread and Move read best biggest-first (widest disagreement, biggest risers).
    if(c===sortCol){asc=!asc;} else {sortCol=c; asc=(c!==SPREAD&&c!==MOVE);}
    draw();
  });
});
// The movers strip and the table share one window: picking "Last 3 days" swaps
// the cards and re-points the Move column - header, numbers, and any sort or
// Movers-only filter already running on it - at that window.
document.querySelectorAll('.mv-win').forEach(function(b){
  b.addEventListener('click',function(){
    var was=MOVE;
    window_=b.dataset.win; MOVE=MOVES[window_];
    document.querySelectorAll('.mv-win').forEach(function(o){o.classList.toggle('active',o===b);});
    document.querySelectorAll('.movers-window').forEach(function(w){
      w.hidden = w.dataset.win!==window_;
    });
    MOVEHEAD.dataset.col=MOVE;
    MOVEHEAD.textContent=HEADS_MV[window_][0];
    MOVEHEAD.title=HEADS_MV[window_][1];
    if(sortCol===was){sortCol=MOVE;}                   // follow the sort across
    else if(moversOnly){sortCol=MOVE; asc=false;}
    draw();
  });
});
document.querySelectorAll('.adp-pos').forEach(function(b){
  b.addEventListener('click',function(){
    pos=b.dataset.pos;
    document.querySelectorAll('.adp-pos').forEach(function(o){o.classList.toggle('active',o===b);});
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
  if(moversOnly){sortCol=MOVE; asc=false;}          // land on the biggest risers
  draw();
});
draw();
})();
</script>{% endraw %}"""


def _controls(has_movement: bool) -> str:
    buttons = "".join(
        f'<button class="adp-pos{" active" if p == "ALL" else ""}" data-pos="{p}">{p}</button>'
        for p in ["ALL"] + POSITIONS
    )
    limits = "".join(f'<option value="{v}"{" selected" if v == 100 else ""}>{label}</option>'
                     for v, label in [(50, "Top 50"), (100, "Top 100"), (200, "Top 200"), (0, "All")])
    movers_btn = ('<button id="adp-movers" class="adp-toggle">Movers only</button>'
                  if has_movement else "")
    return (f'<div class="adp-controls"><span class="adp-label">Position:</span>{buttons}</div>'
            '<div class="adp-controls">'
            '<input id="adp-search" type="search" placeholder="Search player or team...">'
            f'<select id="adp-limit">{limits}</select>{movers_btn}'
            '<span class="adp-label" id="adp-count"></span></div>')


_LABELS = {"player": "Player", "PosRk": "Pos", "team": "Tm",
           "Ovr": "Ovr", "Pick": "Pick"}
_TIPS = dict({
    "Ovr": f"Round and pick in a {LEAGUE_TEAMS}-team draft, with the overall pick in brackets",
    "Pick": f"Round and pick that lands on in a {LEAGUE_TEAMS}-team draft",
    "PosRk": "Position, and where he ranks in it on this board",
    "Avg": "Average of the site ADPs in this row",
    "Spread": f"Widest disagreement between sites (through pick {COMPARABLE_MAX})",
}, **SOURCES, **{spec["move"]: f"Picks gained ({spec['label'].lower()})"
                 for spec in WINDOWS.values()})


def _header() -> str:
    """Header cells; data-col is the row index to sort on (-2 = derived, no sort).

    The columns are re-ordered here rather than in _FIELDS: the JSON rows keep
    player / pos / team up front for the JS to address by index, while the table
    leads with the draft slot the way a draft board reads. The ovr / pick / name
    classes match the body cells, so the phone layout can drop the overall pick
    and pin the name in place (see _BOARD_CSS).

    Move is the one column whose header moves: id="adp-move" so the window
    buttons can re-point its data-col and relabel it (see _table_js).
    """
    # Pick has no sort of its own: it is Ovr in draft form, and sorting its
    # "2.10" strings as text would put 10.1 before 2.1. Sort on Ovr beside it.
    slot = [(_FIELDS.index("Ovr"), "Pick", "pick")]
    who = [(_FIELDS.index(f), _LABELS[f], "name" if f == "player" else None)
           for f in ["player", "PosRk", "team"]]
    numbers = [(_FIELDS.index(f), _LABELS.get(f, f), "avg" if f == "Avg" else None)
               for f in ["Avg"] + list(SOURCES)]
    spread = [(_FIELDS.index("Spread"), "Spread", None)]

    opening = WINDOWS["last"]
    move = (f'<th data-col="{_FIELDS.index(opening["move"])}" id="adp-move"'
            f'{_title(_TIPS[opening["move"]])}>{opening["short"]}</th>')

    cells = []
    for i, label, cls in slot + who + numbers:
        tip = _TIPS.get("Pick" if i < 0 else _FIELDS[i])
        cells.append(f'<th data-col="{i}"{_cls(cls)}{_title(tip)}>{label}</th>')
    cells.append(move)
    for i, label, cls in spread:
        cells.append(f'<th data-col="{i}"{_title(_TIPS[_FIELDS[i]])}>{label}</th>')
    return "".join(cells)


def _cls(name) -> str:
    return f' class="{name}"' if name else ""


def _title(text) -> str:
    return f' title="{text}"' if text else ""


def _when(when) -> str:
    """Timestamps as 'Aug 2, 7:25 PM ET' (no zero padding on the hour).

    Everything upstream is a file mtime or snapshot name in the build machine's
    own timezone, which nobody reading the page has any reason to share. Naive
    values are converted from local, so this reads the same whether the site was
    built on a laptop in Denver or in CI on UTC.
    """
    when = when.astimezone(LEAGUE_TZ)
    hour = when.hour % 12 or 12
    return f"{when:%b} {when.day}, {hour}:{when:%M %p} ET"


def _stamp(year=UPCOMING_YEAR) -> str:
    when = last_updated(year)
    return _when(when) if when else "just now"


# --------------------------------------------------------------------------- #
# Movement tracker
# --------------------------------------------------------------------------- #

def _mover_items(df: pd.DataFrame, spec: dict, rising: bool) -> str:
    """<li> per mover: name, position, and the baseline -> current ADP jump."""
    arrow = "▲" if rising else "▼"
    cls = "adp-up" if rising else "adp-down"
    items = []
    for r in df.itertuples(index=False):
        prev, move = getattr(r, spec["prev"]), getattr(r, spec["move"])
        items.append(
            f'<li><strong>{r.player}</strong> <span class="mv-pos">{r.pos}'
            f'{" - " + r.team if isinstance(r.team, str) and r.team else ""}</span><br>'
            f'<span class="mv-num">{prev:.1f} &rarr; {r.Avg:.1f} '
            f'<span class="{cls}">{arrow} {abs(move):.1f}</span></span></li>'
        )
    return "".join(items)


def _mover_cards(year: int, key: str, spec: dict, since) -> str:
    """One window's risers / fallers, plus how far back its baseline reaches."""
    risers, fallers = movers(year, n=MOVERS_SHOWN, min_move=MIN_MOVE, window=key)
    # A young archive can't reach the far end of a window, and then two windows
    # land on the same baseline and show the same names - say so rather than let
    # it look like nothing moved in four days.
    short = spec["delta"] and since > datetime.now() - spec["delta"]
    note = (f"<p class='mv-since'>Measured against the board pulled {_when(since)}"
            + (" - the furthest back the archive goes yet, so this window is still "
               "filling in." if short else ".") + "</p>")
    if risers.empty and fallers.empty:
        return (f"{note}<p class='adp-meta'>No player has moved more than {MIN_MOVE} "
                f"picks over this window.</p>")

    def card(title, frame, rising):
        body = (f'<ol>{_mover_items(frame, spec, rising)}</ol>' if not frame.empty
                else '<p class="mover-none">Nobody.</p>')
        return f'<div class="mover-card"><div class="mover-head">{title}</div>{body}</div>'

    return (note + '<div class="movers">'
            + card("Biggest Risers", risers, True)
            + card("Biggest Fallers", fallers, False)
            + "</div>")


def _movers_strip(year: int) -> str:
    """Risers / fallers over each window, switchable with the buttons above them.

    All three windows are rendered into the page and toggled client-side, and the
    same buttons re-point the table's sort / Movers-only filter (see _table_js).
    """
    since = baseline_times(year)
    if not any(since.values()):
        return ("<p class='adp-meta'>Movement tracking starts with the next refresh - "
                "this is the first board on record, so there is nothing to compare it to yet.</p>")

    buttons, panels = [], []
    for key, spec in WINDOWS.items():
        active = key == "last"
        buttons.append(f'<button class="mv-win{" active" if active else ""}" '
                       f'data-win="{key}">{spec["label"]}</button>')
        body = (_mover_cards(year, key, spec, since[key]) if since[key] else
                "<p class='adp-meta'>Nothing on record this far back yet.</p>")
        panels.append(f'<div class="movers-window" data-win="{key}"'
                      f'{"" if active else " hidden"}>{body}</div>')

    return (
        f"<p class='adp-meta'>How far each player has climbed "
        f"(<span class='adp-up'>&#9650;</span>) or slid "
        f"(<span class='adp-down'>&#9660;</span>) in picks. Pick a window below - it sets "
        f"these cards and the table's <strong>Move</strong> column together. "
        f"Tracked through pick {TRACKED_MAX}, and only where the same sites ranked "
        f"him at both ends - a site adding a player moves his average without anyone "
        f"changing their mind. The 3-day and week windows compare against the closest "
        f"board on record at or before that point, so they reach back only as far as the "
        f"archive does.</p>"
        f'<div class="adp-controls"><span class="adp-label">Movement:</span>'
        + "".join(buttons) + "</div>" + "".join(panels)
    )


def adp_board_section(year=UPCOMING_YEAR) -> str:
    """The interactive multi-site ADP table (or a note if no data is available)."""
    try:
        df = board(year)
    except Exception as exc:
        return f"<p>ADP data unavailable right now ({exc}).</p>"

    legend = "".join(f"<li><strong>{name}</strong> - {desc}</li>" for name, desc in SOURCES.items())
    intro = (
        f"<p>Where the field is going into the {UPCOMING_SEASON} draft, straight from each site. "
        "Click any column header to sort, filter by position, or search for a player. "
        "In each row the site that is <span class='adp-early'>highest</span> on a player and the "
        "one that is <span class='adp-late'>lowest</span> are shaded - sort by "
        "<strong>Spread</strong> to find the players the sites disagree on most.</p>"
        f"<ul>{legend}</ul>"
        f"<p class='adp-meta'>Numbers are overall picks; lower = drafted earlier. "
        f"<strong>Ovr</strong> is the overall pick, <strong>Pick</strong> is the round and "
        f"pick that lands on in our {LEAGUE_TEAMS}-team draft, and <strong>Pos</strong> is "
        f"where he ranks within his own position (RB1, WR2). "
        f"<strong>Spread</strong> (max - min across sites) is only "
        f"shown through pick {COMPARABLE_MAX}, where all three boards are dense enough to "
        f"compare - past that a gap mostly reflects how deep each site ranks, not real "
        f"disagreement. Refreshed at build time; last pulled {_stamp()}.</p>"
    )
    table = (f'<div class="adp-wrap"><table class="adp-table">'
             f'<thead id="adp-head"><tr>{_header()}</tr></thead>'
             f'<tbody id="adp-body"></tbody></table></div>')

    has_movement = df[_MOVE_FIELDS].notna().any().any()
    return (_BOARD_CSS + intro + _movers_strip(year)
            + _controls(has_movement) + table + _table_js(_rows(df)))


if __name__ == "__main__":
    from fantasy.site import homepage
    homepage.generate()
