from sleeper_wrapper import League
import constants as c
import pandas as pd
import utilities as util

league = League(c.LEAGUEID)

def playoff_stats(df): 
    # Get most recent roster info
    wk = util.get_last_completed_week()
    yr = util.getYrStr()
    path = f'data/rost{yr}_{wk}.json'
    rosters = util.load_df_from_json(path)

    # Update df 
    df['t1_name'] = df.apply(lambda x: (list(rosters[rosters['roster_id'] == x.t1].team_name))[0] \
                                if len((list(rosters[rosters['roster_id'] == x.t1].team_name))) > 0 \
                                else None, axis=1 )
    df['t2_name'] = df.apply(lambda x: (list(rosters[rosters['roster_id'] == x.t2].team_name))[0] \
                                if len((list(rosters[rosters['roster_id'] == x.t2].team_name))) > 0 \
                                else None, axis=1 )

    df['t1_pts'] = df.apply(lambda x: (list(rosters[rosters['roster_id'] == x.t1].myScores))[0][x.r + 13] \
                               if len((list(rosters[rosters['roster_id'] == x.t1].myScores))) > 0 \
                                else None, axis=1 )

    df['t2_pts'] = df.apply(lambda x: (list(rosters[rosters['roster_id'] == x.t2].myScores))[0][x.r + 13] \
                               if len((list(rosters[rosters['roster_id'] == x.t2].myScores))) > 0 \
                            else None, axis=1 )
    return df

def format():
    # r       [int]    Round
    # m       [int]    Match ID - unique for all matchups
    # t1      [int]    Roster ID of team in matchup
    #                       or {w: 1}, winner of match 1
    # t2      [int]    Roster ID of other team in matchup
    #                       or {l: 1} loser of match 1
    # w       [int]    roster id of winning team (if played)
    # l       [int]    roster id of losing team (if played)
    # p       [int]    Placement of winner if applicable
    # t1_from [object] Where t1 comes from winner or loser of match id
    # t2_from [object] Where t2 comes from winner or loser of match id               
    playoff_win_list = league.get_playoff_winners_bracket()
    df = pd.DataFrame(columns=['r', 'm', 't1', 't2', 'w', 'l', 'p', 't1_from', 't2_from'])
    for match in playoff_win_list:
        # df.loc[len(df)] = new_row
        df.loc[len(df)] = match
   
    df = playoff_stats(df)
    '''
        r1      r2      r3
    1   m1      -       -
    2   -       m3      -
    3   -       -       m6
    4   -       m4      - 
    5   m2      -       -
    6   -       m5      m7
    '''
    print(df)



format()