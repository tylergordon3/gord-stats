"""
Median-race calculations (src/): for a given week, who is locked above/below the
league median (5th place), using max-points scenarios for players yet to play.

Library only - the Median pages were retired from the site, so nothing here
writes HTML. `compute()` returns one frame per week, each row carrying the team's
points, hypothetical max, rank and status ("W" / "L" / "tbd").

    from src.site.median import compute
    by_week = compute("2526")
"""
import pandas as pd
from sleeper_wrapper import League

from src import stats, util
from src.config import LEAGUE_IDS, MAX_POINTS, SEASON_YEAR
from src.league import rosters as rosters_mod


def _to_play(starters, weeks_players, db, week):
    """Starters who have not yet played this week (empty for completed weeks)."""
    series = pd.Series(starters)
    to_play = series[~series.isin(weeks_players["sleeper_id"])]
    if week <= util.get_last_completed_week():
        return []
    names = db[db["sleeper_id"].isin(to_play)]["cleaned_name"]
    return list(pd.unique(names))


def _hypothetical_max(names, db):
    players = db[db["cleaned_name"].isin(names)]
    total = 0
    for name in pd.unique(players["cleaned_name"]):
        pos = players[players["cleaned_name"] == name]["position"].mode()
        total += MAX_POINTS.get(list(pos)[0], 0)
    return total


def _set_winners(team, df):
    rank = team["rank"]
    if rank > 5:
        return team["status"]
    beaten = df[(df["rank"] > rank) & ((df["num_to_play"] == 0) | (df["status"] == "L"))]
    magic = 6 - rank
    if (10 - rank - beaten.shape[0]) < magic:
        return "W"
    if team["num_to_play"] == 0:
        return None
    return team["status"]


def _rule_out_set(matchup_df):
    df = matchup_df[["roster_id", "matchup_id", "team", "points", "to_play", "max_pts"]].copy()
    df = df.sort_values("points", ascending=False)
    df["rank"] = df["points"].rank(ascending=False)
    df["num_to_play"] = df["to_play"].apply(len)

    fifth = list(df[df["rank"] == 5]["points"])
    if fifth:
        median = fifth[0]
    elif df["points"].sum() > 0:
        median = df["points"].median()
    else:
        return pd.DataFrame()
    df["status"] = df.apply(lambda t: "L" if t["max_pts"] < median else "tbd", axis=1)
    df["status"] = df.apply(lambda t: _set_winners(t, df), axis=1)
    return df


def median_week(league, week, rosters, db) -> pd.DataFrame:
    """One week's median race, or an empty frame if the week has no matchups."""
    matchups = pd.DataFrame.from_dict(league.get_matchups(week))
    if matchups.empty or "starters" not in matchups.columns:
        return pd.DataFrame()   # week not played / no matchups
    starters = matchups[["roster_id", "matchup_id", "starters"]].copy()

    weeks_players = db[db["week"] == week]
    starters["to_play"] = starters["starters"].apply(lambda s: _to_play(s, weeks_players, db, week))

    combined = starters.merge(rosters, on="roster_id")
    matchups["to_play"] = combined["to_play"]
    matchups["team"] = combined["team_name"]
    matchups["max_pts"] = matchups["to_play"].apply(lambda n: _hypothetical_max(n, db)) + matchups["points"]
    return _rule_out_set(matchups)


def compute(season_str: str) -> dict[int, pd.DataFrame]:
    """Median race for every played week of a season, keyed by week number."""
    league = League(LEAGUE_IDS[season_str])
    rosters = rosters_mod.get(league)[["roster_id", "team_name"]]
    db = stats.get(0, SEASON_YEAR[season_str])   # full-season points, computed once
    last = min(14, util.get_week()) if season_str == util.year_str() else 14

    weeks = {}
    for week in range(1, last + 1):
        df = median_week(league, week, rosters, db)
        if not df.empty:
            weeks[week] = df
    return weeks
