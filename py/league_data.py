import constants
from tqdm import tqdm
import pandas as pd
import league_util
from sleeper_wrapper import League
import utilities as utils
from pathlib import Path

def get_league_id(season):
    match season:
        case "2023":
            return constants.LEAGUEID_2023
        case "2324":
            return constants.LEAGUEID_2023
        case "2024":
            return constants.LEAGUEID_2024
        case "2425":
            return constants.LEAGUEID_2024
        case "2025":
            return constants.LEAGUEID_2025
        case "2526":
            return constants.LEAGUEID_2025

def get_season_path(season):
    season_str = ''
    match season:
        case "2023":
            season_str = '2324'
        case "2324":
            season_str = '2324'
        case "2024":
            season_str = '2425'
        case "2425":
            season_str = '2425'
        case "2025":
            season_str = '2526'
        case "2526":
            season_str = '2526'
    return utils.get_project_root() / Path("data") / Path("season") / Path(f'{season_str}.json')

def get_formal_season(season):
    match season:
        case "2023":
            return "2023-2024"
        case "2324":
            return "2023-2024"
        case "2024":
            return "2024-2025"
        case "2425":
            return "2024-2025"
        case "2025":
            return "2025-2026"
        case "2526":
            return "2025-2026"

def get_season(end_week, season):
    # Fantasy season: 1-14 reg, 15-17 post
    if end_week > 14: end_week = 14
    league = League(get_league_id(season))
    teams = league_util.get_teams(league)
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
            matchup_df['record'] = matchup_df.apply(lambda x: f'{int(x['total_wins'])}-{int(x['total_loss'])}', axis=1)
            matchup_df[['PF', 'PA']] = matchup_df.apply(lambda x: league_util.calc_point_totals(x, season), 
                                                        axis=1, result_type='expand')
            matchup_df = pd.merge(matchup_df, teams, how='left', on='roster_id')
            season = pd.concat([season, matchup_df])
            pbar.update(1)
    return season

   