from sleeper_wrapper import League
import constants as c

league = League(c.LEAGUEID)

rosters = league.get_rosters()
users = league.get_users()
'''
r	int	The round for this matchup, 1st, 2nd, 3rd round, etc.
m	int	The match id of the matchup, unique for all matchups within a bracket.
t1	int	The roster_id of a team in this matchup OR {w: 1} which means the winner of match id 1
t2	int	The roster_id of the other team in this matchup OR {l: 1} which means the loser of match id 1
w	int	The roster_id of the winning team, if the match has been played.
l	int	The roster_id of the losing team, if the match has been played.
t1_from	object	Where t1 comes from, either winner or loser of the match id, necessary to show bracket progression.
t2_from	object	Where t2 comes from, either winner or loser of the match id, necessary to show bracket progression.
'''
r= league.get_playoff_winners_bracket()
print(r)