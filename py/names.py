import json
import pandas as pd
import nflreadpy as nfl

with open('data/players.json', 'r', encoding='utf-8') as file:
    data = json.load(file)
    sleeper_db = pd.DataFrame.from_dict(data, orient='index')

print(sleeper_db.columns)
