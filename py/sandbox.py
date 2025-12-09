from sleeper_wrapper import League
import constants as c

league = League(c.LEAGUEID)

rosters = league.get_rosters()
users = league.get_users()

standings = league.get_standings(rosters=rosters, users=users)
print(standings)