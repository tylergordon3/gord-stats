"""
College football power rankings (docs/cfb/power/): every FBS team.

Ratings are ESPN's Football Power Index, read from the public API behind
espn.com's own FPI page. Preseason it is ESPN's projection model; in season
it updates with results, so - like the CBB page - whatever FPI believes
today is what renders, with no seasonal switch.

The API carries about twenty figures per team as bare positional arrays,
which is why this page long showed only the two it could name for certain.
It now reads the payload's own header block for the position of each field
by name, so a column can never quietly come to hold the number next to it -
the failure that kept the rest of them off the page. Two tabs divide
them: Rating (the ratings with their ranks, schedule strength and, in
season, ESPN's resume ranks) and Odds (the simulation probabilities).

A figure ESPN has not computed yet reads as "-" in the payload rather than
zero, so a column stays hidden until some team has one - the resume ranks
appear by themselves once games are played.

Beside the computer number: the AP poll where one exists for this season
(the human column), our own GordStats rating with its rank (the number the
predictions run on, from cfb.predict via cfb.site.teams), and Move columns
against the snapshot archive (gordstats.rankmoves) once it has more than
one build in it. This is the one rankings page: the GordStats index that
lived at /cfb/teams/ redirects here, and each team links to its own page.

    python -m cfb.site.power             # cached JSON if fresh
    python -m cfb.site.power --refresh
"""
import argparse
import json
import time
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from cfb import cfbd, espn, predict
from cfb.config import DATA_DIR, SEASON, WEB_DIR
from cfb.site import teams as teams_page
from cfb.site import write_page
from gordstats import favorites, logos, rankmoves, share_card

_URL = ("https://site.web.api.espn.com/apis/fitt/v3/sports/football/"
        "college-football/powerindex")
_AP_URL = ("https://site.api.espn.com/apis/site/v2/sports/football/"
           "college-football/rankings")
HISTORY_DIR = DATA_DIR / "power_history" / str(SEASON)
# Same no-UA convention as cfb.espn: ESPN's edge 403s a browser UA coming
# from a non-browser TLS stack, and answers requests' own UA normally.
_HEADERS = {}
_TIMEOUT = 25
MAX_AGE_HOURS = 12
ET = ZoneInfo("America/New_York")

_CSS = """<style>
/* Separate borders, not collapsed: a collapsed border belongs to the grid,
   not the cell, so a sticky header row left its border behind and the rows
   scrolling under it showed through the gap. With each cell owning its right
   and bottom edge the header is a solid bar. */
table.cfb-power{width:100%;border-collapse:separate;border-spacing:0;font-size:14px;margin:0}
table.cfb-power th{background:#eef2f7;color:#334155;padding:7px 10px;text-align:center;
  font-size:12px;text-transform:uppercase;letter-spacing:.03em;white-space:nowrap;
  border:0;border-right:1px solid #e2e8f0;border-bottom:1px solid #e2e8f0;position:sticky;top:0}
table.cfb-power td{padding:6px 10px;border:0;border-right:1px solid #eef2f7;
  border-bottom:1px solid #eef2f7;color:#0f172a;background:#fff;
  text-align:center;white-space:nowrap}
table.cfb-power th:last-child,table.cfb-power td:last-child{border-right:0}
table.cfb-power td.pwr-team{text-align:left;font-weight:600}
table.cfb-power td.pwr-team a{color:inherit;text-decoration:none}
/* A 15px-tall link: padding makes the finger's target taller without moving
   the row. */
table.cfb-power td.pwr-team a{padding:10px 0}
table.cfb-power td.pwr-team a:hover{text-decoration:underline}
/* The GordStats rank rides beside its rating, quiet. */
table.cfb-power td .gs-rk{display:inline-block;min-width:22px;text-align:right;
  font-size:12px;color:#64748b;margin-right:6px}
/* The mascot is the first thing to go when the window narrows: at half a
   screen "Ohio State Buckeyes" pushes the figures off the right edge, and
   "Ohio State" says the same thing. */
@media (max-width:1000px){table.cfb-power .pwr-masc{display:none}}
table.cfb-power tbody tr:nth-child(even) td{background:#f8fafc}
table.cfb-power tr.top25 td{background:#fdf6e3}
table.cfb-power tr.top25:nth-child(even) td{background:#faf0d2}
/* The Slate theme styles every <img> as a framed figure - padding, a border,
   a drop shadow and 10px vertical margins - which boxes each logo and stretches
   the row. Reset all of it here, same as the league table does. */
table.cfb-power td.pwr-team img{width:22px;height:22px;object-fit:contain;
  vertical-align:middle;margin:0 8px 0 0;border:none;padding:0;box-shadow:none;
  background:none;border-radius:0}
/* One table, two tabs: the live view keeps its own columns and hides the
   rest. Cheaper than two tables, and the sort survives a tab change. */
table.cfb-power.view-rating td:not(.v-rating),table.cfb-power.view-rating th:not(.v-rating),
table.cfb-power.view-odds td:not(.v-odds),table.cfb-power.view-odds th:not(.v-odds){
  display:none}
/* The record rides in the Team cell, quiet beside the name. */
table.cfb-power td.pwr-team .pwr-rec{font-weight:400;font-size:12px;color:#64748b;margin-left:7px}
table.cfb-power th.sortable{cursor:pointer;user-select:none}
table.cfb-power th.sortable:hover{color:#0f172a}
/* The caret is always drawn, faint until the column is the one sorting, so a
   header never changes width on click and the sticky row stays put. */
table.cfb-power th.sortable::after{content:"\\2195";margin-left:5px;opacity:.35;
  font-size:11px}
table.cfb-power th.sorted.asc::after{content:"\\25B2";opacity:1}
table.cfb-power th.sorted.desc::after{content:"\\25BC";opacity:1}
/* The live column, header and body: a tint over whatever the row already
   paints. A pseudo-element rather than a background, because the zebra and
   Top 25 rules set the background with more specificity than a class on
   the cell can beat. Team is already sticky (positioned), the rest need to
   be for the overlay to anchor. */
table.cfb-power th.sorted{background:#dbe7f6;color:#0f172a}
table.cfb-power td.sorted-col{font-weight:700}
table.cfb-power td.sorted-col:not(:first-child){position:relative}
table.cfb-power td.sorted-col::after{content:"";position:absolute;inset:0;
  background:rgba(37,99,235,.09);pointer-events:none}
table.cfb-power th.mv-th .mv-of{font-weight:500;opacity:.75;margin-left:5px;text-transform:none}
/* Places climbed answers "did it move"; the rating's own change answers "by
   how much", which a one-place move in a tight table can badly overstate. It
   is printed in the rating's own cell rather than packed into the Move cell,
   beside the number it is the change in. */
table.cfb-power td .pwr-chg{font-size:11px;margin-left:6px;font-variant-numeric:tabular-nums}
table.cfb-power td .pwr-chg:empty{display:none}
@media (max-width:600px){table.cfb-power td .pwr-chg{display:none}}
/* Team is the first cell in every view, so pinning first-child holds the
   identity column while the wide tabs scroll. The cells already carry opaque
   backgrounds (zebra, top25, dark) from the rules above; the z-indexes keep
   header over body and the top-left corner over both. */
table.cfb-power th{z-index:2}
table.cfb-power td:first-child{position:sticky;left:0;z-index:1}
table.cfb-power th:first-child{left:0;z-index:3}
.power-wrap{overflow:auto;border:1px solid #e5e7eb;
  border-radius:12px;box-shadow:0 2px 8px rgba(15,23,42,.05)}
/* Desktop: the table fits, so the frame need not scroll at all - the page
   does, one scrollbar, and the column header sticks under the site header
   and the pinned controls (both measured into CSS variables by the layout).
   A frame that scrolls sideways on a phone is its own scroll container,
   which is where the header would stick instead - so phones keep the frame
   and lose the pinned header. */
@media (min-width:768px){
  .power-wrap{overflow:visible}
  table.cfb-power th{top:calc(var(--header-h,54px) + var(--pin-h,0px))}
  table.cfb-power th:first-child{border-top-left-radius:0}
}
.power-note{font-size:13px;color:#4a5a68;margin:6px 0 10px}
""" + rankmoves.CSS + """
@media (max-width:600px){
  table.cfb-power{font-size:13px}
  table.cfb-power td{padding:5px 7px}
}
@media (prefers-color-scheme: dark){
    table.cfb-power th{background:#223052;color:#dde5ef;border-color:#2b3852}
  table.cfb-power th.sortable:hover{color:#fff}
  table.cfb-power th.sorted{background:#2f4a7a;color:#fff}
  table.cfb-power td.sorted-col::after{background:rgba(147,197,253,.13)}
  table.cfb-power td{background:#16203a;border-color:#2b3852;color:#dde5ef}
  table.cfb-power tbody tr:nth-child(even) td{background:#1b2540}
  table.cfb-power tr.top25 td{background:#33301a}
  table.cfb-power tr.top25:nth-child(even) td{background:#3a361e}
  /* Several teams ship a near-black logo; a faint halo keeps them readable
     against the navy rows. */
  table.cfb-power td.pwr-team img{filter:drop-shadow(0 0 1px rgba(255,255,255,.6))}
  .power-note{color:#aab7c9}
  .power-wrap{border-color:#2b3852}
  table.cfb-power td.pwr-team .pwr-rec{color:#aab7c9}
  table.cfb-power td .gs-rk{color:#aab7c9}
}
</style>"""

# The rows are already rendered by the time this runs, so sorting reorders the
# <tr>s that are there rather than redrawing them from a payload: the Move
# arrows, the Top 25 highlight and the logos all travel with their team, and
# with JS off the page is still the table sorted by rank.
_JS = """{% raw %}<script>
(function(){
var table=document.querySelector('table.cfb-power');
if(!table||!table.tHead||!table.tBodies.length) return;
var head=table.tHead.rows[0], body=table.tBodies[0];
var rows=Array.prototype.slice.call(body.rows);

// --- the Move column ------------------------------------------------------------
// Move follows the column the table is sorted by: places climbed in the
// GordStats rank until the reader sorts by FPI, Playoff%, SOS or anything else,
// and then that figure's change. Every window's figure for every tracked
// column is in DELTA, as one array per (window, column) in rank order - the
// order `rows` never leaves.
var data=document.getElementById('pwr-deltas');
var DELTA={},KIND={},WHEN={},CHG={},DEFAULT='gs_rank';
if(data){try{var d=JSON.parse(data.textContent);DELTA=d.deltas;KIND=d.kinds;WHEN=d.when;CHG=d.chg;}catch(e){}}
var moveTh=head.querySelector('th.mv-th'), baseTh=head.querySelector('th.sortable[data-field=gs_rank]');
var moveI=moveTh?Array.prototype.indexOf.call(head.cells,moveTh):-1;
var win=null, field=DEFAULT;
var first=document.querySelector('.win-btn.active');
if(first) win=first.getAttribute('data-win');

function arrow(v){
  v=Math.round(v);
  if(v===0) return "<span class='mv-flat'>&middot;</span>";
  return v>0?"<span class='mv-up'>&#9650;"+v+"</span>":"<span class='mv-down'>&#9660;"+(-v)+"</span>";
}
function signed(v,dec){
  if(Math.abs(v)<0.5*Math.pow(10,-dec)) return "<span class='mv-flat'>&middot;</span>";
  return "<span class='"+(v>0?'mv-up':'mv-down')+"'>"+(v>0?'+':'')+v.toFixed(dec)+"</span>";
}
function draw(){
  if(moveI<0) return;
  var col=(DELTA[win]||{})[field], kind=KIND[field]||{k:'num',d:1,label:field,tip:field+' change'};
  // A ranking column carries its own figure too (FPI's rating, GordStats'),
  // so the cell says both: places climbed, and how far the number itself moved.
  var amt=kind.v?(DELTA[win]||{})[kind.v]:null;
  rows.forEach(function(r,k){
    var td=r.cells[moveI], v=col?col[k]:null;
    if(v===null||v===undefined){td.innerHTML='';return;}
    // A rating that did not move prints nothing rather than "(.)": the dot
    // beside the arrow's own dot was two ways of saying the same nothing.
    var a=amt?amt[k]:null, flat=(a===null||a===undefined)||Math.abs(a)<0.5*Math.pow(10,-kind.vd);
    td.innerHTML=kind.k!=='rank'?signed(v,kind.d)
      :arrow(v)+(flat?'':"<span class='mv-amt'>("+signed(a,kind.vd)+")</span>");
  });
  moveTh.innerHTML='Move'+(kind.label?"<span class='mv-of'>"+kind.label+"</span>":'');
  moveTh.title=kind.tip+(WHEN[win]?' since '+WHEN[win]:'');
}

// --- sorting -------------------------------------------------------------------
// Every sortable cell carries data-sort; a cell without one (a team outside the
// AP poll, a resume rank ESPN hasn't computed) sorts as missing and sinks to the
// bottom in both directions.
function val(row,i){
  var cell=row.cells[i], v=cell?cell.dataset.sort:undefined;
  return v===undefined||v===''?null:v;
}

// Numbers where both cells are numbers, text otherwise.
function compare(x,y){
  var nx=parseFloat(x), ny=parseFloat(y);
  if(!isNaN(nx)&&!isNaN(ny)) return nx-ny;
  return String(x).localeCompare(String(y));
}

function sortBy(th,force){
  var i=Array.prototype.indexOf.call(head.cells,th);
  // Move tracks the column being sorted: places climbed on FPI, otherwise
  // that figure's change.
  var f=th.dataset.field||DEFAULT;
  if(f!==field){field=f;draw();}
  // A column that is already the live one reverses; one being picked up opens
  // in the direction it reads best, even if it was left reversed earlier. The
  // tab switcher passes the direction it wants, so falling back never flips.
  var dir=force||(th.dataset.now?(th.dataset.now==='asc'?'desc':'asc'):th.dataset.dir);
  var sorted=rows.slice().sort(function(a,b){
    var x=val(a,i), y=val(b,i);
    if(x===null&&y===null) return 0;
    if(x===null) return 1;
    if(y===null) return -1;
    return dir==='asc'?compare(x,y):compare(y,x);
  });
  // Ties keep the order they came in, which is rank order: sort is stable and
  // `rows` is never re-read from the DOM.
  var frag=document.createDocumentFragment();
  sorted.forEach(function(r){frag.appendChild(r);});
  body.appendChild(frag);
  Array.prototype.forEach.call(head.cells,function(c){
    c.classList.remove('sorted','asc','desc');
    c.removeAttribute('aria-sort');
    delete c.dataset.now;
  });
  th.classList.add('sorted',dir);
  th.dataset.now=dir;
  th.setAttribute('aria-sort',dir==='asc'?'ascending':'descending');
  // The sorted column is tinted down the body too, so the Move figures have
  // a visible column to refer to.
  rows.forEach(function(r){
    Array.prototype.forEach.call(r.cells,function(c,k){c.classList.toggle('sorted-col',k===i);});
  });
}

Array.prototype.forEach.call(head.cells,function(th){
  if(!th.classList.contains('sortable')) return;
  th.tabIndex=0;
  th.addEventListener('click',function(){sortBy(th);});
  th.addEventListener('keydown',function(e){
    if(e.key==='Enter'||e.key===' '){e.preventDefault(); sortBy(th);}
  });
});

// --- the change in each rating's own cell ---------------------------------
// FPI and GordStats print how far the rating itself has moved beside the
// rating, where the Move column can only ever describe one figure at a time.
function drawChanges(){
  var cells=body.querySelectorAll('.pwr-chg');
  Array.prototype.forEach.call(cells,function(span){
    var f=span.getAttribute('data-chg'), col=(DELTA[win]||{})[f];
    var k=Array.prototype.indexOf.call(rows,span.closest('tr'));
    var v=(col&&k>=0)?col[k]:null, dec=CHG[f]===undefined?1:CHG[f];
    // Flat prints nothing here - see _chg in the generator.
    span.innerHTML=(v===null||v===undefined||Math.abs(v)<0.5*Math.pow(10,-dec))?'':signed(v,dec);
    span.title=(v===null||v===undefined)?'':
      f.toUpperCase().replace('GS','GordStats')+' change since '+(WHEN[win]||'the last build');
  });
}

// A new window redraws the Move column and the ratings' own changes.
document.addEventListener('winchange',function(e){win=e.detail;draw();drawChanges();});

// --- tabs -----------------------------------------------------------------
var TABS=document.querySelectorAll('.pv-btn');
Array.prototype.forEach.call(TABS,function(btn){
  btn.addEventListener('click',function(){
    var view=btn.dataset.view;
    table.className='cfb-power view-'+view;
    Array.prototype.forEach.call(TABS,function(b){b.classList.toggle('active',b===btn);});
    // A sort running on a column this tab doesn't show would leave the table in
    // an order with nothing on screen to explain it, so it falls back to the
    // GordStats order the page opens in - the live column then being one this
    // tab hides, nothing is tinted.
    var live=head.querySelector('th.sorted');
    if(live&&!live.classList.contains('v-'+view)&&baseTh) sortBy(baseTh,baseTh.dataset.dir);
  });
});
})();
</script>{% endraw %}"""


def _cache_path():
    return DATA_DIR / f"fpi_{SEASON}.json"


def fpi(refresh: bool = False) -> dict:
    """The raw FPI payload, cached under data/cfb/ and refreshed twice a day."""
    cache = _cache_path()
    fresh = cache.exists() and (time.time() - cache.stat().st_mtime) < MAX_AGE_HOURS * 3600
    if cache.exists() and (fresh and not refresh):
        return json.loads(cache.read_text(encoding="utf-8"))
    try:
        r = requests.get(_URL, params={"region": "us", "lang": "en",
                                       "limit": 300, "season": SEASON},
                         headers=_HEADERS, timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        assert data.get("teams"), "no teams in FPI payload"
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data), encoding="utf-8")
    except Exception as exc:
        if not cache.exists():
            raise
        print(f"  ! FPI fetch failed ({exc}); using the cached copy")
        data = json.loads(cache.read_text(encoding="utf-8"))
    return data


def ap_poll(refresh: bool = True, others: bool = False):
    """({espn team id: AP rank}, poll season year, poll label), or (None, None, None).

    Fetched on every build: the poll moves once a week and this is one small
    request, so a 12-hour cache only ever served a stale Sunday. The cached
    copy is the fallback when ESPN does not answer.

    `others` goes on down "others receiving votes" by points, 26 and on, ties
    sharing a place - where the poll puts a team it does not rank.
    """
    cache = DATA_DIR / "ap.json"
    data = None
    if cache.exists() and not refresh:
        data = json.loads(cache.read_text(encoding="utf-8"))
    else:
        try:
            r = requests.get(_AP_URL, headers=_HEADERS, timeout=_TIMEOUT)
            r.raise_for_status()
            data = r.json()
            assert data.get("rankings"), "no rankings in AP payload"
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(data), encoding="utf-8")
        except Exception as exc:
            if cache.exists():
                print(f"  ! AP fetch failed ({exc}); using the cached copy")
                data = json.loads(cache.read_text(encoding="utf-8"))
            else:
                print(f"  ! AP poll unavailable ({exc}); page renders without it")
    for poll in (data or {}).get("rankings", []):
        if poll.get("name") != "AP Top 25":
            continue
        season = (poll.get("season") or {}).get("year")
        label = (poll.get("occurrence") or {}).get("displayValue") or ""
        ranks = {str((r.get("team") or {}).get("id")): int(r["current"])
                 for r in poll.get("ranks", []) if r.get("current")}
        if ranks and others:
            votes = sorted(((float(o.get("points") or 0), str((o.get("team") or {}).get("id")))
                            for o in poll.get("others", []) if o.get("points")),
                           key=lambda v: -v[0])
            top, place, last = len(ranks), len(ranks), None
            for i, (points, team_id) in enumerate(votes):
                if points != last:
                    place, last = top + 1 + i, points
                ranks.setdefault(team_id, place)
        return (ranks or None), season, label
    return None, None, None


# Each team's figures arrive as two parallel arrays: `values` holds the raw
# numbers and `totals` ESPN's own rendering of them, where "-" means the figure
# does not exist yet. Reading both is what lets a column tell a real 0% from a
# resume number that no team can have until games are played.
_FIELDS = {
    "fpi": ["fpi", "projectedw", "projectedl", "probwinout", "prob6wins",
            "probmakeplayoffs", "probwintitle", "probwinconf",
            "numwins", "numlosses", "numties"],
    "resume": ["accomplishmentrank", "avgsosrank", "sosremainingrank",
               "gamecontrolrank"],
}
# Where those fields sat when this was written, used only if a payload arrives
# without its header block. The three the page has always read - FPI and the
# projected record - are the ones worth surviving that.
_FALLBACK = {"fpi": {"fpi": 0, "projectedw": 3, "projectedl": 4}, "resume": {}}


def _field_index(data: dict) -> dict:
    """{category: {field name: position}}, read from the payload's own header.

    The per-team arrays are positional and unlabelled; the top-level categories
    list is where ESPN says what each slot holds. Taking the map from there
    means a column inserted upstream shifts nothing here.
    """
    index = {c.get("name"): {n: i for i, n in enumerate(c.get("names") or [])}
             for c in data.get("categories") or []}
    return {cat: index.get(cat) or _FALLBACK[cat] for cat in _FIELDS}


def _figures(entry: dict, index: dict) -> dict:
    """{field name: float or None} for one team, None where ESPN prints "-"."""
    out = {}
    for cat_name, fields in _FIELDS.items():
        cat = next((c for c in entry["categories"] if c.get("name") == cat_name), {})
        values, totals = cat.get("values") or [], cat.get("totals") or []
        for field in fields:
            pos = index[cat_name].get(field)
            shown = totals[pos].strip() if pos is not None and pos < len(totals) else "-"
            if pos is None or pos >= len(values) or shown in ("-", ""):
                out[field] = None
                continue
            try:
                out[field] = float(values[pos])
            except (TypeError, ValueError):
                out[field] = None
    return out


def _rows(data: dict) -> list:
    """One dict per team - name, logo, conference and every figure - best first."""
    index = _field_index(data)
    out = []
    for entry in data["teams"]:
        team = entry["team"]
        figures = _figures(entry, index)
        if figures["fpi"] is None:
            continue
        logos = team.get("logos") or []
        group = team.get("group") or {}
        name = team.get("displayName") or team.get("nickname")
        # "Ohio State Buckeyes" is the school plus the mascot ESPN calls
        # `name`. Split off the tail rather than using `nickname`, which
        # abbreviates ("Mississippi St", "Jax State").
        mascot = team.get("name") or ""
        school = (name[:-len(mascot)].rstrip()
                  if mascot and name and name.endswith(" " + mascot) else name)
        out.append({
            "id": str(team.get("id")),
            "name": name,
            "school": school,
            "mascot": name[len(school):] if school != name else "",
            "logo": logos[0]["href"] if logos else None,
            "conf": group.get("shortName"),
            **figures,
        })
    return sorted(out, key=lambda t: -t["fpi"])


# The three tabs, and the columns each one carries. One table holds every
# column and the tab hides the ones it does not want, so switching tabs keeps
# the rows, the sort and the highlight exactly where they were.
VIEWS = [("rating", "Rating"), ("odds", "Odds")]
ALL = tuple(v for v, _ in VIEWS)

# Columns built and archived but kept off the table. The projected record
# lives on each team's page now, beside the other sources' projections; game
# control was more noise than signal next to SOR. Flip one back to show it -
# every snapshot still carries both figures, so its Move history is intact.
SHOW_PROJ_RECORD = False
SHOW_GAME_CONTROL = False

# The figures each snapshot archives beyond the rank, and how a change in each
# reads: "num" is the value now minus the baseline's, to `dec` places; "rank"
# is places climbed (baseline minus now), drawn with arrows. Every sortable
# column names one of these, and the Move column shows whichever the table is
# sorted by. Older snapshots lack most of them - a window whose baseline
# predates a figure shows nothing for it, not a wrong number.
TRACKED = {
    "rank": ("rank", 0), "fpi": ("num", 1), "ap": ("rank", 0), "numwins": ("num", 0),
    "gs": ("num", 1), "gs_rank": ("rank", 0),
    "sp": ("num", 1), "sp_rank": ("rank", 0), "elo": ("num", 0),
    "projectedw": ("num", 1), "probmakeplayoffs": ("num", 1), "probwinconf": ("num", 1),
    "prob6wins": ("num", 1), "probwinout": ("num", 1), "probwintitle": ("num", 1),
    "avgsosrank": ("rank", 0), "sosremainingrank": ("rank", 0),
    "accomplishmentrank": ("rank", 0), "gamecontrolrank": ("rank", 0),
}


def _td(views, value, text, team=False, sortable=True, extra="") -> str:
    cls = " ".join(f"v-{v}" for v in views) + (" pwr-team" if team else "") + extra
    if isinstance(value, float):
        value = round(value, 3)      # ESPN sends 38.800000000000004
    key = f" data-sort='{value}'" if sortable and value is not None else ""
    return f"<td class='{cls}'{key}>{text}</td>"


def _th(views, label, tip, direction, first=False, team=False, tips=None,
        field=None, extra="") -> str:
    cls = " ".join(f"v-{v}" for v in views) + (" pwr-team" if team else "") + extra
    if direction:
        cls += " sortable"
    if tips:
        cls += " win-th"
    attrs = f' title="{escape(tip, quote=True)}"' if tip else ""
    if tips:
        attrs += f" data-tips='{tips}'"
    if direction:
        attrs += f" data-dir='{direction}'"
    if field:
        attrs += f" data-field='{field}'"
    # The table is written in GordStats order, so that column opens as the
    # live one, in its own direction.
    if first:
        cls += f" sorted {direction}"
        attrs += f" data-now='{direction}' aria-sort='{'ascending' if direction == 'asc' else 'descending'}'"
    return f"<th class='{cls}'{attrs}>{label}</th>"


def _plain(v):
    """A rank cell: the integer, or nothing at all when there isn't one."""
    return (None, "") if v is None else (int(v), f"{int(v)}")


def _pct(v):
    """A probability cell. A real 0% is drawn as a dot - a column like Title%
    is mostly zeros, and 130 rows of "0.0%" bury the teams that have a chance -
    but it still sorts as the zero it is, above the teams with no figure."""
    if v is None:
        return None, ""
    return v, ("<span class='mv-flat'>&middot;</span>" if v == 0 else f"{v:.1f}%")


def _record(t) -> str:
    w, l, ties = t["numwins"] or 0, t["numlosses"] or 0, t["numties"] or 0
    return f"{w:.0f}-{l:.0f}" + (f"-{ties:.0f}" if ties else "")


def _team(t, record: bool) -> str:
    logo = logos.img("ncaa", t["id"], 22) if t["logo"] else ""
    rec = f"<span class='pwr-rec'>{_record(t)}</span>" if record else ""
    label = t["school"] + (f"<span class='pwr-masc'>{t['mascot']}</span>" if t["mascot"] else "")
    # A rated team has a page of its own; the name is the way there.
    name = (f"<a href='/cfb/teams/{teams_page.team_slug(t['gs_name'])}/'>{label}</a>"
            if t.get("gs_name") else label)
    return logo + name + rec + favorites.star("cfb", t["id"], t["name"])


def _gordstats(t) -> tuple:
    """The GordStats cell: rank beside rating, sorted by the rating."""
    if t.get("gs") is None:
        return None, ""
    return t["gs"], (f"<span class='gs-rk'>{t['gs_rank']}</span>{t['gs']:+.1f}"
                     f"<span class='pwr-chg' data-chg='gs'>{t['gs_chg']}</span>")


def _sp(t) -> tuple:
    """The SP+ cell: Bill Connelly's rating with its rank, same shape as ours."""
    if t.get("sp") is None:
        return None, ""
    rank = f"<span class='gs-rk'>{t['sp_rank']}</span>" if t.get("sp_rank") else ""
    return t["sp"], (rank + f"{t['sp']:+.1f}"
                     + f"<span class='pwr-chg' data-chg='sp'>{t['sp_chg']}</span>")


def _fpi(t) -> tuple:
    """The FPI cell: rank beside rating, the same shape as GordStats."""
    return t["fpi"], (f"<span class='gs-rk'>{t['rank']}</span>{t['fpi']:+.1f}"
                      f"<span class='pwr-chg' data-chg='fpi'>{t['fpi_chg']}</span>")


def _switcher() -> str:
    buttons = "".join(
        f'<button class="pv-btn{" active" if i == 0 else ""}" id="pv-tab-{vid}" '
        f'data-view="{vid}">{label}</button>'
        for i, (vid, label) in enumerate(VIEWS))
    return f'<div class="view-switch"><span class="switch-label">Show:</span>{buttons}</div>'


def _deltas(bases: dict, teams: list) -> dict:
    """{window: {field: [change per team, in rank order]}} for every tracked
    figure a window's baseline carries - the page's whole change-since answer,
    handed to the script as JSON so a sort or a button redraws without a fetch.
    A team with no figure on either end (unranked in the AP poll, a resume
    rank ESPN has not computed) is None; a field nobody has is left out."""
    out = {}
    for win, b in bases.items():
        frame, cols = b["frame"], {}
        for field, (kind, dec) in TRACKED.items():
            if field not in frame.columns:
                continue
            base = frame[field]
            vals = []
            for t in teams:
                now, then = t.get(field), base.get(t["id"])
                if now is None or then is None or pd.isna(then):
                    vals.append(None)
                    continue
                delta = (float(then) - now) if kind == "rank" else (now - float(then))
                vals.append(int(round(delta)) if dec == 0 else round(delta, dec))
            if any(v is not None for v in vals):
                cols[field] = vals
        out[win] = cols
    return out


def _chg(v, dec: int) -> str:
    """A rating's own change, for the cell beside it. A rating that has not
    moved prints nothing at all: a dot in all 138 rows of two columns is noise,
    and the Move column already says whether anything happened."""
    if v is None or abs(v) < 0.5 * 10 ** -dec:
        return ""
    return rankmoves.signed(v, dec)


def _change(v, field) -> tuple:
    """The Move cell as the page first renders it - the script redraws it."""
    kind, dec = TRACKED[field]
    if v is None:
        return None, ""
    return v, (rankmoves.cell(v) if kind == "rank" else rankmoves.signed(v, dec))


def body() -> str:
    data = fpi()
    teams = _rows(data)
    season = (data.get("requestedSeason") or {}).get("year") or SEASON

    ap_ranks, ap_season, ap_label = ap_poll()
    show_ap = bool(ap_ranks) and ap_season == season
    # Our own rating and rank, keyed by ESPN team id like everything here.
    frame, model, names = predict.season()
    gs_table = teams_page._standings(frame, model, names)
    gs = {str(r["team"]): (float(r["rating"]), int(r["rank"]), str(r["name"]))
          for _, r in gs_table.iterrows()}
    # SP+ (CollegeFootballData), bridged onto ESPN ids the way the schedule
    # page does it.
    sp, elo = cfbd.sp_by_id(), cfbd.elo_by_id()
    for rank, t in enumerate(teams, 1):
        t["rank"] = rank
        t["ap"] = ap_ranks.get(t["id"]) if show_ap else None
        t["gs"], t["gs_rank"], t["gs_name"] = gs.get(t["id"], (None, None, None))
        entry = sp.get(t["id"]) or {}
        t["sp"] = entry.get("rating")
        t["sp_rank"] = entry.get("rank")
        t["elo"] = elo.get(t["id"])

    # Our own order is the one the page opens in: this is the site's ranking,
    # and FPI is the column beside it. `rank` stays ESPN's - it is what the FPI
    # cell prints, what the top-25 highlight marks and what the archive stores;
    # only the order the rows are written in changes. Everything positional
    # downstream (the deltas, the opening change cells, the script's DELTA
    # arrays) is built from `teams` after this sort, so they stay in step.
    # A team we have no rating for sinks to the bottom rather than to rank 0.
    teams.sort(key=lambda t: (t["gs_rank"] is None, t["gs_rank"] or 0))
    order = {t["id"]: i for i, t in enumerate(teams)}
    _CARD["rows"] = [
        (str(t["gs_rank"]), t["school"] or t["name"],
         " \u00b7 ".join(x for x in (
             f"{int(t['numwins'])}-{int(t['numlosses'] or 0)}" if t.get("numwins") is not None else "",
             f"AP {t['ap']}" if t.get("ap") else "") if x))
        for t in teams[:5] if t["gs_rank"] is not None]

    bases = rankmoves.baselines(HISTORY_DIR, weeks=espn.week_spans(),
                                  week_label=espn.short_week_label)
    show_move = bool(bases)
    first_win = next(iter(bases)) if bases else None
    first_at = bases[first_win]["at"] if bases else None
    deltas = _deltas(bases, teams)

    # A figure ESPN has not filled in yet - every resume rank until games are
    # played - comes back None for all 138 teams. Rather than print a column of
    # dashes for weeks, each column asks whether anyone has a value at all.
    def live(field) -> bool:
        return any(t[field] is not None for t in teams)

    # The change each rating cell opens with, for the window the buttons open
    # on; CHANGE_JS redraws them when another window is picked.
    opening_win = deltas.get(first_win, {}) if first_win else {}
    for i, t in enumerate(teams):
        for field, key in (("fpi", "fpi_chg"), ("gs", "gs_chg"), ("sp", "sp_chg")):
            vals = opening_win.get(field)
            t[key] = _chg(vals[i] if vals else None, TRACKED[field][1])

    show_rec = live("numwins") and any(t["numwins"] or t["numlosses"] for t in teams)
    # Until a game is played, what's left of a schedule is the whole schedule:
    # the two SOS columns hold the same 138 numbers, and printing both twice is
    # noise. It comes back on its own the week they start to diverge.
    show_rem_sos = any(t["sosremainingrank"] != t["avgsosrank"] for t in teams)
    ranks_now = {t["id"]: t["rank"] for t in teams}

    # (views, label, tooltip, opening direction, cell, tracked field) per
    # column. `cell` returns the figure to sort on and the text to show; the
    # two are separate so the sort never has to parse "+28.7" or "10.2-2.4"
    # back out of the rendering. `field` is the archived figure whose change
    # the Move column shows while this column sorts the table.
    # Team leads with the FPI rank folded in: a leading RK column froze a bare
    # counter on phones while the names scrolled away. Neither Team nor Move
    # sorts: the figures do, and GordStats - the order the table is written in -
    # is the opening sort and the one the tab switcher falls back to. Its Move
    # figure is places climbed in our own ranking; every other column's is the
    # change in that column's own figure.
    def col(views, label, tip, direction, cell, field=None):
        return views, label, tip, direction, cell, field

    # The FPI rank rides in the FPI column, beside its rating, rather than
    # leading the Team cell - where it read as the row's rank under any sort.
    cols = [
        col(ALL, "Team", None, None, lambda t: (t["rank"], _team(t, show_rec))),
    ]
    # Move opens on the first window and the rank, as the script would draw it.
    def opening(t):
        vals = deltas[first_win].get("gs_rank") if first_win else None
        return _change(vals[order[t["id"]]] if vals else None, "gs_rank")

    if show_move:
        cols.append(col(ALL, "Move", f"Places climbed since {first_at:%b %-d}", None, opening))
    # Our column leads the figures: it is the order the table opens in, and on
    # a phone the rest scroll off to the right - the sorted column cannot be
    # one you have to go looking for.
    cols.append(col(("rating",), "GordStats", "This site's own rating - points better than "
                    "an average FBS team, the number the predictions run on - with its rank",
                    "desc", _gordstats, "gs_rank"))
    if show_ap:
        cols.append(col(("rating",), "AP", f"AP poll rank ({ap_label})" if ap_label else "AP poll rank", "asc",
                        lambda t: _plain(t["ap"]), "ap"))
    cols.append(col(("rating",), "FPI", "Expected point margin against an average FBS team, "
                    "with its rank", "desc", _fpi, "rank"))
    if any(t.get("sp") is not None for t in teams):
        cols.append(col(("rating",), "SP+", "Bill Connelly's SP+ (CollegeFootballData): "
                        "points better than average, with its rank", "desc", _sp, "sp_rank"))
    if any(t.get("elo") is not None for t in teams):
        cols.append(col(("rating",), "Elo", "CollegeFootballData's Elo rating - a chess "
                        "rating for football: every result moves it, nothing else does",
                        "desc", lambda t: (t["elo"], "" if t["elo"] is None else f"{t['elo']:.0f}"),
                        "elo"))
    if SHOW_PROJ_RECORD:
        cols.append(col(("rating",), "Proj W-L", "ESPN's simulation of the full schedule",
                        "desc", lambda t: (t["projectedw"], f"{t['projectedw']:.1f}-{t['projectedl']:.1f}"),
                        "projectedw"))
    cols += [
        col(("odds",), "Playoff%", "Chance of making the playoff", "desc",
            lambda t: _pct(t["probmakeplayoffs"]), "probmakeplayoffs"),
        col(("odds",), "Win Conf%", "Chance of winning the conference", "desc",
            lambda t: _pct(t["probwinconf"]), "probwinconf"),
        col(("odds",), "Bowl%", "Chance of reaching six wins, the bowl-eligibility line",
            "desc", lambda t: _pct(t["prob6wins"]), "prob6wins"),
        col(("odds",), "Win Out%", "Chance of winning every remaining game", "desc",
            lambda t: _pct(t["probwinout"]), "probwinout"),
        col(("odds",), "Title%", "Chance of winning the national title", "desc",
            lambda t: _pct(t["probwintitle"]), "probwintitle"),
        col(("rating",), "SOS", "Strength-of-schedule rank, hardest first", "asc",
            lambda t: _plain(t["avgsosrank"]), "avgsosrank"),
    ]
    if show_rem_sos:
        cols.append(col(("rating",), "Rem SOS", "Strength-of-schedule rank for the "
                        "games still to play", "asc",
                        lambda t: _plain(t["sosremainingrank"]), "sosremainingrank"))
    if live("accomplishmentrank"):
        cols.append(col(("rating",), "SOR", "Strength-of-record rank: where an average "
                        "top-25 team would sit with this resume", "asc",
                        lambda t: _plain(t["accomplishmentrank"]), "accomplishmentrank"))
    if SHOW_GAME_CONTROL and live("gamecontrolrank"):
        cols.append(col(("rating",), "GC", "Game-control rank: share of game time "
                        "spent in the lead", "asc",
                        lambda t: _plain(t["gamecontrolrank"]), "gamecontrolrank"))

    # What the script calls each figure once Move follows it: the column's own
    # label, and a tooltip phrase that reads right for a value or a rank.
    kinds = {"rank": {"k": "rank", "d": 0, "label": "", "tip": "Places climbed"}}
    for _views, label, _tip, _dir, _cell, field in cols:
        if field and field != "rank" and field in TRACKED:
            kind, dec = TRACKED[field]
            tip = ("Wins added" if field == "numwins"
                   else f"{label} places climbed" if kind == "rank" else f"{label} change")
            if field == "gs_rank":
                tip = "GordStats places climbed"
            kinds[field] = {"k": kind, "d": dec, "label": label, "tip": tip}

    rows = []
    for t in teams:
        cells = []
        for views, label, _tip, direction, cell, _field in cols:
            value, text = cell(t)
            cells.append(_td(views, value, text, team=(label == "Team"),
                             sortable=direction is not None,
                             extra=(" mv-cell" if label == "Move"
                                    else " sorted-col" if label == "GordStats" else "")))
        rows.append(f"<tr{' class=\"top25\"' if t['rank'] <= 25 else ''}"
                    f"{favorites.row_attr('cfb', t['id'])}>"
                    + "".join(cells) + "</tr>")

    # Move's header is retitled by the script as the sorted column changes, so
    # it carries no data-tips for WINDOW_JS to retitle it with.
    head = "".join(
        _th(views, label, tip, direction, first=(label == "GordStats"), team=(label == "Team"),
            field=field, extra=(" mv-th" if label == "Move" else ""))
        for views, label, tip, direction, _cell, field in cols)

    move_note = ""
    if show_move:
        move_note = (" <strong>Move</strong> is the change in whichever column the table "
                     "is sorted by - places climbed in the GordStats rank until you "
                     "sort by another, then that figure's change - since the point the buttons "
                     f"pick. It opens on the rankings as they stood before this week's "
                     f"games ({first_at:%b %-d}); every build is archived, so the choice "
                     "runs from there back to the season's first, or to the end of any "
                     "week's games.")

    intro = (
        "<details class='section'><summary>About these rankings</summary>"
        "<p class='power-note'><strong>GordStats</strong> is "
        "<a href='/cfb/predictions/'>this site's own rating</a> - points better than an "
        "average FBS team - and the order the table opens in. <strong>FPI</strong> is "
        "ESPN's version of the same idea, and <strong>AP</strong> the writers' poll. "
        "<strong>SP+</strong> (Bill Connelly) and <strong>Elo</strong> come from "
        f"CollegeFootballData.{move_note}</p>"
        "<p class='power-note'><strong>Rating</strong> is the ratings, each with its rank, "
        "and what the schedule has been worth; <strong>Odds</strong> "
        "what ESPN's simulations give each team. Projected records - ESPN's and "
        "ours - are on each team's page. "
        "Click a figure's header to sort by it; click again to reverse. Top 25 "
        "highlighted - the highlight follows the team, so the FPI top 25 stay "
        "marked however the table is sorted. "
        "<strong>SOS</strong> is strength-of-schedule rank (hardest first) and "
        "<strong>Rem SOS</strong> the same for the games still to play; "
        "<strong>SOR</strong> is strength of record - where an average top-25 "
        "team would sit with this resume.</p>"
        + ("" if live("accomplishmentrank") else
           "<p class='power-note'>The resume ranks ESPN computes from results - "
           "strength of record - appear here once games have been "
           "played.</p>")
        + "</details>")

    rankmoves.snapshot(HISTORY_DIR, pd.Series(ranks_now),
                       extra=pd.DataFrame({**{f: [t[f] for t in teams] for f in TRACKED if f != "rank"},
                                           "name": [t["name"] for t in teams]},
                                          index=[str(t["id"]) for t in teams]).round(3))
    # The decimals each in-cell change is drawn to, by field.
    chg = {f: TRACKED[f][1] for f in ("fpi", "gs", "sp")}
    blob = json.dumps({"deltas": deltas, "kinds": kinds, "chg": chg,
                       "when": {win: f"{b['at']:%b %-d}" for win, b in bases.items()}},
                      separators=(",", ":"))
    return (_CSS + favorites.table_css("table.cfb-power") + intro
            + "<div class='pin-bar'>" + _switcher() + rankmoves.window_switch(bases)
            + favorites.controls() + "</div>"
            + "<div class='power-wrap'>"
            + f"<table class='cfb-power view-rating'><thead><tr>{head}</tr></thead>"
            + f"<tbody>{''.join(rows)}</tbody></table></div>"
            + "{% raw %}<script type='application/json' id='pwr-deltas'>" + blob
            + "</script>{% endraw %}" + _JS + rankmoves.WINDOW_JS)


_CARD: dict = {}


def card() -> dict | None:
    """The link-preview card (gordstats.share_card): our top five, with each
    team's record and AP rank."""
    rows = _CARD.get("rows")
    if not rows:
        return None
    return share_card.ranked("cfb-rankings", f"College football \u00b7 {SEASON}",
                             "GordStats Top 25", "The model's ranking, ahead of the AP and FPI",
                             rows, alt="GordStats college football rankings: "
                             + ", ".join(f"{r[0]}. {r[1]}" for r in rows))


def generate():
    html = body()
    write_page(WEB_DIR / "power" / "index.html", "CFB Rankings", html,
               subtitle=f"{SEASON} season", image=card())


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Build the CFB power rankings page.")
    p.add_argument("--refresh", action="store_true")
    args = p.parse_args()
    if args.refresh:
        fpi(refresh=True)
    generate()
