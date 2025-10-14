from sleeper_wrapper import League, Drafts, Players, Stats
import pandas as pd
import json
league = League(league_id="1257466498994143232")
draft = Drafts(draft_id="1257466498994143233")
players = Players()

users_names = ['Austin', 'Jackson', 'Tyler', 'Colin', 'Max', 'Trevor', 'Matt', 'Mark', 'George', 'Everett']
users = league.map_users_to_team_name(league.get_users())

users_dict = {k: (v1, v2) for k, v1, v2 in zip(users_names, users.values(), users.keys())}
usersDF = pd.DataFrame.from_dict(users_dict, orient='index', columns=['Name', 'ID']) 

allPicks = pd.DataFrame(draft.get_all_picks())
apMeta = allPicks['metadata'].apply(pd.Series)
apMeta = apMeta.drop(columns=['team_abbr', 'team_changed_at', 'sport', 'news_updated', 'years_exp', 'status', 'injury_status', 'number', 'player_id'])

draftDF = pd.concat([allPicks, apMeta], axis=1)
draftDF = draftDF.drop(columns=['metadata', 'reactions', 'is_keeper', 'draft_id', 'draft_slot', 'roster_id'])

draftDF['teamName'] = draftDF['picked_by']
draftDF['teamName'] = draftDF['teamName'].replace(pd.unique(draftDF['teamName']), usersDF['Name'])

# DRAFTDF COLUMNS
# Index(['pick_no', 'picked_by', 'player_id', 'roster_id', 'round', 'first_name',
#       'last_name', 'position', 'team', 'teamName],
#      dtype='object')

try:
    with open('players.json', 'r') as file:
        data = json.load(file)
    playersDF = pd.DataFrame.from_dict(data, orient='index')
except FileNotFoundError:
    print("Error: The file 'your_file.json' was not found.")
except json.JSONDecodeError:
    print("Error: Failed to decode JSON from the file. Check for valid JSON format.")

print(playersDF.head())
print(pd.unique(playersDF['team_changed_at']))
stats = Stats()

# pulls all of the stats for week 1 of the 2023 regular season
week_stats = stats.get_week_stats("regular", 2024, 1)

# retrieves stats for the Detroit defense for the provided week
score = stats.get_player_week_score(week_stats, "DET")
print(score)