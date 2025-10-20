import nflreadpy as nfl
from sleeper_wrapper import League
import constants as c
import fantasy_rosters, fantasy_stats

week = nfl.get_current_week()
prev_week = week
#stats = fantasy_stats.get(prev_week)

league = League(c.LEAGUEID)
rosters = fantasy_rosters.get(league)

team_last_week = fantasy_rosters.getTeam(rosters, "Big Gourds", week=week)

kicker = fantasy_stats.kicker_fpts(team_last_week)
