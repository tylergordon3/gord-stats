import pandas as pd
import constants
from sleeper_wrapper import League

def find_opponents(team, week_df):
    this_id = team['matchup_id']
    this_roster = team['roster_id']
    this_score = team['points']
    opponents = week_df[(week_df['matchup_id'] == this_id) &
                        (week_df['roster_id'] != this_roster)]

    opp = list(opponents['roster_id'])[0]
    opp_score = list(opponents['points'])[0]
    
    if opp_score > this_score:
        h2h_win = 0
    else:
        h2h_win = 1

    return [opp, opp_score, h2h_win]

def calc_totals(team, season_df):
    
    if season_df.empty:
        h2h_wins = team['win']
        med_wins = team['median']
        h2h_loss = 1 if h2h_wins == 0 else 0
        med_loss = 1 if med_wins == 0 else 0
        return [h2h_wins, med_wins, h2h_loss, med_loss]
    
    roster_id = team['roster_id']
    prev_weeks = season_df[season_df['roster_id'] == roster_id]
    if team['week'] > 14:
        h2h_wins = prev_weeks['win'].sum() + team['win']
        h2h_loss = len(prev_weeks) - h2h_wins + 1
        med_wins = prev_weeks['median'].sum()
        med_loss = len(prev_weeks)
    else:
        h2h_wins = prev_weeks['win'].sum() + team['win']
        h2h_loss = len(prev_weeks) - h2h_wins + 1
        med_wins = prev_weeks['median'].sum() + team['median']
        med_loss = len(prev_weeks) -med_wins + 1

    return [h2h_wins, med_wins, h2h_loss, med_loss]

def calc_point_totals(team, season_df):
    roster_id = team['roster_id']
    if season_df.empty:
        pf = team['points']
        pa = team['opp_points']
    else:
        prev_weeks = season_df[season_df['roster_id'] == roster_id]
        pf = prev_weeks['points'].sum() + team['points']
        pa = prev_weeks['opp_points'].sum() + team['opp_points']
    return [pf, pa]

def get_teams(league) -> pd.DataFrame:
    users = league.map_users_to_team_name(league.get_users())
    users = pd.Series(users).to_frame().reset_index()
    users.columns = ['owner_id', 'team_name']
    rosters = pd.DataFrame.from_dict(league.get_rosters())
    users = pd.merge(users, rosters[['owner_id', 'roster_id']].copy(), 
                     'left', on='owner_id')
    return users

def team_from_id(roster_id):
    teams = get_teams(League(constants.LEAGUEID))
    return list(teams[teams['roster_id'] == roster_id]['team_name'])[0]

def name_from_id(roster_id):
    return constants.NAME_MAP[str(roster_id)]
