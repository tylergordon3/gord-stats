'''
    This module is used for gathering draft data for a league.
'''
import pandas as pd
import re
from pytz import timezone
import datetime
from sleeper_wrapper import League, Drafts
import league_data
import league_util
import fantasy_rosters
import constants as c
import player_db as pdb
import html_builder as htmb
import constants
import archive
import numpy as np
import matplotlib.pyplot as plt
import io
import base64
# ------------------
# Globals
# ------------------

CUTOFF_ROWS = 15

# ------------------
# Helper Functions
# ------------------
def get_final_rank_missed_szn(final_ranks, position, pts):
    filtered = final_ranks[final_ranks['pos'] == position]
    same_pts = filtered[filtered['tot_pts'] == pts]
    if not same_pts.empty:
        return list(same_pts.head(1)['pos_rank'])[0]
    else:
        return 999
    
def sum_pts(players, id):
    sleeper = str(id)
    pts = players[players['sleeper_id'] == sleeper]['fantasy_points_ppr'].sum()
    return pts

def num_games(players, id):
    sleeper = str(id)
    pts = players[players['sleeper_id'] == sleeper]['fantasy_points_ppr'][:13].count()
    return pts

def final_rank(row, df):
    this_rank = row.total_pts
    return len(df[df['total_pts'] > this_rank]) + 1

def final_pos_rank(row, df):
    this_rank = row.total_pts
    return len(df[df['total_pts'] > this_rank]) + 1

def get_over(pick_str):
    pattern = r'(\d+).(\d+)'
    match = re.search(pattern, pick_str)
    pick_no = match.group(2)
    return pick_no

def default_style(df, cols, opt_styler="RdYlGn"):
    return (df
        .style
        .hide(axis="index") 
        .background_gradient(cmap=opt_styler, subset=cols))

def table_html(styler):
    return f'''<div class="table-scroll">
            {styler.to_html()}
            </div>'''

def pos_rank(row, position_df):
    this_rank = row.pick_no
    return len(position_df[position_df['pick_no'] < this_rank]) + 1

def save_base64(df, x_col, title, rot):
    # Saving plot to base64 html
    _ = df.plot(x=x_col, kind='bar', stacked=True, title=title, rot=rot)
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight') 
    buf.seek(0)
    img_base64 = base64.b64encode(buf.read()).decode('utf-8')
    buf.close()
    plt.close()
    return img_base64
# ------------------
# Team Breakdowns
# ------------------
def byTeam(df):
    grouped = df.groupby(by=['roster_id', 'Pos.']).agg(
        pos_delt = ("Pos. Rank Δ", "sum"),
        ovr_delt = ("Overall Rank Δ", "sum")
    )
    grouped['pos_delt'] = grouped['pos_delt'].fillna(0)
    grouped['ovr_delt'] = grouped['ovr_delt'].fillna(0)
    grouped_tot = df.groupby(by=['roster_id']).agg(
        ovr_delt = ("Overall Rank Δ", 'sum')
    )
    grouped_tot['ovr_delt'] = grouped_tot['ovr_delt'].fillna(0)
    df_result = grouped.reset_index()
    df_result = df_result.rename(columns={'pos_delt':'Total Pos. Rank Δ', 'ovr_delt':' Total Ovr. Rank Δ'})
    qb = df_result[df_result['Pos.'] == 'QB'].sort_values(by='Total Pos. Rank Δ', ascending=False)
    rb = df_result[df_result['Pos.'] == 'RB'].sort_values(by='Total Pos. Rank Δ', ascending=False)
    wr = df_result[df_result['Pos.'] == 'WR'].sort_values(by='Total Pos. Rank Δ', ascending=False)
    te = df_result[df_result['Pos.'] == 'TE'].sort_values(by='Total Pos. Rank Δ', ascending=False)

    grouped_tot = df.groupby(by=['roster_id']).agg(
        ovr_delt = ("Overall Rank Δ", 'sum')
    )
    grouped_tot['ovr_delt'] = grouped_tot['ovr_delt'].fillna(0)

    overall = grouped_tot.reset_index()
    overall = overall.rename(columns={'ovr_delt':' Total Ovr. Rank Δ'})

    return [qb, rb, wr, te, overall]

def merge_breakdowns(all, injuries):
    combined_list = []
    for all_df, inj_df in zip(all, injuries):
        combined = pd.merge(all_df, inj_df, 'left', on='roster_id')
        combined = combined.fillna(0)
        combined_list.append(combined)
    return combined_list

def format_breakdown(df_list, html):
    for df in df_list:
        html += '<details>'
        df = df.rename(columns={
            "Pos._x" : "Pos.",
            "Total Pos. Rank Δ_x": "Total Pos. Rank Δ",
            " Total Ovr. Rank Δ_x": "Total Ovr. Rank Δ",
            "Total Pos. Rank Δ_y": "Total Pos. Rank Δ w/o Injuries",
            " Total Ovr. Rank Δ_y": "Total Ovr. Rank Δ w/o Injuries"
        })

        if 'Total Pos. Rank Δ w/o Injuries' in df.columns:
            df['Total Pos. Rank Δ w/o Injuries'] = df['Total Pos. Rank Δ w/o Injuries'].astype(int)
        df = df.reset_index(drop=True)
        if 'Pos._y' in df.columns:
            df = df.drop(columns=['Pos._y', 'Total Ovr. Rank Δ w/o Injuries', 'Total Ovr. Rank Δ'])
            pos = list(df['Pos.'])[0]
            df = df.drop(columns=['Pos.'])
            df = df.sort_values(by='Total Pos. Rank Δ', ascending=False)
            styler = default_style(df, ["Total Pos. Rank Δ", "Total Pos. Rank Δ w/o Injuries"])
            html += f'<summary><strong>{pos}</strong></summary>'
        else:
            df = df.sort_values(by='Total Ovr. Rank Δ', ascending=False)
            styler = default_style(df, ["Total Ovr. Rank Δ", "Total Ovr. Rank Δ w/o Injuries"])
            html += f'<summary><strong>Overall</strong></summary>'
        html += table_html(styler)
        html += '</details>'
    return html

# ------------------
# Position Rankings
# ------------------

def original_draft(df, position, number):
    pos_filter = df[df['Pos.'] == position]
    top_x = pos_filter.head(number).copy()
    top_x['Pos. Rank'] = range(1, len(top_x) + 1)
    top_x = top_x.rename(columns={'Name':'Draft'})
    return top_x[['Owner', 'Draft', 'Pos. Rank']]

def final(final_ranks, position, number):
    final_filter = final_ranks[final_ranks['pos'] == position]
    top_x = final_filter.head(number)
    top_x = top_x.rename(columns=
        {'pos_rank':'Pos. Rank'}
    )
    top_x.index.name = 'Final'
    top_x = top_x.drop(columns=['tot_games', 'pos', 'overall', 'tot_pts'])
    top_x = top_x.reset_index()
    return top_x

# ------------------
# Main Logic
# ------------------
def main(season_str):
    league = League(league_data.get_league_id(season_str))
    draft = Drafts(league_data.get_draft_id(season_str))
    #players = Players()
    rosters = fantasy_rosters.get(league)
    allPicks = pd.DataFrame(draft.get_all_picks())
    players = pdb.get(week=0)
    players = players[players['week'] < 15]
    final_ranks = players.groupby(by=['cleaned_name']).agg(
            tot_pts = ("fantasy_points_ppr", 'sum'),
            tot_games = ("fantasy_points_ppr", 'count'),
            pos = ("position", "first")
        )

    final_ranks['overall'] = final_ranks['tot_pts'].rank(ascending=False).astype(int)
    final_ranks = final_ranks.sort_values(by='overall')

    final_ranks['pos_rank'] = final_ranks.groupby('pos')['tot_pts'].rank(ascending=False).astype(int)
    apMeta = allPicks['metadata'].apply(pd.Series)
    
    apMeta = apMeta.drop(columns=['team_abbr', 'team_changed_at', 'sport', 'news_updated',
                                'years_exp', 'status', 'injury_status', 'number', 'player_id'], errors='ignore')

    draftDF = pd.concat([allPicks, apMeta], axis=1)
    draftDF = draftDF.drop(columns=['metadata', 'reactions', 'is_keeper',
                                    'draft_id', 'draft_slot', 'roster_id'])

    draftDF['roster_id'] = draftDF['picked_by'].apply(lambda x: list(rosters[rosters['owner_id'] == x].roster_id)[0])
    draftDF['team_name'] = draftDF['roster_id'].apply(lambda x: list(rosters[rosters['roster_id'] == x].team_name)[0])

    df = draftDF[['pick_no', 'roster_id', 'team_name', 'player_id', 'first_name', 'last_name', 'round', 'position', 'team']].copy()

    df['name'] = df['first_name']+ ' ' + df['last_name']
    df['name'] = df['name'].replace('Mike Badgley', 'Michael Badgley')
    df['name'] = df['name'].replace('Amon-Ra St. Brown', 'AmonRa StBrown')
    df['name'] = df['name'].replace('ChigoziemOkonkwo', 'ChigOkonkwo')
    df['name'] = df['name'].apply(lambda x: x.replace(".", "") if not x == None else x)
    df['name'] = df['name'].apply(lambda x: x.replace("'", "") if not x == None else x)
    df['name'] = df['name'].apply(lambda x: x.replace("-", "") if not x == None else x)
    df['name'] = df['name'].str.split()

    df['name'] = df['name'].apply(lambda lst: lst.str.join('') if len(lst) < 2 else ''.join(lst[:2]))
    df['name'] = df.apply(lambda x: x['team'] if x['position'] == 'DEF' else x['name'], axis=1)
    df['pos_rank'] = df.apply(lambda x: pos_rank(x, df[df['position'] == x.position]), axis=1)

    df['total_pts'] = df.apply(lambda x: sum_pts(players, x['player_id']), axis=1)
    df['num_games'] = df.apply(lambda x: num_games(players, x['player_id']), axis=1)
    df['final_rank'] = df.apply(lambda x: final_rank(x, df), axis=1)
    df['final_pos_rank'] = df.apply(lambda x: list(final_ranks[final_ranks.index == x['name']]['pos_rank']), axis=1)
    df['final_pos_rank'] = df.apply(lambda x: x['final_pos_rank'][0] if len(x['final_pos_rank']) > 0 else get_final_rank_missed_szn(final_ranks,
                                                                                                            x['position'], x['total_pts']), axis=1)
    df['overall_diff'] = df['pick_no'] - df['final_rank']
    df['pos_diff'] = df['pos_rank'] - df['final_pos_rank']

    df['Position Rk'] = df.apply(lambda x: f'{x['pos_rank']} -> {x['final_pos_rank']}', axis=1)
    df['Overall Rk'] = df.apply(lambda x: f'{x['pick_no']} -> {x['final_rank']}', axis =1)
 
    df = df.drop(columns=['player_id', 'first_name', 'last_name', 'pos_rank', 'final_pos_rank',
                        'final_rank'])

    df =  df[~df['position'].isin(['K', 'DEF'])]

    df = df.rename(columns={
            "pos_diff" : "Pos. Rank Δ",
            "overall_diff" : "Overall Rank Δ",
            "pick_no" : "Pick",
            "position" : "Pos.",
            "team_name" : "Owner",
            "total_pts" : "Pts.",
            "name" : "Name",
            "team" : "Team",
            "num_games" : "Games Played"
        })

    df['Pick'] = df.apply(lambda x: f'{x['round']}.{x['Pick']}', axis=1)

    df_lottery = df[df['round'] < 5]

    df = df[['Pick', 'Owner', 
            'Name', 'Pos.', 'Team', 'Position Rk', 'Pos. Rank Δ', 'Overall Rk', 'Overall Rank Δ', 'Games Played', 'roster_id']]

    # ------------------
    # Copies for lottery
    # ------------------
    df_lottery = df_lottery[['Pick', 'Owner', 
            'Name', 'Pos.', 'Team', 'Position Rk', 'Pos. Rank Δ', 'Overall Rk', 'Overall Rank Δ', 'Games Played', 'roster_id']]
    df_lottery_no_injuries = df_lottery[~((df_lottery['Games Played'] < 10))]

    # ------------------
    # DataFrames including injuries
    # ------------------
    df_best = df.sort_values(by='Overall Rank Δ', ascending=False)
    df_worst = df.sort_values(by='Overall Rank Δ')

    styler = (df
            .style
            .hide(axis="index") 
            .background_gradient(cmap="RdYlGn", subset=['Pos. Rank Δ'], vmin=-60)
            .background_gradient(cmap="RdYlGn", subset=['Overall Rank Δ'], vmin=-75))
    styler_best = default_style(df_best.head(CUTOFF_ROWS), ["Overall Rank Δ"], opt_styler='Greens')
    styler_worst = default_style(df_worst.head(CUTOFF_ROWS), ["Overall Rank Δ"], opt_styler='Reds_r')

    # ------------------
    # DataFrames removing injuries
    # ------------------
    df_no_injuries = df[~((df['Games Played'] < 10))]

    df_no_injuries_best = df_no_injuries.sort_values(by='Overall Rank Δ', ascending=False)
    df_no_injuries_worst = df_no_injuries.sort_values(by='Overall Rank Δ')

    styler_no_injuries = default_style(df_no_injuries, ["Pos. Rank Δ", "Overall Rank Δ"])
    styler_best_no_injuries = default_style(df_no_injuries_best.head(CUTOFF_ROWS), ["Overall Rank Δ"], opt_styler='Greens')
    styler_worst_no_injuries = default_style(df_no_injuries_worst.head(CUTOFF_ROWS), ["Overall Rank Δ"], opt_styler='Reds_r')

    # ------------------
    # Copies for below
    # ------------------
    team_breakdown = df.copy()
    team_breakdown_noinj = df_no_injuries.copy()

    # ------------------
    # Main Draft Page HTML
    # ------------------
    tz = timezone("EST")
    time_obj = datetime.datetime.now(tz)
    time = time_obj.strftime("Last Update: %A %m/%d/%y %I:%M %p")
    df_html = f"<p>{time}</p>"
    df_html += '<p>Δ = Delta = Change/Difference</p>'
    df_html += "<a href='draft_team.html'>Team Draft Breakdown</a>"
    df_html +=  f'''
        <p>Note: Does not include defenses or kickers.</p>
        <details>
        <summary><strong>Full Draft</strong></summary>
        {table_html(styler)}
        </details>
        <details>
        <summary><strong>Biggest OVERALL Steals</strong></summary>
        {table_html(styler_best)}
        </details>
        <details>
        <summary><strong>Biggest OVERALL Busts</strong></summary>
        {table_html(styler_worst)}
        </details>
        <p>The following tables only include players who played in 10 or more games. (~64.5% game requirement)</p>
        <p> - Only inlcudes fantasy regular season (weeks 1-14)</p>
        <details>
        <summary><strong>Biggest OVERALL Steals (Injury adjusted)</strong></summary>
        {table_html(styler_best_no_injuries)}
        </details>
        <details>
        <summary><strong>Biggest OVERALL Busts (Injury adjusted)</strong></summary>
        {table_html(styler_worst_no_injuries)}
        </details>
        '''

    page = htmb.add_front_matter(df_html, f'Draft - {league_data.get_formal_season(season_str)}', subnav='draft_nav')
    with open(f'docs/{season_str}/draft/index.html', "w", encoding="utf-8") as f:
        f.write(page)

    breakdown = byTeam(team_breakdown)
    breakdown_no_injuries = byTeam(team_breakdown_noinj)
    combined = merge_breakdowns(breakdown, breakdown_no_injuries)

    lottery_breakdown = byTeam(df_lottery)
    lottery_breakdown_no_injuries = byTeam(df_lottery_no_injuries)
    lottery_combined = merge_breakdowns(lottery_breakdown, lottery_breakdown_no_injuries)

    # ------------------
    # Missed Games due to Injury
    # ------------------
    
    missing = team_breakdown.groupby(by=['Owner', 'roster_id']).agg(
            num_games = ("Games Played", 'sum'),
            tot_players = ("Games Played", 'count')
        )
    missing['tot_games'] = missing['tot_players'] * 14

    missing['Total Games Missed'] = missing['tot_games'] - missing['num_games']
    missing["% of Games Missed"] = missing['Total Games Missed'] / missing['tot_games']
    missing["% of Games Missed"] = missing["% of Games Missed"].apply(lambda x: f'{x:.2%}')
    copy = missing.copy()
    copy = copy.reset_index()
    archive.save_statistic(season_str, 'missing_df', copy.to_dict(orient='records'))
    missing = missing.sort_values(by='Total Games Missed', ascending=False)
    missing = missing.drop(columns=['tot_players', 'num_games', 'tot_games'])
    missing = missing.reset_index(names=['Owners', 'roster_id'])
    missing = missing[['Owners', 'Total Games Missed', '% of Games Missed']].copy()
    
    missing_styler = default_style(missing, ["Total Games Missed"], opt_styler="RdYlGn_r")

    html = ''
    html += "<p>Number of games drafted players missed over the course of the 14 week regular season."
    html += "Missed is defined as not starting or playing an entire game. If a player leaves a game due to injury, this is counted as a game played.</p>"
    html += table_html(missing_styler)
    html += '''<h1>Drafted Position Change</h1>
            <p>Sorted by: Total Pos. Rank Δ, or the total change from draft position to final ranking amongst position group.</p>
            <p>Total Pos. Rank Δ w/o Injuries - change in draft position to final ranking among position group. Not counting players with less than 10 games played.</p> '''
    html = format_breakdown(combined, html)

    html += '<h1>Drafted Position Change in first 4 rounds</h1>'
    html += '<p>Same as above, but now only using picks in rounds 1-4</p>'
    html = format_breakdown(lottery_combined, html)

    def draft_plot(dfs):
        overall_df = pd.DataFrame()
        positional_df = pd.DataFrame()
        for i in range (0, len(dfs)-1):
            dfs[i]['Team'] = dfs[i]['roster_id'].apply(lambda x: league_util.name_from_id(x))
            add_pos = dfs[i][['Team', 'Pos.', 'Total Pos. Rank Δ']].copy()
            add_ovr = dfs[i][['Team', 'Pos.', ' Total Ovr. Rank Δ']].copy()
            overall_df = pd.concat([overall_df, add_ovr])
            positional_df = pd.concat([positional_df, add_pos])
        
        pos_group = positional_df.groupby(by=['Team', 'Pos.'], as_index=False).sum() #.unstack()
        #pos_group = pos_group.reset_index(names='Team')
        ovr_group = overall_df.groupby(by=['Team', 'Pos.']).sum().unstack()
        ovr_group = ovr_group.reset_index(names='Team')
        #pos_group = pos_group.rename_axis(None, axis=1)
        pos_group = pos_group.pivot_table(
            index='Team', 
            columns='Pos.', 
            values='Total Pos. Rank Δ', 
            aggfunc='sum'
        )
        pos_group = pos_group.rename_axis(None, axis=1).reset_index()
        print(pos_group)
        pos_img = save_base64(pos_group, 'Team', 'Pos. Rank Change', rot=45)
        return pos_img
    pos_img = draft_plot(breakdown)
    html += f'<img src="data:image/png;base64,{pos_img}" alt="Position Rank Change"/>'
    page = htmb.add_front_matter(html, f'Draft Team Breakdown - {league_data.get_formal_season(season_str)}', subnav='draft_nav')
    with open(f'docs/{season_str}/draft/draft_team.html', "w", encoding="utf-8") as f:
        f.write(page)

    #og = original_draft(df, "QB", 10)
    #end = final(final_ranks, "QB", 10)

def all_time_missed():
    ##############################
    # Unpack archived data
    ###############################
    history = archive._open()
    keys = history.keys()
    all = pd.DataFrame()
    dfs = [pd.DataFrame(history[key]['missing_df']) for key in keys]

    for i in range(0, len(dfs)):
        all = pd.concat([all, dfs[i]])

    ##############################
    # Injury Breakdown by Year Plot 
    ###############################
    breakdown = all.groupby('roster_id').agg(list)
    breakdown = breakdown.reset_index(names='roster_id')
    breakdown = breakdown[['roster_id', 'tot_games', 'Total Games Missed']].copy()

    breakdown['Total'] = breakdown['Total Games Missed'].apply(lambda x: sum(x))
    breakdown['Team'] = breakdown['roster_id'].apply(lambda x: league_util.name_from_id(x))
    breakdown = breakdown.drop(columns=['tot_games',  'roster_id', 'Total'])
    values_df = pd.DataFrame(breakdown['Total Games Missed'].tolist(), columns=keys)
    out = pd.concat([breakdown, values_df], axis=1)
    out = out.drop(columns=['Total Games Missed'])

    # Saving plot to base64 html
    ax = out.plot(x='Team', kind='bar', stacked=True, title='Games Missed for Injury by Season', rot=45)
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight') 
    buf.seek(0)
    img_base64 = base64.b64encode(buf.read()).decode('utf-8')
    buf.close()
    plt.close()

    ##############################
    # Injury Breakdown DataFrame
    ###############################
    arr = []
    for i in range(0, len(dfs)):
        arr.append([])
        breakdown['Total Games Missed'].apply(lambda x: arr[i].append(x[i]))

    grouped = all.groupby(by='roster_id').sum()
    grouped = grouped.reset_index(names='roster_id')

    grouped = grouped.drop(columns=['% of Games Missed'])
    grouped["% of Games Missed"] = grouped['Total Games Missed'] / grouped['tot_games']
    grouped["% of Games Missed"] = grouped["% of Games Missed"].apply(lambda x: f'{x:.2%}')
    grouped['Team'] = grouped.apply(lambda x: league_util.name_from_id(int(x['roster_id'])), axis=1)
    grouped = grouped.drop(columns=['tot_games', 'roster_id', 'Owner'])
    
    grouped = grouped.sort_values(by='Total Games Missed', ascending=False)
    grouped = grouped[['Team', 'Total Games Missed', '% of Games Missed']].copy()
    missing_styler = default_style(grouped, ["Total Games Missed"], opt_styler="RdYlGn_r")

    return img_base64, missing_styler