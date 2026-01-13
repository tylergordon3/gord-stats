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
import schedule_stats

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

#       ****** MAIN ******
def schedule_main():
    # Set up
    html = ''
    wk = util.get_week()
    # All Play Standings
    html += '<h2>All-Play Standings</h2>'
    html += '<p>Whole league goes H2H, every week.</p>'
    html += '<div class="table-scroll">'
    html += schedule_stats.calc_roto().to_html()
    html += '</div>'

    html += '<h2>Strength of Schedule & Victory</h2>'
    html += "<p><strong>SOS:</strong> Strength of Schedule - Difficulty of Schedule (<a href=https://hackastat.eu/en/learn-a-stat-strength-of-schedule-sos/>Learn More</a>)</p>"
    html += "<p><strong>SOV:</strong> Strength of Victory - Combined Win-Loss percentage of defeated opponents</p>"
    html += "<p><strong>SOV:</strong> Expected Wins (vs Actual), used Pythagorean Expectation to estimate wins based on PF and PA</p>"
    html += '<p>*Sorted by SOS</p>'
    html += '<div class="table-scroll">'
    html += schedule_stats.schedule_metrics().to_html()
    html += '</div>'

    # All-Play Stats
    html += '<h2>Records vs Every Schedule</h2>'
    html += '<div class="table-scroll">'
    html += schedule_stats.schedule_compare().to_html(index=False, classes='sticky-table')
    html += '</div>'
    lines = html.split("\n")
    # Make first row and column freeze on scroll
    for i, line in enumerate(lines):
        if "<td>" in line:
            line = line.replace("<td>", '<td class="first-col">', 1)
            lines[i] = line
    new_html = "\n".join(lines)

    output = htmb.add_front_matter(new_html, 'Schedule Stats')
    with open('./docs/schedule/schedule.html', 'w') as f:
        f.write(output)