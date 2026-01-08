import pandas as pd
import constants
import html_util

def load_stats():
    return pd.read_json(constants.SEASON_PATH)

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
    season = load_stats()
    regular_season = season[season['week'] < 15]
    df = regular_season.groupby('week')
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
        .set_table_styles([html_util.light_grid_style_data, html_util.light_grid_style_header], overwrite=False) \
        .set_table_attributes('class="sticky-table"')
    return styler

def reg_season_stats():
    season = load_stats()
    regular_season = season[season['week'] < 15]
    roto = calc_roto()

   

reg_season_stats()


