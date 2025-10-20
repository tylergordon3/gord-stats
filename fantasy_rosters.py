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
   
    
def getTeam(rosters, team_name, week):
    myTeam = rosters[rosters['team_name'] == team_name]
    starters = myTeam['players'].values[0]

    with open('players.json', 'r', encoding='utf-8') as file:
        data = json.load(file)
        players = pd.DataFrame.from_dict(data, orient='index')

    players_filter = players[players.player_id.isin(starters)]
    # sleeper players for chosen team
    team = players_filter[['search_full_name', 'team', 'fantasy_positions', 'fantasy_data_id']]
    
    wk = fantasy_stats.get(week)
    wk['name_match'] = [re.sub(r'\s+', '', str(x)).lower() for x in wk['player_display_name']]
    wk_me = wk[wk.name_match.isin(team['search_full_name'])]
    
    # fantasy stats for players on chosen team
    print("RESULTS FOR WEEK: ", week)
    print(wk_me)

    return wk_me


myLeague = League(league_id="1257466498994143232")
teams = get(league=myLeague)
