import injuries
import player
import league_data as league_data
import nflreadpy as nfl
import utilities as utils
from pathlib import Path

SEASON_STR = '2425'#utils.getYrStr()
SEASON = 2024 #nfl.get_current_season()

def main():
    # Gets regular season week for current season
    # Max is 18- last week of regular season
    # Note: Fantasy regular season goes to week 14
    curr_overall_week = utils.get_last_completed_week()
    
    player.player_json()

    data_path = utils.get_project_root() / Path("data")
    inj_path = data_path / Path("injuries") / Path(f'{SEASON_STR}.json')
    if (inj_path.exists() == False) | (curr_overall_week < 18):
        injury_df = injuries.scrape_injuries_all(SEASON, 1, curr_overall_week)
        injury_df = injury_df.reset_index(drop=True)
        injury_df.to_json(inj_path)

    season_path = data_path / Path("season")
    szn_data = league_data.get_season(utils.get_last_completed_week())
    szn_data = szn_data.reset_index(drop=True)
    szn_data.to_json(f'{season_path}/{SEASON_STR}.json')