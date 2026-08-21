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
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np               # noqa: E402
import pandas as pd              # noqa: E402

from fantasy import paths                                      # noqa: E402
from fantasy.config import (                                   # noqa: E402
    FANTASY_REG_WEEKS, FORMAL_SEASON, LEAGUE_IDS, UPCOMING_SEASON, UPCOMING_YEAR,
)
from fantasy.league import power, validation                   # noqa: E402
from fantasy.site import layout, styles                        # noqa: E402
from gordstats import charts                                   # noqa: E402
from gordstats.frontmatter import add_front_matter             # noqa: E402

_GRID = [styles.GRID_TD, styles.GRID_TH, styles.TABLE_STYLE]
_SECTION = "power"

SECTIONS = [
    ("rankings", "Power Rankings &mdash; every roster, ten thousand seasons", "Rankings"),
    ("range", "Projected Wins &mdash; and how wide the range really is", "Range"),
    ("positions", "Positional Strength &mdash; where each roster is built", "Positions"),
    ("lineups", "Projected Lineups &mdash; the roster behind the number", "Lineups"),
    ("method", "Method &mdash; what this is measuring, and how well it works", "Method"),
]

INTRO = f"""<p>Every roster in the league, run through {UPCOMING_SEASON} ten thousand
times. <strong>Nothing here reads ADP, auction price or an expert ranking</strong> &mdash;
those would only tell you what the draft board already said. Player projections
come from usage (targets, carries, air yards, target share), rookies from where
the <em>NFL</em> drafted them, and kickers and defenses from nothing at all,
because nothing predicts them. Those projections then have to play the season:
fourteen weeks, byes, injuries, and a legal starting lineup every week, which is
the only way bench depth and a bye-week pileup ever show up in a number.</p>"""


# --------------------------------------------------------------------------- #
# Rankings table
# --------------------------------------------------------------------------- #

def _record(wins: float) -> str:
    """Projected wins as a record. Each week awards two: opponent and median."""
    games = FANTASY_REG_WEEKS * 2
    return f"{wins:.1f}-{games - wins:.1f}"


def _rankings_table(table: pd.DataFrame) -> str:
    display = pd.DataFrame({
        "#": range(1, len(table) + 1),
        "Manager": table["manager"],
        "Power": table["power"],
        "Proj. Record": table["proj_wins"].map(_record),
        "Proj. Points": table["proj_points"],
        "Playoffs": table["playoff_odds"],
        "1 Seed": table["first_seed_odds"],
        "Title": table["title_odds"],
        "Last": table["last_odds"],
    })
    return (display.style.hide(axis="index")
            .format({"Power": "{:.1f}", "Proj. Points": "{:,.0f}",
                     "Playoffs": "{:.0%}", "1 Seed": "{:.0%}",
                     "Title": "{:.0%}", "Last": "{:.0%}"})
            .background_gradient(cmap="RdYlGn", subset=["Power"])
            .background_gradient(cmap="RdYlGn", subset=["Playoffs"])
            .background_gradient(cmap="RdYlGn", subset=["Title"])
            .background_gradient(cmap="RdYlGn_r", subset=["Last"])
            .set_table_styles(_GRID, overwrite=False)
            .set_table_attributes('class="sticky-table"')).to_html()


def _rankings_section(table: pd.DataFrame) -> str:
    leader = table.iloc[0]
    tail = table.iloc[-1]
    note = (f"<p><strong>{leader['manager']}</strong> comes out of the draft with the "
            f"strongest roster &mdash; {leader['playoff_odds']:.0%} to make the playoffs "
            f"and {leader['title_odds']:.0%} to win it, against "
            f"{tail['playoff_odds']:.0%} and {tail['title_odds']:.0%} for "
            f"<strong>{tail['manager']}</strong>. Power is points per week against the "
            f"league average, so 105 means a roster projected 5% above the field.</p>")
    return f"<h2>Power Rankings</h2>{note}" + \
        f"<div class='table-scroll'>{_rankings_table(table)}</div>"


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
            "actually scored, for every season the league has played, with the model "
            "given only the years before each one. Running backs and receivers land "
            "around <strong>+0.6</strong> every year; quarterbacks and tight ends around "
            "<strong>+0.4</strong>. That is the part of this page that demonstrably "
            "works.</p>")


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
    return ("<h2>Method</h2>"
            "<p>Three things go into a player's projection, and ADP is not one of them.</p>"
            "<ul>"
            "<li><strong>Usage, not points.</strong> A ridge regression per position maps "
            "last season's per-game volume &mdash; targets, carries, air yards, target "
            "share, WOPR &mdash; onto this season's points per game. Volume survives the "
            "offseason; points carry touchdown luck that does not. Held out on the two "
            "most recent seasons, that beats projecting last year's points forward at "
            "receiver and tight end and ties at running back.</li>"
            "<li><strong>Draft capital for rookies.</strong> A rookie has no usage to "
            "read, so the prior is where the NFL drafted him, fit against what drafted "
            "rookies have actually scored since 2021. That is 32 front offices spending "
            "picks, not a fantasy consensus.</li>"
            "<li><strong>Nothing for kickers and defenses.</strong> The same model fit to "
            "K and DST has <em>negative</em> held-out skill: last season's kicker points "
            "do not predict this season's at any amount of regularization. Both positions "
            "get the positional mean, so they cancel out of the rankings entirely.</li>"
            "</ul>"
            "<p>Each projection carries its own error bar, and every simulated season "
            "deals each player a true rate drawn from it. Without that step the page would "
            "quote playoff odds far more confident than a projection this uncertain can "
            "support.</p>"
            "<h3>How well does it work? Player by player: well.</h3>"
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
{layout.internal_link('/fantasy/live/', 'live board')} does.</p>
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
        "range": _range_section(table),
        "positions": _positions_section(board, rosters, table),
        "lineups": _lineups_section(board, rosters, table),
        "method": _method_section(),
    }
    nav = layout.section_nav([(a, label) for a, _, label in SECTIONS])
    return INTRO + nav + "".join(
        layout.details(summary, content[anchor], open=(i == 0), anchor=anchor)
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
