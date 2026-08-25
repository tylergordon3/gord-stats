"""
College football power rankings (docs/cfb/power/): every FBS team.

Ratings are ESPN's Football Power Index, read from the public API behind
espn.com's own FPI page. Preseason it is ESPN's projection model; in season
it updates with results, so - like the CBB page - whatever FPI believes
today is what renders, with no seasonal switch. Only the unambiguous
columns are shown: the FPI value and the projected record. The API carries
a dozen more unlabelled figures per team; naming them by guesswork is how a
"win conference" column ends up holding playoff odds.

    python -m cfb.site.power             # cached JSON if fresh
    python -m cfb.site.power --refresh
"""
import argparse
import json
import time
from datetime import datetime

import requests

from cfb.config import DATA_DIR, SEASON, WEB_DIR
from cfb.site import write_page

_URL = ("https://site.web.api.espn.com/apis/fitt/v3/sports/football/"
        "college-football/powerindex")
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
table.cfb-power img{width:20px;height:20px;vertical-align:-4px;margin-right:6px}
.power-wrap{overflow:auto;max-height:calc(100vh - 170px);border:1px solid #e5e7eb;
  border-radius:12px;box-shadow:0 2px 8px rgba(15,23,42,.05)}
.power-note{font-size:13px;color:#4a5a68;margin:6px 0 10px}
@media (max-width:600px){
  table.cfb-power{font-size:13px}
  table.cfb-power td{padding:5px 7px}
}
@media (prefers-color-scheme: dark){
  table.cfb-power th{background:#223052;color:#dde5ef;border-color:#2b3852}
  table.cfb-power td{background:#16203a;border-color:#2b3852;color:#dde5ef}
  table.cfb-power tbody tr:nth-child(even) td{background:#1b2540}
  table.cfb-power tr.top25 td{background:#33301a}
  table.cfb-power tr.top25:nth-child(even) td{background:#3a361e}
  .power-note{color:#aab7c9}
  .power-wrap{border-color:#2b3852}
}
</style>"""


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

    rows = []
    for rank, t in enumerate(teams, 1):
        logo = f"<img src='{t['logo']}' alt='' loading='lazy'>" if t["logo"] else ""
        rows.append(
            f"<tr{' class=\"top25\"' if rank <= 25 else ''}>"
            f"<td>{rank}</td><td class='pwr-team'>{logo}{t['name']}</td>"
            f"<td>{t['fpi']:+.1f}</td><td>{t['pw']:.1f}-{t['pl']:.1f}</td></tr>")

    intro = (
        f"<p>All {len(teams)} FBS teams, ranked by <strong>ESPN's Football Power "
        f"Index</strong> for the {season} season, pulled {stamp}. FPI is expected "
        f"point margin against an average FBS team on a neutral field; the projected "
        f"record is ESPN's simulation of each team's actual schedule. Preseason these "
        f"are projections; once games are played the same numbers update with "
        f"results.</p>"
        "<p class='power-note'>Top 25 highlighted.</p>")

    return (_CSS + intro
            + "<div class='power-wrap'><table class='cfb-power'><thead><tr>"
            + "<th>RK</th><th class='pwr-team'>Team</th><th>FPI</th><th>Proj W-L</th>"
            + f"</tr></thead><tbody>{''.join(rows)}</tbody></table></div>")


def generate():
    write_page(WEB_DIR / "power" / "index.html", "CFB Power Rankings", body(),
               subtitle=f"{SEASON} season")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Build the CFB power rankings page.")
    p.add_argument("--refresh", action="store_true")
    args = p.parse_args()
    if args.refresh:
        fpi(refresh=True)
    generate()
