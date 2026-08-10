"""
Draft pick data (src/) - internal data module.

Builds each season's drafted players with where they were taken (overall +
positional) and where they finished, from Sleeper draft picks + rosters and
src.stats.player_points. Consumed by src.site.adp (the Draft vs ADP page).

Also archives per-team games-missed for the homepage injury section
(save_games_missed), which is why this module survived the draft-page removal.
"""
from functools import lru_cache

import pandas as pd
from sleeper_wrapper import Drafts, League

from src import archive, stats
from src.config import DRAFT_IDS, LEAGUE_IDS, SEASON_YEAR

REG_WEEKS = 14


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


@lru_cache(maxsize=None)
def _build(season_str: str):
    """Return (picks df, final_ranks) for the season. Cached; callers must not mutate."""
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

    # Where the pick sits inside its round, for the "2.3" label below. Derived
    # from the overall pick rather than Sleeper's draft_slot: draft_slot is the
    # manager's seat, so in a snake round it counts backwards (the first pick of
    # round 2 belongs to seat 10 and is 2.1, not 2.10).
    per_round = int(draft_df.groupby("round")["pick_no"].count().max())
    df["pick_in_round"] = df["pick_no"] - (df["round"] - 1) * per_round

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
    df["Pick"] = df["round"].astype(str) + "." + df["pick_in_round"].astype(str)
    return df.drop(columns="pick_in_round"), final_ranks


def save_games_missed(season_str: str):
    """Archive per-team games missed by drafted players (feeds the homepage injury section)."""
    df, _ = _build(season_str)
    missing = df.groupby(by=["Owner", "roster_id"]).agg(
        num_games=("Games Played", "sum"), tot_players=("Games Played", "count"))
    missing["tot_games"] = missing["tot_players"] * REG_WEEKS
    missing["Total Games Missed"] = missing["tot_games"] - missing["num_games"]
    missing["% of Games Missed"] = (missing["Total Games Missed"] / missing["tot_games"]).apply(
        lambda x: f"{x:.2%}")
    archive.save_statistic(season_str, "missing_df", missing.reset_index().to_dict(orient="records"))

    # Per-player detail so the injury section can weight injuries by how much the
    # player mattered (draft capital, scoring pace) instead of counting all missed
    # games equally. Tiering/weighting happens at render time in src.site.injuries.
    detail = df[["Owner", "roster_id", "Name", "Pos.", "round", "Pick",
                 "Pts.", "Games Played"]].copy()
    archive.save_statistic(season_str, "injury_detail_df", detail.to_dict(orient="records"))
    print(f"[games-missed] archived {season_str}")
