import pandas as pd
import numpy as np
import constants
import html_util

def load_stats():
    df = pd.read_json(constants.SEASON_PATH)
    return df[df['week'] < 15]

def process_roto(group_df):
    def record(team, df):
        wins = 0
        loss = 0
        for score in df['points']:
            if team['points'] > score:
                wins += 1
            elif team['points'] < score:
                loss += 1
        return [f'{wins}-{loss}', wins, loss]
    
    group_df[['roto', 'roto_win', 'roto_loss']] = group_df.apply(lambda team:
        record(team, group_df), axis=1, result_type='expand')
    return group_df

def calc_roto():
    reg_season = load_stats()
    df = reg_season.groupby('week')
    results = []
    for _, group in df:
        result = process_roto(group)
        results.append(result)
    roto_df = pd.concat(results)
    roto = roto_df[['team_name', 'roto', 'week']]
    summary = roto_df[['roto_win', 'roto_loss', 'team_name']].groupby('team_name').sum()
    summary['roto'] = summary.apply(lambda x: f'{x['roto_win']}-{x['roto_loss']}', axis=1)
    summary['week'] = 'Total'
    summary = summary.drop(columns=['roto_win', 'roto_loss'])
    summary = summary.reset_index()
    roto = pd.concat([roto, summary])
    roto_pivot = roto.pivot(index='team_name', columns='week', values='roto')
    roto_pivot[['win', 'loss']] = roto_pivot['Total'].str.extract(r'(\d+)-(\d+)')
    roto_return = roto_pivot.sort_values(by='win', ascending=False)
    win_series = pd.to_numeric(roto_return['win']) / (pd.to_numeric(roto_return['win']) + pd.to_numeric(roto_return['loss']))
    roto_return['Win %'] = win_series.map("{:.1%}".format)
    roto_return = roto_return.drop(columns=['win', 'loss'])
    roto_return.index.name = 'Team'
    roto_return.columns.name = 'Week'
    
    styler = roto_return.style \
        .apply(html_util.highlight_roto, subset=[c for c in roto_return.columns[:-2]]) \
        .apply(html_util.highlight_on_record, subset=['Total']) \
        .set_table_styles([html_util.light_grid_style_data, html_util.light_grid_style_header], overwrite=False) \
        .set_table_attributes('class="sticky-table"')
    return styler

def calc_ow(team, season, dict):
    only_team = season[season['roster_id'] == team['roster_id']].copy()
    opps = only_team['opp'].to_numpy()
    arr = [dict[x] for x in opps]
    ow = sum(arr) / len(arr)
    return ow

def calc_sov(team, season, dict):
    only_team = season[season['roster_id'] == team['roster_id']].copy()
    filter = only_team[only_team['win'] == 1]['opp'].tolist()
    arr = [dict[x] for x in filter]
    sov = sum(arr)/len(arr)
    return sov

def schedule_metrics():
    reg_season = load_stats()
    # Winning Percentage
    reg_season['W%'] = reg_season['total_wins'] / (reg_season['total_wins'] + reg_season['total_loss'])

    # Overall Opponent Winning Percentage [OW%]
    curr_winp = reg_season[reg_season['week'] == (len(reg_season)/10)].copy()
    winp_dict = dict(zip(curr_winp['roster_id'], curr_winp['W%']))
    curr_winp['OW%'] = curr_winp.apply(lambda x: calc_ow(x, reg_season, winp_dict), axis=1)

    # Calculate Overall Opponent Winning Percentage of the opponents faced [OOW%]
    oow_winp_dict = dict(zip(curr_winp['roster_id'], curr_winp['OW%']))
    curr_winp['OOW%'] = curr_winp.apply(lambda x: calc_ow(x, reg_season, oow_winp_dict), axis=1)

    # Calculate Strength of Schedule - (2 * OW) + OOW divided by 3
    curr_winp['SOS'] = ((curr_winp['OW%'] * 2) + curr_winp['OOW%'])/3

    # Calculate Strength of Victory - Average win % of defeated opponents
    curr_winp['SOV'] = curr_winp.apply(lambda x: calc_sov(x, reg_season, winp_dict), axis=1)

    # Calculate Strength of Victory - Average win % of defeated opponents
    curr_winp['Exp W (Actual)'] = curr_winp.apply(lambda x:
           f'{(x['PF']**constants.EXPW_RATIO)/((x['PF']**constants.EXPW_RATIO) + (x['PA']**constants.EXPW_RATIO))*14:.1f} ({x['h2h_wins']})', 
           axis=1)
    
    df = curr_winp[['team_name', 'SOS', 'SOV', 'Exp W (Actual)']].sort_values(by='SOS', ascending=False)
    styler = (
       df
        .style
        .hide(axis="index") 
        .format( lambda x: f"{x:.3f}" if isinstance(x, (int, float)) else x) 
        .background_gradient(cmap="RdYlGn_r", subset=["SOS"]) 
        .background_gradient(cmap="RdYlGn", subset=["SOV"])
        .apply(html_util.bg_from_pythag_str, subset=["Exp W (Actual)"])
        .set_table_styles([html_util.light_grid_style_data, html_util.light_grid_style_header, html_util.table_style], overwrite=False)
        )
    return styler

def reg_season_stats():
    season = load_stats()

    roto = calc_roto(season)
    metrics = schedule_metrics(season)
   




