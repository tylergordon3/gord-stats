"""
League Home (docs/fantasy/index.html).

The page holds two versions of itself and shows one.

  * **This league**, built on the Pi out of the archive: all-time metrics
    (SOS, SOV, expected wins) computed from data/season/*.json, and the team
    profiles. None of it exists for anybody else's league - it is years of
    this one, kept here.

  * **The reader's league**, rendered in the browser from Sleeper: champions,
    season by season, all-time records, head-to-head (gordstats.my_history)
    and every draft it has held (gordstats.my_draft). Those two used to be
    links on the Analytics hub, which is a strange place for the history of
    the league whose home page this is.

`my_league.takeover` picks between them before the page paints.

The all-time studies that need the archive rather than the league - injury
impacts, draft values and busts - moved to Analytics, where the rest of the
deeper work lives.

    python -m fantasy.site.homepage
"""
import math

import pandas as pd

from fantasy import paths
from fantasy.config import (
    CHAMPIONS, EXPW_RATIO, FANTASY_REG_WEEKS, ROOT, ROSTER_NAMES, SEASON_DIR,
)
from fantasy.site import layout, styles, team_profiles, upcoming
from gordstats import my_history, my_home, my_league, my_league_data
from gordstats.frontmatter import add_front_matter

OUTPUT = paths.WEB_FANTASY_HOME

# The live ADP board (upcoming.adp_board_section) is a pre-draft page: it
# reads where the market has every player going into the draft. The 2026
# draft is done, so it is off; flip it back on next summer, when the
# "predraft" rebuild preset starts refreshing the board again.
LIVE_ADP_BOARD = False

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
    season_frames = []
    for path in sorted(SEASON_DIR.glob("*.json")):
        df = pd.read_json(path)
        season_frames.append(df[df["week"] <= FANTASY_REG_WEEKS])

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

    # Expected wins via Pythagorean expectation, scaled to the head-to-head
    # games each team has actually played - not 14 a season, which credited a
    # season two weeks old with fourteen games (280 expected wins against 220).
    g["Exp W (Actual)"] = g.apply(
        lambda x: f"{(x.PF**EXPW_RATIO) / (x.PF**EXPW_RATIO + x.PA**EXPW_RATIO) * (x.h2h_wins + x.h2h_loss):.1f}"
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
        .background_gradient(text_color_threshold=styles.GRADIENT_INK, cmap="RdYlGn_r", subset=["SOS"])
        .background_gradient(text_color_threshold=styles.GRADIENT_INK, cmap="RdYlGn", subset=["SOV"])
        .apply(styles.bg_from_pythag_str, subset=["Exp W (Actual)"])
        .set_table_styles([styles.GRID_TD, styles.GRID_TH, styles.TABLE_STYLE], overwrite=False)
        .set_table_attributes('class="sticky-table"')
    )


def metrics_section() -> str:
    """The All-Time Metrics block of the homepage (legend, table)."""
    table = _style(all_time_metrics()).to_html()
    # One line per column. "Read = Weaker Teams" was a typo for Red that had
    # stood here since the page was ported.
    return f"""<p><strong>PF / PA</strong>: points for and against, all seasons.</p>
<p><strong>SOS</strong> (strength of schedule): green easier, red harder.</p>
<p><strong>SOV</strong> (strength of victory): green = wins over stronger teams, red = over weaker ones.</p>
<p><strong>Exp W (Actual)</strong>: head-to-head wins expected from points scored and allowed (Pythagorean, constant {EXPW_RATIO}), actual in parentheses; green beat it, red fell short.</p>
<div class="table-scroll">
{table}
</div>"""


def teams_section() -> str:
    """The team profiles (fantasy.site.team_profiles), with the current Sleeper
    team names and pictures where Sleeper answers."""
    try:
        from fantasy.league.matchups import teams
        current = teams()
    except Exception as exc:                            # noqa: BLE001
        print(f"[homepage] team names unavailable ({exc})")
        current = {}
    return team_profiles.section(current)


def mine_section() -> str:
    """The reader's own league, in this page's own format (gordstats.my_home):
    All-Time Metrics and the team profiles, drawn from Sleeper in the browser.
    It used to be a different page - champions, a table per season, an
    all-time table and a head-to-head grid, one after another - longer,
    plainer, and not what everybody else was looking at."""
    nav = layout.section_nav([("mh-metrics-h", "All-Time Metrics"), ("mh-teams-h", "Teams")])
    links = ("<p class='lh-more'>Champions, every season's table and the head-to-head grid "
             "are on " + layout.internal_link("/fantasy/history/", "League History")
             + "; every draft on "
             + layout.internal_link("/fantasy/draft-review/", "Draft Review") + ".</p>")
    return "<div id='lh-mine' hidden>" + my_home.section(nav, links) + "</div>"


def generate(output=OUTPUT):
    """Write League Home to `output`."""
    inline = [
        ("metrics", "All-Time Metrics", metrics_section()),
        ("teams", "Teams", teams_section()),
    ]
    board = (layout.details("Draft Board - Live ADP by Site", upcoming.adp_board_section(),
                            open=True, anchor="board") if LIVE_ADP_BOARD else "")
    nav = layout.section_nav(([("board", "Draft Board")] if LIVE_ADP_BOARD else [])
                             + [(a, title) for a, title, _ in inline])
    built = ("<div id='lh-built'>" + nav + board
             + "".join(f'<h2 id="{a}">{title}</h2>{html}' for a, title, html in inline)
             + "</div>")
    body = (layout.HEAD + upcoming.countdown_banner() + my_league.bar()
            + mine_section() + built + my_league.takeover("lh-mine", "lh-built")
            # my_history's script carries the Sleeper reading my_home draws
            # from (window.GSHist); its own section is not on this page.
            + my_league_data.JS + my_league.JS + my_history.JS + my_home.JS)

    page = add_front_matter(body, "Fantasy Football")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page, encoding="utf-8")
    print(f"Wrote homepage -> {output}")


if __name__ == "__main__":
    generate()
