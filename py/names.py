import json
import pandas as pd
import nflreadpy as nfl
import numpy as np
import src_bridge as bridge

DROP_POS = ['OL', 'CB', 'LB', 'FS', 'DE', 'DT', 'T', 'DL', 'DB', 'OT',
    'G', None, 'C', 'SS', 'LS', 'P', 'ILB', 'NT', 'OLB', 'S', 'OG', 'SAF', 'OG', 'MLB']

sleeper_db = bridge.sleeper_players()


stats_players = nfl.load_player_stats()
stats_players = stats_players.to_pandas()

sleeper_db = sleeper_db[(~sleeper_db['position'].isin(DROP_POS)) & (sleeper_db['status'] == "Active")]
stats_players = stats_players[~stats_players['position'].isin(DROP_POS)]

stat = list(stats_players['player_display_name'])
sleep = list(sleeper_db['full_name'])

nickname_dict = {
    "Joshua Palmer" : "Josh Palmer",
    "Mike Badgley" : "Michael Badgley",
    "Scott Miller" : "Scotty Miller",
    "Mitchell Tinsley" : "Mitch Tinsley",
    "Bam Knight" : "Zonovan Knight",
    "Andrew Ogletree" : "Drew Ogletree",
    "Audric Estimé" : "Audric Estime",
    "Nathan Carter" : "Nate Carter",
    "Nyheim Miller-Hines" : "Nyheim Hines",
    "John Parker Romo" : "Parker Romo",
    "Amon-Ra St. Brown" : "AmonRa St Brown",
    "Chigoziem Okonkwo" : "Chig Okonkwo",
    "Hollywood Brown" : "Marquise Brown",
}

symbols = [
    ".",
    "'",
    " III",
    " II",
    " IV",
    " Jr",
    " Sr"
]

def format(name):
    for sym in symbols:
        name = name.replace(sym, "")
    for nickname in nickname_dict:
        name = name.replace(nickname, nickname_dict[nickname])
    return name

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


