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
import matplotlib.colors as mcolors
from matplotlib.colors import Normalize
import matplotlib.pyplot as plt
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

def calch2h(team):
    me = np.asarray(team['myScores'])
    opp = np.asarray(team['sched_score'])
    res = me > opp
    res = res.astype(int)
    return sum(res)

def saveSchedules():
    yr = util.getYrStr()
    wk = util.get_week()
    week = min(14, wk)
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
    rosters['h2hW'] = rosters.apply(lambda x: calch2h(x), axis=1)
    util.save_df_to_json(rosters, f'data/rost{yr}_{week}.json')

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
    wk = min(14, util.get_last_completed_week())
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

def allPlay_border(col):
    return ['border-left: 3px solid black !important;' for _ in col]

def style_last_col(col):
    # Apply border-left and border-right to all cells in the last column
    return ['font-weight: bold' for _ in col]
    
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
                flex-direction: column;
                padding: 10px;
                width: 100%;
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
    table = styled_df.to_html(index=False, classes='sticky-table')

    table_div = f'''
        {legend_html}
        <div class="table-scroll">
            {table}
        </div>
'''
    html = return_html + table_div
    return html

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
    pivot = pivot.sort_values(by="Win %", ascending=False)
    week_cols = [c for c in pivot.columns if str(c).isdigit() or c.startswith('week_')]

    styled = pivot.style \
        .apply(highlight_week, subset=week_cols) \
        .apply(highlightSpec, subset=['Total']) \
        .apply(allPlay_border, subset=['Total']) \
        .set_table_styles([light_grid_style_data, light_grid_style_header], overwrite=False) \
        .apply(style_last_col, axis=0, subset=pd.IndexSlice[:, pivot.columns[-1]:]) \
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

def calcLuck(row, luck_dict):
    oppsPF = [luck_dict[opp-1] for opp in row['sched']]
    opps_scores = row['sched_score']
    res = 0
    for tot, pts in zip(oppsPF, opps_scores):
        ratio = pts / tot
        res += ratio
    return (res/len(oppsPF))

def calcPythag(row):
    ratio = 2.37
    exp = (row['PF']**ratio)/((row['PF']**ratio) + (row['PA']**ratio))*14
    h2h = row['h2hW']
    val = f'{exp:.1f} ({h2h})'
    return val

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

    # Calculating Scoring Luck
    # % of opponent points scored against you
    # Higher % = Opponents tend to score higher against you compared to normal
    luck_dict = rosters[['roster_id', 'PF']].copy().to_dict()['PF']
    rosters['Scoring Luck'] = rosters.apply(lambda row: calcLuck(row, luck_dict), axis=1)

    rosters['Exp W (Actual)'] = rosters.apply(lambda row: calcPythag(row), axis=1)

    table_style = {
        "selector": "th.col_heading,td",
        "props": [
        ("width", "100px"), # px instead of %
        ("text-align", "center"), # optional ?
    ]}

    def bg_from_pythag_str(series, cmap='RdYlGn'):
        numeric_values = series.str.extract(r'([+-]?[0-9]*[.]?[0-9]+) \(([+-]?[0-9]*[.]?[0-9]+)\)').astype(float).squeeze()
        numeric_values = numeric_values.iloc[:, 1] - numeric_values.loc[:, 0]
        norm = Normalize(vmin=numeric_values.min(), vmax=numeric_values.max())
        cmap = plt.cm.get_cmap(cmap)
        colors = [mcolors.rgb2hex(c) for c in cmap(norm(numeric_values))]
        return ['background-color: %s' % color for color in colors]


    final_df = rosters[['team_name', 'SOS', 'SOV', 'Exp W (Actual)']].sort_values(by='SOS', ascending=False)
    styler = (
        final_df
        .style
        .hide(axis="index") 
        .format( lambda x: f"{x:.3f}" if isinstance(x, (int, float)) else x) 
        .background_gradient(cmap="RdYlGn_r", subset=["SOS"]) 
        .background_gradient(cmap="RdYlGn", subset=["SOV"])
        .apply(bg_from_pythag_str, subset=["Exp W (Actual)"])
        .set_table_styles([light_grid_style_data, light_grid_style_header, table_style], overwrite=False)
        .set_properties(subset=['Exp W (Actual)'], **{'color': 'white'})
        )

    return [rosters, styler]

def standings():
    yr = util.getYrStr()
    wk = util.get_week()
    week = min(14, wk)
    checkPath = f'data/rost{yr}_{week}.json'
    rosters = util.load_df_from_json(checkPath)
    [rosters, _] = SoS(rosters)
    rosters = rosters.sort_values(['wins', 'PF'],ascending=False)
    return rosters[['team_name', 'wins', 'losses', 'PF', 'PA', 'SOS', 'SOV', 'Exp W (Actual)']].copy()

#       ****** MAIN ******
def schedule_main(update_all):
    # Set up
    html = ''
    yr = util.getYrStr()
    wk = util.get_week()
    week = min(14, wk)
    checkPath = f'data/rost{yr}_{week}.json'
    if not os.path.exists(checkPath) or (update_all == True):
       saveSchedules()
    rosters = util.load_df_from_json(checkPath)
    # All Play Standings
    html += '<h2>All-Play Standings</h2>'
    html += '<p>Whole league goes H2H, every week.</p>'
    allplay_styled = calc_allplay(rosters)
    html += '<div class="table-scroll">'
    html += allplay_styled.to_html()
    html += '</div>'

    # Strength of Schedule Stats
    [rosters, sos_df] = SoS(rosters)
    html += '<h2>Strength of Schedule & Victory</h2>'
    html += "<p><strong>SOS:</strong> Strength of Schedule - Difficulty of Schedule (<a href=https://hackastat.eu/en/learn-a-stat-strength-of-schedule-sos/>Learn More</a>)</p>"
    html += "<p><strong>SOV:</strong> Strength of Victory - Combined Win-Loss percentage of defeated opponents</p>"
    html += "<p><strong>Scoring Luck:</strong> Average percentage of an opponent's points scored on you vs their total PF for season.</p>"
    html += f"<p>Luck Example: After week 13, if an opponent scored same amount of points every game, their ratio per game would be 7.69% (~7.69 * 13 = 100)</p>"
    html += f"<p>More Examples: Week 4: 25% | Week 8: 12.5% | Week 12: 8.33% | Week 13: 7.69% | Week 14: 7.14% </p>"
    html += '<p>*Sorted by SOS</p>'
    html += '<div class="table-scroll">'
    html += sos_df.to_html()
    html += '</div>'

    # All-Play Stats
    allSched_df = dfVsAllSched(rosters)
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