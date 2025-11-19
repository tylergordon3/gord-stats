'''
    Module to calculate schedule related stats
'''
import utilities as util
import constants as cons
import fantasy_rosters as fr
import bestball as bb
import pandas as pd
import numpy as np
import os
from sleeper_wrapper import League

def getTeamIndex(rosters, roster_id):
    roster_bool = rosters['roster_id'] == roster_id
    index = (np.where(roster_bool))[0][0]
    return index

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

def Sos():
    yr = util.getYrStr()
    wk = util.get_week()
    checkPath = f'data/rost{yr}_{wk}.json'
    if not os.path.exists(checkPath):
       saveSchedules()
    rosters = util.load_df_from_json(checkPath)

league = League(cons.LEAGUEID)
Sos()
