import pandas as pd
import constants as c

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

