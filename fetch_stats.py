'''
    This module fetches general NFL and player stats. 
'''
import nflreadpy as nfl
import pandas as pd
# Load current season play-by-play data
pbp = nfl.load_pbp()

# Load player game-level stats for multiple seasons
player_stats = nfl.load_player_stats([2022, 2023])

# Load all available team level stats
team_stats = nfl.load_team_stats(seasons=True)

# nflreadpy uses Polars instead of pandas. Convert to pandas if needed:
pbp_pandas = pd.DataFrame(pbp)

print(pbp_pandas)
