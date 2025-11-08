import nflreadpy as nfl
from sleeper_wrapper import League
from tabulate import tabulate
import constants as c
import pandas as pd
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
    #printable = combined[["team_name", "to_play_monday"]].copy()
    #print(tabulate(printable, headers='keys', tablefmt='psql'))
    matchup_df['to_play_monday'] = combined['to_play_monday']
    matchup_df['team'] = combined['team_name']
    matchup_df['max_pts'] = matchup_df['to_play_monday'].apply(lambda x: getHypotheticalMaxPts(x, weeks_players))
    matchup_df['max_pts'] = matchup_df['max_pts'] + matchup_df['points']
    prep_for_median = ruleOutAlreadySet(matchup_df)
    #print(prep_for_median)
    calculate(prep_for_median)
    #print(calculated)

def calculate(input_df):
    df = input_df
    see_above = []
    df.apply(lambda row: printSetup(row, df, see_above), axis=1)
    print('--------------------------------------------------------------------------------------------------')
    print('See above for points needed: ')
    for item in see_above:
        print(item)
    return

def printSetup(row, df, see_above):
    if ((row['status'] == "L") | (row['status'] == "W")):
        print(row['team'], "has:", row["status"], "vs the median.")
    elif (row['rank'] > 5):
        see_above.append(row['team'])
        return 
    else:
        check = df[(df["status"] == "tbd") & (df['rank'] > row['rank'])]
        printMedianScenarios(row, check)

def printMedianScenarios(currTeam, df):
    toLoseMedian = 6-currTeam['rank']
    print(currTeam['team'], 'loses median if', int(toLoseMedian), '/', len(df), 'pass.')
    for team in df.itertuples(index=True):
        diff = round(currTeam['points'] - team.points, 2)
        if currTeam['num_to_play'] > 0:
            print(team.team,':', ', '.join(team.to_play_monday),'outscore(s)',', '.join(currTeam['to_play_monday']),'by',diff)
        else:
            print(team.team,":", ', '.join(team.to_play_monday),'scores',diff)
    print('--------------------------------------------------------------------------------------------------')

def getHypotheticalMaxPts(row, weeks_players):
    positions = weeks_players[weeks_players['cleaned_name'].isin(row)]['position']
    max_pts = 0
    for player in positions:
        max_pts = max_pts + c.MAX.get(player)
    return max_pts

def ruleOutAlreadySet(matchup_df):
    curr_points = matchup_df[['roster_id', 'matchup_id', 'team', 'points', 'to_play_monday', 'max_pts']]
    df = curr_points.sort_values(by='points', ascending=False)
    df['rank'] = df['points'].rank(ascending=False)
    df['num_to_play'] = df['to_play_monday'].apply(lambda row: len(row))
    median = list(df[df['rank'] == 5]['points'])
    df['status'] = df.apply(lambda team: "L" if (team['max_pts'] < median[0]) else "tbd", axis=1)
    df['status'] = df.apply(lambda team: setWinners(team, df), axis=1)
    return df

def setWinners(team, df):
    rank = team['rank']
    if rank > 5:
        return team['status']
    search = df[(df['rank'] > rank) & ((df['num_to_play'] == 0) | (df['status'] == "L"))]
    num_above = search.shape[0]
    if ((9-num_above) < (6-rank)):
        return "W"
    elif (team['num_to_play'] == 0):
        return
    else: 
        return team['status']

def getMondayPlayers(starters, weeks_players):
    starters_series = pd.Series(starters)
    monday = starters_series[(starters_series.isin(weeks_players['sleeper_id'])) | (starters_series.isin(weeks_players['team']))]
    monday_names = weeks_players[(weeks_players['sleeper_id'].isin(monday)) | (weeks_players['cleaned_name'].isin(monday))]['cleaned_name']
    #return {A: B for A, B in zip(monday, monday_names)}
    return list(monday_names)

def getMondayGames(week):
    schedule = nfl.load_schedules(nfl.get_current_season())
    monday_df = schedule.filter((schedule['weekday'] == "Monday") & (schedule['week'] == week))
    monday_teams = monday_df['home_team'].to_list() + monday_df['away_team'].to_list()
    return monday_teams

median(league, 8)

