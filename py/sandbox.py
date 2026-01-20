
import utils
import os
import pandas as pd
import scraper

master = pd.read_json(utils.get_path("data/teams/master_new.json"))


#master['short'] = ''
# df.loc[row, col]
team = "Southern Indiana"
short = 'USI'

master = scraper.getMasterTeams()

print(master.columns)

#master.loc[master['team'] == team, 'short'] = short
#print(master[['team', 'short']].to_string())

#master.to_json(utils.get_path("data/teams/master_new.json"))

