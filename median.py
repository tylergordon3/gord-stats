import nflreadpy as nfl
from sleeper_wrapper import League
from tabulate import tabulate
import constants as c
import numpy as np
import pandas as pd
import nfl_stats as stats
import fantasy_rosters as fr
import player_db as pdb

league = League(c.LEAGUEID)

def median(league, week):
    monday_teams = getMondayGames(week)
    matchup_df = pd.DataFrame.from_dict(league.get_matchups(week))
    
    starters = matchup_df[['roster_id', 'matchup_id', 'starters']].copy()
    all_players = pdb.get(week)
    weeks_players = all_players[all_players['team'].isin(monday_teams)]
    starters['to_play_monday'] = starters['starters'].apply(lambda x: getMondayPlayers(x, weeks_players))
    rosters = fr.get(league)
    combined = pd.merge(starters, rosters, on='roster_id')
    printable = combined[["team_name", "to_play_monday"]].copy()
    print(tabulate(printable, headers='keys', tablefmt='psql'))
    matchup_df['to_play_monday'] = combined['to_play_monday']
    matchup_df['team'] = combined['team_name']
    matchup_df['max_pts'] = matchup_df['to_play_monday'].apply(lambda x: getPositions(x, weeks_players))
    median_calc = getMedianCalcs(matchup_df)

def getPositions(row, weeks_players):
    positions = weeks_players[weeks_players['cleaned_name'].isin(row)]['position']
    max_pts = 0
    for player in positions:
        max_pts = max_pts + c.MAX.get(player)
    return max_pts

def getMedianCalcs(matchup_df):
    curr_points = matchup_df[['roster_id', 'matchup_id', 'team', 'points', 'to_play_monday', 'max_pts']]
    df = curr_points.sort_values(by='points', ascending=False)
    df['rank'] = df['points'].rank(ascending=False)
    df['num_to_play'] = df['to_play_monday'].apply(lambda row: len(row))
    num_left = df['num_to_play'].value_counts().get(0, 0)
    median = df[df['rank'] == 5]['points']
    df['status'] = df.apply(lambda x: getStatus(x, num_left, list(median)), axis=1)
    print(df)

def getStatus(row, num_left, median):
    if (row['num_to_play'] == 0):
        num_left = num_left - 1
   
    if (row['rank'] > 5):
        if ((row['points'] + row['max_pts']) < median[0]):
            return "LOCK_BELOW"
    #   if (row['num_to_play'] == 0):
    #        return "LOCK_BELOW"
    
    elif ((6-row['rank']) > num_left):
       return "LOCK_ABOVE"
    

def getMondayPlayers(starters, weeks_players):
    starters_series = pd.Series(starters)
    monday = starters_series[starters_series.isin(weeks_players['sleeper_id'])]
    monday_names = weeks_players[weeks_players['sleeper_id'].isin(monday)]['cleaned_name']
    #return {A: B for A, B in zip(monday, monday_names)}
    return list(monday_names)

def getMondayGames(week):
    schedule = nfl.load_schedules(nfl.get_current_season())
    monday_df = schedule.filter((schedule['weekday'] == "Monday") & (schedule['week'] == week))
    monday_teams = monday_df['home_team'].to_list() + monday_df['away_team'].to_list()
    return monday_teams

median(league, 9)

