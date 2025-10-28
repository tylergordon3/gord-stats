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
   
    getMondayGames(filter_schedule)
    matchup_dict = league.get_matchups(week)
    matchups = pd.DataFrame(matchup_dict)

    
    
def getMondayGames(filter_schedule_df):
    print(filter_schedule_df)
    print(np.array(filter_schedule_df['team']))

median(league, 8)