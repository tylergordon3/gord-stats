'''
    Module that retrieves Sleeper player data and saves to a JSON file.
'''
import json
from sleeper_wrapper import Players

players = Players()
all_players = players.get_all_players(sport="nfl")
FILENAME = "players.json"

with open(FILENAME, 'w', encoding="utf-8") as f:
    json.dump(all_players, f, indent=4)

print(f"Data successfully saved to {FILENAME}")
