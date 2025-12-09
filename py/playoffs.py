from sleeper_wrapper import League
import constants as c
import pandas as pd
import utilities as util

league = League(c.LEAGUEID)
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
    wk = util.get_last_completed_week()
    yr = util.getYrStr()
    path = f'data/rost{yr}_{wk}.json'
    rosters = util.load_df_from_json(path)
    df['names'] = df.apply(lambda x: (list(rosters[rosters['roster_id'] == x.t2].team_name)), axis=1 )
    print(df['names'])
format()