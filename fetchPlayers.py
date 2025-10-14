from sleeper_wrapper import Players
import json

players = Players()
all_players = players.get_all_players(sport="nfl")
filename = "players.json"

with open(filename, 'w') as f:
    json.dump(all_players, f, indent=4)

print(f"Data successfully saved to {filename}")