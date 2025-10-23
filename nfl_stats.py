'''
    This module fetches general NFL and player stats. 
'''
import nflreadpy as nfl
import pandas as pd
import constants as c

import json

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
def kicker_fpts(player):
    # 0-39  +3 pts
    # 40-49 +4 pts
    # 50+   +5 pts
    # PAT   +1 pts
    # missed PAT/XP -1 pts
    # df = df[['a','b']]
    #kicker_df = kicker_df[["full_name","fg_made", "fg_att", "fg_missed", "fg_blocked", "fg_long", "fg_pct", "fg_made_0_19",
    #                    "fg_made_20_29", "fg_made_30_39", "fg_made_40_49", "fg_made_50_59", "fg_made_60_",
    #                    "fg_missed_0_19", "fg_missed_20_29", "fg_missed_30_39", "fg_missed_40_49", "fg_missed_50_59",
    #                    "fg_missed_60_", "fg_made_list", "fg_missed_list", "fg_blocked_list",
    #                    "fg_made_distance", "fg_missed_distance", "fg_blocked_distance", "pat_made",
    #                    "pat_att", "pat_missed", "pat_blocked", "fantasy_points", "fantasy_points_ppr"]]

    range3 = 3 * (player["fg_made_0_19"] + player["fg_made_20_29"] + player["fg_made_30_39"])
    range4 = 4 * (player["fg_made_40_49"]) 
    range5 = 5* (player["fg_made_50_59"] + player["fg_made_60_"])
    value = range3 + range4 + range5 +  player["pat_made"] + player['pat_missed'] - player['fg_missed']
    
    return value

'''
    TD          6pts
    PA 0        10pts
    PA 1-6      7pts
    PA 7-13     4pts
    PA 14-20    1pts
    PA 28-34    -1pts
    PA 35+      -4pts
    Sacks       1pts per
    INTs        2pts per
    FR          2pts per
    ST FR       1pts per
    SAF         2pts per
    FF          1pts per
    BK          2pts per
'''
def def_fpts(def_df):
    df = def_df[['team', 'week', 'special_teams_tds', 'def_fumbles_forced', 'def_sacks',
                 'def_interceptions', 'def_tds', 'def_fumbles',
                 'def_safeties']]
    sched_stats = nfl.load_schedules(nfl.get_current_season())
    df_sched = sched_stats.to_pandas()
    print(df)


with open('players.json', 'r', encoding='utf-8') as file:
            data = json.load(file)
            sleeper_players = pd.DataFrame.from_dict(data, orient='index')
defenses = sleeper_players[sleeper_players['position'] == 'DEF']
defenses = defenses.dropna(axis=1, how='all')
stats_defenses = nfl.load_team_stats(nfl.get_current_season(), 'week')
stats_defenses = stats_defenses.to_pandas()
print(def_fpts(stats_defenses))