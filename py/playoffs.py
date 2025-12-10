from sleeper_wrapper import League
import constants as c
import pandas as pd
import utilities as util

league = League(c.LEAGUEID)

css = '''
 <div class="playoff-container">
    <div class="round-container">
      <h3 class="inner-text">Round 1</h3>
      <div class="playoff-matchup">
        <p class="inner-text">Matchup 1</p>
      </div>
      <div class="playoff-space">
        <p class="inner-text">&nbsp;</p>
      </div>
      <div class="playoff-space">
        <p class="inner-text">&nbsp;</p>
      </div>
      <div class="playoff-space">
        <p class="inner-text">&nbsp;</p>
      </div>
      <div class="playoff-matchup">
        <p class="inner-text">Matchup 2</p>
      </div>
      <div class="playoff-space">
        <p class="inner-text">&nbsp;</p>
      </div>
      <div class="playoff-space">
        <p class="inner-text">&nbsp;</p>
      </div>
    </div>
    <div class="round-container">
      <h3 class="inner-text">Round 2</h3>
      <div class="playoff-space">
        <p class="inner-text">&nbsp;</p>
      </div>
      <div class="playoff-matchup">
        <p class="inner-text">Matchup 3</p>
      </div>
      <div class="playoff-space"></div>
      <div class="playoff-matchup">
        <p class="inner-text">Matchup 4</p>
      </div>
      <div class="playoff-space">
        <p class="inner-text">&nbsp;</p>
      </div>
      <div class="playoff-space">
        <p class="inner-text">&nbsp;</p>
      </div>
      <div class="playoff-matchup">
        <p class="inner-text">Matchup 5</p>
      </div>
    </div>
    <div class="round-container">
      <h3 class="inner-text">Round 3</h3>
      <div class="playoff-space">
        <p class="inner-text">&nbsp;</p>
      </div>
      <div class="playoff-space">
        <p class="inner-text">&nbsp;</p>
      </div>
      <div class="playoff-matchup">
        <p class="inner-text">Matchup 6</p>
      </div>
      <div class="playoff-space">
        <p class="inner-text">&nbsp;</p>
      </div>
      <div class="playoff-space">
        <p class="inner-text">&nbsp;</p>
      </div>
      <div class="playoff-space">
        <p class="inner-text">&nbsp;</p>
      </div>
      <div class="playoff-matchup">
        <p class="inner-text">Matchup 7</p>
      </div>
    </div>
  </div>
'''
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
        r1      r2      r3      Container for round                                          
    1   m1      -       -           - Divs                                                          
    2   -       m3      -               - Div for 'empty' - aka just blank for structure                
    3   -       -       m6              - Div for matchups                                         
    4   -       m4      -                   - one div for each team                                 
    5   m2      -       -                       - Seed? Name, current score                          
    6   -       m5      m7
    '''
    print(df)



format()