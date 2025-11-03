import nflreadpy as nfl
from sleeper_wrapper import League
import constants as c
import numpy as np
import pandas as pd
import nfl_stats as stats

league = League(c.LEAGUEID)

def median(league, week):
    nfl_schedule = nfl.load_team_stats(nfl.get_current_season(), 'week')
    schedule_df = nfl_schedule.to_pandas()
    filter_schedule = schedule_df[schedule_df['week'] == week]
   
    monday_arr = getMondayGames(filter_schedule, week)
    matchup_dict = league.get_matchups(week)
    matchups = pd.DataFrame(matchup_dict)
    print('MONDAY: ', monday_arr)
    print(matchups)
    
    
def getMondayGames(filter_schedule_df, week):
    on_bye = c.BYES.get(week)
    monday_game = [item for item in c.TEAMS if (item not in on_bye) & (item not in np.array(filter_schedule_df['team']))]
    return monday_game

median(league, 9)