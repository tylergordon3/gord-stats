import nflreadpy as nfl
from sleeper_wrapper import League
import constants as c
import player_db as db
import fantasy_rosters as fr
import player_db as pdb
import numpy as np
import pandas as pd
import player as p

league = League(c.LEAGUEID)
rosters = fr.get(league)

week = 1
wk1 = pd.DataFrame.from_dict(league.get_matchups(week))
db = pdb.get(week)

wk1 = wk1[['roster_id', 'players_points', 'matchup_id']]
roster_id = 2
team = wk1[wk1.roster_id == roster_id]
key = roster_id - 1
ps = team.players_points.get(key)

players = []
for id, pts in ps.items():
    this_player = db[db.sleeper_id == id]
    print(this_player['full_name'], ", ID: ", id)
    print('Pts: ' ,pts, '\n')