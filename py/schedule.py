'''
    Module to calculate schedule related stats
'''
import utilities as util
import constants as cons
import fantasy_rosters as fr
import bestball as bb
import pandas as pd
import numpy as np
import re
import os
from sleeper_wrapper import League
from pretty_html_table import build_table

def getTeamIndex(rosters, roster_id):
    roster_bool = rosters['roster_id'] == roster_id
    index = (np.where(roster_bool))[0][0]
    return index

def getVals(str_list):
    pattern = r"(\d{1,2})-(\d{1,2})"
    wins = 0
    loss = 0
    for record in str_list:
        match = re.search(pattern, record)
        wins += int(match.group(1))
        loss += int(match.group(2))
    return f'{wins}-{loss}'
    
def getIndValues(str):
    pattern = r"(\d{1,2})-(\d{1,2})"
    match = re.search(pattern, str)
    wins = int(match.group(1))
    loss = int(match.group(2))
    return [wins, loss]
    

def saveSchedules():
    yr = util.getYrStr()
    wk = util.get_week()
    league = League(cons.LEAGUEID)
    rosters = fr.get(league)
    rosters['sched'] = [[] for _ in range(len(rosters))]
    # Playoffs begin week 15
    for week in range(1,15):
        matchup_df = pd.DataFrame.from_dict(league.get_matchups(week))
        matchups = bb.getMatchups(matchup_df)
        for teamA, teamB in matchups:
            indexA = getTeamIndex(rosters, teamA)
            rosters.loc[indexA,:]['sched'].append(teamB)
            indexB = getTeamIndex(rosters, teamB)
            rosters.loc[indexB,:]['sched'].append(teamA)
    rosters = schedScores(rosters)
    rosters['myScores'] = rosters.apply(lambda x: np.repeat(x['roster_id'], 14), axis=1)
    rosters['myScores'] = rosters['myScores'].apply(lambda x: getScoreArr(x))
    rosters['wins_vs'] = rosters.apply(lambda x: recordsVsAll(rosters, x), axis=1)
    rosters['total'] = rosters['wins_vs'].apply(lambda x: getVals(x))
    util.save_df_to_json(rosters, f'data/rost{yr}_{wk}.json')
    
def getScore(roster_id, week):
    league = League(cons.LEAGUEID)
    matchup_df = pd.DataFrame.from_dict(league.get_matchups(week+1))
    score = list(matchup_df[matchup_df['roster_id'] == roster_id]['points'])[0]
    return score

def getScoreArr(team):
    scores = [getScore(id, index) for index, id in enumerate(team)]
    return scores

def schedScores(rosters):
    rosters['sched_score'] = rosters['sched'].apply(lambda x: getScoreArr(x))
    return rosters

def recordsVsAll(all, team):
    # For current team, calculate wins vs each schedule
    curr_team = team['myScores']
    wins_vs_each_arr = all['sched_score'].apply(lambda opp: recordVsHelper(curr_team, opp))
    return list(wins_vs_each_arr)

def recordVsHelper(team_scores, opp_scores):
    wk = util.get_week()
    # For current team calculate wins vs 1 opponents schedule
    np_team = np.array(team_scores[:wk], dtype='float32')
    
    np_opp= np.array(opp_scores[:wk], dtype='float32')
    same = (np_team != np_opp)
    diff1 = np_team[same]
    diff2 = np_opp[same]
    bool_arr = (diff1 > diff2)
    wins = bool_arr.sum()
    loss = len(diff1) - wins
    return f'{wins}-{loss}'

def dfVsAllSched(rosters):
    yr = util.getYrStr()
    wk = util.get_week()
    rosters = util.load_df_from_json(f'data/rost{yr}_{wk}.json')
    all_results = {}
    for index, row in rosters.iterrows():
        # index, value in enumerate(my_array)
        arr = {}
        total = row['total']
        for idx, val in enumerate(row['wins_vs']):
            name = rosters[rosters['roster_id'] == idx+1]['team_name']
            arr[list(name)[0]] = val
        arr['Team Total Record'] = total
        all_results[row['roster_id']] = arr
    all_df = pd.DataFrame.from_dict(all_results, orient='index')
    dict = fr.mapNameToId(rosters)
    df = all_df.rename(index = dict)
    to_add ={}
    total_row = df.apply(lambda x: getVals(x))
    to_add['Totals'] = total_row
    add_df = pd.DataFrame(total_row)
    add_df = add_df.rename(columns={0 : "Schedule Total"})
    return pd.concat([df, add_df.T])

def highlightSpec(styles):
    def getColor(val):
        [wins, loss] = getIndValues(val)
        if wins > loss:
            color = '#648fff'
        elif wins < loss:
            color = '#dc267f'
        else: 
            color = '#ffb000'
        return f'background-color: {color}'
    ret = map(getColor, list(styles))
    return list(ret)

def highlightActualRecords(df):
    # each row
    styles = pd.DataFrame('', index=df.index, columns=df.columns)
    styles = df.apply(lambda x: highlightSpec(x))
    
    for idx in df.index:
        for col in df.columns:
            if idx == col:
                styles.loc[idx, col] = 'background-color: lightgray'
            elif (idx == 'Schedule Total') & (col == 'Team Total Record'):
                styles.loc[idx, col] = 'background-color: lightgray'
    return styles

def Sos():
    return
    
def main():
    update = False
    yr = util.getYrStr()
    wk = util.get_week()
    checkPath = f'data/rost{yr}_{wk}.json'
    if not os.path.exists(checkPath) or (update == True):
       saveSchedules()
    rosters = util.load_df_from_json(checkPath)
    df = dfVsAllSched(rosters)
    styled_df = df.style \
        .apply(highlightActualRecords, axis=None) \
        .set_table_styles([
        {"selector": "", "props": [("border", "1px solid black")]},  # Entire table border
        {"selector": "tbody td", "props": [("border", "1px solid black")]}, # Borders for data cells
        {"selector": "th", "props": [("border", "1px solid black")]} # Borders for header cells
        ])

    ## Columns are teams, rows are schedules
    html = '''
    <h2>Records vs Every Schedule</h2>
    <p>Columns represent a team's schedule</p>
    <p>Rows represent a team's record against each schedule</p>
    '''
    html += styled_df.to_html()

    # Save to html file
    with open('./docs/schedule/allSchedules.html', 'w') as f:
        f.write(html)
main()