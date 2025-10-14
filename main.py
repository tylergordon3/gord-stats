from sleeper_wrapper import League, Drafts
import pandas as pd

league_id = 1257466498994143232
users_names = ['Austin', 'Jackson', 'Tyler', 'Colin', 'Max', 'Trevor', 'Matt', 'Mark', 'George', 'Everett']
league = League(league_id)
users = league.map_users_to_team_name(league.get_users())

users_dict = {k: (v1, v2) for k, v1, v2 in zip(users_names, users.values(), users.keys())}
usersDF = pd.DataFrame.from_dict(users_dict, orient='index', columns=['Name', 'ID']) 

draft = Drafts(draft_id="1257466498994143233")
allPicks = pd.DataFrame(draft.get_all_picks())

apMeta = allPicks['metadata'].apply(pd.Series)
apMeta = apMeta.drop(columns=['team_abbr', 'team_changed_at', 'sport', 'news_updated', 'years_exp', 'status', 'injury_status', 'number', 'player_id'])

draftDF = pd.concat([allPicks, apMeta], axis=1)
draftDF = draftDF.drop(columns=['metadata', 'reactions', 'is_keeper', 'draft_id', 'draft_slot', 'roster_id'])

# DRAFTDF COLUMNS
# Index(['pick_no', 'picked_by', 'player_id', 'roster_id', 'round', 'first_name',
#       'last_name', 'position', 'team'],
#      dtype='object')

draftDF['teamName'] = draftDF['picked_by']
draftDF['teamName'] = draftDF['teamName'].replace(pd.unique(draftDF['teamName']), usersDF['Name'])
print(draftDF)

print(draftDF.loc[draftDF['teamName'] == "Big Gourds"])

