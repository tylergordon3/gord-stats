"""
Weekly league matchup / record data (ported from py/league_data + league_util).

get_season(end_week, league_id) pulls each week's matchups from Sleeper and
builds cumulative H2H + median records, points for/against, and opponent info.
"""
import pandas as pd
from sleeper_wrapper import League
from tqdm import tqdm


def _teams(league: League) -> pd.DataFrame:
    users = league.map_users_to_team_name(league.get_users())
    users = pd.Series(users).rename_axis("owner_id").reset_index(name="team_name")
    rosters = pd.DataFrame.from_dict(league.get_rosters())[["owner_id", "roster_id"]]
    return users.merge(rosters, on="owner_id", how="left")


def _find_opponent(team, week_df):
    opps = week_df[(week_df["matchup_id"] == team["matchup_id"]) &
                   (week_df["roster_id"] != team["roster_id"])]
    opp = opps["roster_id"].iloc[0]
    opp_score = opps["points"].iloc[0]
    win = 0 if opp_score > team["points"] else 1
    return [opp, opp_score, win]


def _totals(team, season_df):
    if season_df.empty:
        h2h_wins, med_wins = team["win"], team["median"]
        return [h2h_wins, med_wins, 1 - h2h_wins, 1 - med_wins]
    prev = season_df[season_df["roster_id"] == team["roster_id"]]
    h2h_wins = prev["win"].sum() + team["win"]
    h2h_loss = len(prev) - h2h_wins + 1
    if team["week"] > 14:
        med_wins = prev["median"].sum()
        med_loss = len(prev)
    else:
        med_wins = prev["median"].sum() + team["median"]
        med_loss = len(prev) - med_wins + 1
    return [h2h_wins, med_wins, h2h_loss, med_loss]


def _point_totals(team, season_df):
    if season_df.empty:
        return [team["points"], team["opp_points"]]
    prev = season_df[season_df["roster_id"] == team["roster_id"]]
    return [prev["points"].sum() + team["points"], prev["opp_points"].sum() + team["opp_points"]]


def get_season(end_week: int, league_id: str) -> pd.DataFrame:
    """Cumulative weekly records/points for a league, weeks 1..min(end_week, 14)."""
    end_week = min(end_week, 14)
    league = League(league_id)
    teams = _teams(league)

    season = pd.DataFrame()
    for week in tqdm(range(1, end_week + 1), desc="Loading season"):
        wk = pd.DataFrame.from_dict(league.get_matchups(week)).rename(
            columns={"players_points": "players_dict"})
        wk["starters_dict"] = wk.apply(lambda x: dict(zip(x["starters"], x["starters_points"])), axis=1)
        wk["bench_dict"] = wk.apply(
            lambda x: {k: v for k, v in x["players_dict"].items() if k not in x["starters_dict"]}, axis=1)
        wk["matchup_id"] = wk["matchup_id"].astype("Int64")
        wk = wk[wk["matchup_id"].notna()]
        wk = wk.drop(columns=["starters", "starters_points", "players", "custom_points"])
        wk["week"] = week

        wk[["opp", "opp_points", "win"]] = wk.apply(
            lambda x: _find_opponent(x, wk), axis=1, result_type="expand")
        wk["median"] = (wk["points"].rank() > len(wk) / 2).astype(int)

        wk[["h2h_wins", "median_wins", "h2h_loss", "median_loss"]] = wk.apply(
            lambda x: _totals(x, season), axis=1, result_type="expand")
        wk["total_wins"] = wk["h2h_wins"] + wk["median_wins"]
        wk["total_loss"] = wk["h2h_loss"] + wk["median_loss"]
        wk["record"] = wk.apply(lambda x: f"{int(x['total_wins'])}-{int(x['total_loss'])}", axis=1)
        wk[["PF", "PA"]] = wk.apply(lambda x: _point_totals(x, season), axis=1, result_type="expand")

        wk = wk.merge(teams, how="left", on="roster_id")
        season = pd.concat([season, wk])
    return season
