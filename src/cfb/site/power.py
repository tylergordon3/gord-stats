"""
College football power rankings (docs/cfb/power/): every FBS team.

Ratings are ESPN's Football Power Index, read from the public API behind
espn.com's own FPI page. Preseason it is ESPN's projection model; in season
it updates with results, so - like the CBB page - whatever FPI believes
today is what renders, with no seasonal switch. Only the unambiguous
columns are shown: the FPI value and the projected record. The API carries
a dozen more unlabelled figures per team; naming them by guesswork is how a
"win conference" column ends up holding playoff odds.

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

import pandas as pd
import requests

from cfb.config import DATA_DIR, SEASON, WEB_DIR
from cfb.site import write_page
from gordstats import rankmoves

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
table.cfb-power{width:100%;border-collapse:collapse;font-size:14px}
table.cfb-power th{background:#eef2f7;color:#334155;padding:7px 10px;text-align:center;
  font-size:12px;text-transform:uppercase;letter-spacing:.03em;white-space:nowrap;
  border:1px solid #e2e8f0;position:sticky;top:0}
table.cfb-power td{padding:6px 10px;border:1px solid #eef2f7;color:#0f172a;background:#fff;
  text-align:center;white-space:nowrap}
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
table.cfb-power th.sortable{cursor:pointer;user-select:none}
table.cfb-power th.sortable:hover{color:#0f172a}
/* The caret is always drawn, faint until the column is the one sorting, so a
   header never changes width on click and the sticky row stays put. */
table.cfb-power th.sortable::after{content:"\\2195";margin-left:5px;opacity:.35;
  font-size:11px}
table.cfb-power th.sorted.asc::after{content:"\\25B2";opacity:1}
table.cfb-power th.sorted.desc::after{content:"\\25BC";opacity:1}
.power-wrap{overflow:auto;max-height:calc(100vh - 170px);border:1px solid #e5e7eb;
  border-radius:12px;box-shadow:0 2px 8px rgba(15,23,42,.05)}
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
// AP poll) sorts as missing and sinks to the bottom in both directions.
function val(row,i){
  var cell=row.cells[i], v=cell?cell.dataset.sort:undefined;
  return v===undefined||v===''?null:parseFloat(v);
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
    return dir==='asc'?x-y:y-x;
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


def _rows(data: dict) -> list:
    """(name, logo, fpi, proj_w, proj_l) per team, best first.

    The fpi category's totals open with the four figures that are stable and
    self-describing on ESPN's own page: the FPI value, the rank, the trend,
    and the projected wins and losses. Everything after that is unlabelled
    percentages, deliberately unread.
    """
    out = []
    for entry in data["teams"]:
        team = entry["team"]
        cat = next((c for c in entry["categories"] if c.get("name") == "fpi"), None)
        if not cat:
            continue
        totals = cat.get("totals") or []
        try:
            value = float(totals[0])
            proj_w, proj_l = float(totals[3]), float(totals[4])
        except (IndexError, ValueError, TypeError):
            continue
        logos = team.get("logos") or []
        out.append({
            "id": str(team.get("id")),
            "name": team.get("displayName") or team.get("nickname"),
            "logo": logos[0]["href"] if logos else None,
            "fpi": value, "pw": proj_w, "pl": proj_l,
        })
    return sorted(out, key=lambda t: -t["fpi"])


def body() -> str:
    data = fpi()
    teams = _rows(data)
    season = (data.get("requestedSeason") or {}).get("year") or SEASON
    stamp = datetime.fromtimestamp(_cache_path().stat().st_mtime).strftime("%b %-d")

    ap_ranks, ap_season = ap_poll()
    show_ap = bool(ap_ranks) and ap_season == season

    moves = rankmoves.movement(HISTORY_DIR)
    show_move = "prev" in moves
    show_week = "prev7" in moves and moves.get("prev7_at") != moves.get("prev_at")

    rows = []
    ranks_now = {}
    for rank, t in enumerate(teams, 1):
        ranks_now[t["id"]] = rank
        logo = f"<img src='{t['logo']}' alt='' loading='lazy'>" if t["logo"] else ""
        ap = ap_ranks.get(t["id"]) if show_ap else None
        move = (moves["prev"].get(t["id"]) - rank
                if show_move and t["id"] in moves["prev"].index else None)
        week = (moves["prev7"].get(t["id"]) - rank
                if show_week and t["id"] in moves["prev7"].index else None)
        # data-sort carries the number the JS sorts on, so the sort never has to
        # parse a rendered cell ("+28.7", "10.2-2.4") back into a figure. A team
        # outside the AP poll carries none, which sinks it to the bottom either way.
        ap_cell = "<td></td>" if ap is None else f"<td data-sort='{ap}'>{ap}</td>"
        rows.append(
            f"<tr{' class=\"top25\"' if rank <= 25 else ''}>"
            f"<td data-sort='{rank}'>{rank}</td>"
            + (f"<td>{rankmoves.cell(move)}</td>" if show_move else "")
            + (f"<td>{rankmoves.cell(week)}</td>" if show_week else "")
            + f"<td class='pwr-team'>{logo}{t['name']}</td>"
            + (ap_cell if show_ap else "")
            + f"<td data-sort='{t['fpi']:.1f}'>{t['fpi']:+.1f}</td>"
            + f"<td data-sort='{t['pw']:.1f}'>{t['pw']:.1f}-{t['pl']:.1f}</td></tr>")

    # data-dir is the direction the column opens on: rank and the AP poll read
    # best-first ascending, the two ratings best-first descending.
    head = ("<th class='sortable sorted asc' data-dir='asc' data-now='asc'"
            " aria-sort='ascending'>RK</th>"
            + ("<th>Move</th>" if show_move else "")
            + ("<th>7d</th>" if show_week else "")
            + "<th class='pwr-team'>Team</th>"
            + ("<th class='sortable' data-dir='asc'>AP</th>" if show_ap else "")
            + "<th class='sortable' data-dir='desc'>FPI</th>"
            + "<th class='sortable' data-dir='desc'>Proj W-L</th>")

    move_note = ""
    if show_move:
        move_note = f" <strong>Move</strong> is places climbed since {moves['prev_at']:%b %-d}"
        if show_week:
            move_note += f"; <strong>7d</strong> since {moves['prev7_at']:%b %-d}"
        move_note += "."

    intro = (
        f"<p>All {len(teams)} FBS teams, ranked by <strong>ESPN's Football Power "
        f"Index</strong> for the {season} season"
        + (", with the <strong>AP poll</strong> beside it as the human column" if show_ap else "")
        + f", pulled {stamp}. FPI is expected point margin against an average FBS team "
        f"on a neutral field; the projected record is ESPN's simulation of each team's "
        f"actual schedule. Preseason these are projections; once games are played the "
        f"same numbers update with results.{move_note}</p>"
        "<p class='power-note'>Top 25 highlighted. Click <strong>RK</strong>"
        + (", <strong>AP</strong>" if show_ap else "")
        + ", <strong>FPI</strong> or <strong>Proj W-L</strong> to sort by that "
        "column; click it again to reverse. The highlight follows the team, so "
        "the FPI top 25 stay marked however the table is sorted.</p>")

    rankmoves.snapshot(HISTORY_DIR, pd.Series(ranks_now))
    return (_CSS + intro
            + f"<div class='power-wrap'><table class='cfb-power'><thead><tr>{head}</tr></thead>"
            + f"<tbody>{''.join(rows)}</tbody></table></div>" + _JS)


def generate():
    write_page(WEB_DIR / "power" / "index.html", "CFB Power Rankings", body(),
               subtitle=f"{SEASON} season")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Build the CFB power rankings page.")
    p.add_argument("--refresh", action="store_true")
    args = p.parse_args()
    if args.refresh:
        fpi(refresh=True)
        ap_poll(refresh=True)
    generate()
