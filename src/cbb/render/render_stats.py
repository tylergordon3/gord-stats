"""
CBB team stats (/cbb/stats/): every Division I team on Bart Torvik's numbers -
adjusted efficiency, tempo, Barthag, schedule strength and, once the season is
under way, Dean Oliver's four factors and the shooting splits - on the shared
table (gordstats.stats_page) the CFB and NFL pages use.

    T-Rank          {TRANK_YEAR}_team_results.csv, the table render_power
                    already caches: adjusted offensive and defensive
                    efficiency (points per 100 possessions against an average
                    D-I team), tempo, Barthag, projected record, SOS, WAB
    four factors    {TRANK_YEAR}_fffinal.csv: effective FG%, turnover rate,
                    offensive rebound rate and free-throw rate, both ends,
                    plus 2- and 3-point, free-throw and assist rates. Torvik
                    publishes it once games are played; until then those
                    columns are left off rather than shown empty.

Preseason every figure is Torvik's projection; the page says so.

    python -m cbb.render.render_stats
"""
import time
import warnings
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from cbb import paths
from cbb.render import render_power
from cbb.render.render_power import SEASON_LABEL, TRANK_YEAR
from gordstats import stats_page
from gordstats.frontmatter import add_front_matter

OUT = paths.DOCS / "cbb" / "stats" / "index.html"
FF_URL = f"https://barttorvik.com/{TRANK_YEAR}_fffinal.csv"
FF_CACHE = paths.DATA / "cbb" / f"fffinal_{TRANK_YEAR}.csv"
# The women's, for the women's previews (cbb.render.render_previews).
FF_URL_W = f"https://barttorvik.com/ncaaw/{TRANK_YEAR}_fffinal.csv"
FF_CACHE_W = paths.DATA / "cbb" / f"fffinal_w_{TRANK_YEAR}.csv"
MAX_AGE_HOURS = 12

# The fffinal file is value, rank, value, rank... under repeated "Rk" headers;
# these are its values in order, named for the page.
FF_FIELDS = ["efg", "efg_d", "ftr", "ftr_d", "orb", "drb", "tov", "tov_d", "p3", "p3_d",
             "p2", "p2_d", "ft", "ft_d", "r3", "r3_d", "ast", "ast_d"]

POWER_CONFS = {"ACC", "B10", "B12", "SEC", "BE"}


def four_factors(refresh: bool = False, gender: str = "M") -> dict:
    """{team: {field: value}} from Torvik's four-factors file, or {} before he
    publishes it for the season. Cached beside the T-Rank table; `gender`
    "W" is the women's."""
    url, cache = (FF_URL, FF_CACHE) if gender == "M" else (FF_URL_W, FF_CACHE_W)
    fresh = cache.exists() and time.time() - cache.stat().st_mtime < MAX_AGE_HOURS * 3600
    if not fresh or refresh:
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=25)
            if r.status_code == 200 and r.text.lstrip().startswith("TeamName"):
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(r.text, encoding="utf-8")
        except requests.RequestException as exc:
            print(f"  ! four factors fetch failed ({exc}); using the cache")
    if not cache.exists():
        return {}
    # Torvik's rows carry more fields than his header (trailing ones), and
    # pandas would take the extras as an index - keying every team by a rank.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", pd.errors.ParserWarning)
        raw = pd.read_csv(cache, index_col=False)
    values = raw.iloc[:, 1::2]                     # skip the rank beside each figure
    out = {}
    for team, row in zip(raw.iloc[:, 0], values.itertuples(index=False)):
        # Every figure in the file is a percentage (49.4 is 49.4%); the page's
        # "pct" format wants a share.
        out[str(team)] = {k: None if pd.isna(v) else round(float(v) / 100, 4)
                          for k, v in zip(FF_FIELDS, row)}
    return out


def _c(key, label, tip, fmt, better, *views):
    return {"key": key, "label": label, "tip": tip, "fmt": fmt, "better": better, "views": views}


BASE = [
    _c("rec", "Rec", "Won-lost this season.", "rec", None, "overview"),
    _c("trank", "T-Rank", "Bart Torvik's rank, by Barthag.", "int", "low", "overview"),
    _c("net", "Net", "Adjusted offensive efficiency minus adjusted defensive efficiency: points per "
       "100 possessions better than an average D-I team would be against the same schedule.",
       "num1", "high", "overview"),
    _c("adjoe", "AdjO", "Points scored per 100 possessions, adjusted for the defenses faced and "
       "where the games were played.", "num1", "high", "overview", "offense"),
    _c("adjde", "AdjD", "Points allowed per 100 possessions, adjusted. Lower is better.",
       "num1", "low", "overview", "defense"),
    _c("barthag", "Barthag", "Chance of beating an average D-I team on a neutral floor.",
       "pct", "high", "overview"),
    _c("proj", "Proj W-L", "Torvik's projected final record.", "rec", None, "overview"),
    _c("tempo", "Tempo", "Adjusted possessions per 40 minutes.", "num1", None, "overview",
       "situational"),
    _c("sos", "SOS", "Strength of schedule (Barthag of the average opponent) - projected for the "
       "whole season before games are played.", "num2", "high", "situational"),
    _c("ncsos", "Non-conf SOS", "The same for the non-conference schedule.", "num2", "high",
       "situational"),
    _c("wab", "WAB", "Wins above bubble: wins beyond what a bubble team would have against this "
       "schedule. Zero before games.", "num1", "high", "situational"),
    _c("conf_proj", "Conf proj", "Torvik's projected conference record.", "rec", None,
       "situational"),
]

FOUR = [
    _c("efg", "eFG%", "Effective field goal %: made threes count 1.5.", "pct", "high", "offense"),
    _c("tov", "TO%", "Turnovers per possession.", "pct", "low", "offense"),
    _c("orb", "OR%", "Share of its own misses the offense rebounds.", "pct", "high", "offense"),
    _c("ftr", "FT rate", "Free throws attempted per field goal attempt.", "pct", "high", "offense"),
    _c("p3", "3P%", "Three-point percentage.", "pct", "high", "offense"),
    _c("p2", "2P%", "Two-point percentage.", "pct", "high", "offense"),
    _c("r3", "3P rate", "Share of shots taken from three.", "pct", None, "offense"),
    _c("ft", "FT%", "Free-throw percentage.", "pct", "high", "offense"),
    _c("ast", "Ast rate", "Share of made baskets assisted.", "pct", None, "offense"),
    _c("efg_d", "eFG% allowed", "Opponents' effective field goal %.", "pct", "low", "defense"),
    _c("tov_d", "TO% forced", "Opponents' turnovers per possession.", "pct", "high", "defense"),
    # Torvik's "DR%" is the opponents' offensive rebounding: the share of
    # their own misses they get back. Low is the good end.
    _c("drb", "OR% allowed", "Share of their own misses opponents rebound.", "pct", "low",
       "defense"),
    _c("ftr_d", "FT rate allowed", "Opponents' free throws per field goal attempt.", "pct", "low",
       "defense"),
    _c("p3_d", "3P% allowed", "Opponents' three-point percentage.", "pct", "low", "defense"),
    _c("p2_d", "2P% allowed", "Opponents' two-point percentage.", "pct", "low", "defense"),
    _c("r3_d", "3P rate allowed", "Share of opponents' shots from three.", "pct", "low", "defense"),
]


def _record(w, l) -> str | None:
    try:
        return f"{round(float(w))}-{round(float(l))}"
    except (TypeError, ValueError):
        return None


def rows(trank: pd.DataFrame = None, ff: dict = None) -> list:
    df = render_power.trank() if trank is None else trank
    ff = four_factors() if ff is None else ff
    stars = {}
    try:
        stars = render_power.star_teams(df["team"])
    except Exception as exc:                      # logos are a nicety
        print(f"  ! CBB stats: no logos ({exc})")
    # star_teams is keyed by T-Rank's own slug; the rows are T-Rank's names.
    logo_by_team = {}
    for key, (name, logo) in stars.items():
        logo_by_team[key] = logo
        logo_by_team[name] = logo
    played = df["record"].astype(str).str.split("-").str[0].astype(int).sum() > 0
    out = []
    for r in df.itertuples(index=False):
        t = r._asdict()
        team, conf = str(t["team"]), str(t["conf"])
        adjoe, adjde = float(t["adjoe"]), float(t["adjde"])
        row = {
            "name": team, "group": conf, "tags": ["Power"] if conf in POWER_CONFS else [],
            "logo": logo_by_team.get(team),
            "rec": str(t["record"]) if played else None,
            "trank": int(t["rank"]), "net": round(adjoe - adjde, 1),
            "adjoe": round(adjoe, 1), "adjde": round(adjde, 1),
            "barthag": round(float(t["barthag"]), 4),
            "tempo": round(float(t["adjt"]), 1),
        }
        out.append(row)
    # Columns whose names itertuples cannot carry, read by name instead.
    by_name = df.set_index("team")
    for row in out:
        src = by_name.loc[row["name"]]
        row["proj"] = _record(src.get("proj. W"), src.get("Proj. L"))
        row["conf_proj"] = _record(src.get("Pro Con W"), src.get("Pro Con L"))
        sos = src.get("sos") if played else src.get("Proj. SOS")
        ncsos = src.get("ncsos") if played else src.get("Proj. Noncon SOS")
        row["sos"] = None if pd.isna(sos) else round(float(sos), 3)
        row["ncsos"] = None if pd.isna(ncsos) else round(float(ncsos), 3)
        wab = src.get("WAB")
        row["wab"] = round(float(wab), 1) if played and not pd.isna(wab) else None
        for k, v in (ff.get(row["name"]) or {}).items():
            row[k] = v
    return out


def columns(have_ff: bool, played: bool) -> list:
    cols = [c for c in BASE if played or c["key"] not in ("rec", "wab")]
    return cols + (FOUR if have_ff else [])


def body() -> str:
    df = render_power.trank()
    ff = four_factors()
    played = df["record"].astype(str).str.split("-").str[0].astype(int).sum() > 0
    table_rows = rows(df, ff)
    cols = columns(bool(ff), played)
    confs = sorted({r["group"] for r in table_rows}, key=lambda c: (c not in POWER_CONFS, c))
    filters = [("", "All D-I"), ("Power", "Power conferences")] + [(c, c) for c in confs]
    views = stats_page.VIEWS if ff else [("overview", "Overview"), ("situational", "Schedule")]
    lede = ("Every Division I team on Bart Torvik's adjusted efficiency - points per 100 "
            "possessions, allowing for the opponents and the floor"
            + ("" if played else " - projected until the season tips off")
            + ". Tap a column to sort; the shading is where a team ranks.")
    extra = ("<p><b>Adjusted efficiency</b> is points per 100 possessions against an average D-I "
             "team on a neutral floor. The four factors (Dean Oliver's: shooting, turnovers, "
             "rebounding, free throws) "
             + ("are as played." if ff else "join the table once games are played.")
             + " Source: barttorvik.com.</p>")
    return ("<p>" + lede + "</p>"
            + stats_page.table(table_rows, cols, views=views, filters=filters,
                               filter_label="Show", sort_key="trank")
            + stats_page.glossary(cols, extra))


def generate() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    # "Updated" is when T-Rank was last downloaded, as on the rankings page.
    fetched = datetime.fromtimestamp(render_power._cache_path().stat().st_mtime,
                                     tz=ZoneInfo("America/New_York"))
    OUT.write_text(add_front_matter(
        body(), "Team Stats", f"{SEASON_LABEL} season, Torvik's numbers", updated=fetched,
        description="Every Division I basketball team's adjusted offense, defense, tempo and "
                    "schedule, and the four factors once games are played."),
        encoding="utf-8")
    print(f"Wrote CBB team stats -> {OUT}")


if __name__ == "__main__":
    generate()
