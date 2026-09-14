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
from gordstats import charts, palette                          # noqa: E402
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

# (anchor, heading, jump-bar label, collapsible). The draft-week three-source
# table sits under the live rankings: frozen on draft week, it is the fixed
# point every later rating is read against. Only Method folds away.
SECTIONS = [
    ("rankings", "Power Rankings", "Rankings", False),
    ("draft-consensus", "Draft Rankings (frozen)", "Draft", False),
    ("season", "Through the Season", "Season", False),
    ("positions", "Positional Strength", "Positions", False),
    ("method", "Method", "Method", True),
]

INTRO = f"""<p>Every Sleeper roster played through {UPCOMING_SEASON} ten thousand
times, averaged with the FantasyPros League Analyzer. <strong>100 is the league
average</strong>; a point is one percent better.</p>"""


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


def _rankings_table(table: pd.DataFrame) -> str:
    in_season = "wins" in table.columns and table["week"].iloc[0] > 0
    display = pd.DataFrame(
        {"Manager": _manager_col(table["rank"], table["manager"])})
    display["Move"] = table["move"]
    blended = "combined" in table.columns and table.get("ext_vorp") is not None \
        and table["ext_vorp"].notna().any()
    short = table.attrs.get("ext_short", "Ext")
    if blended:
        display["Rating"] = table["combined"]
        display["GordStats"] = table["power"]
        display[short] = table["ext_vorp"]
    else:
        display["Power"] = table["power"]
    if in_season:
        display["Record"] = (table["wins"].astype(int).astype(str) + "-"
                             + table["losses"].astype(int).astype(str))
        display["Luck"] = table["luck"]
    display["Proj. Record"] = table["proj_wins"].map(_record)
    display["Playoffs"] = table["playoff_odds"]
    display["Title"] = table["title_odds"]

    fmt = {"Move": _signed, "Power": "{:.1f}", "Playoffs": "{:.0%}",
           "Title": "{:.0%}", "Luck": "{:+.1f}"}
    if blended:
        fmt.update({"Rating": "{:.1f}", "GordStats": "{:.1f}", short: "{:.1f}"})
    styled = (display.style.hide(axis="index").format(fmt, na_rep="")
              .background_gradient(cmap="RdYlGn", subset=["Rating" if blended else "Power"])
              .background_gradient(cmap="RdYlGn", subset=["Playoffs"]))
    if table["move"].notna().any():
        bound = max(1.0, float(table["move"].abs().max()))
        styled = styled.background_gradient(cmap="RdYlGn", subset=["Move"], vmin=-bound, vmax=bound)
    if in_season:
        bound = max(1.0, float(table["luck"].abs().max()))
        styled = styled.background_gradient(cmap="RdYlGn", subset=["Luck"], vmin=-bound, vmax=bound)
    return (styled.set_table_styles(_GRID, overwrite=False)
            .set_table_attributes('class="sticky-table"')).to_html()


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

    return (f"{note}"
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
              .background_gradient(cmap="RdYlGn", subset=["Consensus"])
              .set_table_styles(_GRID, overwrite=False)
              .set_table_attributes('class="sticky-table"'))

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


def _heat(values: dict) -> dict:
    """{manager: css background} - green for the league's best at a column,
    red for its worst, by rank so one outlier cannot wash the rest out."""
    order = sorted(values, key=lambda m: -values[m])
    n = max(1, len(order) - 1)
    cmap = matplotlib.colormaps["RdYlGn"]
    out = {}
    for i, m in enumerate(order):
        r, g, b, _ = cmap(0.15 + 0.7 * (1 - i / n))
        out[m] = f"background:rgba({int(r * 255)},{int(g * 255)},{int(b * 255)},.55)"
    return out


def _positions_section(rosters: pd.DataFrame, table: pd.DataFrame) -> str:
    proj = league_matchups.sleeper_season_projections(int(UPCOMING_YEAR))
    if not proj:
        return "<p>Sleeper's projections are unavailable right now.</p>"
    frame = _positional_frame(rosters, proj)
    managers = [m for m in table["manager"] if m in frame]

    def total(names):
        return sum(ppg for _, ppg in names)

    def tip(names):
        return escape(", ".join(f"{n} {ppg:.1f}" for n, ppg in names), quote=True)

    cols = {pos: {m: total(frame[m]["start"][pos]) for m in managers} for pos in POS_ORDER}
    bench_cols = {pos: {m: total(frame[m]["bench"][pos]) for m in managers} for pos in BENCH_DEPTH}
    starters = {m: sum(cols[pos][m] for pos in POS_ORDER) for m in managers}
    benches = {m: sum(bench_cols[pos][m] for pos in BENCH_DEPTH) for m in managers}
    heat = {pos: _heat(cols[pos]) for pos in POS_ORDER}
    heat_bench = {pos: _heat(bench_cols[pos]) for pos in BENCH_DEPTH}
    heat_start, heat_all_bench = _heat(starters), _heat(benches)
    rank_of = dict(zip(table["manager"], table["rank"]))

    head = ("<tr><th rowspan='2'>Manager</th>"
            + "".join(f"<th colspan='{2 if pos in BENCH_DEPTH else 1}'>{pos}</th>" for pos in POS_ORDER)
            + "<th colspan='2'>Total</th></tr><tr>"
            + "".join("<th>Start</th><th class='ps-bn'>Bench</th>" if pos in BENCH_DEPTH
                      else "<th>Start</th>" for pos in POS_ORDER)
            + "<th>Start</th><th class='ps-bn'>Bench</th></tr>")
    rows = []
    for m in managers:
        cells = [f"<td>{_manager_col([rank_of[m]], [m])[0]}</td>"]
        for pos in POS_ORDER:
            names = frame[m]["start"][pos]
            cells.append(f"<td style='{heat[pos][m]}' title='{tip(names)}'>"
                         f"{cols[pos][m]:.1f}</td>")
            if pos in BENCH_DEPTH:
                names = frame[m]["bench"][pos]
                cells.append(f"<td class='ps-bn' style='{heat_bench[pos][m]}' "
                             f"title='{tip(names)}'>{bench_cols[pos][m]:.1f}</td>")
        cells.append(f"<td class='ps-tot' style='{heat_start[m]}'>{starters[m]:.1f}</td>")
        cells.append(f"<td class='ps-bn ps-tot' style='{heat_all_bench[m]}'>{benches[m]:.1f}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")

    css = ("<style>table.pos-strength{border-collapse:collapse;font-size:14px;width:100%}"
           "table.pos-strength th,table.pos-strength td{padding:6px 8px;text-align:center;"
           "white-space:nowrap;border:1px solid rgba(148,163,184,.35)}"
           "table.pos-strength td:first-child{text-align:left;font-weight:600}"
           "table.pos-strength th{font-size:12px;text-transform:uppercase;letter-spacing:.03em}"
           "table.pos-strength .ps-bn{font-size:12px;opacity:.85}"
           "table.pos-strength .ps-tot{font-weight:700}"
           "table.pos-strength td[title]{cursor:help}</style>")
    note = ("<p>Projected points per game from <strong>Sleeper's season projections</strong>, "
            "split the way the lineup is filled: <strong>Start</strong> is the QB, two RBs, two "
            "WRs, TE, the best two RB/WR/TE left over at <strong>FLEX</strong>, K and DEF; "
            "<strong>Bench</strong> is the next "
            + ", ".join(f"{n} {pos}" for pos, n in BENCH_DEPTH.items())
            + " &mdash; the depth that would step in. Green is the league's best at a column, "
            "red its worst. Hover a cell for the players.</p>")
    return (css + note + "<div class='table-scroll'><table class='pos-strength sticky-table'>"
            f"<thead>{head}</thead><tbody>{''.join(rows)}</tbody></table></div>")


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
            .background_gradient(cmap="RdYlGn", vmin=-0.8, vmax=0.8)
            .set_table_styles(_GRID, overwrite=False)
            .set_table_attributes('class="sticky-table"')).to_html()
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
                .background_gradient(cmap="RdYlGn_r", subset=["Projected", "Actual"])
                .set_table_styles(_GRID, overwrite=False)
                .set_table_attributes('class="sticky-table"')).to_html()
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
            "weighed against five games of the preseason projection; played weeks are "
            "locked in and only the rest is simulated.</li>"
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
    charts.clear(_SECTION)
    try:
        table, board, rosters = power.rankings(UPCOMING_YEAR)
    except Exception as exc:
        print(f"[power] no rankings yet: {exc}")
        return PRE_DRAFT + layout.details(
            "Method &mdash; what this will measure, and how well it works",
            _method_section(), open=True, anchor="method")

    content = {
        "rankings": _rankings_section(table),
        "draft-consensus": draft_consensus_section(),
        "season": _season_section(),
        "positions": _positions_section(rosters, table),
        "method": _method_section(),
    }
    nav = layout.section_nav([(a, label) for a, _, label, _ in SECTIONS])
    return INTRO + nav + "".join(
        layout.details(summary, content[anchor], anchor=anchor) if folds
        else f"<section id='{anchor}' class='pw-section'><h2>{summary}</h2>{content[anchor]}</section>"
        for anchor, summary, _, folds in SECTIONS if content[anchor]
    )


def generate():
    page = add_front_matter(layout.HEAD + body(), "Power Rankings")
    out = paths.WEB_POWER
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"Wrote Power Rankings -> {out}")


if __name__ == "__main__":
    generate()
