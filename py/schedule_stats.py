import pandas as pd
import league_util
import constants
import html_util
import plotly.express as px
import numpy as np

import plotly.graph_objects as go

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

def schedule_metrics(standings=False):
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
    
    if standings:
        df = curr_winp[['team_name', 'record', 'total_wins', 'PF', 'PA', 'SOS', 'SOV', 'Exp W (Actual)']].sort_values(['total_wins', 'PF'],ascending=False)
        df = df.rename(columns={"team_name":"Team", 'record' : 'Record'})
        df = df.drop(columns=['total_wins'])
    else:
        df = curr_winp[['team_name', 'SOS', 'SOV', 'Exp W (Actual)']].sort_values(by='SOS', ascending=False)
        df = df.rename(columns={"team_name":"Team"})
    styler = (
       df
        .style
        .hide(axis="index") 
        .format( lambda x: f"{x:.3f}" if isinstance(x, float) else x) 
        .background_gradient(cmap="RdYlGn_r", subset=["SOS"]) 
        .background_gradient(cmap="RdYlGn", subset=["SOV"])
        .apply(html_util.bg_from_pythag_str, subset=["Exp W (Actual)"])
        .set_table_styles([html_util.light_grid_style_data, html_util.light_grid_style_header, html_util.table_style], overwrite=False)
        .set_table_attributes('class="sticky-table"')
        )
    return styler

def schedule_compare():
    reg_season = load_stats()
    roster_ids = pd.unique(reg_season['roster_id'])

    df = pd.DataFrame()
    indexes = []

    names_arr = [league_util.name_from_id(x) for x in roster_ids]
    team_totals = dict.fromkeys(names_arr, [0,0])
    
    for id in roster_ids:
        schedule = reg_season[reg_season['roster_id'] == id]['opp_points'].to_numpy()
        schedule_name = league_util.name_from_id(id)
        this_schedule = {}
        
        this_sched_w = 0
        this_sched_l = 0
        indexes.append(schedule_name)
        for check_id in roster_ids:
            this_team_name = league_util.name_from_id(check_id)
            to_compare = reg_season[reg_season['roster_id'] == check_id]['points'].to_numpy()
            wins = int(sum(to_compare > schedule))
            losses = int(sum(to_compare < schedule))
            this_schedule[this_team_name] = f'{wins}-{losses}'
            
            this_sched_w += wins
            this_sched_l += losses
           
            [team_w, team_l] = team_totals[this_team_name]
            team_totals[this_team_name] = [team_w+wins, team_l+losses]
        # end looping through this schedule
        this_schedule['Schedule Totals'] = f'{this_sched_w}-{this_sched_l}'
        df = pd.concat([df, pd.DataFrame([this_schedule])])
    for team, record in team_totals.items():
        team_totals[team] = f'{record[0]}-{record[1]}'
    team_totals['Schedule Totals'] = f'{0}-{0}'
    df = pd.concat([df, pd.DataFrame([team_totals])])
    indexes.append("Team Totals")
    # all teams been looped
    df.index = indexes
    df.index.name = 'Schedules'
    df.columns.name = 'Teams'

    styled_df = df.style \
        .set_table_styles([html_util.light_grid_style_data, html_util.light_grid_style_header], overwrite=False) \
        .apply(html_util.highlightActualRecords, axis=None) \
        .apply(html_util.style_total_bottom, axis=1, subset=pd.IndexSlice[df.index[-1]:, :]) \
        .apply(html_util.style_total_right, axis=0, subset=pd.IndexSlice[:, df.columns[-1]:]) \
        .set_table_attributes('class="sticky-table"')
    return styled_df

def weekly_rankings():
    reg_season = load_stats()
    df = reg_season.sort_values(by=['week', 'total_wins', 'PF'], ascending=[True, False, False])
    # df_sorted['Rank'] = df_sorted.groupby('Category')['Score1'].rank(method='min', ascending=True)
    df['Rank'] = df.groupby('week')['total_wins'].rank(method='first', ascending=False)
    #df['Frame'] = df['week']
    #df.pivot(index="week", columns="team_name", values="Rank").plot()
    df_indexed = pd.DataFrame()
    N_UNIQUE_TEAMS = 10
    for index in np.arange(start=0, stop=len(df)+1, step = N_UNIQUE_TEAMS):
        df_slicing = df.iloc[:index].copy()
        df_slicing['frame'] = (index//N_UNIQUE_TEAMS)
        df_indexed = pd.concat([df_indexed, df_slicing])

    scatter_plot = px.scatter(
        df_indexed,
        x='week',
        y='Rank',
        color='team_name',
        animation_frame='frame'
    )

    for frame in scatter_plot.frames:
        for data in frame.data:
            data.update(mode='markers',
                showlegend=True,
                opacity=1)
            data['x'] = np.take(data['x'], [-1])
            data['y'] = np.take(data['y'], [-1])
    line_plot = px.line(
        df_indexed,
        x='week',
        y='Rank',
        color='team_name',
        animation_frame='frame'
    )
    line_plot.update_traces(showlegend=False) 
    for frame in line_plot.frames:
        for data in frame.data:
            data.update(mode='lines', opacity=0.8, showlegend=False) 

    combined_plot = go.Figure(
        data=line_plot.data + scatter_plot.data,
        frames=[
            go.Frame(data=line_plot.data + scatter_plot.data, name=scatter_plot.name)
            for line_plot, scatter_plot in zip(line_plot.frames, scatter_plot.frames)
        ],
        layout=line_plot.layout
    )

    combined_plot.update_yaxes(
        gridcolor='#7a98cf',
        griddash='dot',
        gridwidth=0.5,
        linewidth=2,
        tickwidth=2
    )

    combined_plot.update_xaxes(
        title_font=dict(size=16),
        linewidth=2,
        tickwidth=2
    )

    combined_plot.update_traces(
        line=dict(width=5),
        marker=dict(size=25))
        
    combined_plot.update_layout(
        title="<b>Team Rankings 2025</b>",
        xaxis_title="<b>Week</b>",
        yaxis_title="<b>Rank</b>",
        xaxis_range=[df_indexed['week'].min() - 1,
                 df_indexed['week'].max() + 1]
    )

    combined_plot['layout'].pop("sliders")
    combined_plot.layout.updatemenus[0].buttons[0]['args'][1]['frame']['duration'] = 120
    combined_plot.layout.updatemenus[0].buttons[0]['args'][1]['transition']['duration'] = 50
    combined_plot.layout.updatemenus[0].buttons[0]['args'][1]['transition']['redraw'] = False

    combined_plot.write_html("your_plot.html")
   

