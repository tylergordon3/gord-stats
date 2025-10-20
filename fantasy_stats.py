'''
    This module fetches general NFL and player stats. 
'''
import nflreadpy as nfl
import pandas as pd
import constants as c


def get(week) -> pd.DataFrame:
    """Returns NFL fantasy player stats for a given week.

    :param week: Week of (current) NFL season to get stats for
    :type week: int
    :return: DataFrame with a wholllleee lotttaaa data
    :rtype: pd.DataFrame
    """
    # Load player game-level stats for multiple seasons
    player_stats = nfl.load_player_stats(nfl.get_current_season(), 'week')

    # nflreadpy uses Polars instead of pandas. Convert to pandas if needed:
    p_stats = player_stats.to_pandas()
    p_stats.columns = c.player_stats_headers
    pos_groups_remove = ["LB", "DL", "OL", "DB", "None"]
    spec_teams_remove = ["P", "LS"]
    p_stats_filter = p_stats[~p_stats.position_group.isin(pos_groups_remove)]
    p_stats = p_stats_filter[~p_stats_filter.position.isin(spec_teams_remove)]

    this_week = p_stats[p_stats['week'] == week]

    return this_week

'''
fg_made", "fg_att", "fg_missed", "fg_blocked", "fg_long", "fg_pct", "fg_made_0_19",
                        "fg_made_20_29", "fg_made_30_39", "fg_made_40_49", "fg_made_50_59", "fg_made_60_",
                        "fg_missed_0_19", "fg_missed_20_29", "fg_missed_30_39", "fg_missed_40_49", "fg_missed_50_59",
                        "fg_missed_60_", "fg_made_list", "fg_missed_list", "fg_blocked_list",
                        "fg_made_distance", "fg_missed_distance", "fg_blocked_distance", "pat_made",
                        "pat_att", "pat_missed", "pat_blocked",
'''
def kicker_fpts(team_df):
    # 0-39  +3 pts
    # 40-49 +4 pts
    # 50+   +5 pts
    # PAT   +1 pts
    # missed PAT/XP -1 pts
    kicker_df = team_df[team_df.position == "K"]
    # df = df[['a','b']]
    kicker_df = kicker_df[["fg_made", "fg_att", "fg_missed", "fg_blocked", "fg_long", "fg_pct", "fg_made_0_19",
                        "fg_made_20_29", "fg_made_30_39", "fg_made_40_49", "fg_made_50_59", "fg_made_60_",
                        "fg_missed_0_19", "fg_missed_20_29", "fg_missed_30_39", "fg_missed_40_49", "fg_missed_50_59",
                        "fg_missed_60_", "fg_made_list", "fg_missed_list", "fg_blocked_list",
                        "fg_made_distance", "fg_missed_distance", "fg_blocked_distance", "pat_made",
                        "pat_att", "pat_missed", "pat_blocked"]]
    range3 = 3 * (kicker_df["fg_made_0_19"] + kicker_df["fg_made_20_29"] + kicker_df["fg_made_30_39"])
    range4 = 4 * kicker_df["fg_made_40_49"]
    range5 = 5* (kicker_df["fg_made_50_59"] + kicker_df["fg_made_60_"])
    kicker_df['fpts'] = range3 + range4 + range5 + kicker_df['pat_made'] - kicker_df['pat_missed'] - kicker_df['fg_missed']
    print(kicker_df)
    return team_df