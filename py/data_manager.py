import injuries
import nflreadpy as nfl
import utilities as utils
from pathlib import Path

SEASON_STR = utils.getYrStr()
SEASON = nfl.get_current_season()

def main():
    # Gets regular season week for current season
    # Max is 18- last week of regular season
    # Note: Fantasy regular season goes to week 14
    curr_overall_week = utils.get_last_completed_week()
    
    data_path = utils.get_project_root() / Path("data")
    inj_path = data_path / Path("injuries") 

    injury_df = injuries.scrape_injuries_all(SEASON, 1, curr_overall_week)
    injury_df = injury_df.reset_index(drop=True)
    injury_df.to_json(f'{inj_path}/{SEASON_STR}.json')

main()