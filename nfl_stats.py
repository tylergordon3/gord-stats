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

def def_fpts(def_df):
    defense_df = def_df[['team', 'week', 'special_teams_tds', 'def_fumbles_forced', 'def_sacks',
                 'def_interceptions', 'def_tds', 'fumble_recovery_opp',
                 'def_safeties']].copy()

    sched_stats = nfl.load_schedules(nfl.get_current_season())
    df_sched = sched_stats.to_pandas()
    df_sched_clean = df_sched[df_sched['week'] <= nfl.get_current_week()]
    score_given_up_h = df_sched_clean[['week', 'home_team', 'away_score']]
    score_given_up_a = df_sched_clean[['week', 'away_team', 'home_score']]
    score_given_up_h = score_given_up_h.rename(columns={"home_team" : "team", "away_score" : "PA"})
    score_given_up_a = score_given_up_a.rename(columns={"away_team" : "team", "home_score" : "PA"})
    score_given_up_h['team'] = score_given_up_h['team'].replace('LA', 'LAR')
    score_given_up_a['team'] = score_given_up_a['team'].replace('LA', 'LAR')
    def_PA = pd.concat([score_given_up_a, score_given_up_h], ignore_index=True)
    # PA 0        10pts PA 1-6      7pts
    # PA 7-13     4pts  PA 14-20    1pts
    # PA 28-34    -1pts PA 35+      -4pts
    def_PA['fantasy_points'] = def_PA['PA'].apply(lambda x: pa_adj(x))
    defense_df['fantasy_points'] = defense_df.apply(def_pts, axis=1)
    def_fpts = pd.concat([def_PA[['week', 'team', 'fantasy_points']], defense_df[['week', 'team', 'fantasy_points']]], ignore_index=True)
    def_fpts = def_fpts.dropna()
    pts = def_fpts.groupby(['week', 'team']).agg(fpts=('fantasy_points', 'sum')).reset_index()

    pts['cleaned_name'] = pts['team']
    pts['team1'] = pts['team']
    # pts['sleeper_id'] = pts['team']
    return pts
   

    
def def_pts(df):
    sacks = df['def_sacks']
    ints = 2*(df['def_interceptions'])
    fr = 2*(df['fumble_recovery_opp'])
    ff = df['def_fumbles_forced'] 
    safety = 2*(df['def_safeties'])
    tds = 6 * (df['def_tds'] + df['special_teams_tds'])
    values = sacks + ints + fr + ff + safety + tds
    return values

def pa_adj(pa):
    if pa == 0:
          return 10
    elif (1 <= pa) & (pa <= 6):
          return 7
    elif (7 <= pa) & (pa <= 13):
          return 4
    elif (14 <= pa) & (pa <= 20):
          return 1
    elif (21 <= pa) & (pa <= 27):
          return 0
    elif (28 <= pa) & (pa <= 34):
          return -1
    if 35 <= pa:
          return -4
    else:
        return None


with open('data/players.json', 'r', encoding='utf-8') as file:
            data = json.load(file)
            sleeper_players = pd.DataFrame.from_dict(data, orient='index')
defenses = sleeper_players[sleeper_players['position'] == 'DEF']
defenses = defenses.dropna(axis=1, how='all')
stats_defenses = nfl.load_team_stats(nfl.get_current_season(), 'week')
stats_defenses = stats_defenses.to_pandas()
def_fpts(stats_defenses)