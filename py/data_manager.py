from pathlib import Path
import utilities as utils
import constants as cons

SEASON_STR = utils.getYrStr()

def main():
    # Gets regular season week for current season
    # Max is 14 - last week of fantasy regular season
    curr_overall_week = utils.get_last_completed_week()
    reg_season_week = min(curr_overall_week, 14)
    
    data_path = utils.get_project_root() / Path("data")
    inj_path = data_path / Path("injuries") / Path(SEASON_STR)

    inj_path.mkdir(parents=True, exist_ok=True)
    
    

main()