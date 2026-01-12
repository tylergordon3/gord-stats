import constants
from tqdm import tqdm
import pandas as pd
import league_util
from sleeper_wrapper import League

def get_season(end_week):
    # Fantasy season: 1-14 reg, 15-17 post
    if end_week > 17: end_week = 17
    league = League(constants.LEAGUEID)
    teams = get_teams(league)
    season = pd.DataFrame()
    with tqdm(total=end_week, desc="Loading season") as pbar:
        for week in range(1,end_week+1):
            # matchup_df:
            # points          float
            # players         [int]
            # roster_id       int
            # custom_points   None / int
            # matchup_id      int / float (if NaN present in col)
            # starters        [int]
            # starters_points [float]
            # players_points  {int str : float}
            matchup_df = pd.DataFrame.from_dict(league.get_matchups(week))
            matchup_df = matchup_df.rename(columns={'players_points':'players_dict'})

            matchup_df['starters_dict'] = matchup_df.apply(lambda x:
                    dict(zip(x['starters'], x['starters_points'])), axis=1)
            
            matchup_df['bench_dict'] = matchup_df.apply(lambda x:
                    {key : value for key, value in x['players_dict'].items() if key not in x['starters_dict']}, axis=1)

            matchup_df['matchup_id'] = matchup_df['matchup_id'].astype('Int64')
            matchup_df = matchup_df[matchup_df['matchup_id'].notna()]

            matchup_df['matchup_id'] = matchup_df['matchup_id'].astype('Int64')
            matchup_df = matchup_df.drop(columns=['starters', 'starters_points', 
                                                'players', 'custom_points'])
            # matchup_df:
            # points          float
            # roster_id       int
            # matchup_id      int (0 -> no game)
            # players_dict    {int str : float}
            # starters_dict   {int str : float}
            # bench_dict      {int str : float}
            matchup_df['week'] = week
            matchup_df[['opp', 'opp_points', 'win']] = matchup_df.apply(lambda x:
                league_util.find_opponents(x, matchup_df), axis=1, result_type='expand')
            matchup_df['point_ranks'] = matchup_df['points'].rank()
            median_rank = len(matchup_df) / 2
            matchup_df['median'] = matchup_df.apply(lambda x:
                1 if x['point_ranks'] > median_rank else 0, axis=1)

            matchup_df = matchup_df.drop(columns=['point_ranks'])
            
            matchup_df[['h2h_wins', 'median_wins', 'h2h_loss', 'median_loss']] = matchup_df.apply(lambda x:
                league_util.calc_totals(x, season), axis=1, result_type='expand')
            matchup_df['total_wins'] = matchup_df.apply(lambda x: x['h2h_wins'] + x['median_wins'], axis=1)
            matchup_df['total_loss'] = matchup_df.apply(lambda x: x['h2h_loss'] + x['median_loss'], axis=1)
            matchup_df['record'] = matchup_df.apply(lambda x: f'{x['total_wins']}-{x['total_loss']}', axis=1)
            matchup_df[['PF', 'PA']] = matchup_df.apply(lambda x: league_util.calc_point_totals(x, season), 
                                                        axis=1, result_type='expand')
            matchup_df = pd.merge(matchup_df, teams, how='left', on='roster_id')
            season = pd.concat([season, matchup_df])
            pbar.update(1)
    return season


def get_teams(league) -> pd.DataFrame:
    users = league.map_users_to_team_name(league.get_users())
    users = pd.Series(users).to_frame().reset_index()
    users.columns = ['owner_id', 'team_name']
    rosters = pd.DataFrame.from_dict(league.get_rosters())
    users = pd.merge(users, rosters[['owner_id', 'roster_id']].copy(), 
                     'left', on='owner_id')
    return users

   