import pandas as pd
import constants as c
import json
from sleeper_wrapper import League

league = League(c.LEAGUEID_2025)
users = league.get_users()
rosters = league.get_rosters()

user_df = pd.DataFrame(users)
user_df = pd.concat([user_df, user_df['metadata'].apply(pd.Series)['team_name']], axis=1)

roster_df = pd.DataFrame(rosters)
roster_df = roster_df.rename(columns={'owner_id' : 'user_id'})

info = pd.merge(user_df, roster_df, 'inner', 'user_id')
info = info[['user_id', 'display_name', 'team_name', 'roster_id']].copy()

with open('data/players.json', 'r', encoding='utf-8') as file:
    data = json.load(file)
    df = pd.DataFrame.from_dict(data, orient='index')



players = df[['full_name', 'search_first_name', 'injury_start_date', 'number', 'active', 'years_exp', 'last_name', 
              'search_last_name', 'weight', 'status', 'height', 'injury_notes', 'team_changed_at', 'injury_status', 
              'search_full_name', 'college', 'depth_chart_order', 'practice_participation', 
              'player_id', 'team', 'first_name', 'position', 'search_rank', 'age']].copy()
print(players)
