import nflreadpy as nfl
from sleeper_wrapper import League
import constants as c
import fantasy_rosters, fantasy_stats
import player_db as db
import fantasy_rosters as fr
import numpy as np
import pandas as pd

#stats = fantasy_stats.get(prev_week)
league = League(c.LEAGUEID)
rosters = fantasy_rosters.get(league)


week = 1
wk1 = pd.DataFrame.from_dict(league.get_matchups(week))
wk1 = pd.DataFrame.from_dict(wk1['players_points'])

print(wk1)