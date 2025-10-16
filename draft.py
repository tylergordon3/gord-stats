'''
    This module is used for gathering draft data for a league.
'''
import json
import pandas as pd
from sleeper_wrapper import League, Drafts, Players
import fantasy_rosters
import constants as c

league = League(c.LEAGUEID)
draft = Drafts(c.DRAFTID)
players = Players()

rosters = fantasy_rosters.get(league)
print(rosters[rosters['team_name'] == 'Big Gourds'])

allPicks = pd.DataFrame(draft.get_all_picks())
apMeta = allPicks['metadata'].apply(pd.Series)
apMeta = apMeta.drop(columns=['team_abbr', 'team_changed_at', 'sport', 'news_updated',
                              'years_exp', 'status', 'injury_status', 'number', 'player_id'])

draftDF = pd.concat([allPicks, apMeta], axis=1)
draftDF = draftDF.drop(columns=['metadata', 'reactions', 'is_keeper',
                                'draft_id', 'draft_slot', 'roster_id'])

draftDF['teamName'] = draftDF['picked_by']

# DRAFTDF COLUMNS
# Index(['pick_no', 'picked_by', 'player_id', 'roster_id', 'round', 'first_name',
#       'last_name', 'position', 'team', 'teamName],
#      dtype='object')

try:
    with open('players.json', 'r', encoding='utf-8') as file:
        data = json.load(file)
    playersDF = pd.DataFrame.from_dict(data, orient='index')
except FileNotFoundError:
    print("Error: The file 'your_file.json' was not found.")
except json.JSONDecodeError:
    print("Error: Failed to decode JSON from the file. Check for valid JSON format.")
