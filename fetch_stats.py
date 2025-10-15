'''
    This module fetches general NFL and player stats. 
'''
import nflreadpy as nfl
import pandas as pd


# Load player game-level stats for multiple seasons
player_stats = nfl.load_player_stats([2025])


# nflreadpy uses Polars instead of pandas. Convert to pandas if needed:
pbp_pandas = pd.DataFrame(player_stats)

print(pbp_pandas)
