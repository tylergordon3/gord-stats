import nflreadpy as nfl
from sleeper_wrapper import League
import constants as c
import fantasy_rosters, fantasy_stats
import player_db as db

week = nfl.get_current_week()
prev_week = week
#stats = fantasy_stats.get(prev_week)

league = League(c.LEAGUEID)
rosters = fantasy_rosters.get(league)

players = db.get(7)
print(players)