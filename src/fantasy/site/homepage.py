"""
League homepage generation (src/).

First migrated page. Sections:
  * All-Time Metrics  - computed directly from data/season/*.json (no archive).
  * All-Time Injury Impacts - aggregated from the archive's per-season
    missing_df (see src/site/injuries.py).

    python -m fantasy.site.homepage            # writes docs/index.html
"""
import math

import pandas as pd

from fantasy import paths
from fantasy.config import (
    CHAMPIONS, EXPW_RATIO, FANTASY_REG_WEEKS, ROOT, ROSTER_NAMES, SEASON_DIR,
)
from fantasy.site import adp, injuries, layout, styles, upcoming
from fantasy.site.draft import PICKUP_MIN_WEEKS
from gordstats.frontmatter import add_front_matter

OUTPUT = paths.WEB_FANTASY_HOME

# Cumulative season-total columns carried on every weekly row.
_SUM_COLS = ["median_wins", "h2h_loss", "h2h_wins", "median_loss",
             "total_wins", "total_loss", "PF", "PA"]


def _avg(values):
    return sum(values) / len(values) if values else 0.0


def all_time_metrics() -> pd.DataFrame:
    """SOS / SOV / Expected-Wins standings aggregated across all stored seasons.

    Metrics mirror the legacy schedule_stats.all_time_metrics, but are computed
    from the raw season files instead of the pre-archived per-season stats.
    """
    season_frames, n_seasons = [], 0
    for path in sorted(SEASON_DIR.glob("*.json")):
        df = pd.read_json(path)
        season_frames.append(df[df["week"] <= FANTASY_REG_WEEKS])
        n_seasons += 1

    # Per-team season totals (final-week snapshot) + full opponent / win history.
    snapshots, opps, if_win = [], {}, {}
    for df in season_frames:
        last_week = df["week"].max()
        snapshots.append(df[df["week"] == last_week])
        for rid, g in df.sort_values("week").groupby("roster_id"):
            opps.setdefault(rid, []).extend(g["opp"].tolist())
            if_win.setdefault(rid, []).extend(g["win"].tolist())

    g = pd.concat(snapshots).groupby("roster_id")[_SUM_COLS].sum().reset_index()

    g["Win %"] = g["total_wins"] / (g["total_wins"] + g["total_loss"])
    winp = dict(zip(g["roster_id"], g["Win %"]))

    # Opponent win % (OW%), opponents-of-opponents (OOW%) -> strength of schedule.
    g["OW%"] = g["roster_id"].map(lambda r: _avg([winp[o] for o in opps[r]]))
    oow = dict(zip(g["roster_id"], g["OW%"]))
    g["OOW%"] = g["roster_id"].map(lambda r: _avg([oow[o] for o in opps[r]]))
    g["SOS"] = (g["OW%"] * 2 + g["OOW%"]) / 3

    # Strength of victory: avg win % of the opponents you actually beat.
    g["SOV"] = g["roster_id"].map(
        lambda r: _avg([winp[o] for o, w in zip(opps[r], if_win[r]) if w == 1])
    )

    # Expected wins via Pythagorean expectation, scaled to total h2h games played.
    exp_games = FANTASY_REG_WEEKS * n_seasons
    g["Exp W (Actual)"] = g.apply(
        lambda x: f"{(x.PF**EXPW_RATIO) / (x.PF**EXPW_RATIO + x.PA**EXPW_RATIO) * exp_games:.1f}"
                  f" ({int(x.h2h_wins)})",
        axis=1,
    )

    g["Team"] = g["roster_id"].map(ROSTER_NAMES)
    g["Record"] = g["total_wins"].astype(int).astype(str) + "-" + g["total_loss"].astype(int).astype(str)
    g["Titles"] = g["Team"].map(lambda t: "👑" if t in CHAMPIONS else "-")

    g = g.sort_values(["total_wins", "PF"], ascending=False)
    return g[["Team", "Titles", "Record", "PF", "PA", "SOS", "SOV", "Exp W (Actual)"]].reset_index(drop=True)


def _style(df: pd.DataFrame):
    return (
        df.style
        .hide(axis="index")
        .format(lambda x: f"{x:.3f}" if isinstance(x, float) else x)
        .background_gradient(cmap="RdYlGn_r", subset=["SOS"])
        .background_gradient(cmap="RdYlGn", subset=["SOV"])
        .apply(styles.bg_from_pythag_str, subset=["Exp W (Actual)"])
        .set_table_styles([styles.GRID_TD, styles.GRID_TH, styles.TABLE_STYLE], overwrite=False)
        .set_table_attributes('class="sticky-table"')
    )


def metrics_section() -> str:
    """The All-Time Metrics block of the homepage (legend, table)."""
    table = _style(all_time_metrics()).to_html()
    return f"""<p><strong>SOS - Strength of Schedule</strong>: Green = Easier | Red = Harder</p>
<p><strong>SOV - Strength of Victory</strong>: More Wins Against [Green = Stronger Teams | Read = Weaker Teams] </p>
<p><strong>Exp W (Actual) - Expected H2H Wins vs Actual H2H Wins</strong>: Green = Better than Expected | Red = Worse than Expected
*Expected Wins calculated using Pythagorean Wins formula using a constant of {EXPW_RATIO}.</p>
<div class="table-scroll">
{table}
</div>"""


def injury_section() -> str:
    """The All-Time Draft Injury Impacts block (heading, note, tables, by-season chart)."""
    img, table, top = injuries.all_time_missed()
    premium = injuries.PREMIUM_ROUNDS
    top_pct = round((1 - injuries.STARTER_PCTL) * 100)
    min_games = math.ceil(injuries.REG_WEEKS * injuries.MIN_GAMES_SHARE)
    top_html = "" if top is None else f"""<h2>Most Impactful Injuries</h2>
<p>The single most damaging player absences across all seasons, ranked by estimated points lost.</p>
<div class="table-scroll">
{top.to_html()}
</div>"""
    return f"""<p>Eligible players: drafted by a team (accountable all {injuries.REG_WEEKS} weeks), plus
    waiver / free-agent pickups held at least {PICKUP_MIN_WEEKS} weeks — a pickup only answers for games
    missed while actually on the roster (add week until dropped or traded).<br>
    Not eligible: short-term streamers, and pickups of players drafted that season
    (their missed games are already charged to the drafter).</p>
<p>Not all missed games hurt equally, so each injury is also weighted by how much the player mattered:<br>
<strong>High-Impact Games Missed</strong> — games missed by players drafted in the first {premium} rounds
or scoring at weekly-starter pace: top {top_pct}% <em>median</em> weekly points among drafted players at
their position that season, with at least {min_games} games played (so a couple of spike weeks
don't count as starter production).<br>
<strong>Est. Pts Lost</strong> — games missed &times; the player's median weekly score, so losing a stud
costs far more than losing a bench stash.</p>
<div class="table-scroll">
{table.to_html()}
</div>
{top_html}
<h2>Injury Breakdown by Season</h2>
<img src="data:image/png;base64,{img}" alt="Games Missed Plot"/>"""


def generate(output=OUTPUT):
    """Write the homepage to `output` (default docs/index.html)."""
    sections = [
        ("board", "Draft Board - Live ADP by Site", upcoming.adp_board_section(), True),
        ("metrics", "All-Time Metrics", metrics_section(), False),
        ("injuries", "All-Time Injury Impacts", injury_section(), False),
        ("adp", "All-Time Draft Values & Busts", adp.all_time_section(), False),
    ]
    nav = layout.section_nav([(a, title) for a, title, _, _ in sections])
    body = layout.HEAD + upcoming.countdown_banner() + nav + "".join(
        layout.details(title, html, open=is_open, anchor=a) for a, title, html, is_open in sections)

    page = add_front_matter(body, "Home")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page, encoding="utf-8")
    print(f"Wrote homepage -> {output}")


if __name__ == "__main__":
    generate()
