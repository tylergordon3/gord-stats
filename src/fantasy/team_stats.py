"""
    Calculates fantasy stats for NFL teams each year. Currently just schedule adjusted values.
"""

from fantasy.config import LEAGUE_IDS, TEAMS

import pandas as pd
import polars as pl
import nflreadpy as nfl
import fantasy.stats as stats

SEASONS = list(LEAGUE_IDS)

#print(szn[(szn["week"] == 3) & (szn["team"] == "CLE")])

"""
    End Goal: Df that contains  Team, Season, Week and points given up 
    to each position
"""

def _nfl_schedule(season) -> pd.DataFrame:
    sched = nfl.load_schedules(season)
    df = sched[['season', 'week', 'home_team', 'away_team']].to_pandas()
    df['teams'] = pd.concat([df['home_team'], df['away_team']], axis=1).values.tolist()
    print(df)

def _season_schedule_adjusted(season=None) -> pd.DataFrame:
    szn = stats.player_points(season) 
    games = _nfl_schedule(season)
    
    # week,  home_team, away_team
    
def _schedule_adjusted() -> pd.DataFrame:
    # add other seasons when working
    season = nfl.get_current_season()
    df = _season_schedule_adjusted(season)

_schedule_adjusted()