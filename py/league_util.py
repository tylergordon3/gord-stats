
def find_opponents(team, week_df):
    this_id = team['matchup_id']
    this_roster = team['roster_id']
    this_score = team['points']
    opponents = week_df[(week_df['matchup_id'] == this_id) &
                        (week_df['roster_id'] != this_roster)]

    opp = list(opponents['roster_id'])[0]
    opp_score = list(opponents['points'])[0]
    
    if opp_score > this_score:
        h2h_win = 0
    else:
        h2h_win = 1

    return [opp, h2h_win]

def calc_totals(team, season_df):
    
    if season_df.empty:
        h2h_wins = team['win']
        med_wins = team['median']
        h2h_loss = 1 if h2h_wins == 0 else 0
        med_loss = 1 if med_wins == 0 else 0
        return [h2h_wins, med_wins, h2h_loss, med_loss]
    
    roster_id = team['roster_id']
    prev_weeks = season_df[season_df['roster_id'] == roster_id]
    if team['week'] > 14:
        h2h_wins = prev_weeks['win'].sum() + team['win']
        h2h_loss = len(prev_weeks) - h2h_wins + 1
        med_wins = prev_weeks['median'].sum()
        med_loss = len(prev_weeks)
    else:
        h2h_wins = prev_weeks['win'].sum() + team['win']
        h2h_loss = len(prev_weeks) - h2h_wins + 1
        med_wins = prev_weeks['median'].sum()
        med_loss = len(prev_weeks)

    return [h2h_wins, med_wins, h2h_loss, med_loss]