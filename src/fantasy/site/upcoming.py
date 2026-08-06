"""
Upcoming-draft block for the homepage.

Two pieces, both rendered by src.site.homepage:

  * countdown_banner() - live JS countdown to config.DRAFT_DATETIME.
  * adp_board_section() - the multi-site ADP board (src.league.adp_board) as a
    sortable / filterable / searchable table, plus the movement tracker: how far
    each player has climbed or slid since the previous pull (the Move column and
    the risers / fallers strip above the table). The data is baked into the page
    as JSON at build time; all the interaction is vanilla JS, since the site is a
    static Jekyll build with no JS dependencies.

    python -m src.site.upcoming     # rebuilds the homepage
"""
import json

import pandas as pd

from src.config import (
    DRAFT_DATETIME, DRAFT_LABEL, LEAGUE_TEAMS, UPCOMING_SEASON, UPCOMING_YEAR,
)
from src.league.adp_board import (
    COMPARABLE_MAX, SOURCES, TRACKED_MAX, board, last_updated, movers,
    previous_updated,
)

# Row layout for the embedded JSON (arrays, not objects - keeps the page small).
_FIELDS = ["player", "pos", "team", "bye", "Consensus", "ESPN", "FFC", "Avg", "Move", "Spread"]
POSITIONS = ["QB", "RB", "WR", "TE", "K", "DST"]
MOVERS_SHOWN = 8            # risers / fallers listed in the movement strip
MIN_MOVE = 0.5              # picks of drift before a player counts as "moved"


# --------------------------------------------------------------------------- #
# Countdown
# --------------------------------------------------------------------------- #

_COUNTDOWN_CSS = """<style>
.draft-banner{margin:14px 0 18px;padding:16px 18px;border-radius:8px;
  background:linear-gradient(135deg,#17293b,#2f4a63);color:#fff;text-align:center}
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
.adp-controls button{padding:5px 12px;cursor:pointer;border:1px solid #888;background:#eee;
  border-radius:5px;font-size:14px}
.adp-controls button.active{background:#3CB371;color:#fff;font-weight:bold;border-color:#2e8b57}
.adp-controls input,.adp-controls select{padding:5px 8px;border:1px solid #888;border-radius:5px;
  font-size:14px}
.adp-controls input{min-width:170px}
.adp-wrap{max-height:620px;overflow:auto;border:1px solid #b9c4d0;border-radius:6px}
table.adp-table{width:100%;border-collapse:collapse;font-size:14px;font-family:monospace}
table.adp-table th{position:sticky;top:0;z-index:2;background:#17293b;color:#fff;
  padding:8px 10px;text-align:center;cursor:pointer;white-space:nowrap;
  border-right:1px solid #33475c;-webkit-user-select:none;user-select:none}
table.adp-table th:hover{background:#28405a}
table.adp-table th.sorted::after{content:' \\25BE';font-size:11px}
table.adp-table th.sorted.asc::after{content:' \\25B4'}
table.adp-table td{border:1px solid #dde3ea;padding:5px 10px;text-align:center;white-space:nowrap}
table.adp-table td.name{text-align:left;font-family:inherit}
table.adp-table tbody tr:nth-child(even){background:#f5f7fa}
table.adp-table tbody tr:hover{background:#e6eef6}
.pos-tag{display:inline-block;min-width:34px;padding:1px 6px;border-radius:4px;color:#fff;
  font-size:12px;font-weight:700}
.pos-QB{background:#c1436b}.pos-RB{background:#2f9e6d}.pos-WR{background:#2b7ba8}
.pos-TE{background:#b98a2a}.pos-K{background:#7a6bbd}.pos-DST{background:#6b7785}
.adp-early{background:#d8f0dd!important}.adp-late{background:#fadddd!important}
.adp-meta{font-size:13px;color:#4a5a68;margin:6px 0 0}
.adp-empty{padding:14px;text-align:center;color:#666}
.adp-up{color:#1a7f4b;font-weight:700}
.adp-down{color:#b3382c;font-weight:700}
.adp-flat{color:#93a1ad}
.adp-controls button.adp-toggle.active{background:#17293b;border-color:#17293b}
.movers{display:flex;flex-wrap:wrap;gap:12px;margin:10px 0 4px}
.movers .mover-card{flex:1 1 260px;min-width:0;border:1px solid #b9c4d0;border-radius:6px;
  overflow:hidden;background:#fff}
.movers .mover-head{padding:6px 10px;font-size:13px;font-weight:700;letter-spacing:.03em;
  background:#17293b;color:#fff}
.movers ol{margin:0;padding:6px 10px 8px 26px;font-size:13px}
.movers li{padding:2px 0;line-height:1.45}
.movers .mv-pos{color:#4a5a68;font-size:12px}
.movers .mv-num{font-family:monospace;white-space:nowrap}
.movers .mover-none{padding:10px;font-size:13px;color:#4a5a68}
@media (max-width:600px){
  .adp-controls{gap:6px;margin:8px 0}
  .adp-controls button{padding:5px 9px}
  .adp-controls input{min-width:0;flex:1 1 100%}
  .adp-controls select{flex:0 0 auto}
  .adp-controls .adp-label#adp-count{flex:1 1 100%;font-weight:normal}
  .adp-wrap{max-height:70vh}
  .movers{gap:8px}
  .movers .mover-card{flex:1 1 100%}
  /* A phone screen only fits ~6 columns, and #/Rd/Player/Pos/Tm/Bye filled all
     of them - every ADP number sat off to the right. Drop the round (it is just
     Avg / league size) and pin the name so the numbers keep a player attached
     to them while the table scrolls sideways. */
  table.adp-table .rd{display:none}
  table.adp-table td,table.adp-table th{padding:5px 7px}
  table.adp-table td.name,table.adp-table th.name{position:sticky;left:0;
    max-width:118px;overflow:hidden;text-overflow:ellipsis;
    box-shadow:2px 0 4px -2px rgba(0,0,0,.3)}
  table.adp-table td.name{z-index:1;background:#fff}
  table.adp-table th.name{z-index:4;background:#17293b}
  table.adp-table tbody tr:nth-child(even) td.name{background:#f5f7fa}
}
</style>"""


def _rows(df: pd.DataFrame) -> list:
    """Board frame -> compact JSON rows (None for missing numbers)."""
    out = []
    for row in df[_FIELDS].itertuples(index=False, name=None):
        out.append([v if isinstance(v, str) else (None if pd.isna(v) else float(v) if i >= 3 else v)
                    for i, v in enumerate(row)])
    return out


def _table_js(rows) -> str:
    """The board's data + renderer. Wrapped in {% raw %} so Liquid leaves it alone."""
    cfg = json.dumps({
        "rows": rows,
        "sites": [_FIELDS.index(s) for s in SOURCES],
        "avg": _FIELDS.index("Avg"),
        "spread": _FIELDS.index("Spread"),
        "move": _FIELDS.index("Move"),
        "minMove": MIN_MOVE,
        "teams": LEAGUE_TEAMS,
    }, separators=(",", ":"))
    return """{% raw %}<script>
(function(){
var CFG=""" + cfg + """;
var D=CFG.rows, SITES=CFG.sites, AVG=CFG.avg, SPREAD=CFG.spread, MOVE=CFG.move;
var MINMOVE=CFG.minMove, TEAMS=CFG.teams;
var HEADS=document.querySelectorAll('#adp-head th');
var sortCol=AVG, asc=true, pos='ALL', query='', limit=100, moversOnly=false;

function fmt(v){return v===null||v===undefined?'-':v.toFixed(1);}

// Move is baseline ADP minus current: positive = going earlier = rising.
function moveCell(v){
  if(v===null||v===undefined) return '<td class="adp-flat">-</td>';
  if(Math.abs(v)<MINMOVE) return '<td class="adp-flat">&ndash;</td>';
  var cls=v>0?'adp-up':'adp-down';
  return '<td class="'+cls+'">'+(v>0?'\\u25B2 ':'\\u25BC ')+Math.abs(v).toFixed(1)+'</td>';
}

function compare(a,b){
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

function cells(r,rank){
  var best=null,worst=null;
  SITES.forEach(function(i){
    if(r[i]===null) return;
    if(best===null||r[i]<r[best]) best=i;
    if(worst===null||r[i]>r[worst]) worst=i;
  });
  var round=r[AVG]===null?'-':Math.ceil(r[AVG]/TEAMS);
  var html='<td>'+rank+'</td><td class="rd">'+round+'</td>'
          +'<td class="name">'+r[0]+'</td>'
          +'<td><span class="pos-tag pos-'+r[1]+'">'+r[1]+'</span></td>'
          +'<td>'+(r[2]||'-')+'</td><td>'+(r[3]===null?'-':r[3])+'</td>';
  SITES.forEach(function(i){
    var cls = (best!==null&&worst!==null&&best!==worst)
      ? (i===best?' class="adp-early"':i===worst?' class="adp-late"':'') : '';
    html+='<td'+cls+'>'+fmt(r[i])+'</td>';
  });
  return html+'<td>'+fmt(r[AVG])+'</td>'+moveCell(r[MOVE])+'<td>'+fmt(r[SPREAD])+'</td>';
}

function draw(){
  var rows=filtered(), shown=limit>0?rows.slice(0,limit):rows;
  document.getElementById('adp-body').innerHTML = shown.length
    ? shown.map(function(r,i){return '<tr>'+cells(r,i+1)+'</tr>';}).join('')
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
    if(c<0) return;                                    // rank / round aren't sortable
    // Spread and Move read best biggest-first (widest disagreement, biggest risers).
    if(c===sortCol){asc=!asc;} else {sortCol=c; asc=(c!==SPREAD&&c!==MOVE);}
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


def _header() -> str:
    """Header cells; data-col is the row index to sort on (negative = derived).

    The Rd / Player classes match the body cells, so the phone layout can drop
    the round column and pin the name in place (see _BOARD_CSS).
    """
    labels = {"player": "Player", "pos": "Pos", "team": "Tm", "bye": "Bye"}
    classes = {-2: "rd", 0: "name"}
    cols = [(-1, "#"), (-2, "Rd")] + [(i, labels.get(f, f)) for i, f in enumerate(_FIELDS)]
    return "".join(f'<th data-col="{i}"{_cls(classes.get(i))}>{label}</th>' for i, label in cols)


def _cls(name) -> str:
    return f' class="{name}"' if name else ""


def _when(when) -> str:
    """Timestamps as 'Aug 2, 7:25 PM' (no zero padding on the hour)."""
    hour = when.hour % 12 or 12
    return f"{when:%b} {when.day}, {hour}:{when:%M %p}"


def _stamp(year=UPCOMING_YEAR) -> str:
    when = last_updated(year)
    return _when(when) if when else "just now"


# --------------------------------------------------------------------------- #
# Movement tracker
# --------------------------------------------------------------------------- #

def _mover_items(df: pd.DataFrame, rising: bool) -> str:
    """<li> per mover: name, position, and the baseline -> current ADP jump."""
    arrow = "▲" if rising else "▼"
    cls = "adp-up" if rising else "adp-down"
    items = []
    for r in df.itertuples(index=False):
        items.append(
            f'<li><strong>{r.player}</strong> <span class="mv-pos">{r.pos}'
            f'{" - " + r.team if isinstance(r.team, str) and r.team else ""}</span><br>'
            f'<span class="mv-num">{r.Prev:.1f} &rarr; {r.Avg:.1f} '
            f'<span class="{cls}">{arrow} {abs(r.Move):.1f}</span></span></li>'
        )
    return "".join(items)


def _movers_strip(year: int) -> str:
    """Biggest risers / fallers since the previous pull (empty before baseline)."""
    since = previous_updated(year)
    if not since:
        return ("<p class='adp-meta'>Movement tracking starts with the next refresh - "
                "this is the first board on record, so there is nothing to compare it to yet.</p>")

    risers, fallers = movers(year, n=MOVERS_SHOWN, min_move=MIN_MOVE)
    if risers.empty and fallers.empty:
        return (f"<p class='adp-meta'>No player has moved more than {MIN_MOVE} picks since "
                f"the last pull ({_when(since)}).</p>")

    def card(title, frame, rising):
        body = (f'<ol>{_mover_items(frame, rising)}</ol>' if not frame.empty
                else '<p class="mover-none">Nobody.</p>')
        return f'<div class="mover-card"><div class="mover-head">{title}</div>{body}</div>'

    return (
        f"<p class='adp-meta'>Movement since the previous pull ({_when(since)}): "
        f"<strong>Move</strong> is how many picks earlier (<span class='adp-up'>&#9650;</span>) "
        f"or later (<span class='adp-down'>&#9660;</span>) a player is going now. "
        f"Sort by <strong>Move</strong>, or hit <strong>Movers only</strong>, to see it "
        f"across the whole board. Tracked through pick {TRACKED_MAX}, and only where the "
        f"same sites ranked him both times - a site adding a player moves his average "
        f"without anyone changing their mind.</p>"
        '<div class="movers">'
        + card("Biggest Risers", risers, True)
        + card("Biggest Fallers", fallers, False)
        + "</div>"
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
        f"<strong>Rd</strong> is the round the average ADP lands in for our {LEAGUE_TEAMS}-team "
        f"league. <strong>Spread</strong> (max - min across sites) is only shown through pick "
        f"{COMPARABLE_MAX}, where all three boards are dense enough to compare - past that a gap "
        f"mostly reflects how deep each site ranks, not real disagreement. "
        f"Refreshed at build time; last pulled {_stamp()}.</p>"
    )
    table = (f'<div class="adp-wrap"><table class="adp-table">'
             f'<thead id="adp-head"><tr>{_header()}</tr></thead>'
             f'<tbody id="adp-body"></tbody></table></div>')

    has_movement = df["Move"].notna().any()
    return (_BOARD_CSS + intro + _movers_strip(year)
            + _controls(has_movement) + table + _table_js(_rows(df)))


if __name__ == "__main__":
    from src.site import homepage
    homepage.generate()
