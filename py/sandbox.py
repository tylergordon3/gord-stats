
import utils
import os
import pandas as pd
import scraper


orig = pd.read_json(utils.get_path('data/teams/master copy.json'))
new = pd.read_json(utils.get_path('data/teams/master.json'))

diff = new['team'].compare(orig['team'])

print(diff.to_string())