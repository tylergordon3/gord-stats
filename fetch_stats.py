'''
    This module fetches general NFL and player stats. 
'''
import nflreadpy as nfl
import pandas as pd
import constants

# Load player game-level stats for multiple seasons
player_stats = nfl.load_player_stats(2025, 'week')

# nflreadpy uses Polars instead of pandas. Convert to pandas if needed:
p_stats = player_stats.to_pandas()
p_stats.columns = constants.player_stats_headers
print(p_stats.describe())
pos_groups_remove = ["LB", "DL", "OL", "DB", "None"]
spec_teams_remove = ["P", "LS"]
p_stats_filter = p_stats[~p_stats.position_group.isin(pos_groups_remove)]
p_stats = p_stats_filter[~p_stats_filter.position.isin(spec_teams_remove)]

print(p_stats.describe())
