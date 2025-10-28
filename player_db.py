import json
import pandas as pd
import nflreadpy as nfl
import constants as c
import re
import nfl_stats as stats
import numpy as np
import json

def get(week):
    # Week returns specific week, 0 returns all
    with open('players.json', 'r', encoding='utf-8') as file:
            data = json.load(file)
            sleeper_players = pd.DataFrame.from_dict(data, orient='index')

    defenses = sleeper_players[sleeper_players['position'] == 'DEF']
    defenses = defenses.dropna(axis=1, how='all')
    stats_defenses = nfl.load_team_stats(nfl.get_current_season(), 'week')
    stats_defenses = stats_defenses.to_pandas()
    
    def_fpts = stats.def_fpts(stats_defenses)
    
    stats_players = nfl.load_player_stats(nfl.get_current_season(), 'week')
    stats_players = stats_players.to_pandas()
    stats_players.columns = c.player_stats_headers
    stats_players = stats_players.iloc[:-1]
    stats_players['cleaned_name'] = stats_players['player_display_name'].str.split()
    stats_players = stats_players[~stats_players['cleaned_name'].isnull()]
    stats_players['cleaned_name'] = stats_players['cleaned_name'].apply(lambda lst: lst.str.join('') if len(lst) < 2 else ''.join(lst[:2]))
    
    
    stats_players['search_full_name'] = [re.sub(r'\s+', '', str(x)).lower() for x in stats_players['cleaned_name']]
    
    merged_players =  pd.merge(sleeper_players, stats_players, on='search_full_name', how='inner')
    merged_players = merged_players.drop(columns=['competitions', 'team_abbr', 'high_school', 'practice_participation', 'opta_id', 'birth_country', 'injury_start_date', 'birth_state',
                                 'height', 'team_changed_at', 'practice_description', 'birth_city', 'fantasy_positions', 'position_x', 'injury_notes',
                                 'pandascore_id', 'sport', 'metadata', 'news_updated', 'search_rank', 'team_y', 'depth_chart_order', 'hashtag', 'player_name',
                                 'search_first_name', 'search_last_name', 'player_display_name'])
    
    merged_players = merged_players.rename(columns={"position_y" : "position", "team_x" : "team", "player_id_x" : "sleeper_id", "player_id_y" : "nflstats_id"})
    # positions is position_y
    pos_groups_remove = ["LB", "DL", "OL", "DB", "None"]
    spec_teams_remove = ["P", "LS"]
    merged_players = merged_players[~merged_players.position_group.isin(pos_groups_remove)]
    
    merged_players = merged_players[~merged_players.position.isin(spec_teams_remove)]
    merged_players = merged_players.drop(columns="position_group")

    # IDs in DF
    #   espn_id, swish_id, fantasy_data_id, sportradar_id, yahoo_id, kalshi_id
    #   oddsjam_id, stats_id, rotowire_id, rotoworld_id, sleeper_id, nflstats_id

    # Player Info in DF
    #   birth_date, search_full_name, last_name, years_exp, team
    #   injury_body_part, status, weight, college, number, age,
    #   injury status, first_name, full_name, headshot_url

    # Fantasy Stats in DF
    #   "completions", "attempts", "passing_yards", "passing_tds", "passing_interceptions", "sacks_suffered",
    #   "sack_yards_lost", "sack_fumbles", "sack_fumbles_lost", "passing_air_yards",
    #   "passing_yards_after_catch", "passing_first_downs", "passing_epa", "passing_cpoe",
    #   "passing_2pt_conversions", "pacr", "carries", "rushing_yards", "rushing_tds",
    #   "rushing_fumbles", "rushing_fumbles_lost", "rushing_first_downs", "rushing_epa",
    #    "rushing_2pt_conversions", "receptions", "targets", "receiving_yards", "receiving_tds",
    #    "receiving_fumbles", "receiving_fumbles_lost", "receiving_air_yards",
    #    "receiving_yards_after_catch", "receiving_first_downs", "receiving_epa",
    #    "receiving_2pt_conversions", "racr", "target_share", "air_yards_share", "wopr",
    #    "special_teams_tds", "def_tackles_solo", "def_tackles_with_assist", "def_tackle_assists",
    #    "def_tackles_for_loss", "def_tackles_for_loss_yards", "def_fumbles_forced", "def_sacks",
    #    "def_sack_yards", "def_qb_hits", "def_interceptions", "def_interception_yards",
    #    "def_pass_defended", "def_tds", "def_fumbles", "def_safeties", "misc_yards",
    #    "fumble_recovery_own", "fumble_recovery_yards_own", "fumble_recovery_opp",
    #    "fumble_recovery_yards_opp", "fumble_recovery_tds", "penalties", "penalty_yards",
    #    "punt_returns", "punt_return_yards", "kickoff_returns", "kickoff_return_yards",
    #    "fg_made", "fg_att", "fg_missed", "fg_blocked", "fg_long", "fg_pct", "fg_made_0_19",
    #    "fg_made_20_29", "fg_made_30_39", "fg_made_40_49", "fg_made_50_59", "fg_made_60_",
    #    "fg_missed_0_19", "fg_missed_20_29", "fg_missed_30_39", "fg_missed_40_49", "fg_missed_50_59",
    #    "fg_missed_60_", "fg_made_list", "fg_missed_list", "fg_blocked_list",
    #    "fg_made_distance", "fg_missed_distance", "fg_blocked_distance", "pat_made",
    #    "pat_att", "pat_missed", "pat_blocked", "pat_pct", "gwfg_made", "gwfg_att", "gwfg_missed",
    #    "gwfg_blocked", "gwfg_distance", "fantasy_points", "fantasy_points_ppr"
    
    merged_players['fantasy_points'] = np.where(merged_players.position == "K", stats.kicker_fpts(merged_players), merged_players['fantasy_points'])
    merged_players['fantasy_points_ppr'] = np.where(merged_players.position == "K", stats.kicker_fpts(merged_players), merged_players['fantasy_points_ppr'])

    print(pd.concat([merged_players, def_fpts]))
    if (week <= 0): 
        #print("Returning player database for entire season.")
        return merged_players
    else: 
        #print("Returning player database for week: ", week)
        return merged_players[merged_players['week'] == week]
 

db = get(8)
