"""
Draft-review page (src/).

For a season, compares where each player was drafted to where they finished
(overall and positional), with injury-adjusted views, per-team breakdowns, and
a games-missed summary that is archived for the homepage injury section.

    python -m src.site.draft 2526

Sources: Sleeper draft picks + rosters, and src.stats.player_points for finish.
Uses the correct season's stats via SEASON_YEAR (the legacy draft.py always used
the current season).
"""
import base64
import io
import sys

import matplotlib
matplotlib.use("Agg")           # non-interactive backend
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd              # noqa: E402
from sleeper_wrapper import Drafts, League  # noqa: E402

from src import archive, stats                          # noqa: E402
from src.config import (DRAFT_IDS, FORMAL_SEASON, LEAGUE_IDS,  # noqa: E402
                        ROOT, ROSTER_NAMES, SEASON_YEAR)
from src.site import styles                             # noqa: E402
from src.site.frontmatter import add_front_matter       # noqa: E402

CUTOFF_ROWS = 15
REG_WEEKS = 14


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def _rosters(league) -> pd.DataFrame:
    """roster_id -> owner_id, team_name."""
    users = league.map_users_to_team_name(league.get_users())
    users = pd.Series(users).rename_axis("owner_id").reset_index(name="team_name")
    rosters = pd.DataFrame(league.get_rosters())[["owner_id", "roster_id"]]
    return rosters.merge(users, on="owner_id", how="inner")


def _sum_pts(players, pid):
    return players[players["sleeper_id"] == str(pid)]["fantasy_points_ppr"].sum()


def _num_games(players, pid):
    return players[players["sleeper_id"] == str(pid)]["fantasy_points_ppr"][:13].count()


def _final_rank(row, df):
    return len(df[df["total_pts"] > row.total_pts]) + 1


def _pos_rank(row, position_df):
    return len(position_df[position_df["pick_no"] < row.pick_no]) + 1


def _final_rank_missed_szn(final_ranks, position, pts):
    same = final_ranks[(final_ranks["pos"] == position) & (final_ranks["tot_pts"] == pts)]
    return int(same.head(1)["pos_rank"].iloc[0]) if not same.empty else 999


def _table_html(styler) -> str:
    return f'<div class="table-scroll">\n{styler.to_html()}\n</div>'


def _plot_b64(df, x_col, title, rot=45) -> str:
    df.plot(x=x_col, kind="bar", stacked=True, title=title, rot=rot)
    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight")
    buf.seek(0)
    img = base64.b64encode(buf.read()).decode("utf-8")
    buf.close()
    plt.close()
    return img


# --------------------------------------------------------------------------- #
# Core data build
# --------------------------------------------------------------------------- #

def _build(season_str: str):
    """Return (display df, final_ranks) for the season's draft review."""
    league = League(LEAGUE_IDS[season_str])
    draft = Drafts(DRAFT_IDS[season_str])
    rosters = _rosters(league)

    players = stats.player_points(season=SEASON_YEAR[season_str])
    players = players[players["week"] < REG_WEEKS + 1]

    final_ranks = players.groupby("cleaned_name").agg(
        tot_pts=("fantasy_points_ppr", "sum"),
        tot_games=("fantasy_points_ppr", "count"),
        pos=("position", "first"),
    )
    final_ranks["overall"] = final_ranks["tot_pts"].rank(ascending=False).astype(int)
    final_ranks = final_ranks.sort_values("overall")
    final_ranks["pos_rank"] = final_ranks.groupby("pos")["tot_pts"].rank(ascending=False).astype(int)

    picks = pd.DataFrame(draft.get_all_picks())
    # Drop metadata fields that collide with pick columns (esp. player_id) or add noise.
    meta = picks["metadata"].apply(pd.Series).drop(
        columns=["team_abbr", "team_changed_at", "sport", "news_updated", "years_exp",
                 "status", "injury_status", "number", "player_id"], errors="ignore")
    draft_df = pd.concat([picks, meta], axis=1)

    roster_by_owner = dict(zip(rosters["owner_id"], rosters["roster_id"]))
    team_by_roster = dict(zip(rosters["roster_id"], rosters["team_name"]))
    draft_df["roster_id"] = draft_df["picked_by"].map(roster_by_owner)
    draft_df["team_name"] = draft_df["roster_id"].map(team_by_roster)

    df = draft_df[["pick_no", "roster_id", "team_name", "player_id", "first_name",
                   "last_name", "round", "position", "team"]].copy()

    # Player key (same CamelCase scheme as stats), team abbrev for defenses.
    df["name"] = stats.cleaned_name(df["first_name"].fillna("") + " " + df["last_name"].fillna(""))
    df["name"] = df.apply(lambda x: x["team"] if x["position"] == "DEF" else x["name"], axis=1)

    df["pos_rank"] = df.apply(lambda x: _pos_rank(x, df[df["position"] == x.position]), axis=1)
    df["total_pts"] = df["player_id"].apply(lambda pid: _sum_pts(players, pid))
    df["num_games"] = df["player_id"].apply(lambda pid: _num_games(players, pid))
    df["final_rank"] = df.apply(lambda x: _final_rank(x, df), axis=1)

    df["final_pos_rank"] = df["name"].apply(
        lambda n: list(final_ranks[final_ranks.index == n]["pos_rank"]))
    df["final_pos_rank"] = df.apply(
        lambda x: x["final_pos_rank"][0] if len(x["final_pos_rank"]) > 0
        else _final_rank_missed_szn(final_ranks, x["position"], x["total_pts"]), axis=1)

    df["overall_diff"] = df["pick_no"] - df["final_rank"]
    df["pos_diff"] = df["pos_rank"] - df["final_pos_rank"]
    df["Position Rk"] = df.apply(lambda x: f"{x['pos_rank']} -> {x['final_pos_rank']}", axis=1)
    df["Overall Rk"] = df.apply(lambda x: f"{x['pick_no']} -> {x['final_rank']}", axis=1)

    df = df.drop(columns=["player_id", "first_name", "last_name", "pos_rank",
                          "final_pos_rank", "final_rank"])
    df = df[~df["position"].isin(["K", "DEF"])]
    df = df.rename(columns={
        "pos_diff": "Pos. Rank Δ", "overall_diff": "Overall Rank Δ", "pick_no": "Pick",
        "position": "Pos.", "team_name": "Owner", "total_pts": "Pts.",
        "name": "Name", "team": "Team", "num_games": "Games Played",
    })
    df["Pick"] = df.apply(lambda x: f"{x['round']}.{x['Pick']}", axis=1)
    return df, final_ranks


# --------------------------------------------------------------------------- #
# Per-team breakdowns + plots
# --------------------------------------------------------------------------- #

def _by_team(df):
    grouped = df.groupby(by=["roster_id", "Pos."]).agg(
        pos_delt=("Pos. Rank Δ", "sum"), ovr_delt=("Overall Rank Δ", "sum")).fillna(0)
    result = grouped.reset_index().rename(
        columns={"pos_delt": "Total Pos. Rank Δ", "ovr_delt": " Total Ovr. Rank Δ"})
    by_pos = [result[result["Pos."] == p].sort_values("Total Pos. Rank Δ", ascending=False)
              for p in ("QB", "RB", "WR", "TE")]
    overall = df.groupby(by=["roster_id"]).agg(ovr_delt=("Overall Rank Δ", "sum")).fillna(0)
    overall = overall.reset_index().rename(columns={"ovr_delt": " Total Ovr. Rank Δ"})
    return by_pos + [overall]


def _draft_plots(breakdown):
    overall_df, positional_df = pd.DataFrame(), pd.DataFrame()
    for i in range(len(breakdown) - 1):
        d = breakdown[i]
        d["Team"] = d["roster_id"].map(ROSTER_NAMES)
        positional_df = pd.concat([positional_df, d[["Team", "Pos.", "Total Pos. Rank Δ"]]])
        overall_df = pd.concat([overall_df, d[["Team", "Pos.", " Total Ovr. Rank Δ"]]])

    pos_group = (positional_df.groupby(["Team", "Pos."], as_index=False).sum()
                 .pivot_table(index="Team", columns="Pos.", values="Total Pos. Rank Δ", aggfunc="sum")
                 .rename_axis(None, axis=1).reset_index())
    ovr_group = (overall_df.groupby(["Team", "Pos."], as_index=False).sum()
                 .pivot_table(index="Team", columns="Pos.", values=" Total Ovr. Rank Δ", aggfunc="sum")
                 .rename_axis(None, axis=1).reset_index())
    return (_plot_b64(pos_group, "Team", "Positional Rank Change"),
            _plot_b64(ovr_group, "Team", "Overall Rank Change"))


def _games_missed(df, season_str):
    """Per-team games missed by drafted players; archive it + return a display df."""
    missing = df.groupby(by=["Owner", "roster_id"]).agg(
        num_games=("Games Played", "sum"), tot_players=("Games Played", "count"))
    missing["tot_games"] = missing["tot_players"] * REG_WEEKS
    missing["Total Games Missed"] = missing["tot_games"] - missing["num_games"]
    missing["% of Games Missed"] = (missing["Total Games Missed"] / missing["tot_games"]).apply(
        lambda x: f"{x:.2%}")
    archive.save_statistic(season_str, "missing_df", missing.reset_index().to_dict(orient="records"))

    disp = missing.reset_index().rename(columns={"Owner": "Owners"})
    disp = disp.sort_values("Total Games Missed", ascending=False)
    return disp[["Owners", "Total Games Missed", "% of Games Missed"]]


def _plot_pair(breakdown, alt_prefix):
    pos_img, ovr_img = _draft_plots(breakdown)
    return (f'<div class="img-pair">'
            f'<img src="data:image/png;base64,{pos_img}" alt="{alt_prefix} Position Rank Change"/>'
            f'<img src="data:image/png;base64,{ovr_img}" alt="{alt_prefix} Overall Rank Change"/>'
            f"</div>")


# --------------------------------------------------------------------------- #
# Page assembly
# --------------------------------------------------------------------------- #

def _page_html(season_str: str) -> str:
    df, _ = _build(season_str)

    display_cols = ["Pick", "Owner", "Name", "Pos.", "Team", "Position Rk", "Pos. Rank Δ",
                    "Overall Rk", "Overall Rank Δ", "Games Played", "roster_id"]
    full = df[display_cols + ["round"]]
    lottery = full[full["round"] < 5]
    no_inj = full[full["Games Played"] >= 10]
    lottery_no_inj = lottery[lottery["Games Played"] >= 10]

    def steals_busts(frame):
        return (styles.default_style(frame.sort_values("Overall Rank Δ", ascending=False).head(CUTOFF_ROWS),
                                     ["Overall Rank Δ"], cmap="Greens"),
                styles.default_style(frame.sort_values("Overall Rank Δ").head(CUTOFF_ROWS),
                                     ["Overall Rank Δ"], cmap="Reds_r"))

    full_styler = (full[display_cols].style.hide(axis="index")
                   .background_gradient(cmap="RdYlGn", subset=["Pos. Rank Δ"], vmin=-60)
                   .background_gradient(cmap="RdYlGn", subset=["Overall Rank Δ"], vmin=-75))
    steals, busts = steals_busts(full)
    steals_ni, busts_ni = steals_busts(no_inj)

    html = f"""<p>Note: Does not include defenses or kickers.</p>
<details><summary><strong>Full Draft</strong></summary>{_table_html(full_styler)}</details>
<details><summary><strong>Biggest OVERALL Steals</strong></summary>{_table_html(steals)}</details>
<details><summary><strong>Biggest OVERALL Busts</strong></summary>{_table_html(busts)}</details>
<p>The following tables only include players who played in 10 or more games. (~64.5% game requirement)</p>
<p> - Only includes fantasy regular season (weeks 1-14)</p>
<details><summary><strong>Biggest OVERALL Steals (Injury adjusted)</strong></summary>{_table_html(steals_ni)}</details>
<details><summary><strong>Biggest OVERALL Busts (Injury adjusted)</strong></summary>{_table_html(busts_ni)}</details>
"""

    # Games missed: archive (for the homepage) + on-page table.
    missing = _games_missed(full.copy(), season_str)
    html += ("<p>Number of games drafted players missed over the 14-week regular season. "
             "Missed = not starting or playing an entire game; leaving mid-game counts as played.</p>")
    html += _table_html(styles.default_style(missing, ["Total Games Missed"], cmap="RdYlGn_r"))

    # Rank-change plots: all, injury-removed, first-4-rounds, first-4-rounds injury-removed.
    html += "<h1>Player Rank Change</h1>"
    html += "<p>Change in position & overall rank from draft slot to season finish (by fpts).</p>"
    html += "<h3>Rank Changes, All Players</h3>" + _plot_pair(_by_team(full.copy()), "All")
    html += "<h3>Rank Changes, Injured Players Removed</h3>" + _plot_pair(_by_team(no_inj.copy()), "No Inj")
    html += "<h3>Rank Changes, First 4 Rounds</h3>" + _plot_pair(_by_team(lottery.copy()), "Lottery")
    html += ("<h3>Rank Changes, First 4 Rounds, Injured Players Removed</h3>"
             + _plot_pair(_by_team(lottery_no_inj.copy()), "Lottery No Inj"))
    return html


def generate(season_str: str):
    """Build and write docs/<season_str>/draft/index.html."""
    html = _page_html(season_str)
    page = add_front_matter(html, f"Draft - {FORMAL_SEASON[season_str]}")
    out = ROOT / "docs" / season_str / "draft" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"Wrote draft page -> {out}")


if __name__ == "__main__":
    season = sys.argv[1] if len(sys.argv) > 1 else "2526"
    generate(season)
