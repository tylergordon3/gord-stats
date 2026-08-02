"""
Upcoming-draft block for the homepage.

Two pieces, both rendered by src.site.homepage:

  * countdown_banner() - live JS countdown to config.DRAFT_DATETIME.
  * adp_board_section() - the multi-site ADP board (src.league.adp_board) as a
    sortable / filterable / searchable table. The data is baked into the page as
    JSON at build time; all the interaction is vanilla JS, since the site is a
    static Jekyll build with no JS dependencies.

    python -m src.site.upcoming     # rebuilds the homepage
"""
import json

import pandas as pd

from src.config import (
    DRAFT_DATETIME, DRAFT_LABEL, LEAGUE_TEAMS, UPCOMING_SEASON, UPCOMING_YEAR,
)
from src.league.adp_board import COMPARABLE_MAX, SOURCES, board, last_updated

# Row layout for the embedded JSON (arrays, not objects - keeps the page small).
_FIELDS = ["player", "pos", "team", "bye", "Consensus", "ESPN", "FFC", "Avg", "Spread"]
POSITIONS = ["QB", "RB", "WR", "TE", "K", "DST"]


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
@media (max-width:480px){.countdown .unit{min-width:62px}.countdown .num{font-size:22px}}
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
        "teams": LEAGUE_TEAMS,
    }, separators=(",", ":"))
    return """{% raw %}<script>
(function(){
var CFG=""" + cfg + """;
var D=CFG.rows, SITES=CFG.sites, AVG=CFG.avg, SPREAD=CFG.spread, TEAMS=CFG.teams;
var HEADS=document.querySelectorAll('#adp-head th');
var sortCol=AVG, asc=true, pos='ALL', query='', limit=100;

function fmt(v){return v===null||v===undefined?'-':v.toFixed(1);}

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
  var html='<td>'+rank+'</td><td>'+round+'</td>'
          +'<td class="name">'+r[0]+'</td>'
          +'<td><span class="pos-tag pos-'+r[1]+'">'+r[1]+'</span></td>'
          +'<td>'+(r[2]||'-')+'</td><td>'+(r[3]===null?'-':r[3])+'</td>';
  SITES.forEach(function(i){
    var cls = (best!==null&&worst!==null&&best!==worst)
      ? (i===best?' class="adp-early"':i===worst?' class="adp-late"':'') : '';
    html+='<td'+cls+'>'+fmt(r[i])+'</td>';
  });
  return html+'<td>'+fmt(r[AVG])+'</td><td>'+fmt(r[SPREAD])+'</td>';
}

function draw(){
  var rows=filtered(), shown=limit>0?rows.slice(0,limit):rows;
  document.getElementById('adp-body').innerHTML = shown.length
    ? shown.map(function(r,i){return '<tr>'+cells(r,i+1)+'</tr>';}).join('')
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
    if(c<0) return;                                    // rank / round aren't sortable
    if(c===sortCol){asc=!asc;} else {sortCol=c; asc=(c!==SPREAD);}
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
draw();
})();
</script>{% endraw %}"""


def _controls() -> str:
    buttons = "".join(
        f'<button class="adp-pos{" active" if p == "ALL" else ""}" data-pos="{p}">{p}</button>'
        for p in ["ALL"] + POSITIONS
    )
    limits = "".join(f'<option value="{v}"{" selected" if v == 100 else ""}>{label}</option>'
                     for v, label in [(50, "Top 50"), (100, "Top 100"), (200, "Top 200"), (0, "All")])
    return (f'<div class="adp-controls"><span class="adp-label">Position:</span>{buttons}</div>'
            '<div class="adp-controls">'
            '<input id="adp-search" type="search" placeholder="Search player or team...">'
            f'<select id="adp-limit">{limits}</select>'
            '<span class="adp-label" id="adp-count"></span></div>')


def _header() -> str:
    """Header cells; data-col is the row index to sort on (negative = derived)."""
    labels = {"player": "Player", "pos": "Pos", "team": "Tm", "bye": "Bye"}
    cols = [(-1, "#"), (-2, "Rd")] + [(i, labels.get(f, f)) for i, f in enumerate(_FIELDS)]
    return "".join(f'<th data-col="{i}">{label}</th>' for i, label in cols)


def _stamp(year=UPCOMING_YEAR) -> str:
    when = last_updated(year)
    if not when:
        return "just now"
    hour = when.hour % 12 or 12
    return f"{when:%b} {when.day}, {hour}:{when:%M %p}"


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

    return _BOARD_CSS + intro + _controls() + table + _table_js(_rows(df))


if __name__ == "__main__":
    from src.site import homepage
    homepage.generate()
