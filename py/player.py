'''
    Functions for player data.
'''
import json
from sleeper_wrapper import Players

def player_json():
    players = Players()
    all_players = players.get_all_players(sport="nfl")
    FILENAME = "data/players.json"

    with open(FILENAME, 'w', encoding="utf-8") as f:
        json.dump(all_players, f, indent=4)
players = Players()
all_players = players.get_all_players(sport="nfl")
print(all_players['12518'])