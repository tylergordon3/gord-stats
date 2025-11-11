from sleeper_wrapper import League
import datetime
import constants as c
import pandas as pd
import fantasy_rosters as fr
import player_db as pdb

league = League(c.LEAGUEID)

def median(league, week):
    # Get starters for week
    matchup_df = pd.DataFrame.from_dict(league.get_matchups(week))
    starters = matchup_df[['roster_id', 'matchup_id', 'starters']].copy()

    # Get players for week and season as a whole
    weeks_players = pdb.get(week)
    db = pdb.get(0)

    # Add df column for players who have not played yet this week
    starters['to_play'] = starters['starters'].apply(lambda x: getToPlay(x, weeks_players, db))

    # Combine this week matchups with league info
    rosters = fr.get(league)
    combined = pd.merge(starters, rosters, on='roster_id')

    # Add colmns back to original matchup df
    matchup_df['to_play'] = combined['to_play']
    matchup_df['team'] = combined['team_name']

    # Calculate hypothetical max points for each team
    matchup_df['max_pts'] = matchup_df['to_play'].apply(lambda x: getHypotheticalMaxPts(x, db))
    matchup_df['max_pts'] = matchup_df['max_pts'] + matchup_df['points']

    # Remove teams already locked in above or below median 
    prep_for_median = ruleOutAlreadySet(matchup_df)
 
    # If week has not occured return string otherwise output to html for webpage
    if prep_for_median.empty: 
        save_to_html("No median yet!")
    else:
        consoleOutput(prep_for_median)
        save_to_html(input)

def getHypotheticalMaxPts(row, db):
    # Get position for each player still to play
    players = db[db['cleaned_name'].isin(row)]
    names = pd.unique(players['cleaned_name'])
    positions = []
    for x in names:
        common = players[players.cleaned_name == x]['position'].mode()
        positions.append(common)

    # Calulcate max points for each player let
    # Uses highest points at position record since 2020
    max_pts = 0
    for player in positions:
       max_pts = max_pts + c.MAX.get(list(player)[0])
    return max_pts

def ruleOutAlreadySet(matchup_df):
    # Pull out values, sort by current score 
    curr_points = matchup_df[['roster_id', 'matchup_id', 'team', 'points', 'to_play', 'max_pts']]
    df = curr_points.sort_values(by='points', ascending=False)
    df['rank'] = df['points'].rank(ascending=False)

    # Find # of players left to play from length of names array
    df['num_to_play'] = df['to_play'].apply(lambda row: len(row))

    # Get current median or 5th place team
    median = list(df[df['rank'] == 5]['points'])

    # Calculate teams locked below median and then teams locked above median
    if len(median) != 0:
        df['status'] = df.apply(lambda team: "L" if (team['max_pts'] < median[0]) else "tbd", axis=1)
        df['status'] = df.apply(lambda team: setWinners(team, df), axis=1)
        return df
    else:
        return pd.DataFrame()

def setWinners(team, df):
    # If team below median, return calculated status already
    rank = team['rank']
    if rank > 5:
        return team['status']
    
    # Searching for teams we have already beaten for certain
    # Criteria - lower rank than us, with no players left 
    #           or max points already deemed lower than median
    search = df[(df['rank'] > rank) & ((df['num_to_play'] == 0) | (df['status'] == "L"))]

    # Locked Above - # of teams you are certain to beat
    # Ex. Rank 5 on week, out of teams rank 6-10, 2 have no players left
    #     and 1 has max points below median. You would have a locked
    #     above value of 3 (out of 4)
    locked_above = search.shape[0]

    # Magic Number - # of teams needed to beat your score to lose median
    # Ex. Rank 1 on week - 6-1 = 5, 5 teams needed to beat you to lose median
    magic_num = 6-rank

    # Logic for determining Ws
    # Ex. Our team at rank 2, magic number is 4 - lose median if 4 teams pass our team.
    #     We search teams at rank 3-10 (8 teams) to find teams we are locked above.
    #     We find we are locked above 5 teams. These teams have no players left for week. 
    #     3 teams still have players left and could pass our team. 
    #     Since 3 < 4, we are locked above median, if all 3 teams pass us, we will still 
    #     end up in 5th place.
    if ((10-rank-locked_above) < magic_num):
        return "W"
    elif (team['num_to_play'] == 0):
        return
    else: 
        return team['status']

def getToPlay(starters, weeks_players, db):
    # Grab team's starters as a series
    starters_series = pd.Series(starters)
    
    # Filter out players who have already played this week
    to_play = starters_series[~(starters_series.isin(weeks_players['sleeper_id']))]
    to_play_names = db[(db['sleeper_id'].isin(to_play))]['cleaned_name']

    # Return names of players who haven't played
    names = pd.unique(to_play_names)
    return list(names)

# ------ Functions for printing to console and HTML formatting --------
def save_to_html(input):
    if not isinstance(input, pd.DataFrame):
        return input
    table = input.drop(columns=["roster_id","matchup_id","status","rank","num_to_play"]).to_html()
    return input

def consoleOutput(input_df):
    df = input_df
    time = datetime.datetime.now()
    print(time.strftime("As of: %m/%d/%y %I:%M %p"))
    see_above = []
    df.apply(lambda row: doConsoleOutput(row, df, see_above), axis=1)
    print('--------------------------------------------------------------------------------------------------')
    print('See above for points needed: ')
    for item in see_above:
        print(item)
    return

def doConsoleOutput(row, df, see_above):
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


median(league, 10)

