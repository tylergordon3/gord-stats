import json
import pandas as pd
import nflreadpy as nfl
import numpy as np

DROP_POS = ['OL', 'CB', 'LB', 'FS', 'DE', 'DT', 'T', 'DL', 'DB', 'OT',
    'G', None, 'C', 'SS', 'LS', 'P', 'ILB', 'NT', 'OLB', 'S', 'OG', 'SAF', 'OG', 'MLB']

with open('data/players.json', 'r', encoding='utf-8') as file:
    data = json.load(file)
    sleeper_db = pd.DataFrame.from_dict(data, orient='index')

stats_players = nfl.load_player_stats()
stats_players = stats_players.to_pandas()

sleeper_db = sleeper_db[~sleeper_db['position'].isin(DROP_POS)]
stats_players = stats_players[~stats_players['position'].isin(DROP_POS)]

stat = list(stats_players['player_display_name'])
sleep = list(sleeper_db['full_name'])

def format(name):
    ret = name.replace(".", "")
    ret = ret.replace(" III","")
    ret = ret.replace(" II","")
    ret = ret.replace(" IV","")
    ret = ret.replace(" Jr","")
    ret = ret.replace(" Sr","")
    ret = ret.replace("Joshua Palmer", "Josh Palmer")
    ret = ret.replace('Mike Badgley', 'Michael Badgley')
    ret = ret.replace('Scott Miller', 'Scotty Miller')
    ret = ret.replace('Mitchell Tinsley', 'Mitch Tinsley')
    return ret

st = np.sort(np.array(stat))
sl = np.sort(np.array(sleep))

st = np.apply_along_axis(np.vectorize(format), 0, st)
sl = np.apply_along_axis(np.vectorize(format), 0, sl)

diff1 = np.setdiff1d(st, sl)
diff2 = np.setdiff1d(sl, st)
match = np.intersect1d(st, sl)

print(str(len(diff1)) + " players in readPy and not sleeper.")
print(str(len(diff2)) + " players in sleeper and not readPy.")
print(str(len(match)) + " players matched!")



print(diff1[:20])
print(diff2[1900:2000])