import nflreadpy as nfl
from sleeper_wrapper import League
import constants as c
import fantasy_rosters, nfl_stats
import player_db as db
import fantasy_rosters as fr
import numpy as np

#stats = fantasy_stats.get(prev_week)
league = League(c.LEAGUEID)
rosters = fantasy_rosters.get(league)

leagueData = fr.get(league)

BigGourds = leagueData.loc[1]
print(leagueData)


players = db.get(7)
#print(BigGourds)

# merged_players[~merged_players.position.isin(spec_teams_remove)]
team = players[players.sleeper_id.isin(values=BigGourds.players)]
#print(team)