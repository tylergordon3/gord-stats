import json
import utilities as utils
from pathlib import Path

import league_data

ARCHIVE_PATH= utils.get_project_root() / Path("data") / Path("historical.json")

def _open():
    with open(ARCHIVE_PATH, 'r') as file:
            data_dict = json.load(file)
    return data_dict

def _save(dict):
    with open(ARCHIVE_PATH, 'w') as json_file:
        json.dump(dict, json_file, indent=4)

def save_statistic(season, stat, value):
    archive = _open()
    key = league_data.get_formal_season(season)
    try:
        current = archive[key]
    except:
        current = {}
    current[stat] = value
    archive[key] = current
    _save(archive)
