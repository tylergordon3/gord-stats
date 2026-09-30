"""
Power Rankings page (docs/fantasy/power/).

The draft page grades the picks. This one grades the rosters they add up to,
and it does it without looking at where anyone was drafted — see
`fantasy.projections` for why that constraint shapes the whole model, and
`fantasy.league.power` for the simulation that turns projections into wins.

Sections, each kept to its table or chart plus a line of context. All but
Method are open on the page - they are the page; Method is reference:
  * The rankings, with record, playoff odds and the projected-wins range.
  * The frozen three-source draft-week rankings.
  * Every team's rating build by build.
  * Where each team's strength sits, position by position, starters and
    bench, on Sleeper's season projections.
  * Method, with player accuracy and the roster backtest.

    python -m fantasy.site.power
"""
import json
from datetime import datetime
from html import escape

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np               # noqa: E402
import pandas as pd              # noqa: E402

from fantasy import paths                                      # noqa: E402
from fantasy.config import (                                   # noqa: E402
    FANTASY_REG_WEEKS, FORMAL_SEASON, LEAGUE_IDS, UPCOMING_SEASON, UPCOMING_YEAR,
)
from fantasy.league import consensus, external, power, validation  # noqa: E402
from fantasy.league import matchups as league_matchups         # noqa: E402
from fantasy.site import layout, styles                        # noqa: E402
from gordstats import charts, palette, share_button, share_card, stakes  # noqa: E402
from gordstats import my_league, my_league_data, my_power       # noqa: E402
from gordstats.frontmatter import add_front_matter             # noqa: E402

_GRID = [styles.GRID_TD, styles.GRID_TH, styles.TABLE_STYLE]
_SECTION = "power"

# Shared with every other chart on the site; see gordstats.palette for why
# three categorical slots is the cap rather than an arbitrary stopping point.
SOURCE_COLOURS = dict(zip(("us", "fp", "ff"), palette.SERIES))
INK = palette.INK
MUTED = palette.MUTED
GRIDLINE = palette.GRIDLINE
CONTEXT = palette.CONTEXT

# (anchor, heading, jump-bar label, collapsible). How the rankings have moved
# through the season sits right under them; the draft-week three-source table,
# frozen on draft week, folds away with Method - it is the fixed point later
# ratings are read against, and by October a reference rather than the news.
SECTIONS = [
    ("mine", "Your League", "Yours", False),
    ("rankings", "Power Rankings", "Rankings", False),
    ("season", "Through the Season", "Season", False),
    ("stakes", "This Week's Stakes", "Stakes", False),
    ("positions", "Positional Strength", "Positions", False),
    ("draft-consensus", "Draft Rankings (frozen)", "Draft", True),
    ("method", "Method", "Method", True),
]

INTRO = f"""<p id="pw-intro">Every Sleeper roster played through {UPCOMING_SEASON}
ten thousand times, averaged with the FantasyPros League Analyzer. <strong>100 is
the league average</strong>; a point is one percent better.</p>"""


# --------------------------------------------------------------------------- #
# Rankings table
# --------------------------------------------------------------------------- #

def _record(wins: float) -> str:
    """Projected wins as a record. Each week awards two: opponent and median."""
    games = FANTASY_REG_WEEKS * 2
    return f"{wins:.1f}-{games - wins:.1f}"


def _signed(v) -> str:
    """+2 / -1 / blank, for the rank-movement columns."""
    if pd.isna(v) or int(v) == 0:
        return "" if pd.isna(v) else "&middot;"
    return f"{int(v):+d}"


def _manager_col(ranks, managers) -> list[str]:
    """Rank folded into the manager cell: '3 Kraft YAC-N-Chee'.

    The rank used to be its own leading '#' column, which meant the frozen
    first column (see .sticky-table td:first-child) pinned a counter while
    the name - the thing a scrolled row is about - slid away on a phone.
    """
    return [f'<span class="row-rank">{int(r)}</span>{escape(str(m))}'
            for r, m in zip(ranks, managers)]


# --------------------------------------------------------------------------- #
# Heat shading, for both themes
# --------------------------------------------------------------------------- #

def _heat(col: pd.Series, cmap: str = "RdYlGn", vmin=None, vmax=None) -> list[str]:
    """The RdYlGn shading as a translucent wash over the cell's own background.

    pandas' background_gradient paints opaque colours in an ID rule, so the
    table's dark theme never reached them: at night the neutral "·" of Move
    and every middling rating were pale-yellow blocks on navy. A wash - the
    ramp's colour at an opacity that grows with the distance from the middle
    - sits on whatever the cell already is, white or zebra or navy, with the
    theme's own ink on top, and the middle of the scale is no colour at all.

    It is a background-image layer rather than a background-color so the
    themed colour underneath survives. How strong the ends get is --heat,
    set per theme on .pw-table (_TABLE_CSS): .35 keeps the light theme's
    slate ink at 4.8:1 on the reddest cell, and the dark theme can take .6.
    """
    values = pd.to_numeric(col, errors="coerce")
    lo = values.min() if vmin is None else vmin
    hi = values.max() if vmax is None else vmax
    span = (hi - lo) or 1.0
    ramp = matplotlib.colormaps[cmap]
    out = []
    for v in values:
        t = 0.5 if pd.isna(v) else min(max((v - lo) / span, 0.0), 1.0)
        strength = abs(2 * t - 1)
        if strength < 0.03:
            out.append("")
            continue
        r, g, b = (round(c * 255) for c in ramp(t)[:3])
        wash = f"rgb({r} {g} {b} / calc(var(--heat, .35) * {strength:.2f}))"
        out.append(f"background-image: linear-gradient({wash}, {wash})")
    return out


# Every pandas table on the page carries .pw-table. The phone rules undo the
# site-wide sticky-table floor (every column 70px or more, the first 150px),
# which gave "+2" a 90px column and put Record, Playoffs and Title past the
# edge of a 390px screen; each column now takes what its header needs.
_TABLE_CSS = """<style>
.pw-table{--heat:.35}
@media (prefers-color-scheme: dark){ .pw-table{--heat:.6} }
@media (max-width:600px){
  /* important: pandas states the padding in an ID rule (styles.GRID_TD). */
  .sticky-table.pw-table th,.sticky-table.pw-table td{min-width:0;padding:6px 7px !important}
  .sticky-table.pw-table td:first-child,.sticky-table.pw-table th:first-child{
    min-width:0;max-width:122px}
  .sticky-table.pw-table .row-rank{min-width:1.5em;font-size:12px}
}
</style>"""

# The name column reads left to right like every name column; pandas states
# its grid centred in an ID rule, so the override has to be one too.
_NAME_LEFT = [{"selector": "td.col0", "props": [("text-align", "left")]},
              {"selector": "th.col0", "props": [("text-align", "left")]}]


def _rankings_table(table: pd.DataFrame) -> str:
    in_season = "wins" in table.columns and table["week"].iloc[0] > 0
    display = pd.DataFrame(
        {"Manager": _manager_col(table["rank"], table["manager"])})
    blended = "combined" in table.columns and table.get("ext_vorp") is not None \
        and table["ext_vorp"].notna().any()
    short = table.attrs.get("ext_short", "Ext")
    rating = "Rating" if blended else "Power"
    # What a phone sees beside the name is what a reader came for - the
    # record, then the playoff and title odds - with the rating the rows are
    # ranked by after it, and the movement and the parts of the blend last.
    if in_season:
        display["Record"] = (table["wins"].astype(int).astype(str) + "-"
                             + table["losses"].astype(int).astype(str))
    display["Playoffs"] = table["playoff_odds"]
    display["Title"] = table["title_odds"]
    display[rating] = table["combined"] if blended else table["power"]
    display["Move"] = table["move"]
    if blended:
        display["GordStats"] = table["power"]
        display[short] = table["ext_vorp"]
    display["Proj. Record"] = table["proj_wins"].map(_record)
    if in_season:
        display["Luck"] = table["luck"]

    fmt = {"Move": _signed, "Power": "{:.1f}", "Playoffs": "{:.0%}",
           "Title": "{:.0%}", "Luck": "{:+.1f}"}
    if blended:
        fmt.update({"Rating": "{:.1f}", "GordStats": "{:.1f}", short: "{:.1f}"})
    styled = (display.style.hide(axis="index").format(fmt, na_rep="")
              .apply(_heat, subset=[rating])
              .apply(_heat, subset=["Playoffs"]))
    if table["move"].notna().any():
        bound = max(1.0, float(table["move"].abs().max()))
        styled = styled.apply(_heat, subset=["Move"], vmin=-bound, vmax=bound)
    if in_season:
        bound = max(1.0, float(table["luck"].abs().max()))
        styled = styled.apply(_heat, subset=["Luck"], vmin=-bound, vmax=bound)
    return (styled.set_table_styles(_GRID + _NAME_LEFT, overwrite=False)
            .set_table_attributes('class="sticky-table pw-table"')).to_html()


def _with_external(table: pd.DataFrame) -> pd.DataFrame:
    """Attach the source descriptor for the legend.

    The ratings themselves arrive on the table from `power.rankings`, which is
    where the blend happens; this only reads the snapshot for who said it and
    when, and never re-fetches.
    """
    ext = external.load(int(UPCOMING_YEAR), live=False)
    if ext.empty:
        return table
    table = table.copy()
    table.attrs = dict(table.attrs) | {f"ext_{k}": v for k, v in ext.attrs.items()}
    return table


def _rankings_section(table: pd.DataFrame) -> str:
    table = _with_external(table)
    leader = table.iloc[0]
    tail = table.iloc[-1]
    week = int(table["week"].iloc[0])
    when = ("comes out of the draft with" if week == 0
            else f"has, through week {week},")
    note = (f"<p><strong>{leader['manager']}</strong> {when} the strongest roster: "
            f"{leader['playoff_odds']:.0%} playoffs, {leader['title_odds']:.0%} title "
            f"(<strong>{tail['manager']}</strong>: {tail['playoff_odds']:.0%}, "
            f"{tail['title_odds']:.0%}).</p>")

    legend = ["<strong>Move</strong>: places climbed since "
              + (f"{table.attrs['prev_taken']:%b %-d}" if "prev_taken" in table.attrs
                 else "the previous build")]
    if week > 0:
        legend.append("<strong>Record</strong> includes the weekly median win; "
                      "<strong>Luck</strong> is record minus all-play expectation. "
                      "Played weeks are locked in")
    if "combined" in table.columns and table["ext_vorp"].notna().any():
        src = table.attrs.get("ext_source", "an outside source")
        url = table.attrs.get("ext_url") or ""
        named = f"<a href='{url}'>{src}</a>" if url else src
        when = table.attrs.get("ext_captured") or ""
        try:
            when = f"{datetime.strptime(when, '%Y-%m-%d'):%b %-d}"
        except ValueError:
            pass
        short = table.attrs.get("ext_short", "Ext")
        legend.append(f"<strong>Rating</strong> averages <strong>GordStats</strong> (our "
                      f"simulation) and <strong>{short}</strong> ({named}"
                      + (f", {when}" if when else "") + ") as ratings, not ranks")

    top = ", ".join(f"{int(r['rank'])}. {r['manager']}" for _, r in table.head(3).iterrows())
    share = share_button.row("/fantasy/power/", (f"Power rankings through week {week}: {top}"
                                                 if week else f"Power rankings out of the draft: {top}"))
    return (f"{share}{note}"
            f"<div class='table-scroll'>{_rankings_table(table)}</div>"
            f"<p>{'. '.join(legend)}.</p>"
            + layout.details("Projected wins range", _range_chart(table)))


def _draft_chart(rows: pd.DataFrame) -> str:
    """Where the three sources agree, and where they do not.

    A dot per source on a shared scale, joined by the span between the highest
    and lowest of them. The span is the point of the chart: a roster every
    source rates the same is a roster we know something about, and a roster
    they disagree about by seventeen points is not a ranking at all, it is
    three opinions that happened to be averaged.
    """
    ordered = rows.sort_values("combined")            # best at the top once drawn
    y = np.arange(len(ordered))
    sources = [("us", "GordStats"), ("fp", "FantasyPros"), ("ff", "Fantasy Footballers")]

    fig, ax = plt.subplots(figsize=(9, 5.0))
    ax.axvline(100, color=MUTED, linewidth=1.0, linestyle="--", zorder=1)

    lo = ordered[[c for c, _ in sources]].min(axis=1)
    hi = ordered[[c for c, _ in sources]].max(axis=1)
    ax.hlines(y, lo, hi, color=CONTEXT, linewidth=2.0, zorder=2)

    for column, label in sources:
        ax.plot(ordered[column], y, "o", markersize=9, label=label,
                color=SOURCE_COLOURS[column], markeredgecolor="white",
                markeredgewidth=1.5, linestyle="none", zorder=3)
    ax.plot(ordered["combined"], y, "|", markersize=17, markeredgewidth=2.4,
            color=INK, label="Consensus", linestyle="none", zorder=4)

    ax.set_yticks(y)
    ax.set_yticklabels(ordered["manager"])
    ax.set_ylim(-0.7, len(ordered) - 0.3)
    ax.set_xlabel("rating (100 = league average)")
    ax.set_title("Draft power rankings, and how far the sources disagree")
    ax.grid(axis="x", color=GRIDLINE)
    ax.set_axisbelow(True)
    ax.tick_params(axis="y", length=0)      # the left spine is gone; its ticks would float
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.legend(fontsize=9, ncol=4, loc="upper center", bbox_to_anchor=(0.5, -0.11),
              frameon=False)
    fig.tight_layout()
    return charts.save("draft-consensus", "sources",
                       alt="Each team's rating from all three sources, with the "
                           "consensus marked and the spread between sources drawn")


def draft_consensus_section() -> str:
    """The three-source draft ranking, exactly as it was frozen - the static
    reference under the live table."""
    charts.clear("draft-consensus")
    snap = consensus.draft(int(UPCOMING_YEAR))
    if not snap or not snap.get("teams"):
        return ""
    rows = pd.DataFrame(snap["teams"])

    display = pd.DataFrame(
        {"Manager": _manager_col(rows["rank"], rows["manager"])})
    display["Consensus"] = rows["combined"]
    display["GordStats"] = rows["us"]
    display["FP"] = rows["fp"]
    display["FF"] = rows["ff"]
    display["GordStats #"] = rows["us_rank"]
    display["FP #"] = rows["fp_rank"]
    display["FF #"] = rows["ff_rank"]

    fmt = {c: "{:.1f}" for c in ["Consensus", "GordStats", "FP", "FF"]}
    styled = (display.style.hide(axis="index").format(fmt, na_rep="")
              .apply(_heat, subset=["Consensus"])
              .set_table_styles(_GRID + _NAME_LEFT, overwrite=False)
              .set_table_attributes('class="sticky-table pw-table"'))

    frozen = snap.get("frozen", "")
    try:
        frozen = f"{datetime.strptime(frozen, '%Y-%m-%d'):%B %-d, %Y}"
    except ValueError:
        pass
    widest = (rows[["us", "fp", "ff"]].max(axis=1) - rows[["us", "fp", "ff"]].min(axis=1))
    argued = rows.loc[widest.idxmax()]

    note = (f"<p>All three sources on draft-week rosters, frozen <strong>{frozen}</strong>. "
            f"Widest disagreement: <strong>{argued['manager']}</strong>, "
            f"{widest.max():.0f} points.</p>")
    legend = ("<p><strong>GordStats</strong> is our simulation, "
              "<strong>FP</strong> the FantasyPros League Analyzer, <strong>FF</strong> The "
              "Fantasy Footballers' projected points per game (their points, not their "
              "grade-sorted rank).</p>")
    return (note + _draft_chart(rows)
            + f"<div class='table-scroll'>{styled.to_html()}</div>{legend}")


def _season_section() -> str:
    """Every team's published rating, build by build."""
    year = int(UPCOMING_YEAR)
    hist = power.history(year)
    column = "combined" if not hist.empty and "combined" in hist.columns else "power"
    if hist.empty or hist["taken"].dt.date.nunique() < 2:
        return ("<p>Each team's rating across every build; the chart appears once a "
                "second day is on record.</p>")

    pivot = hist.pivot_table(index="taken", columns="manager", values=column).sort_index()
    order = [m for m in pivot.iloc[-1].sort_values(ascending=False).index]

    cols = 5
    fig_rows = int(np.ceil(len(order) / cols))
    fig, axes = plt.subplots(fig_rows, cols, figsize=(11, 2.5 * fig_rows),
                             sharex=True, sharey=True)
    axes = np.atleast_1d(axes).ravel()

    for ax, manager in zip(axes, order):
        # Ten lines on one pair of axes is a tangle and needs ten colours nobody
        # can tell apart. One panel each, with the rest kept as grey context, so
        # a team is read against the league instead of against a legend.
        for other in pivot.columns:
            ax.plot(pivot.index, pivot[other], color=CONTEXT, linewidth=1.0, zorder=1)
        ax.plot(pivot.index, pivot[manager], color=SOURCE_COLOURS["us"],
                linewidth=2.0, marker="o", markersize=4, zorder=3)
        ax.axhline(100, color=MUTED, linewidth=0.9, linestyle="--", zorder=2)
        ax.set_title(manager, fontsize=10)
        ax.grid(color=GRIDLINE)
        ax.set_axisbelow(True)
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)
        ax.tick_params(labelsize=8)
        # Ten panels share one x-axis; full ISO dates on each collide into a
        # smear. A handful of "Sep 3" ticks is all a reader needs here.
        ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=2, maxticks=4))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %-d"))
        for label in ax.get_xticklabels():
            label.set_rotation(30)
            label.set_horizontalalignment("right")
    for ax in axes[len(order):]:
        ax.set_visible(False)

    fig.suptitle("Published rating through the season, one panel per team", y=1.0)
    fig.tight_layout()
    chart = charts.save(_SECTION, "season-trend",
                        alt="One small chart per team showing its rating across every "
                            "build, with the rest of the league in grey behind it")
    first, last = pivot.index[0], pivot.index[-1]
    swing = (pivot.iloc[-1] - pivot.iloc[0])
    up, down = swing.idxmax(), swing.idxmin()
    return (f"<p>Since <strong>{first:%b %-d}</strong>: <strong>{up}</strong> "
            f"{swing[up]:+.1f}, <strong>{down}</strong> {swing[down]:+.1f}.</p>" + chart)


# --------------------------------------------------------------------------- #
# Range chart
# --------------------------------------------------------------------------- #

def _range_chart(table: pd.DataFrame) -> str:
    """Projected wins with the middle 80% of seasons - the uncertainty behind
    the odds, kept under the table rather than as a section of its own."""
    ordered = table.sort_values("proj_wins")
    positions = np.arange(len(ordered))
    low = ordered["proj_wins"] - ordered["wins_p10"]
    high = ordered["wins_p90"] - ordered["proj_wins"]

    fig, ax = plt.subplots(figsize=(9, 4.6))
    ax.errorbar(ordered["proj_wins"], positions, xerr=[low, high], fmt="o",
                color="#334155", ecolor="#94a3b8", elinewidth=3, capsize=4,
                markersize=7)
    ax.set_yticks(positions)
    ax.set_yticklabels(ordered["manager"])
    ax.set_xlabel(f"projected wins (of {FANTASY_REG_WEEKS * 2})")
    ax.set_title("Projected wins, with the middle 80% of simulated seasons")
    ax.grid(axis="x", color="#e2e8f0")
    ax.set_axisbelow(True)
    chart = charts.save(_SECTION, "win-range",
                        alt="Projected wins per team with 10th-90th percentile bars")

    overlap = (table["wins_p90"].min() >= table["wins_p10"].max())
    caveat = ("Every team's range overlaps every other team's" if overlap
              else "Most of these ranges overlap")
    return (f"<p>Dot: average season; bar: middle 80%. {caveat}.</p>" + chart)


# --------------------------------------------------------------------------- #
# Positional strength
# --------------------------------------------------------------------------- #

# Bench depth that counts per position: the backups who would actually step
# in for a starter. A fourth backup receiver never plays for this roster.
BENCH_DEPTH = {"QB": 1, "RB": 2, "WR": 2, "TE": 1}
POS_ORDER = ["QB", "RB", "WR", "TE", "FLEX", "K", "DEF"]


def _positional_frame(rosters: pd.DataFrame, proj: dict) -> dict:
    """{manager: {"start": {slot: [(name, ppg)]}, "bench": {pos: [(name, ppg)]}}}.

    Starters are filled the way the league's lineup is - QB, 2 RB, 2 WR, TE,
    then the best two RB/WR/TE left for FLEX, K, DEF - on Sleeper's projected
    points per game. Whoever is left at a position, best first, is its bench.
    """
    out = {}
    for rid, group in rosters.groupby("roster_id"):
        players = []
        for pid in group["sleeper_id"].astype(str):
            p = proj.get(pid)
            if p and p.get("ppg") is not None and p.get("pos") in power.STARTERS:
                players.append((p["pos"], p["name"] or pid, float(p["ppg"])))
        players.sort(key=lambda x: -x[2])
        start = {pos: [] for pos in POS_ORDER}
        left = []
        for pos, name, ppg in players:
            if len(start[pos]) < power.STARTERS[pos]:
                start[pos].append((name, ppg))
            else:
                left.append((pos, name, ppg))
        bench = {pos: [] for pos in BENCH_DEPTH}
        for pos, name, ppg in left:
            if pos in power.FLEX_POSITIONS and len(start["FLEX"]) < power.FLEX_SLOTS:
                start["FLEX"].append((name, ppg))
            elif pos in bench and len(bench[pos]) < BENCH_DEPTH[pos]:
                bench[pos].append((name, ppg))
        out[power.ROSTER_NAMES.get(rid, f"Roster {rid}")] = {"start": start, "bench": bench}
    return out


_POS_CSS = """<style>
.ps-viz{--ps-up:#2a78d6;--ps-down:#e34948;--ps-text:#0f172a;--ps-muted:#64748b;
  --ps-rule:#e2e8f0;--ps-panel:#ffffff;--ps-border:#e5e7eb;--ps-avg:#94a3b8}
@media (prefers-color-scheme: dark){
  .ps-viz{--ps-up:#3987e5;--ps-down:#e66767;--ps-text:#e3eaf4;--ps-muted:#aab7c9;
    --ps-rule:#2b3852;--ps-panel:#16203a;--ps-border:#2b3852;--ps-avg:#7f8ea3}
}
.ps-legend{display:flex;flex-wrap:wrap;gap:6px 16px;align-items:center;font-size:13px;color:var(--ps-muted);margin:4px 0 10px}
.ps-legend span{white-space:nowrap}
.ps-legend i{display:inline-block;width:14px;height:8px;border-radius:0 4px 4px 0;margin-right:6px;vertical-align:middle}
.ps-legend .avg{width:0;height:12px;border-left:2px solid var(--ps-avg);border-radius:0}
.ps-legend .thick{height:10px;border-radius:4px;background:var(--ps-muted)}
.ps-legend .thin{height:4px;border-radius:4px;background:var(--ps-muted)}
.ps-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:14px}
.ps-panel{background:var(--ps-panel);border:1px solid var(--ps-border);border-radius:12px;padding:12px 14px 10px}
.ps-panel h3{margin:0 0 2px;font-size:15px;color:var(--ps-text);text-align:left}
.ps-panel .ps-sub{font-size:12px;color:var(--ps-muted);margin:0 0 8px}
.ps-row{display:grid;grid-template-columns:78px 1fr 70px;align-items:center;column-gap:8px;
  padding:3px 0;border-radius:6px;cursor:default}
.ps-row:hover{background:var(--ps-rule)}
.ps-name{font-size:13px;font-weight:600;color:var(--ps-text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ps-name .rk{display:inline-block;width:16px;font-size:11px;font-weight:500;color:var(--ps-muted)}
.ps-track{position:relative;height:22px}
.ps-bar{position:absolute;min-width:2px}
.ps-bar.up{background:var(--ps-up);border-radius:0 4px 4px 0}
.ps-bar.down{background:var(--ps-down);border-radius:4px 0 0 4px}
.ps-bar.s{top:2px;height:11px}
.ps-bar.b{top:15px;height:5px}
.ps-avgline{position:absolute;left:50%;top:-3px;bottom:-3px;border-left:2px solid var(--ps-avg)}
.ps-axis{display:grid;grid-template-columns:78px 1fr 70px;column-gap:8px;font-size:11px;color:var(--ps-muted);margin-bottom:2px}
.ps-axis span{display:flex;justify-content:space-between}
.ps-val{font-size:13px;font-weight:700;color:var(--ps-text);text-align:right;font-variant-numeric:tabular-nums;line-height:1.1}
.ps-val small{display:block;font-size:11px;font-weight:500;color:var(--ps-muted)}
.ps-val .d{font-weight:600;color:var(--ps-muted);font-size:11px;margin-left:3px}
.ps-table{margin-top:12px}
.ps-table table{border-collapse:collapse;font-size:13px;width:100%}
.ps-table th,.ps-table td{padding:5px 8px;text-align:center;white-space:nowrap;border-bottom:1px solid var(--ps-rule);color:var(--ps-text)}
/* The theme paints every th #373737, and this header set only its text:
   #0f172a on it read at 1.5:1 in the light theme (the 2026-09-28 phone audit). */
.ps-table th{background:var(--ps-rule)}
.ps-table td:first-child{text-align:left;font-weight:600}
/* The phone floor: the ranks, the gaps to average, the bench line and the
   axis were 11px, which is the size this site stopped using for numbers. */
@media (max-width:600px){
  .ps-name .rk,.ps-axis,.ps-val small,.ps-val .d{font-size:12px}
}
</style>"""


def _positions_section(rosters: pd.DataFrame, table: pd.DataFrame) -> str:
    """Small multiples: one panel per position, every team a row in power-rank
    order (so a team sits on the same line in every panel), starters as the
    main bar and bench depth as a thin one under it, on that panel's own scale
    from zero, with the league's average starter figure dashed across."""
    proj = league_matchups.sleeper_season_projections(int(UPCOMING_YEAR))
    if not proj:
        return "<p>Sleeper's projections are unavailable right now.</p>"
    frame = _positional_frame(rosters, proj)
    managers = [m for m in table["manager"] if m in frame]
    rank_of = dict(zip(table["manager"], table["rank"]))

    def total(names):
        return sum(ppg for _, ppg in names)

    def players(names):
        return ", ".join(f"{n} {ppg:.1f}" for n, ppg in names) or "nobody"

    panels = [("ALL", "Whole roster", "All starters, and the bench depth below them")]
    panels += [(pos, pos, "Starters and the next " + str(BENCH_DEPTH[pos]) + " behind them"
                if pos in BENCH_DEPTH else
                "The best two RB/WR/TE left after the starters" if pos == "FLEX" else "The starter")
               for pos in POS_ORDER]

    html = []
    for key, title, sub in panels:
        rows = []
        for m in managers:
            if key == "ALL":
                st = sum(total(frame[m]["start"][p]) for p in POS_ORDER)
                bn = sum(total(frame[m]["bench"][p]) for p in BENCH_DEPTH)
                tip = f"{m}: starters {st:.1f}, bench {bn:.1f} projected points per game"
            else:
                st = total(frame[m]["start"][key])
                bn = total(frame[m]["bench"][key]) if key in BENCH_DEPTH else None
                tip = (f"{m} {key}: {players(frame[m]['start'][key])}"
                       + (f" | bench: {players(frame[m]['bench'][key])}" if bn is not None else ""))
            rows.append((m, st, bn, tip))
        # Each bar is the gap to the league's average at this position -
        # starters against starters, bench against bench - on a scale shared
        # by both and symmetric about the average, so left is below and right
        # is above and the lengths compare across the panel.
        # A team with nobody behind its starters at a position draws no bench
        # bar at all - a bar would read as a measured shortfall - and stays
        # out of the bench average, which is over the benches that exist.
        empty = {m for m in managers if key != "ALL" and key in BENCH_DEPTH
                 and not frame[m]["bench"][key]}
        avg = sum(st for _, st, _, _ in rows) / len(rows)
        has_bench = rows[0][2] is not None
        benches = [bn for m, _, bn, _ in rows if has_bench and m not in empty]
        bavg = sum(benches) / len(benches) if benches else 0.0
        reach = max([abs(st - avg) for _, st, _, _ in rows]
                    + [abs(bn - bavg) for bn in benches]) or 1.0

        def bar(delta, cls):
            w = abs(delta) / reach * 50
            side = "up" if delta >= 0 else "down"
            left = 50 if delta >= 0 else 50 - w
            return f'<div class="ps-bar {cls} {side}" style="left:{left:.1f}%;width:{w:.1f}%"></div>'

        lines = []
        for m, st, bn, tip in rows:
            val = (f"{st:.1f}<span class='d'>{st - avg:+.1f}</span>"
                   + ("<small>no bench</small>" if m in empty
                      else f"<small>bench {bn:.1f}</small>" if bn is not None else ""))
            lines.append(
                f'<div class="ps-row" title="{escape(tip, quote=True)}">'
                f'<div class="ps-name"><span class="rk">{int(rank_of[m])}</span>{escape(m)}</div>'
                f'<div class="ps-track"><div class="ps-avgline"></div>{bar(st - avg, "s")}'
                + (bar(bn - bavg, "b") if bn is not None and m not in empty else "")
                + f'</div><div class="ps-val">{val}</div></div>')
        axis = (f'<div class="ps-axis"><i></i><span><b>&minus;{reach:.1f}</b>'
                f'<b>avg</b><b>+{reach:.1f}</b></span><i></i></div>')
        avgs = f"avg {avg:.1f}" + (f", bench {bavg:.1f}" if has_bench else "")
        html.append(f'<div class="ps-panel"><h3>{title}</h3><p class="ps-sub">{sub} &middot; '
                    f'{avgs}</p>{axis}{"".join(lines)}</div>')

    # The same numbers as a plain table, for anyone who wants to read across.
    head = ("<tr><th>Manager</th>" + "".join(
        f"<th>{p}</th>" + (f"<th>{p} bench</th>" if p in BENCH_DEPTH else "") for p in POS_ORDER)
        + "<th>Starters</th><th>Bench</th></tr>")
    body = []
    for m in managers:
        cells = [f"<td>{int(rank_of[m])} {escape(m)}</td>"]
        for p in POS_ORDER:
            cells.append(f"<td>{total(frame[m]['start'][p]):.1f}</td>")
            if p in BENCH_DEPTH:
                cells.append(f"<td>{total(frame[m]['bench'][p]):.1f}</td>")
        cells.append(f"<td>{sum(total(frame[m]['start'][p]) for p in POS_ORDER):.1f}</td>")
        cells.append(f"<td>{sum(total(frame[m]['bench'][p]) for p in BENCH_DEPTH):.1f}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    table_html = ("<details class='ps-table'><summary>Show as a table</summary>"
                  "<div class='table-scroll'><table><thead>" + head + "</thead><tbody>"
                  + "".join(body) + "</tbody></table></div></details>")

    note = ("<p>Projected points per game from <strong>Sleeper's season projections</strong>, "
            "filled the way the lineup is: QB, two RBs, two WRs, TE, the best two RB/WR/TE left "
            "at FLEX, K and DEF. The bench is the next "
            + ", ".join(f"{n} {pos}" for pos, n in BENCH_DEPTH.items())
            + " &mdash; the depth that would step in. Each bar is the gap to the league average "
            "at that position: <strong>right of the line is better than average, left is "
            "worse</strong>. Teams run in power-ranking order in every panel; hover a row for "
            "the players.</p>")
    legend = ('<div class="ps-legend"><span><i class="thick"></i>Starters</span>'
              '<span><i class="thin"></i>Bench</span>'
              '<span><i style="background:var(--ps-up)"></i>Above average</span>'
              '<span><i style="background:var(--ps-down)"></i>Below average</span>'
              '<span><i class="avg"></i>League average</span></div>')
    return (_POS_CSS + '<div class="ps-viz">' + note + legend
            + '<div class="ps-grid">' + "".join(html) + "</div>" + table_html + "</div>")


# --------------------------------------------------------------------------- #
# Method + backtest
# --------------------------------------------------------------------------- #

def _player_accuracy_section(scored: dict) -> str:
    """The model's own report card: projected points per game vs actual."""
    frame = validation.accuracy_frame(scored)
    if frame.empty:
        return ""

    pivot = frame.pivot_table(index="pos", columns="season", values="correlation")
    pivot = pivot.reindex([p for p in ["QB", "RB", "WR", "TE"] if p in pivot.index])
    pivot["Average"] = pivot.mean(axis=1)
    pivot.columns = [str(c) for c in pivot.columns]
    pivot.index.name = "Position"

    html = (pivot.style.format("{:+.2f}")
            .apply(_heat, vmin=-0.8, vmax=0.8)
            .set_table_styles(_GRID, overwrite=False)
            .set_table_attributes('class="sticky-table pw-table"')).to_html()
    return f"<div class='table-scroll'>{html}</div>"


def _backtest_section(scored: dict) -> str:
    blocks, correlations = [], []
    for season_str in LEAGUE_IDS:
        result = validation.backtest_frame(scored, season_str)
        if result.empty:
            continue
        spearman = scored["spearman"][season_str]
        correlations.append(spearman)
        display = result.sort_values("proj_rank")[
            ["manager", "proj_rank", "proj_points", "actual_rank", "PF", "total_wins"]]
        display = display.rename(columns={
            "manager": "Manager", "proj_rank": "Projected", "proj_points": "Proj. Points",
            "actual_rank": "Actual", "PF": "Actual Points", "total_wins": "Wins"})
        html = (display.style.hide(axis="index")
                .format({"Proj. Points": "{:,.0f}", "Actual Points": "{:,.0f}"})
                .apply(_heat, cmap="RdYlGn_r", subset=["Projected", "Actual"])
                .set_table_styles(_GRID + _NAME_LEFT, overwrite=False)
                .set_table_attributes('class="sticky-table pw-table"')).to_html()
        blocks.append((season_str, FORMAL_SEASON[season_str],
                       f"<p>Rank correlation: <strong>{spearman:+.2f}</strong>.</p>"
                       f"<div class='table-scroll'>{html}</div>"))

    if not blocks:
        return "<p>No completed season is available to backtest against yet.</p>"

    average = sum(correlations) / len(correlations)
    verdict = (
        f"<p>Average over {len(correlations)} seasons: <strong>{average:+.2f}</strong>. "
        f"Thirty team-seasons can't separate a good roster model from a coin flip; "
        f"read the rankings as a measure of what was drafted, not a forecast.</p>")
    return layout.view_switcher(blocks, group="backtest", label="Season:") + verdict


def _method_section() -> str:
    scored = validation.load()
    from fantasy.projections import MARKET_WEIGHT

    market_pct = round(MARKET_WEIGHT * 100)
    return ("<ul>"
            f"<li><strong>Projection:</strong> {market_pct}% consensus ADP (turned into "
            f"points by a per-position curve), {100 - market_pct}% a usage ridge regression "
            "on last season's targets, carries, air yards and WOPR. Consensus correlated "
            "0.81 with actual points in held-out seasons vs 0.53 for usage alone.</li>"
            "<li><strong>Rookies</strong> without an ADP line: NFL draft capital. "
            "<strong>K and DEF</strong>: positional mean (no predictive signal).</li>"
            "<li><strong>In season:</strong> each player's actual points per game are "
            "weighed against five games of the preseason projection, and a back's, "
            "receiver's or tight end's rate is then taken halfway to Sleeper's own "
            "projections for the last three weeks - on 2023-25 the blend predicted the "
            "next month better than either alone. Played weeks are locked in and only "
            "the rest is simulated.</li>"
            "<li><strong>Injuries</strong> persist for weeks at a time; Sleeper's "
            "Out/IR/PUP designations start a player out. Every simulated season draws each "
            "player's true rate from his projection's error bar.</li>"
            "</ul>"
            "<h3>Player accuracy</h3>"
            "<p>Correlation of projected with actual points per game, each season "
            "rebuilt from prior years only.</p>"
            + _player_accuracy_section(scored)
            + "<h3>Roster backtest</h3>"
            "<p>This page run on past draft-day rosters: projected finish vs points "
            "actually scored.</p>"
            + _backtest_section(scored))


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #

PRE_DRAFT = f"""<p>The {UPCOMING_SEASON} draft has not happened yet, so there are no
rosters to rank. This page fills in as soon as the last pick is in &mdash; it reads
the draft straight from Sleeper, the same way the
{layout.internal_link('/fantasy/draft/', 'draft page')} does.</p>
<p>What it will show, and how it gets there, is below.</p>"""


def body() -> str:
    """The page. Falls back to the method write-up until a draft exists to rank.

    The site rebuilds on a schedule, and for most of the year — every day from
    the end of one season to the night of the next draft — there is no roster
    to rank. Raising here would fail the whole nightly build over a page that is
    simply waiting, so instead it publishes the part that is already true.
    """
    # Only "no rosters" is the pre-draft page. Anything else - Sleeper down
    # after its retries, a bug - raises, so the step fails and the page on disk
    # stands: a Sleeper glitch in week 3 (2026-09-23) published "the draft has
    # not happened yet" to a league three weeks into its season.
    try:
        table, board, rosters = power.rankings(UPCOMING_YEAR)
    except power.NoRosters as exc:
        print(f"[power] no rankings yet: {exc}")
        charts.clear(_SECTION)
        return (f"<div id='pw-intro'>{PRE_DRAFT}</div>" + my_league.bar()
                + "<section id='mine' class='pw-section'>"
                + "<h2 id='pw-mine-h'>Your League</h2>"
                + my_power.section() + "</section>"
                + "<div id='pw-built'>" + _TABLE_CSS + layout.details(
                    "Method &mdash; what this will measure, and how well it works",
                    _method_section(), open=True, anchor="method")
                + "</div>"
                + my_league_data.JS + my_league.JS
                + my_power.SIM_JS + my_power.JS)

    charts.clear(_SECTION)            # only now: a failed run keeps the last page's charts
    _CARD["table"] = table
    stakes_week, stakes_teams = _stakes(table)
    stakes.write(STAKES_OUT, stakes_week, stakes_teams)
    content = {
        "mine": my_power.section(),
        "rankings": _rankings_section(table),
        "stakes": stakes.table(stakes_week, stakes_teams) if stakes_week else "",
        "draft-consensus": draft_consensus_section(),
        "season": _season_section(),
        "positions": _positions_section(rosters, table),
        "method": _method_section(),
    }
    nav = layout.section_nav([(a, label) for a, _, label, _ in SECTIONS if a != "mine"])
    # This league's sections are wrapped so the reader's own ranking can take
    # the page over: somebody who has synced a league is here for that league,
    # and two rankings of two different leagues on one page only invites the
    # question of whose numbers are on screen. my_power hides this.
    rest = "".join(
        layout.details(summary, content[anchor], anchor=anchor) if folds
        else f"<section id='{anchor}' class='pw-section'><h2>{summary}</h2>{content[anchor]}</section>"
        for anchor, summary, _, folds in SECTIONS
        if anchor != "mine" and content[anchor])
    return (INTRO + my_league.bar()
            + "<section id='mine' class='pw-section'>"
            + "<h2 id='pw-mine-h'>Your League</h2>" + content["mine"] + "</section>"
            + f"<div id='pw-built'>{_TABLE_CSS}{nav}{rest}</div>"
            + my_league_data.JS + my_league.JS + my_power.SIM_JS + my_power.JS)


_CARD: dict = {}

# This week's stakes, for the matchups page's game of the week (gordstats.stakes).
STAKES_OUT = paths.WEB_STAKES


def _stakes(table: pd.DataFrame) -> tuple:
    """(week, teams) for the next week's games, or (None, {}) when that week
    is over already: the model counts a week once nflverse has it too, a day
    or two after Sleeper finishes it, and until then its "next" week has been
    played. Over is either test saying so - the week's archive final (every
    game over, every side scored: what the matchups page goes by), or
    Sleeper's display week past it - since Sleeper keeps a finished week on
    display into Tuesday."""
    teams = stakes.teams_from(table, "roster_id", "manager")
    if not teams:
        return None, {}
    week = int(table["stakes_week"].dropna().iloc[0])
    over = league_matchups.weeks_over(UPCOMING_YEAR)
    if over is not None and week <= over:
        return None, {}
    path = league_matchups._path(week, UPCOMING_YEAR)
    try:
        if path.exists() and league_matchups.week_final(json.loads(path.read_text())):
            return None, {}
    except (OSError, ValueError):
        pass
    return week, teams


def card() -> dict | None:
    """The link-preview card (gordstats.share_card): the top five and their
    playoff odds, which say more in a chat than a rating does."""
    table = _CARD.get("table")
    if table is None or table.empty:
        return None
    week = int(table["week"].iloc[0])
    rows = [(str(int(r["rank"])), str(r["manager"]), f"{r['playoff_odds']:.0%} playoffs")
            for _, r in table.head(5).iterrows()]
    return share_card.ranked("nfl-power", "NFL Fantasy" + (f" \u00b7 Week {week}" if week else ""),
                             "Power Rankings",
                             f"Through week {week}" if week else "Out of the draft", rows,
                             alt="Power rankings: " + ", ".join(f"{r[0]}. {r[1]}" for r in rows))


def generate():
    html = body()
    page = add_front_matter(layout.HEAD + html, "Power Rankings", image=card())
    out = paths.WEB_POWER
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"Wrote Power Rankings -> {out}")


if __name__ == "__main__":
    generate()
