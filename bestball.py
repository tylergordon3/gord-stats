import nflreadpy as nfl
from sleeper_wrapper import League
import constants as c
import player_db as db
import fantasy_rosters as fr
import player_db as pdb
import numpy as np
import pandas as pd
import player as p

league = League(c.LEAGUEID)
rosters = fr.get(league)


def bestball(week):
    matchup_df = pd.DataFrame.from_dict(league.get_matchups(week))
    db = pdb.get(week)
    df = matchup_df[['roster_id', 'players_points', 'matchup_id']]
    week_results = []
    for roster_id in df['roster_id']:
        team = df[df.roster_id == roster_id]
        key = roster_id - 1
        ps = team.players_points.get(key)
        raw_df = pd.DataFrame(ps.items())
        raw_df.columns = ['id', 'points']
        valid_df = createDataframe(raw_df, db)
        best_df = findBestball(valid_df)
        rosters = fr.get(league)
        this_team = rosters[rosters['roster_id'] == roster_id]
        print(list(this_team['team_name'])[0], '\n', best_df)
        week_results.append({list(this_team['team_name'])[0] : best_df})
    return week_results

def createDataframe(df,db):
    df['obj'] = df['id'].apply(lambda x: pdb.getFromID(x, db))
    df['name'] = df['obj'].apply(lambda y: y.cleaned_name.item() if not y.cleaned_name.empty else "err")
    df['position'] = df['obj'].apply(lambda y: y.position.item() if not y.position.empty else "err")
    valididated_df = df[(df['name'] != "err") | (df['id'].isin(c.TEAMS))]
    valididated_df = valididated_df.drop(columns=['obj'])
    return valididated_df

def findBestball(df):
    lineup = { "QB"   : 1,
               "RB"   : 2,
               "WR"   : 2,
               "TE"   : 1,
               "FLEX" : 2,
               "DEF"  : 1,
               "K"    : 1}
    bestball = pd.DataFrame()
    for pos, amt in lineup.items():
        if pos == 'FLEX':
            pos_df = df[df['position'].isin(["RB", "TE", "WR"])]
        else:
            pos_df = df[df['position'] == pos]
        pos_df = pos_df.sort_values(by='points', ascending=False)
        bestball = pd.concat([bestball, pos_df.iloc[0:amt]])
        df = df.drop(pos_df.iloc[0:amt].index)

    return bestball

week = bestball(10)
print(week)

