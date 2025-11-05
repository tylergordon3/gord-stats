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


def bestball(week, players):
    matchup_df = pd.DataFrame.from_dict(league.get_matchups(week))
    db = pdb.get(week)

    df = matchup_df[['roster_id', 'players_points', 'matchup_id']]
    roster_id = 2
    team = df[df.roster_id == roster_id]
    key = roster_id - 1
    ps = team.players_points.get(key)

    for id, pts in ps.items():
        player = pdb.getFromID(id, db)
        name = player['cleaned_name']
        print(id, name.item() if not name.empty else ":(", pts)

    return players
    


# Starters: *Caleb, *CMC, *Monangai, *BTJ, *Marv, *Kraft, *Chase Brown, *Javonte, *Eddy, *NE
# Bench: Baker, *Tyrone, *Juan, *Jameson, Fannin, *CLE
# IR: Rhamondre
players = {}
players = bestball(7, players)
print("\n")
players = bestball(8, players)
print("\n")
players = bestball(9, players)
print (players)