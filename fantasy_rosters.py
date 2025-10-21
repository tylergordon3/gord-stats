"""
    Module for providing information on a league's users
"""
from sleeper_wrapper import League
import pandas as pd
import re
import json
import fantasy_stats


def get(league) -> pd.DataFrame:
    """Provides DataFrame with user and roster info:

    owner_id, players, reserve, roster_id, starters, 
    losses, ppts, ppts_decimal, ties, total_moves,
    waiver_budget_used, wins, PF, PA team_name

    :param league: sleeper_wrapper league
    :type league: League()
    :return: DataFrame with roster and user info
    :rtype: pd.DataFrame
    """
    users = league.map_users_to_team_name(league.get_users())
    users = pd.Series(users).to_frame().reset_index()
    users.columns = ['owner_id', 'team_name']

    rosters = pd.DataFrame.from_dict(league.get_rosters())
    rosters = rosters.drop(columns=['keepers', 'co_owners', 'league_id',
                                    'metadata', 'taxi', 'player_map'])
    details = rosters.settings.apply(pd.Series)
    details['roster_id'] = rosters.roster_id
    rosters = pd.merge(rosters, details, on='roster_id', how='inner')
    rosters = rosters.drop(columns=['settings', 'waiver_position'])

    rosters['PF'] = rosters['fpts'] + rosters['fpts_decimal']/10
    rosters['PA'] = rosters['fpts_against'] + \
        rosters['fpts_against_decimal']/10
    rosters = pd.merge(rosters, users, on='owner_id', how='inner')
    rosters = rosters.drop(
        columns=['fpts', 'fpts_decimal', 'fpts_against', 'fpts_against_decimal'])
    
    
    return rosters