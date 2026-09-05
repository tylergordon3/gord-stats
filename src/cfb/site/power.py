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
the failure that kept the rest of them off the page. Three tabs divide
them: Rating (the ratings and the projected record), Odds (the simulation
probabilities) and Resume (schedule strength and, in season, ESPN's
resume ranks).

A figure ESPN has not computed yet reads as "-" in the payload rather than
zero, so a column stays hidden until some team has one - the resume ranks
appear by themselves once games are played.

Beside the computer number: the AP poll where one exists for this season
(the human column), and Move columns against the snapshot archive
(gordstats.rankmoves) once it has more than one build in it.

    python -m cfb.site.power             # cached JSON if fresh
    python -m cfb.site.power --refresh
"""
import argparse
import json
import time
from datetime import datetime
from html import escape

import pandas as pd
import requests

from cfb.config import DATA_DIR, SEASON, WEB_DIR
from cfb.site import write_page
from gordstats import favorites, rankmoves

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
table.cfb-power tbody tr:nth-child(even) td{background:#f8fafc}
table.cfb-power tr.top25 td{background:#fdf6e3}
table.cfb-power tr.top25:nth-child(even) td{background:#faf0d2}
/* The Slate theme styles every <img> as a framed figure - padding, a border,
   a drop shadow and 10px vertical margins - which boxes each logo and stretches
   the row. Reset all of it here, same as the league table does. */
table.cfb-power td.pwr-team img{width:22px;height:22px;object-fit:contain;
  vertical-align:middle;margin:0 8px 0 0;border:none;padding:0;box-shadow:none;
  background:none;border-radius:0}
/* One table, three tabs: the live view keeps its own columns and hides the
   rest. Cheaper than three tables, and the sort survives a tab change. */
table.cfb-power.view-rating td:not(.v-rating),table.cfb-power.view-rating th:not(.v-rating),
table.cfb-power.view-odds td:not(.v-odds),table.cfb-power.view-odds th:not(.v-odds),
table.cfb-power.view-resume td:not(.v-resume),table.cfb-power.view-resume th:not(.v-resume){
  display:none}
table.cfb-power th.sortable{cursor:pointer;user-select:none}
table.cfb-power th.sortable:hover{color:#0f172a}
/* The caret is always drawn, faint until the column is the one sorting, so a
   header never changes width on click and the sticky row stays put. */
table.cfb-power th.sortable::after{content:"\\2195";margin-left:5px;opacity:.35;
  font-size:11px}
table.cfb-power th.sorted.asc::after{content:"\\25B2";opacity:1}
table.cfb-power th.sorted.desc::after{content:"\\25BC";opacity:1}
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
  table.cfb-power td{background:#16203a;border-color:#2b3852;color:#dde5ef}
  table.cfb-power tbody tr:nth-child(even) td{background:#1b2540}
  table.cfb-power tr.top25 td{background:#33301a}
  table.cfb-power tr.top25:nth-child(even) td{background:#3a361e}
  /* Several teams ship a near-black logo; a faint halo keeps them readable
     against the navy rows. */
  table.cfb-power td.pwr-team img{filter:drop-shadow(0 0 1px rgba(255,255,255,.6))}
  .power-note{color:#aab7c9}
  .power-wrap{border-color:#2b3852}
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

// Every sortable cell carries data-sort; a cell without one (a team outside the
// AP poll, a resume rank ESPN hasn't computed) sorts as missing and sinks to the
// bottom in both directions.
function val(row,i){
  var cell=row.cells[i], v=cell?cell.dataset.sort:undefined;
  return v===undefined||v===''?null:v;
}

// Numbers where both cells are numbers, text otherwise - Conf is the one column
// that sorts as a name.
function compare(x,y){
  var nx=parseFloat(x), ny=parseFloat(y);
  if(!isNaN(nx)&&!isNaN(ny)) return nx-ny;
  return String(x).localeCompare(String(y));
}

function sortBy(th){
  var i=Array.prototype.indexOf.call(head.cells,th);
  // A column that is already the live one reverses; one being picked up opens
  // in the direction it reads best, even if it was left reversed earlier.
  var dir=th.dataset.now?(th.dataset.now==='asc'?'desc':'asc'):th.dataset.dir;
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
}

Array.prototype.forEach.call(head.cells,function(th){
  if(!th.classList.contains('sortable')) return;
  th.tabIndex=0;
  th.addEventListener('click',function(){sortBy(th);});
  th.addEventListener('keydown',function(e){
    if(e.key==='Enter'||e.key===' '){e.preventDefault(); sortBy(th);}
  });
});

// A sort running on Move or Δ follows the window the reader picks.
document.addEventListener('winchange',function(){
  var live=head.querySelector('th.sorted');
  if(!live||!live.classList.contains('win-th')) return;
  live.dataset.now=live.dataset.now==='asc'?'desc':'asc';   // sortBy flips it back
  sortBy(live);
});

// --- tabs -----------------------------------------------------------------
var TABS=document.querySelectorAll('.pv-btn');
Array.prototype.forEach.call(TABS,function(btn){
  btn.addEventListener('click',function(){
    var view=btn.dataset.view;
    table.className='cfb-power view-'+view;
    Array.prototype.forEach.call(TABS,function(b){b.classList.toggle('active',b===btn);});
    // A sort running on a column this tab doesn't show would leave the table in
    // an order with nothing on screen to explain it, so it falls back to rank.
    var live=head.querySelector('th.sorted');
    if(live&&!live.classList.contains('v-'+view)) sortBy(head.cells[0]);
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


def ap_poll(refresh: bool = False):
    """({espn team id: AP rank}, poll season year), or (None, None)."""
    cache = DATA_DIR / "ap.json"
    fresh = cache.exists() and (time.time() - cache.stat().st_mtime) < MAX_AGE_HOURS * 3600
    data = None
    if cache.exists() and (fresh and not refresh):
        data = json.loads(cache.read_text(encoding="utf-8"))
    else:
        try:
            r = requests.get(_AP_URL, headers=_HEADERS, timeout=_TIMEOUT)
            r.raise_for_status()
            data = r.json()
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
        ranks = {str((r.get("team") or {}).get("id")): int(r["current"])
                 for r in poll.get("ranks", []) if r.get("current")}
        return (ranks or None), season
    return None, None


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
        out.append({
            "id": str(team.get("id")),
            "name": team.get("displayName") or team.get("nickname"),
            "logo": logos[0]["href"] if logos else None,
            "conf": group.get("shortName"),
            **figures,
        })
    return sorted(out, key=lambda t: -t["fpi"])


# The three tabs, and the columns each one carries. One table holds every
# column and the tab hides the ones it does not want, so switching tabs keeps
# the rows, the sort and the highlight exactly where they were.
VIEWS = [("rating", "Rating"), ("odds", "Odds"), ("resume", "Resume")]
ALL = tuple(v for v, _ in VIEWS)


def _td(views, value, text, team=False, sortable=True, win=False) -> str:
    cls = " ".join(f"v-{v}" for v in views) + (" pwr-team" if team else "") + (" win-cell" if win else "")
    if isinstance(value, float):
        value = round(value, 3)      # ESPN sends 38.800000000000004
    key = f" data-sort='{value}'" if sortable and value is not None else ""
    return f"<td class='{cls}'{key}>{text}</td>"


def _th(views, label, tip, direction, first=False, team=False, tips=None) -> str:
    cls = " ".join(f"v-{v}" for v in views) + (" pwr-team" if team else "")
    if direction:
        cls += " sortable"
    if tips:
        cls += " win-th"
    attrs = f' title="{escape(tip, quote=True)}"' if tip else ""
    if tips:
        attrs += f" data-tips='{tips}'"
    if direction:
        attrs += f" data-dir='{direction}'"
    # The table arrives sorted by rank, so Team - which sorts by it - opens
    # as the live column.
    if first:
        cls += " sorted asc"
        attrs += " data-now='asc' aria-sort='ascending'"
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


def _record(t):
    w, l, ties = t["numwins"] or 0, t["numlosses"] or 0, t["numties"] or 0
    return int(w), f"{w:.0f}-{l:.0f}" + (f"-{ties:.0f}" if ties else "")


def _team(t) -> str:
    logo = f"<img src='{t['logo']}' alt='' loading='lazy'>" if t["logo"] else ""
    return logo + t["name"] + favorites.star("cfb", t["id"], t["name"])



def _switcher() -> str:
    buttons = "".join(
        f'<button class="pv-btn{" active" if i == 0 else ""}" id="pv-tab-{vid}" '
        f'data-view="{vid}">{label}</button>'
        for i, (vid, label) in enumerate(VIEWS))
    return f'<div class="view-switch"><span class="switch-label">Show:</span>{buttons}</div>'


def body() -> str:
    data = fpi()
    teams = _rows(data)
    season = (data.get("requestedSeason") or {}).get("year") or SEASON
    stamp = datetime.fromtimestamp(_cache_path().stat().st_mtime).strftime("%b %-d")

    ap_ranks, ap_season = ap_poll()
    show_ap = bool(ap_ranks) and ap_season == season

    bases = rankmoves.baselines(HISTORY_DIR)
    show_move = bool(bases)
    # The rating itself only rides in snapshots taken from 2026-09-04 on; a
    # change column with nothing in it waits for one that has it.
    show_delta = any("fpi" in b["frame"].columns for b in bases.values())
    first_at = next(iter(bases.values()))["at"] if bases else None

    # A figure ESPN has not filled in yet - every resume rank until games are
    # played - comes back None for all 138 teams. Rather than print a column of
    # dashes for weeks, each column asks whether anyone has a value at all.
    def live(field) -> bool:
        return any(t[field] is not None for t in teams)

    show_rec = live("numwins") and any(t["numwins"] or t["numlosses"] for t in teams)
    # Until a game is played, what's left of a schedule is the whole schedule:
    # the two SOS columns hold the same 138 numbers, and printing both twice is
    # noise. It comes back on its own the week they start to diverge.
    show_rem_sos = any(t["sosremainingrank"] != t["avgsosrank"] for t in teams)
    ranks_now = {t["id"]: rank for rank, t in enumerate(teams, 1)}

    # (views, label, tooltip, opening direction, cell) per column. `cell` returns
    # the figure to sort on and the text to show; the two are separate so the
    # sort never has to parse "+28.7" or "10.2-2.4" back out of the rendering.
    # Team leads with the FPI rank folded in: a leading RK column froze a bare
    # counter on phones while the names scrolled away. Sorting the Team column
    # sorts by that rank, which also keeps it the opening sort and the one the
    # tab switcher falls back to.
    cols = [
        (ALL, "Team", "FPI rank", "asc",
         lambda t, r: (r, f"<span class='row-rank'>{r}</span>{_team(t)}")),
    ]
    if show_move:
        cols.append((("rating",), "Move", f"Places climbed since {first_at:%b %-d}",
                     "desc", lambda t, r: rankmoves.move_spans(bases, t["id"], r)[::-1]))
    cols.append((ALL, "Conf", "Conference", "asc", lambda t, r: (t["conf"], t["conf"] or "")))
    if show_ap:
        cols.append((("rating",), "AP", "AP poll rank", "asc",
                     lambda t, r: _plain(ap_ranks.get(t["id"]))))
    if show_rec:
        cols.append((("rating", "resume"), "Rec", "Record so far", "desc",
                     lambda t, r: _record(t)))
    cols += [
        (("rating",), "FPI", "Expected point margin against an average FBS team",
         "desc", lambda t, r: (t["fpi"], f"{t['fpi']:+.1f}")),
    ]
    if show_delta:
        cols.append((("rating",), "Δ", f"FPI change since {first_at:%b %-d}", "desc",
                     lambda t, r: rankmoves.delta_spans(bases, t["id"], t["fpi"], "fpi")[::-1]))
    cols += [
        (("rating",), "Proj W-L", "ESPN's simulation of the full schedule", "desc",
         lambda t, r: (t["projectedw"], f"{t['projectedw']:.1f}-{t['projectedl']:.1f}")),
        (("odds",), "Playoff%", "Chance of making the playoff", "desc",
         lambda t, r: _pct(t["probmakeplayoffs"])),
        (("odds",), "Win Conf%", "Chance of winning the conference", "desc",
         lambda t, r: _pct(t["probwinconf"])),
        (("odds",), "Bowl%", "Chance of reaching six wins, the bowl-eligibility line",
         "desc", lambda t, r: _pct(t["prob6wins"])),
        (("odds",), "Win Out%", "Chance of winning every remaining game", "desc",
         lambda t, r: _pct(t["probwinout"])),
        (("odds",), "Title%", "Chance of winning the national title", "desc",
         lambda t, r: _pct(t["probwintitle"])),
        (("resume",), "SOS", "Strength-of-schedule rank, hardest first", "asc",
         lambda t, r: _plain(t["avgsosrank"])),
    ]
    if show_rem_sos:
        cols.append((("resume",), "Rem SOS", "Strength-of-schedule rank for the "
                     "games still to play", "asc",
                     lambda t, r: _plain(t["sosremainingrank"])))
    if live("accomplishmentrank"):
        cols.append((("resume",), "SOR", "Strength-of-record rank: where an average "
                     "top-25 team would sit with this resume", "asc",
                     lambda t, r: _plain(t["accomplishmentrank"])))
    if live("gamecontrolrank"):
        cols.append((("resume",), "GC", "Game-control rank: share of game time "
                     "spent in the lead", "asc",
                     lambda t, r: _plain(t["gamecontrolrank"])))

    win_labels = {"Move": "Places climbed", "Δ": "FPI change"}
    rows = []
    for rank, t in enumerate(teams, 1):
        cells = []
        for views, label, _tip, direction, cell in cols:
            value, text = cell(t, rank)
            cells.append(_td(views, value, text, team=(label == "Team"),
                             sortable=direction is not None, win=label in win_labels))
        rows.append(f"<tr{' class=\"top25\"' if rank <= 25 else ''}"
                    f"{favorites.row_attr('cfb', t['id'])}>"
                    + "".join(cells) + "</tr>")

    head = "".join(_th(views, label, tip, direction, first=(label == "Team"),
                       team=(label == "Team"),
                       tips=(rankmoves.window_tips(bases, win_labels[label])
                             if label in win_labels else None))
                   for views, label, tip, direction, _cell in cols)

    move_note = ""
    if show_move:
        move_note = (" <strong>Move</strong> is places climbed"
                     + (" and <strong>&Delta;</strong> the FPI's change" if show_delta else "")
                     + " since the point the buttons pick - every build is "
                     f"archived, so the choice runs from the last build ({first_at:%b %-d}) "
                     "back to the season's first.")

    intro = (
        f"<p>All {len(teams)} FBS teams, ranked by <strong>ESPN's Football Power "
        f"Index</strong> for the {season} season"
        + (", with the <strong>AP poll</strong> beside it" if show_ap else "")
        + f", pulled {stamp}.</p>"
        "<details class='section'><summary>About these rankings</summary>"
        "<p class='power-note'>FPI is expected point margin against an average FBS team "
        "on a neutral field; the projected record is ESPN's simulation of each team's "
        "actual schedule. Preseason these are projections; once games are played the "
        f"same numbers update with results.{move_note}</p>"
        "<p class='power-note'><strong>Rating</strong> is the ratings and the "
        "projected record, <strong>Odds</strong> what ESPN's simulations give "
        "each team, <strong>Resume</strong> what the schedule has been worth. "
        "Click any column header to sort by it; click again to reverse. Top 25 "
        "highlighted - the highlight follows the team, so the FPI top 25 stay "
        "marked however the table is sorted. On the Resume tab, "
        "<strong>SOS</strong> is strength-of-schedule rank (hardest first) and "
        "<strong>Rem SOS</strong> the same for the games still to play; "
        "<strong>SOR</strong> is strength of record - where an average top-25 "
        "team would sit with this resume - and <strong>GC</strong> game "
        "control, the share of game time spent in the lead.</p>"
        + ("" if live("accomplishmentrank") else
           "<p class='power-note'>The resume ranks ESPN computes from results - "
           "strength of record, game control - appear here once games have been "
           "played.</p>")
        + "</details>")

    rankmoves.snapshot(HISTORY_DIR, pd.Series(ranks_now),
                       extra=pd.DataFrame({"fpi": [t["fpi"] for t in teams],
                                           "name": [t["name"] for t in teams]},
                                          index=[str(t["id"]) for t in teams]))
    return (_CSS + favorites.table_css("table.cfb-power") + intro
            + "<div class='pin-bar'>" + _switcher() + rankmoves.window_switch(bases)
            + favorites.controls() + "</div>"
            + "<div class='power-wrap'>"
            + f"<table class='cfb-power view-rating'><thead><tr>{head}</tr></thead>"
            + f"<tbody>{''.join(rows)}</tbody></table></div>" + _JS + rankmoves.WINDOW_JS)


def generate():
    write_page(WEB_DIR / "power" / "index.html", "CFB National Rankings", body(),
               subtitle=f"{SEASON} season")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Build the CFB power rankings page.")
    p.add_argument("--refresh", action="store_true")
    args = p.parse_args()
    if args.refresh:
        fpi(refresh=True)
        ap_poll(refresh=True)
    generate()
