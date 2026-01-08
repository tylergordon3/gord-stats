import pandas as pd
import utilities as utils
import constants
from pathlib import Path

def load_stats():
    return pd.read_json(constants.SEASON_PATH)

def roto_week(df, week):
    return

def calc_roto(df):
    return
    
def reg_season_stats():
    season = load_stats()
    regular_season = season[season['week'] < 15]
    roto = calc_roto(regular_season)

reg_season_stats()


