'''
    Module to calculate schedule related stats
'''
import re
import os
import pandas as pd
import numpy as np
import bestball as bb
import constants as cons
import fantasy_rosters as fr
import html_builder as htmb
import utilities as util
from sleeper_wrapper import League

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
    wk = util.get_last_completed_week()
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
    wk = util.get_last_completed_week()
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
    wk = util.get_last_completed_week()
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
            color = '#CCDDAA'
        elif wins < loss:
            color = '#FFCCCC'
        else: 
            color = "#F1EABE"
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
                styles.loc[idx, col] = 'background-color: #DDDDDD'
    return styles

def style_last_row(row):
    # Apply border-top and border-bottom to all cells in the last row
    return ['border-top: 3px solid black !important; border-bottom: 3px solid black !important;' for _ in row]

def style_last_col(col):
    # Apply border-left and border-right to all cells in the last column
    return ['border-left: 3px solid black !important; border-right: 3px solid black !important;' for _ in col]
    
light_grid_style_data = {
    'selector': 'td',
    'props': [
        ('border', '1px solid black')
    ]
}
light_grid_style_header = {
    'selector': 'th',
    'props': [
        ('border', '1px solid black')
    ]
}

def allSchedulesHTML(df):
    # HTML for All-Play Stats
    styled_df = df.style \
        .set_table_styles([light_grid_style_data, light_grid_style_header], overwrite=False) \
        .apply(highlightActualRecords, axis=None) \
        .apply(style_last_row, axis=1, subset=pd.IndexSlice[df.index[-1]:, :]) \
        .apply(style_last_col, axis=0, subset=pd.IndexSlice[:, df.columns[-1]:])
        
    # Columns are teams, rows are schedules
    return_html = '''
    <h2>Records vs Every Schedule</h2>
    <p>Total column to right is that team's cumulative record
    if they played against every schedule</p>
    <p>Total column on bottom is the cumulative record of everyone if they played
    against your specific schedule.</p>
    <p><strong>Example:</strong>
    <p> Green on right means your team is performing well </p>
    </p> Red on bottom means your schedule has been hard </p>
    '''
    legend_html = """
        <div class="legend-container">
            <div class="legend-item">
                <span class="legend-color-box category-A"></span> Above .500
            </div>
            <div class="legend-item">
                <span class="legend-color-box category-B"></span> Below .500
            </div>
            <div class="legend-item">
                <span class="legend-color-box category-C"></span> .500
            </div>
        </div>
        <style>
            .legend-container {
                display: flex;
                justify-content: space-evenly;
                margin-top: 20px;
                padding: 10px;
                border: 1px solid #ccc;
            }
            .legend-item {
                display: inline-flex;
                align-items: center;
                margin-bottom: 5px;
            }
            .legend-color-box {
                width: 20px;
                height: 20px;
                margin-right: 10px;
                border: 1px solid #000;
            }
            .category-A { background-color: #CCDDAA; }
            .category-B { background-color: #FFCCCC; }
            .category-C { background-color: #F1EABE; }
        </style>
        """
    return_html += legend_html
    return_html += styled_df.to_html()
    return return_html

def highlight_week(col):
    max_w = col.apply(lambda x: int(x.split('-')[0])).max()
    min_w = col.apply(lambda x: int(x.split('-')[0])).min()
    return ['background-color: #c8e6c9' if int(x.split('-')[0]) == max_w
            else 'background-color: #ffcdd2' if int(x.split('-')[0]) == min_w
            else '' for x in col]

#       ****** ALLPLAY ******
def allplay_records(weeks_df, team_lookup):
    records = []

    for week in weeks_df.columns:
        week_scores = weeks_df[week]

        for team in week_scores.index:  # team = roster_id
            team_score = week_scores.loc[team]

            others = week_scores.drop(team)

            wins = (team_score > others).sum()
            losses = (team_score < others).sum()
            ties = (team_score == others).sum()

            records.append({
                'roster_id': team,
                'team_name': team_lookup[team],
                'week': int(week),
                'wins': wins,
                'losses': losses,
                'ties': ties
            })

    return pd.DataFrame(records)

def calc_allplay(df):
    '''
        Calculate record for each week if team's played everyone
    '''
    weeks_df = (
        df.set_index('roster_id')['myScores']
        .apply(pd.Series)
    )
    weeks_df.columns = [f"{i+1}" for i in weeks_df.columns]
    team_lookup = df.set_index('roster_id')['team_name'].to_dict()
    records = allplay_records(weeks_df, team_lookup)
    week = util.get_last_completed_week()
    valid_records = records[records['week'] <= week].copy()
    valid_records['wl'] = valid_records['wins'].astype(str) + "-" + valid_records['losses'].astype(str)
    pivot = valid_records.pivot(
        index='team_name',
        columns='week',
        values='wl'
        )
    pivot.index.name = None
    total_wins = valid_records.groupby('team_name')['wins'].sum()
    total_losses = valid_records.groupby('team_name')['losses'].sum()

    pivot['Total'] = total_wins.astype(str) + "-" + total_losses.astype(str)
    pivot["Win %"] = (total_wins / (total_wins + total_losses)).round(3)
    pivot = pivot.loc[
    total_wins.sort_values(ascending=False).index
    ]
    week_cols = [c for c in pivot.columns if str(c).isdigit() or c.startswith('week_')]

    styled = pivot.style \
        .apply(highlight_week, subset=week_cols) \
        .set_table_attributes('class="sticky-table"')
    styled = styled.format({'Win %': '{:.3f}'})
    return styled

#       ****** SOS ******

# Overall Opponent Winning Percentage [OW%], 
# Add up oppenent win %
# Divide by games
def calcOW(row, dict):
    week = util.get_last_completed_week()
    opp_win = [dict[id-1] for id in row]
    opp_win =  opp_win[:week]
    return sum(opp_win)/len(opp_win)

# Overall Opponent Winning Percentage of Opponent's Opponents[OOW%]
# Add up OW and divide by games 
def calcOOW(row, dict):
    week = util.get_last_completed_week()
    opp_win = [dict[id-1] for id in row]
    opp_win =  opp_win[:week]
    return sum(opp_win)/len(opp_win)
    
# Calculate Strength of Victory
# Average win % of defeated opponents
def calcSOV(row, SOS_dict):
    win_arr = (np.array(row['myScores']) > np.array(row['sched_score'])) 
    opponents = np.array(row['sched'])
    arr = opponents[win_arr]
    sov = [SOS_dict[id-1] for id in arr]
    sov_ret = sum(sov)/len(sov)
    return sov_ret

def SoS(rosters):
    # Calculate Win % of each team
    rosters['Win%'] = rosters['wins'] / (rosters['losses'] + rosters['wins'])
    
    # Calculate overall opponent win %
    # Overall Opponent Winning Percentage [OW%]
    rosters['OW%'] = rosters['sched']
    ow_dict = (rosters[['roster_id', 'Win%']].copy().to_dict())['Win%']
    rosters['OW%'] = rosters['OW%'].apply(lambda row: calcOW(row, ow_dict))

    # Calculate Overall Opponent Winning Percentage of the opponents faced [OOW%]
    rosters['OOW%'] = rosters['sched']
    oow_dict = rosters[['roster_id', 'OW%']].copy().to_dict()['OW%']
    rosters['OOW%'] = rosters['OOW%'].apply(lambda row: calcOOW(row, oow_dict))
    
    # Calculate Strength of Schedule
    # (2 * OW) + OOW divided by 3
    rosters['SOS'] = ((2 * rosters['OW%']) + rosters['OOW%'])/3
    SOS_dict = rosters[['roster_id', 'SOS']].copy().to_dict()['SOS']

    # Calculate Strength of Victory
    # Sum of winning % of defeated opponents
    rosters['SOV'] = rosters.apply(lambda row: calcSOV(row, SOS_dict), axis=1)
    final_df = rosters[['team_name', 'OW%', 'OOW%', 'SOS', 'SOV']].sort_values(by='SOS', ascending=False)
    styler = (
        final_df
        .style
        .hide(axis="index") 
        .format( lambda x: f"{x:.3f}" if isinstance(x, (int, float)) else x) 
        .background_gradient(cmap="RdYlGn", subset=["SOS"]) 
        .background_gradient(cmap="RdYlGn", subset=["SOV"])
        .set_table_attributes('class="sticky-table"'))
    return styler

#       ****** MAIN ******
def schedule_main(update_all):
    # Set up
    html = ''
    yr = util.getYrStr()
    wk = util.get_week()
    checkPath = f'data/rost{yr}_{wk}.json'
    if not os.path.exists(checkPath) or (update_all == True):
       saveSchedules()
    rosters = util.load_df_from_json(checkPath)

    # All Play Standings
    html += '<h2>All-Play Standings</h2>'
    html += '<p>Whole league goes H2H, every week.</p>'
    allplay_styled = calc_allplay(rosters)
    html += allplay_styled.to_html()

    # Strength of Schedule Stats
    sos_df = SoS(rosters)
    html += '<h2>Strength of Schedule & Victory</h2>'
    html += "<p><strong>OW%:</strong> Overall Opponent Winning Percentage - Sum of opponent's winning percentage</p>"
    html += "<p><strong>OOW%:</strong> Overall Winning Percentage of Opponent's Opponents - Sum of each opponent's OW%</p>"
    html += '<p>Sorted by SOS</p>'
    html += sos_df.to_html()

    # All-Play Stats
    allSched_df = dfVsAllSched(rosters)
    #allSched_html = allSchedulesHTML(allSched_df)
    html += allSchedulesHTML(allSched_df)
    lines = html.split("\n")
    # Make first row and column freeze on scroll
    for i, line in enumerate(lines):
        if "<td>" in line:
            line = line.replace("<td>", '<td class="first-col">', 1)
            lines[i] = line
    new_html = "\n".join(lines)
    #html += new_html

    output = htmb.add_front_matter(new_html, 'Schedule Stats')
    with open('./docs/schedule/schedule.html', 'w') as f:
        f.write(output)