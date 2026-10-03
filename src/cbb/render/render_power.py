"""
College basketball power rankings (docs/cbb/power/): every D-1 team.

The spine is Bart Torvik's T-Rank (barttorvik.com), one of the two sources
the March Madness model already trains on. Before any games are played it
carries his preseason projections — returning production, recruiting,
transfers — and once the season starts the same file becomes the current
ratings, so the page needs no seasonal switch.

Around the spine, the dynamic parts:

  * ESPN's BPI as a second computer rating, matched to Torvik's team names.
    When both cover the same season the page orders on their average — the
    ADP board's lesson, applied here: consensus beats any single system.
    While BPI still shows last season (it lags T-Rank's preseason by weeks)
    the column is labelled with its season and stays out of the ordering.
  * The AP poll, where one exists for this season — the human column, which
    makes disagreement with the computers visible instead of implicit.
  * Move columns against the snapshot archive (gordstats.rankmoves), so the
    page answers "who is rising" and not just "who is good".

    python -m cbb.render.render_power             # cached data if fresh
    python -m cbb.render.render_power --refresh   # refetch everything
"""
import argparse
import io
import json
import re
import time
from datetime import datetime

import pandas as pd
import requests

from cbb import constants, paths
from gordstats import favorites, rankmoves, stable
from gordstats.frontmatter import add_front_matter

# The season being ranked, in Torvik's convention (2027 = the 2026-27 season).
# Bump yearly, beside CBB_TIPOFF in render_home.
TRANK_YEAR = 2027
SEASON_LABEL = "2026-27"

_URL = f"https://barttorvik.com/{TRANK_YEAR}_team_results.csv"
_HEADERS = {"User-Agent": "Mozilla/5.0"}
_BPI_URL = ("https://site.web.api.espn.com/apis/fitt/v3/sports/basketball/"
            "mens-college-basketball/powerindex")
_AP_URL = ("https://site.api.espn.com/apis/site/v2/sports/basketball/"
           "mens-college-basketball/rankings")
MAX_AGE_HOURS = 12
HISTORY_DIR = paths.DATA / "cbb" / "power_history" / str(TRANK_YEAR)
# For the home page's "My teams" card (gordstats.my_teams_today); gitignored.
STAR_TEAMS_OUT = paths.DOCS / "cbb" / "star-teams.json"

# Torvik's name for a school where normalising ESPN's doesn't get there.
_ALIASES = {
    "uconn": "connecticut", "nc state": "north carolina state",
    "north carolina state": "north carolina state", "miami": "miami fl",
    "ole miss": "mississippi", "usc": "southern california",
    "smu": "smu", "saint marys": "saint marys",
    "st johns": "st johns", "ucf": "ucf", "utsa": "utsa", "utep": "utep",
    "umass": "massachusetts", "uc davis": "uc davis",
}


def _norm(name: str) -> str:
    """Fold an ESPN or Torvik school name to a comparable key."""
    n = str(name).lower().replace("&", "and")
    n = re.sub(r"[.'()]", "", n)
    n = re.sub(r"\bst\b(?=\s|$)", "state", n)      # michigan st -> michigan state
    n = re.sub(r"\s+", " ", n).strip()
    return _ALIASES.get(n, n)

_CSS = """<style>
table.cbb-power{width:100%;border-collapse:collapse;font-size:14px}
table.cbb-power th{background:#eef2f7;color:#334155;padding:7px 10px;text-align:center;
  font-size:12px;text-transform:uppercase;letter-spacing:.03em;white-space:nowrap;
  border:1px solid #e2e8f0;position:sticky;top:0;z-index:2}
table.cbb-power td{padding:6px 10px;border:1px solid #eef2f7;color:#0f172a;background:#fff;
  text-align:center;white-space:nowrap}
table.cbb-power td.pwr-team{text-align:left;font-weight:600}
/* Frozen identity column at every width, now that Team leads the table. The
   old version pinned it under 600px only and gave the td no z-index, so the
   other cells slid over it. Backgrounds come from the base td rules above —
   every td is painted opaque in both themes, so the stripe/top25 cascade
   keeps working under the pin. z-index ladder: pinned td (1) over plain
   cells, header row (2) over the pinned column, corner header (3) over both. */
table.cbb-power td.pwr-team,table.cbb-power th.pwr-team{position:sticky;left:0;
  box-shadow:2px 0 4px -2px rgba(0,0,0,.3)}
table.cbb-power td.pwr-team{z-index:1}
table.cbb-power th.pwr-team{z-index:3}
table.cbb-power td.conf{color:#4a5a68}
table.cbb-power tbody tr:nth-child(even) td{background:#f8fafc}
table.cbb-power tr.top25 td{background:#fdf6e3}
table.cbb-power tr.top25:nth-child(even) td{background:#faf0d2}
/* overflow-x only by default: with a max-height this box became a nested
   vertical scroller that captured phone swipes on a 366-row table. The
   height cap (and with it the sticky header) is desktop-only now. */
.power-wrap{overflow-x:auto;border:1px solid #e5e7eb;
  border-radius:12px;box-shadow:0 2px 8px rgba(15,23,42,.05)}
@media (min-width:768px){
  .power-wrap{overflow:auto;max-height:calc(100vh - 170px)}
}
.power-note{font-size:13px;color:#4a5a68;margin:6px 0 10px}
.power-lede{margin:6px 0 4px}
/* custom.css sizes .row-rank at .85em, which in the 13px phone table was
   11px - a rank is the number a reader looks for first (2026-09-29 phone
   audit). A floor in px, whatever the table's font does. */
table.cbb-power .row-rank{font-size:12px}
""" + rankmoves.CSS + """
@media (max-width:600px){
  table.cbb-power{font-size:13px}
  table.cbb-power td{padding:5px 7px}
  table.cbb-power td.pwr-team{max-width:150px;overflow:hidden;text-overflow:ellipsis}
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
}
</style>"""


def _cache_path():
    return paths.DATA / "cbb" / f"trank_{TRANK_YEAR}.csv"


def _cached_json(url: str, cache_name: str, params: dict, refresh: bool = False):
    """Fetch-and-cache for the ESPN feeds, same 12-hour rhythm as the CSV."""
    cache = paths.DATA / "cbb" / cache_name
    fresh = cache.exists() and (time.time() - cache.stat().st_mtime) < MAX_AGE_HOURS * 3600
    if cache.exists() and (fresh and not refresh):
        return json.loads(cache.read_text(encoding="utf-8"))
    try:
        r = requests.get(url, params=params, timeout=25)
        r.raise_for_status()
        data = r.json()
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data), encoding="utf-8")
        return data
    except Exception as exc:
        if cache.exists():
            print(f"  ! {cache_name} fetch failed ({exc}); using the cached copy")
            return json.loads(cache.read_text(encoding="utf-8"))
        print(f"  ! {cache_name} unavailable ({exc}); page renders without it")
        return None


def bpi(refresh: bool = False):
    """(rows keyed by normalised school, season year) from ESPN's BPI, or (None, None).

    Asked for TRANK_YEAR; ESPN answers with the newest season it has, which
    lags Torvik's preseason by weeks — requestedSeason says which one came
    back, and the caller decides what that is worth.
    """
    data = _cached_json(_BPI_URL, f"bpi_{TRANK_YEAR}.json",
                        {"region": "us", "lang": "en", "limit": 400,
                         "season": TRANK_YEAR}, refresh)
    if not data or not data.get("teams"):
        return None, None
    season = (data.get("requestedSeason") or {}).get("year")
    out = {}
    for entry in data["teams"]:
        team = entry.get("team") or {}
        cat = next((c for c in entry.get("categories", []) if c.get("name") == "bpi"), None)
        if not cat:
            continue
        totals = cat.get("totals") or []
        rank = re.sub(r"\D", "", str(totals[1] if len(totals) > 1 else ""))
        if not rank:
            continue
        school = team.get("nickname") or team.get("displayName") or ""
        out[_norm(school)] = {"espn_id": str(team.get("id")), "bpi_rank": int(rank)}
    return out, season


def ap_poll(refresh: bool = False):
    """({espn team id: AP rank}, poll season year), or (None, None)."""
    data = _cached_json(_AP_URL, "ap.json", {}, refresh)
    for poll in (data or {}).get("rankings", []):
        if poll.get("name") != "AP Top 25":
            continue
        season = (poll.get("season") or {}).get("year")
        ranks = {str((r.get("team") or {}).get("id")): int(r["current"])
                 for r in poll.get("ranks", []) if r.get("current")}
        return (ranks or None), season
    return None, None


# The columns the site reads (the power page, CBB stats, previews, the game
# model's preseason ratings), each at the decimals worth keeping: one finer
# than any page shows, and far finer than a spread can feel. Torvik's file
# has ~45 columns at 16 digits and re-solves every team each time it is
# asked, so the raw copy differed on every line every run and the Pi
# committed all 147 KB of it ~4 times a day. Trimmed and rounded it is 33 KB,
# and a refetch that moves nothing kept here leaves the file alone.
# "Fun Rk" alone reshuffled every row: before tipoff every FUN is 0, so its
# rank is a tie broken at random each time.
# Add a column here before reading it anywhere.
_KEEP = {"rank": None, "team": None, "conf": None, "record": None,
         "adjoe": 2, "adjde": 2, "barthag": 4, "adjt": 2,
         "proj. W": 2, "Proj. L": 2, "Pro Con W": 2, "Pro Con L": 2,
         "sos": 3, "ncsos": 3, "Proj. SOS": 3, "Proj. Noncon SOS": 3, "WAB": 2}


def _tidy(text: str) -> str:
    """Torvik's CSV as the cache keeps it: the _KEEP columns, rounded, in
    rank order - the same text whenever the numbers that matter are the same."""
    df = pd.read_csv(io.StringIO(text))
    df = df[[c for c in _KEEP if c in df.columns]].copy()
    for col, places in _KEEP.items():
        if places is not None and col in df.columns and df[col].dtype.kind == "f":
            df[col] = df[col].round(places)
    df = df.sort_values(["rank", "team"], kind="mergesort")
    return df.to_csv(index=False, lineterminator="\n")


def trank(refresh: bool = False) -> pd.DataFrame:
    """The T-Rank table, cached under data/cbb/ and refreshed twice a day
    (and by every daily run); the file is rewritten only when it changed."""
    cache = _cache_path()
    fresh = cache.exists() and (time.time() - cache.stat().st_mtime) < MAX_AGE_HOURS * 3600
    if cache.exists() and (fresh and not refresh):
        return pd.read_csv(cache)
    try:
        r = requests.get(_URL, headers=_HEADERS, timeout=25)
        r.raise_for_status()
        assert r.text.lstrip().startswith("rank,"), "unexpected payload"
        stable.write_text(_tidy(r.text), cache)
    except Exception as exc:
        if not cache.exists():
            raise
        print(f"  ! T-Rank fetch failed ({exc}); using the cached copy")
    return pd.read_csv(cache)


def ranked():
    """The table in the page's order, with the sources behind it: (frame with
    `rk`, BPI rows, BPI season, whether that BPI is this season's, AP ranks,
    whether to show AP). The page and the CBB home's top ten share it, so the
    two can never disagree about who is first."""
    df = trank()
    bpi_rows, bpi_season = bpi()
    ap_ranks, ap_season = ap_poll()
    # The file carries `rank` twice (T-Rank, then a duplicate); pandas mangles
    # the second to "rank.1". The first is the one the site shows. Columns are
    # picked by name and renamed to safe identifiers before iterating - the
    # positional _10-style names itertuples invents are one upstream column
    # away from silently meaning something else.
    df = df[["rank", "team", "conf", "record", "adjoe", "adjde", "barthag",
             "proj. W", "Proj. L"]].rename(columns={"rank": "trank", "proj. W": "pw",
                                                    "Proj. L": "pl"})

    # Second source. BPI joins on normalised school name; when it covers the
    # same season as T-Rank the page orders on the average of the two ranks,
    # otherwise on T-Rank alone with BPI shown as last season's context.
    bpi_current = bpi_rows is not None and bpi_season == TRANK_YEAR
    if bpi_rows:
        keyed = df["team"].map(_norm)
        df["bpi"] = keyed.map(lambda k: (bpi_rows.get(k) or {}).get("bpi_rank"))
        df["espn_id"] = keyed.map(lambda k: (bpi_rows.get(k) or {}).get("espn_id"))
        matched = int(df["bpi"].notna().sum())
        print(f"  BPI season {bpi_season}: matched {matched}/{len(df)} teams")
    else:
        df["bpi"] = df["espn_id"] = None

    show_ap = bool(ap_ranks) and ap_season == TRANK_YEAR and df["espn_id"].notna().any()
    df["ap"] = df["espn_id"].map(ap_ranks) if show_ap else None

    if bpi_current:
        df["order"] = df[["trank", "bpi"]].mean(axis=1).fillna(df["trank"])
    else:
        df["order"] = df["trank"]
    df = df.sort_values(["order", "trank"]).reset_index(drop=True)
    df["rk"] = df.index + 1
    return df, bpi_rows, bpi_season, bpi_current, ap_ranks, show_ap


def top(n: int = 10) -> pd.DataFrame:
    """The first `n` teams: rank, team, conference, projected record."""
    df = ranked()[0]
    return df.head(n)[["rk", "team", "conf", "pw", "pl"]]


def body() -> str:
    df, bpi_rows, bpi_season, bpi_current, ap_ranks, show_ap = ranked()

    moves = rankmoves.movement(HISTORY_DIR)
    ranks_now = df.set_index("team")["rk"]
    if "prev" in moves:
        df["move"] = (df["team"].map(moves["prev"]) - df["rk"])
    if "prev7" in moves and moves.get("prev7_at") != moves.get("prev_at"):
        df["move7"] = (df["team"].map(moves["prev7"]) - df["rk"])
    # A move column is shown only once somebody has moved. Preseason, T-Rank's
    # projections sit still for days at a time, and Move against the morning's
    # build was a column of dots in one of the four places a phone has room
    # for (the 2026-09-29 phone audit). The first build with a mover brings it
    # back - nothing seasonal to switch.
    show_move = "move" in df and bool(df["move"].fillna(0).ne(0).any())
    show_week = "move7" in df and bool(df["move7"].fillna(0).ne(0).any())
    # "7d" is the newest snapshot at least a week old, which a young or gappy
    # archive can put a month back: headed by the days it really spans.
    week_head = ""
    if show_week:
        span = (datetime.now() - moves["prev7_at"]).total_seconds() / 86400
        week_head = f"{max(1, round(span))}d"

    # Until BPI counts, the order *is* T-Rank, and its column repeated the row
    # number beside the team. It comes back when the two differ.
    show_trank = bool((df["trank"] != df["rk"]).any())

    played = df["record"].astype(str).str.split("-").str[0].astype(int).sum() > 0

    bpi_head = ""
    if bpi_rows:
        bpi_head = ("BPI" if bpi_current else
                    f"BPI '{str(bpi_season - 1)[2:]}-{str(bpi_season)[2:]}")

    def bpi_cell(t):
        return f"<td>{'&mdash;' if pd.isna(t.bpi) else int(t.bpi)}</td>"

    # (header, cell, shown). One list, so the header and the cells cannot fall
    # out of step. The order is for a phone, where the frozen team column
    # leaves room for three or four more: the record (in season) and T-Rank's
    # projected one first, then movement, then the rest. Last season's final
    # BPI is context, not a rating of this team, so it goes to the far end;
    # this season's is half the ordering and sits beside T-Rank.
    columns = [
        ("Record", lambda t: f"<td>{t.record}</td>", played),
        ("Proj W-L", lambda t: f"<td>{round(t.pw)}-{round(t.pl)}</td>", True),
        ("Move", lambda t: f"<td>{rankmoves.cell(t.move)}</td>", show_move),
        (week_head, lambda t: f"<td>{rankmoves.cell(t.move7)}</td>", show_week),
        ("Conf", lambda t: f"<td class='conf'>{t.conf}</td>", True),
        ("AP", lambda t: f"<td>{'' if pd.isna(t.ap) else int(t.ap)}</td>", show_ap),
        ("T-Rank", lambda t: f"<td>{int(t.trank)}</td>", show_trank),
        (bpi_head, bpi_cell, bool(bpi_rows) and bpi_current),
        ("AdjOE", lambda t: f"<td>{t.adjoe:.1f}</td>", True),
        ("AdjDE", lambda t: f"<td>{t.adjde:.1f}</td>", True),
        ("Barthag", lambda t: f"<td>{t.barthag:.3f}</td>", True),
        (bpi_head, bpi_cell, bool(bpi_rows) and not bpi_current),
    ]
    columns = [(label, fn) for label, fn, shown in columns if shown]

    rows = []
    for t in df.itertuples(index=False):
        rank = int(t.rk)
        rows.append(
            f"<tr{' class=\"top25\"' if rank <= 25 else ''}"
            # T-Rank names the school and carries no id of its own, so the
            # favourite is keyed on the slugified name. That is stable across
            # rebuilds and only breaks if Torvik renames a school.
            f"{favorites.name_attr('cbb-men', t.team)}>"
            # Rank folds into the frozen team cell (the fantasy pages' pattern,
            # .row-rank in custom.css): a standalone RK column meant the sticky
            # first column pinned a counter while the team name slid away.
            f"<td class='pwr-team'><span class=\"row-rank\">{rank}</span>{t.team}"
            f"{favorites.name_star('cbb-men', t.team)}</td>"
            + "".join(fn(t) for _, fn in columns) + "</tr>")

    head = "<th class='pwr-team'>Team</th>" + "".join(f"<th>{label}</th>" for label, _ in columns)

    ordering = ("the average of T-Rank and BPI" if bpi_current else
                "T-Rank" + (f", with last season's final BPI as context" if bpi_rows else ""))
    moved = []
    if show_move:
        moved.append(f"<strong>Move</strong> is places climbed since {moves['prev_at']:%b %-d}")
    if show_week:
        moved.append(f"<strong>{week_head}</strong> since {moves['prev7_at']:%b %-d}")
    move_note = (" " + "; ".join(moved) + ".") if moved else ""

    # One line above the table; the rest folds. The whole explanation used to
    # run ~160 words ahead of it, which put the first team at 769px on a phone
    # (2026-09-29 audit) - the table is what the page is for.
    basis = "T-Rank and BPI, averaged" if bpi_current else "Bart Torvik's T-Rank"
    lede = (f"<p class='power-lede'>Every Division I team, ranked by {basis}"
            f"{'' if played else ' (preseason)'}. Every figure, sortable: "
            "<a href='/cbb/stats/'>Team Stats</a>.</p>")
    about = (
        "<details class='section'><summary>About these numbers</summary>"
        f"<p class='power-note'>Ordered by {ordering}. "
        f"<a href='https://barttorvik.com/' target='_blank'>T-Rank</a> is one of the two "
        f"sources the March Madness model trains on; <strong>BPI</strong> is ESPN's power "
        f"index" + ("" if bpi_current else " (still showing last season until its preseason run)")
        + (", <strong>AP</strong> the human poll" if show_ap else "")
        + ". "
        + ("Until tip-off T-Rank carries <strong>preseason projections</strong> &mdash; returning "
           "production, recruiting and transfers; once games are played the same numbers "
           "become the live ratings." if not played else
           "These are the live in-season ratings.")
        + move_note + "</p>"
        "<p class='power-note'>The number beside each team is its rank in this ordering"
        + ("; <strong>T-Rank</strong> is Torvik's own" if show_trank else "")
        + ". <strong>Proj W-L</strong> is T-Rank's projected final record. "
        "<strong>AdjOE / AdjDE</strong> are points scored / allowed "
        "per 100 possessions against an average opponent (offense high is good, defense low "
        "is good); <strong>Barthag</strong> is the chance of beating an average team on a "
        "neutral floor. Top 25 highlighted.</p></details>")

    rankmoves.snapshot(HISTORY_DIR, ranks_now)
    return (_CSS + favorites.table_css("table.cbb-power") + lede + about
            + "<div class='pin-bar'>" + favorites.controls() + "</div>"
            + f"<div class='power-wrap'><table class='cbb-power'><thead><tr>{head}</tr></thead>"
            + f"<tbody>{''.join(rows)}</tbody></table></div>")


def star_teams(names) -> dict:
    """Each starrable team's key -> [its name on the live scoreboard, its logo].

    The stars on this page are keyed on T-Rank's names. The scoreboard the home
    page's "My teams" card reads (cbb.live_scraper) names teams the master
    list's way, and the logos are filed under names that follow no pattern, so
    the browser is handed the translation rather than the whole master list.
    A school the master list does not know yet (one new to D-1) is left out:
    the scoreboard cannot name it either.
    """
    master = pd.read_json(paths.MASTER_DICT)
    look = {}
    for team, path in zip(master["team"], master["path"]):
        look[team] = (team, path)
    for team, aliases, path in zip(master["team"], master["names"], master["path"]):
        for alias in aliases:
            look.setdefault(alias, (team, path))
    out = {}
    for name in names:
        hit = look.get(constants.TORVIK_RENAMES.get(name, name))
        if hit:
            out[favorites.name_key("cbb-men", name)] = [hit[0], "/assets/images/" + hit[1]]
    return out


def generate():
    out = paths.DOCS / "cbb" / "power" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    # "Updated" is when T-Rank was last downloaded, not when the page was
    # rebuilt: out of season the build runs daily on a cached table.
    fetched = datetime.fromtimestamp(_cache_path().stat().st_mtime)
    out.write_text(add_front_matter(body(), "CBB Power Rankings",
                                    f"{SEASON_LABEL} season", updated=fetched, description="Every Division I men's basketball team ranked on Bart Torvik's T-Rank and ESPN's BPI, with the AP poll, records, conferences and who is rising or falling."),
                   encoding="utf-8")
    print(f"Wrote CBB power rankings -> {out}")
    STAR_TEAMS_OUT.write_text(json.dumps(star_teams(trank()["team"]), separators=(",", ":")),
                              encoding="utf-8")
    print(f"Wrote CBB star teams -> {STAR_TEAMS_OUT}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Build the CBB power rankings page.")
    p.add_argument("--refresh", action="store_true")
    args = p.parse_args()
    if args.refresh:
        trank(refresh=True)
        bpi(refresh=True)
        ap_poll(refresh=True)
    generate()
