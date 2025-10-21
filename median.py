import nflreadpy as nfl
from sleeper_wrapper import League
import constants as c
import fantasy_rosters, fantasy_stats
import player_db as db
import fantasy_rosters as fr

#stats = fantasy_stats.get(prev_week)
league = League(c.LEAGUEID)
rosters = fantasy_rosters.get(league)

leagueData = fr.get(league)

BigGourds = leagueData.loc[1]

players = db.get(7)
print(BigGourds.starters[0])

# merged_players[~merged_players.position.isin(spec_teams_remove)]
team = players[players.sleeper_id.isin(BigGourds.starters)]
print(team)