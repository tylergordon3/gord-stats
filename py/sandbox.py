
import utils
import os
import pandas as pd
import scraper

master = pd.read_json(utils.get_path("docs/assets/data/master.json"))


# df.loc[row, col]

#team = "Southern Indiana"
#short = 'USI'
#master.loc[master['team'] == team, 'short'] = short
#print(master[['team', 'short']].to_string())

print(master)
scraper.saveMasterTeams(master)
#master.to_json(utils.get_path("data/teams/master_new.json"))

