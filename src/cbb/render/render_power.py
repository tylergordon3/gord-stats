"""
College basketball power rankings (docs/cbb/power/): every D-1 team.

Ratings come from Bart Torvik's T-Rank (barttorvik.com), one of the two
sources the March Madness model already trains on. Before any games are
played the file carries Torvik's preseason projections — returning
production, recruiting, transfers — and once the season starts the same
file becomes the current ratings, so the page needs no seasonal switch:
whatever T-Rank believes today is what renders.

    python -m cbb.render.render_power             # cached CSV if present
    python -m cbb.render.render_power --refresh   # refetch from barttorvik.com
"""
import argparse
import time
from datetime import datetime

import pandas as pd
import requests

from cbb import paths
from gordstats.frontmatter import add_front_matter

# The season being ranked, in Torvik's convention (2027 = the 2026-27 season).
# Bump yearly, beside CBB_TIPOFF in render_home.
TRANK_YEAR = 2027
SEASON_LABEL = "2026-27"

_URL = f"https://barttorvik.com/{TRANK_YEAR}_team_results.csv"
_HEADERS = {"User-Agent": "Mozilla/5.0"}
MAX_AGE_HOURS = 12

_CSS = """<style>
table.cbb-power{width:100%;border-collapse:collapse;font-size:14px}
table.cbb-power th{background:#eef2f7;color:#334155;padding:7px 10px;text-align:center;
  font-size:12px;text-transform:uppercase;letter-spacing:.03em;white-space:nowrap;
  border:1px solid #e2e8f0;position:sticky;top:0}
table.cbb-power td{padding:6px 10px;border:1px solid #eef2f7;color:#0f172a;background:#fff;
  text-align:center;white-space:nowrap}
table.cbb-power td.pwr-team{text-align:left;font-weight:600}
table.cbb-power td.conf{color:#4a5a68}
table.cbb-power tbody tr:nth-child(even) td{background:#f8fafc}
table.cbb-power tr.top25 td{background:#fdf6e3}
table.cbb-power tr.top25:nth-child(even) td{background:#faf0d2}
.power-wrap{overflow:auto;max-height:calc(100vh - 170px);border:1px solid #e5e7eb;
  border-radius:12px;box-shadow:0 2px 8px rgba(15,23,42,.05)}
.power-note{font-size:13px;color:#4a5a68;margin:6px 0 10px}
@media (max-width:600px){
  table.cbb-power{font-size:13px}
  table.cbb-power td{padding:5px 7px}
  table.cbb-power td.pwr-team,table.cbb-power th.pwr-team{position:sticky;left:0;
    max-width:150px;overflow:hidden;text-overflow:ellipsis;background:#fff;
    box-shadow:2px 0 4px -2px rgba(0,0,0,.3)}
  table.cbb-power th.pwr-team{z-index:2;background:#eef2f7}
  table.cbb-power tbody tr:nth-child(even) td.pwr-team{background:#f8fafc}
  /* tbody in the selector on purpose: the even-row stripe above outweighs a
     tr.top25 rule without it, and the highlight vanished on alternate rows. */
  table.cbb-power tbody tr.top25 td.pwr-team{background:#fdf6e3}
}
@media (prefers-color-scheme: dark){
  table.cbb-power th{background:#223052;color:#dde5ef;border-color:#2b3852}
  table.cbb-power td{background:#16203a;border-color:#2b3852;color:#dde5ef}
  table.cbb-power tbody tr:nth-child(even) td{background:#1b2540}
  table.cbb-power tr.top25 td{background:#33301a}
  table.cbb-power tr.top25:nth-child(even) td{background:#3a361e}
  table.cbb-power td.conf{color:#aab7c9}
  .power-note{color:#aab7c9}
  .power-wrap{border-color:#2b3852}
  @media (max-width:600px){
    table.cbb-power td.pwr-team{background:#16203a}
    table.cbb-power th.pwr-team{background:#223052}
    table.cbb-power tbody tr:nth-child(even) td.pwr-team{background:#1b2540}
    table.cbb-power tbody tr.top25 td.pwr-team{background:#33301a}
  }
}
</style>"""


def _cache_path():
    return paths.DATA / "cbb" / f"trank_{TRANK_YEAR}.csv"


def trank(refresh: bool = False) -> pd.DataFrame:
    """The T-Rank table, cached under data/cbb/ and refreshed twice a day."""
    cache = _cache_path()
    fresh = cache.exists() and (time.time() - cache.stat().st_mtime) < MAX_AGE_HOURS * 3600
    if cache.exists() and (fresh and not refresh):
        return pd.read_csv(cache)
    try:
        r = requests.get(_URL, headers=_HEADERS, timeout=25)
        r.raise_for_status()
        assert r.text.lstrip().startswith("rank,"), "unexpected payload"
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(r.text, encoding="utf-8")
    except Exception as exc:
        if not cache.exists():
            raise
        print(f"  ! T-Rank fetch failed ({exc}); using the cached copy")
    return pd.read_csv(cache)


def body() -> str:
    df = trank()
    # The file carries `rank` twice (T-Rank, then a duplicate); pandas mangles
    # the second to "rank.1". The first is the one the site shows. Columns are
    # picked by name and renamed to safe identifiers before iterating - the
    # positional _10-style names itertuples invents are one upstream column
    # away from silently meaning something else.
    df = df[["rank", "team", "conf", "record", "adjoe", "adjde", "barthag",
             "proj. W", "Proj. L"]].rename(columns={"proj. W": "pw", "Proj. L": "pl"})
    df = df.sort_values("rank")
    played = df["record"].astype(str).str.split("-").str[0].astype(int).sum() > 0
    stamp = datetime.fromtimestamp(_cache_path().stat().st_mtime).strftime("%b %-d")

    rows = []
    for t in df.itertuples(index=False):
        rank = int(t.rank)
        rows.append(
            f"<tr{' class=\"top25\"' if rank <= 25 else ''}>"
            f"<td>{rank}</td><td class='pwr-team'>{t.team}</td><td class='conf'>{t.conf}</td>"
            + (f"<td>{t.record}</td>" if played else "")
            + f"<td>{round(t.pw)}-{round(t.pl)}</td>"
            f"<td>{t.adjoe:.1f}</td><td>{t.adjde:.1f}</td><td>{t.barthag:.3f}</td></tr>")

    head = ("<th>RK</th><th class='pwr-team'>Team</th><th>Conf</th>"
            + ("<th>Record</th>" if played else "")
            + "<th>Proj W-L</th><th>AdjOE</th><th>AdjDE</th><th>Barthag</th>")

    intro = (
        f"<p>Every Division I team, ranked. Ratings are "
        f"<a href='https://barttorvik.com/' target='_blank'>Bart Torvik's T-Rank</a> &mdash; "
        f"one of the two sources the March Madness model trains on &mdash; pulled {stamp}. "
        + ("Until tip-off these are his <strong>preseason projections</strong>, built from "
           "returning production, recruiting and transfers; once games are played the same "
           "numbers become the live ratings." if not played else
           "These are the live in-season ratings.")
        + "</p>"
        "<p class='power-note'><strong>AdjOE / AdjDE</strong> are points scored / allowed "
        "per 100 possessions against an average opponent (offense high is good, defense low "
        "is good); <strong>Barthag</strong> is the chance of beating an average team on a "
        "neutral floor. Top 25 highlighted.</p>")

    return (_CSS + intro
            + f"<div class='power-wrap'><table class='cbb-power'><thead><tr>{head}</tr></thead>"
            + f"<tbody>{''.join(rows)}</tbody></table></div>")


def generate():
    out = paths.DOCS / "cbb" / "power" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(add_front_matter(body(), "CBB Power Rankings",
                                    f"{SEASON_LABEL} season"), encoding="utf-8")
    print(f"Wrote CBB power rankings -> {out}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Build the CBB power rankings page.")
    p.add_argument("--refresh", action="store_true")
    args = p.parse_args()
    if args.refresh:
        trank(refresh=True)
    generate()
