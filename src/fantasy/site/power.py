"""
Power Rankings page (docs/fantasy/power/).

The draft page grades the picks. This one grades the rosters they add up to,
and it does it without looking at where anyone was drafted — see
`fantasy.projections` for why that constraint shapes the whole model, and
`fantasy.league.power` for the simulation that turns projections into wins.

Five sections:
  * The rankings themselves, with projected record and playoff odds.
  * Projected wins with the middle 80% of outcomes drawn on, because the
    spread between fourth and eighth is smaller than either team's own range.
  * Where each team's strength sits, position by position.
  * The starting lineup behind each team's number.
  * How the same model did on last year's draft, which is the only honest way
    to say how much of this to believe.

    python -m fantasy.site.power
"""
from datetime import datetime

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

SECTIONS = [
    ("draft-consensus", "Draft Power Rankings &mdash; three sources, frozen on draft week",
     "Draft"),
    ("rankings", "Power Rankings &mdash; every roster, ten thousand seasons", "Rankings"),
    ("season", "Through the Season &mdash; every rating, build by build", "Season"),
    ("range", "Projected Wins &mdash; and how wide the range really is", "Range"),
    ("positions", "Positional Strength &mdash; where each roster is built", "Positions"),
    ("lineups", "Projected Lineups &mdash; the roster behind the number", "Lineups"),
    ("method", "Method &mdash; what this is measuring, and how well it works", "Method"),
]

INTRO = f"""<p>Every roster in the league, run through {UPCOMING_SEASON} ten thousand
times. Player values anchor on the <strong>consensus ADP board</strong> &mdash; tested
against three seasons of this league, consensus beat our own usage model at every
position, so it earned the job &mdash; with the usage model adjusting at the edges and
kickers and defenses valued at nothing at all, because nothing predicts them.
The ranking is not those values summed: the projections have to <strong>play the
season</strong> &mdash; fourteen weeks, byes, injuries that keep a starter out for
weeks at a time rather than a game here and there, and a starting lineup set the way a
manager has to set it: on projections, before the week happens. That is the only way
bench depth and a bye-week pileup ever show up in a number, and why this table is not
the draft board read back. The published <strong>Rating</strong> then averages that
simulation with the FantasyPros League Analyzer.</p>"""


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


def _rankings_table(table: pd.DataFrame) -> str:
    in_season = "wins" in table.columns and table["week"].iloc[0] > 0
    display = pd.DataFrame({"#": table["rank"], "Manager": table["manager"]})
    display["Move"] = table["move"]
    display["Pre"] = table["pre_rank"]
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
    display["Proj. Points"] = table["proj_points"]
    display["Playoffs"] = table["playoff_odds"]
    display["1 Seed"] = table["first_seed_odds"]
    display["Title"] = table["title_odds"]
    display["Last"] = table["last_odds"]

    fmt = {"Move": _signed, "Pre": lambda v: "" if pd.isna(v) else f"{int(v)}",
           "Power": "{:.1f}", "Proj. Points": "{:,.0f}", "Playoffs": "{:.0%}",
           "1 Seed": "{:.0%}", "Title": "{:.0%}", "Last": "{:.0%}", "Luck": "{:+.1f}"}
    if blended:
        fmt.update({"Rating": "{:.1f}", "GordStats": "{:.1f}", short: "{:.1f}"})
    styled = (display.style.hide(axis="index").format(fmt, na_rep="")
              .background_gradient(cmap="RdYlGn", subset=["Rating" if blended else "Power"])
              .background_gradient(cmap="RdYlGn", subset=["Playoffs"])
              .background_gradient(cmap="RdYlGn", subset=["Title"])
              .background_gradient(cmap="RdYlGn_r", subset=["Last"]))
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
    note = (f"<p><strong>{leader['manager']}</strong> {when} the strongest roster &mdash; "
            f"{leader['playoff_odds']:.0%} to make the playoffs and {leader['title_odds']:.0%} "
            f"to win it, against {tail['playoff_odds']:.0%} and {tail['title_odds']:.0%} for "
            f"<strong>{tail['manager']}</strong>. Every rating is scaled so 100 is the "
            f"league average and 105 is a roster five percent above the field.</p>")

    legend = ["<strong>Move</strong> is places climbed since "
              + (f"{table.attrs['prev_taken']:%b %-d}" if "prev_taken" in table.attrs
                 else "the previous build")
              + "; <strong>Pre</strong> is where the roster ranked on draft night, before "
              "any game was played"]
    if week > 0:
        legend.append("<strong>Record</strong> counts both the head-to-head and the median "
                      "win each week; <strong>Luck</strong> is that record minus what the "
                      "all-play record says it should be, so +2 is two wins the schedule "
                      "handed over and -2 is two it took away. Played weeks are locked in "
                      "and only the rest of the season is simulated, so the projected "
                      "record is the real one plus what is still expected")
    if "combined" in table.columns and table["ext_vorp"].notna().any():
        src = table.attrs.get("ext_source", "an outside source")
        label = table.attrs.get("ext_label") or ""
        url = table.attrs.get("ext_url") or ""
        named = f"<a href='{url}'>{src}</a>" if url else src
        when = table.attrs.get("ext_captured") or ""
        try:
            when = f"{datetime.strptime(when, '%Y-%m-%d'):%b %-d}"
        except ValueError:
            pass
        short = table.attrs.get("ext_short", "Ext")
        legend.append(f"<strong>Rating</strong> is the published ranking: our simulation "
                      f"(<strong>GordStats</strong>) and the {named}"
                      + (f" {label}" if label else "")
                      + f" (<strong>{short}</strong>"
                      + (f", as of {when}" if when else "") + ") averaged on a common "
                      "scale, where 100 is the league average and a point is one percent "
                      "better than it. Ratings are averaged rather than ranks, on purpose: "
                      "a ranking of ranks would record that the two disagree about Max "
                      "without recording that they disagree by seventeen points")

    return (f"<h2>Power Rankings</h2>{note}"
            f"<div class='table-scroll'>{_rankings_table(table)}</div>"
            f"<p>{'. '.join(legend)}.</p>")


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
    return charts.save(_SECTION, "draft-consensus",
                       alt="Each team's rating from all three sources, with the "
                           "consensus marked and the spread between sources drawn")


def _draft_section() -> str:
    """The three-source draft ranking, exactly as it was frozen."""
    snap = consensus.draft(int(UPCOMING_YEAR))
    if not snap or not snap.get("teams"):
        return ""
    rows = pd.DataFrame(snap["teams"])

    display = pd.DataFrame({"#": rows["rank"], "Manager": rows["manager"]})
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
    spread = rows["combined"].max() - rows["combined"].min()
    widest = (rows[["us", "fp", "ff"]].max(axis=1) - rows[["us", "fp", "ff"]].min(axis=1))
    argued = rows.loc[widest.idxmax()]
    # How many sources rate the whole league inside the gap the three of them
    # leave on one roster — the honest way to say "they really do not agree".
    narrower = sum(1 for c in ("us", "fp", "ff")
                   if rows[c].max() - rows[c].min() < widest.max())

    note = (f"<p>What all three sources made of these rosters coming out of the draft, "
            f"frozen on <strong>{frozen}</strong> and never recomputed. This is the only "
            f"table on the page that does not move: everything below it follows the "
            f"season, and the point of this one is that it cannot. They agree less than "
            f"a single ranking would suggest: the three of them spread "
            f"<strong>{argued['manager']}</strong> across "
            f"{widest.max():.0f} points"
            + (f", more than {narrower} of the three spend on the entire league"
               if narrower else "") + ".</p>")
    legend = (f"<p>Every column is on the same scale &mdash; 100 is the league average, "
              f"and the whole league fits in {spread:.0f} points. "
              f"<strong>GordStats</strong> is our simulation, <strong>FP</strong> the "
              f"FantasyPros League Analyzer, <strong>FF</strong> The Fantasy Footballers' "
              f"projected points per game. The Footballers publish a rank that sorts by "
              f"letter grade first and points only within a grade, which is why their "
              f"ninth-ranked roster carries their fourth-best projection; their points, "
              f"not their rank, are what is averaged here.</p>")
    return (f"<h2>Draft Power Rankings</h2>{note}"
            + _draft_chart(rows)
            + f"<div class='table-scroll'>{styled.to_html()}</div>{legend}")


def _season_section() -> str:
    """Every team's published rating, build by build."""
    year = int(UPCOMING_YEAR)
    hist = power.history(year)
    column = "combined" if not hist.empty and "combined" in hist.columns else "power"
    if hist.empty or hist["taken"].dt.date.nunique() < 2:
        return ("<h2>Through the Season</h2>"
                "<p>Every build of the rankings is archived, and this chart draws each "
                "team's rating across them &mdash; who is climbing, who is sliding, and "
                "whether a move is a real trend or one noisy week. The model was rebuilt "
                "and the archive re-baselined, so there is one build on record; the chart "
                "appears with the second and fills in from there.</p>")

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
    return ("<h2>Through the Season</h2>"
            f"<p>Every build since <strong>{first:%b %-d}</strong>, one panel per team "
            f"with the rest of the league behind it in grey. Since then "
            f"<strong>{up}</strong> has gained the most ({swing[up]:+.1f}) and "
            f"<strong>{down}</strong> has given up the most ({swing[down]:+.1f}), "
            f"as of {last:%b %-d}.</p>" + chart)


# --------------------------------------------------------------------------- #
# Range chart
# --------------------------------------------------------------------------- #

def _range_section(table: pd.DataFrame) -> str:
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
    caveat = ("Every team's range overlaps every other team's. "
              if overlap else
              "Most of these ranges overlap. ")
    return ("<h2>Projected Wins</h2>"
            f"<p>The dot is the average season, the bar is the middle 80% of them. "
            f"{caveat}That is the honest picture of a fantasy season and it is the "
            f"reason this page leads with odds rather than a predicted finish: the "
            f"gap between the best and worst roster in this league is worth a few "
            f"wins, and a single season is noisier than that.</p>" + chart)


# --------------------------------------------------------------------------- #
# Positional strength
# --------------------------------------------------------------------------- #

def _positional_frame(board: pd.DataFrame, rosters: pd.DataFrame) -> pd.DataFrame:
    """Points above replacement each team holds at each position."""
    players = rosters.merge(board, on="sleeper_id", how="left").dropna(subset=["mu"])
    players["manager"] = players["roster_id"].map(power.ROSTER_NAMES)
    # Only the players deep enough to actually start: the eleventh receiver on a
    # roster contributes nothing and would otherwise reward hoarding.
    depth = {"QB": 2, "RB": 4, "WR": 4, "TE": 2, "K": 1, "DEF": 1}
    kept = []
    for (_, pos), group in players.groupby(["manager", "pos"]):
        kept.append(group.nlargest(depth.get(pos, 3), "mu"))
    players = pd.concat(kept)

    pivot = players.pivot_table(index="manager", columns="pos", values="vor",
                                aggfunc="sum").fillna(0.0)
    order = [p for p in ["QB", "RB", "WR", "TE", "K", "DEF"] if p in pivot.columns]
    pivot = pivot[order]
    pivot.columns.name = None
    return pivot


def _positions_section(board: pd.DataFrame, rosters: pd.DataFrame,
                       table: pd.DataFrame) -> str:
    pivot = _positional_frame(board, rosters)
    pivot = pivot.reindex(table["manager"]).dropna(how="all")

    bound = float(np.nanmax(np.abs(pivot.to_numpy(float)))) or 1.0
    styled = (pivot.style.format("{:+.1f}")
              .background_gradient(cmap="RdYlGn", axis=None, vmin=-bound, vmax=bound)
              .set_table_styles(_GRID, overwrite=False)
              .set_table_attributes('class="sticky-table"')).to_html()

    ax = pivot.plot(kind="bar", stacked=True, figsize=(10, 4.4), width=0.8,
                    edgecolor="#333", colormap="tab10")
    ax.axhline(0, color="#333", linewidth=0.9)
    ax.set_xlabel("")
    ax.set_ylabel("points above replacement, per game")
    ax.set_title("Where each roster's edge comes from")
    ax.tick_params(axis="x", labelrotation=35)
    ax.legend(fontsize=9, ncol=len(pivot.columns))
    chart = charts.save(_SECTION, "positional",
                        alt="Points above replacement by position for each team")

    return ("<h2>Positional Strength</h2>"
            "<p>Points per game above the last roster-worthy player at that position, "
            "added up over the players deep enough to actually start. Kicker and "
            "defense are flat at zero for everyone on purpose &mdash; the model finds "
            "no year-over-year signal in either, so no roster gets credit for them.</p>"
            + chart
            + layout.details("Show data table", f"<div class='table-scroll'>{styled}</div>"))


# --------------------------------------------------------------------------- #
# Projected lineups
# --------------------------------------------------------------------------- #

_SLOT_ORDER = ["QB", "RB", "WR", "TE", "FLEX", "K", "DEF"]


def _lineups_section(board: pd.DataFrame, rosters: pd.DataFrame,
                     table: pd.DataFrame) -> str:
    lineups = power.starting_lineup(board, rosters)
    lineups["manager"] = lineups["roster_id"].map(power.ROSTER_NAMES)
    lineups["slot"] = pd.Categorical(lineups["slot"], _SLOT_ORDER, ordered=True)

    views = []
    for manager in table["manager"]:
        team = lineups[lineups["manager"] == manager].sort_values(["slot", "mu"],
                                                                  ascending=[True, False])
        if team.empty:
            continue
        display = team[["slot", "player", "pos", "team", "bye", "mu", "avail", "basis"]]
        display = display.rename(columns={
            "slot": "Slot", "player": "Player", "pos": "Pos", "team": "Team",
            "bye": "Bye", "mu": "Proj. PPG", "avail": "Available", "basis": "From"})
        html = (display.style.hide(axis="index")
                .format({"Proj. PPG": "{:.1f}", "Available": "{:.0%}"})
                .background_gradient(cmap="RdYlGn", subset=["Proj. PPG"])
                .set_table_styles(_GRID, overwrite=False)
                .set_table_attributes('class="sticky-table"')).to_html()
        total = team["mu"].sum()
        note = (f"<p>Projected starting lineup: <strong>{total:.1f}</strong> points per "
                f"week before byes and injuries take anyone out of it.</p>")
        views.append((charts.slug(manager), manager, note +
                      f"<div class='table-scroll'>{html}</div>"))

    return ("<h2>Projected Lineups</h2>"
            "<p>Who the simulation starts, and where each projection came from. "
            "<em>From</em> reads <strong>usage</strong> for a player with a season "
            "behind him, <strong>draft capital</strong> for a rookie, "
            "<strong>positional mean</strong> for a kicker or defense, and "
            "<strong>replacement</strong> for anyone with no signal at all.</p>"
            + layout.view_switcher(views, group="lineup", label="Team:"))


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
    return (f"<div class='table-scroll'>{html}</div>"
            "<p>Correlation between a player's projected points per game and what he "
            "actually scored, for every season the league has played.</p>")


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
                       f"<p>Rank correlation between this page's projected finish and "
                       f"points actually scored: <strong>{spearman:+.2f}</strong>.</p>"
                       f"<div class='table-scroll'>{html}</div>"))

    if not blocks:
        return "<p>No completed season is available to backtest against yet.</p>"

    average = sum(correlations) / len(correlations)
    verdict = (
        f"<p>Across {len(correlations)} seasons those correlations average "
        f"<strong>{average:+.2f}</strong>, on ten teams a year. In other words: at the "
        f"level of a whole roster, over the sample this league has actually played, "
        f"<strong>this page has not demonstrated that it can pick the season's best team "
        f"from the draft</strong>. Thirty team-seasons cannot tell a good model from a "
        f"coin flip, and a roster's points are mostly decided after the draft &mdash; by "
        f"waivers, by injuries, and by who each manager benched on the wrong week. "
        f"Read the rankings as a description of what was drafted, which they measure "
        f"well, rather than as a forecast of what will happen.</p>")
    return layout.view_switcher(blocks, group="backtest", label="Season:") + verdict


def _method_section() -> str:
    scored = validation.load()
    from fantasy.projections import MARKET_WEIGHT

    market_pct = round(MARKET_WEIGHT * 100)
    return ("<h2>Method</h2>"
            f"<p>A player's projection is <strong>{market_pct}% consensus</strong> and "
            f"<strong>{100 - market_pct}% usage model</strong>. It did not start that way: "
            "the first version used no ADP at all, on the theory that market prices would "
            "just restate the draft board. Tested over the league's three seasons &mdash; each "
            "rebuilt knowing only prior years &mdash; consensus predicted players' actual points "
            "at <strong>0.81</strong> correlation against the usage model's 0.53, winning at "
            "every position every year: the market reads depth charts, trades and coaching "
            "changes that last season's usage cannot. So consensus earned the anchor, turned "
            "into points through a per-position curve fit on what past ADP actually bought. "
            "The restatement worry also turned out to be overblown &mdash; run through the "
            "league's real lineup rules and schedule, the same consensus values still "
            "reorder teams, because a roster is not the sum of its draft slots.</p>"
            "<ul>"
            "<li><strong>The usage minority share.</strong> A ridge regression per position "
            "maps last season's per-game volume &mdash; targets, carries, air yards, target "
            "share, WOPR &mdash; onto this season's points per game, and nudges the anchor "
            "where a player's volume disagrees with his price.</li>"
            "<li><strong>Draft capital for rookies</strong> the ADP board has no line on: "
            "where the NFL drafted him, fit against what drafted rookies have scored "
            "since 2021.</li>"
            "<li><strong>Nothing for kickers and defenses.</strong> Neither the market nor "
            "the model has held-out skill there &mdash; last season's kicker points do not "
            "predict this season's at any amount of regularization &mdash; so both positions "
            "get the positional mean and cancel out of the rankings entirely.</li>"
            "</ul>"
            "<p>Each projection carries its own error bar, and every simulated season "
            "deals each player a true rate drawn from it. Without that step the page would "
            "quote playoff odds far more confident than a projection this uncertain can "
            "support.</p>"
            "<h3>How well does it work? Player by player: well.</h3>"
            "<p>Scored the same way the anchor was chosen: each season rebuilt knowing "
            "only the years before it.</p>"
            + _player_accuracy_section(scored)
            + "<h3>Roster by roster: unproven.</h3>"
            "<p>Run the whole page on a past season's draft-day rosters, with only the "
            "seasons before it to learn from, and compare its ranking to what actually "
            "happened over the fourteen weeks that followed.</p>"
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
        "draft-consensus": _draft_section(),
        "season": _season_section(),
        "range": _range_section(table),
        "positions": _positions_section(board, rosters, table),
        "lineups": _lineups_section(board, rosters, table),
        "method": _method_section(),
    }
    nav = layout.section_nav([(a, label) for a, _, label in SECTIONS])
    return INTRO + nav + "".join(
        layout.details(summary, content[anchor], open=(i < 2), anchor=anchor)
        for i, (anchor, summary, _) in enumerate(SECTIONS)
    )


def generate():
    page = add_front_matter(layout.HEAD + body(), "Power Rankings")
    out = paths.WEB_POWER
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"Wrote Power Rankings -> {out}")


if __name__ == "__main__":
    generate()
