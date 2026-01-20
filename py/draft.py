'''
    This module is used for gathering draft data for a league.
'''

import pandas as pd
import re
import numpy as np
from pytz import timezone
import datetime
from sleeper_wrapper import League, Drafts, Players
import fantasy_rosters
import constants as c
import player_db as pdb
import html_builder as htmb
league = League(c.LEAGUEID)
draft = Drafts(c.DRAFTID)
players = Players()

rosters = fantasy_rosters.get(league)
allPicks = pd.DataFrame(draft.get_all_picks())
apMeta = allPicks['metadata'].apply(pd.Series)
apMeta = apMeta.drop(columns=['team_abbr', 'team_changed_at', 'sport', 'news_updated',
                              'years_exp', 'status', 'injury_status', 'number', 'player_id'])

draftDF = pd.concat([allPicks, apMeta], axis=1)
draftDF = draftDF.drop(columns=['metadata', 'reactions', 'is_keeper',
                                'draft_id', 'draft_slot', 'roster_id'])

draftDF['roster_id'] = draftDF['picked_by'].apply(lambda x: list(rosters[rosters['owner_id'] == x].roster_id)[0])
draftDF['team_name'] = draftDF['roster_id'].apply(lambda x: list(rosters[rosters['roster_id'] == x].team_name)[0])

# DRAFTDF COLUMNS
# Index(['pick_no', 'picked_by', 'player_id', 'roster_id', 'round', 'first_name',
#       'last_name', 'position', 'team', 'teamName],
#      dtype='object')
df = draftDF[['pick_no', 'roster_id', 'team_name', 'player_id', 'first_name', 'last_name', 'round', 'position', 'team']].copy()

def pos_rank(row, position_df):
    this_rank = row.pick_no
    return len(position_df[position_df['pick_no'] < this_rank]) + 1

df['pos_rank'] = df.apply(lambda x: pos_rank(x, df[df['position'] == x.position]), axis=1)

players = pdb.get(week=0)

def sum_pts(id):
    sleeper = str(id)
    pts = players[players['sleeper_id'] == sleeper]['fantasy_points_ppr'].sum()
    return pts

def num_games(id):
    sleeper = str(id)
    pts = players[players['sleeper_id'] == sleeper]['fantasy_points_ppr'][:14].count()
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
    # round = match.group(1)
    pick_no = match.group(2)
    return pick_no

df['total_pts'] = df.apply(lambda x: sum_pts(x['player_id']), axis=1)
df['num_games'] = df.apply(lambda x: num_games(x['player_id']), axis=1)
df['final_rank'] = df.apply(lambda x: final_rank(x, df), axis=1)
df['final_pos_rank'] = df.apply(lambda x: final_pos_rank(x, df[df['position'] == x.position]), axis=1)
df['overall_diff'] = df['pick_no'] - df['final_rank']
df['pos_diff'] = df['pos_rank'] - df['final_pos_rank']
df['name'] = df['first_name'] + df['last_name']
df['Position Rk'] = df.apply(lambda x: f'{x['pos_rank']} -> {x['final_pos_rank']}', axis=1)
df['Overall Rk'] = df.apply(lambda x: f'{x['pick_no']} -> {x['final_rank']}', axis =1)
df = df.drop(columns=['player_id', 'roster_id', 'first_name', 'last_name', 'pos_rank', 'final_pos_rank',
                      'final_rank'])

df =  df[~df['position'].isin(['K', 'DEF'])]

df = df.rename(columns={
        "pos_diff" : "Pos Δ",
        "overall_diff" : "Overall Δ",
        "pick_no" : "Pick",
        "position" : "Pos",
        "team_name" : "Owner",
        "total_pts" : "Pts",
        "name" : "Name",
        "team" : "Team",
        "num_games" : "# G"
    })

df['Pick'] = df.apply(lambda x: f'{x['round']}.{x['Pick']}', axis=1)
df = df[['Pick', 'Owner', 
         'Name', 'Pos', 'Team', 'Position Rk', 'Pos Δ', 'Overall Rk', 'Overall Δ', '# G']]

team_breakdown = df.copy()
df_best = df.sort_values(by='Overall Δ', ascending=False)
df_worst = df.sort_values(by='Overall Δ')

styler = (
        df
        .style
        .hide(axis="index") 
        .background_gradient(cmap="RdYlGn", subset=["Pos Δ"]) 
        .background_gradient(cmap="RdYlGn", subset=["Overall Δ"])
        )

styler_best = (
        df_best
        .style
        .hide(axis="index")
        .background_gradient(cmap="RdYlGn", subset=["Overall Δ"]) 
        )

styler_worst = (
        df_worst
        .style
        .hide(axis="index") 
        .background_gradient(cmap="RdYlGn", subset=["Overall Δ"]) 
        )

df_no_inj = df[~((df['# G'] < 10))]
team_breakdown_noinj = df_no_inj .copy()
df_no_inj_best = df_no_inj.sort_values(by='Overall Δ', ascending=False)
df_no_inj_worst = df_no_inj.sort_values(by='Overall Δ')

styler_no_inj = (
        df_no_inj
        .style
        .hide(axis="index") 
        .background_gradient(cmap="RdYlGn", subset=["Pos Δ"]) 
        .background_gradient(cmap="RdYlGn", subset=["Overall Δ"])
        )

styler_best_no_inj = (
        df_no_inj_best
        .style
        .hide(axis="index")
        .background_gradient(cmap="RdYlGn", subset=["Overall Δ"]) 
        )

styler_worst_no_inj = (
        df_no_inj_worst
        .style
        .hide(axis="index") 
        .background_gradient(cmap="RdYlGn", subset=["Overall Δ"]) 
        )

tz = timezone("EST")
time_obj = datetime.datetime.now(tz)
time = time_obj.strftime("Last Update: %A %m/%d/%y %I:%M %p")
df_html = f"<p>{time}</p>"
df_html += "<a href='draft_team.html'>Team Draft Breakdown</a>"
df_html +=  f'''
    <p>Note: Does not include defenses or kickers.</p>
    <details>
    <summary><strong>Full Draft</strong></summary>
    <div class="table-scroll">
        {styler.to_html()}
    </div>
    </details>
    <details>
    <summary><strong>Biggest OVERALL Steals</strong></summary>
    <div class="table-scroll">
        {styler_best.to_html(max_rows=15)}
    </div>
    </details>
    <details>
    <summary><strong>Biggest OVERALL Busts</strong></summary>
    <div class="table-scroll">
        {styler_worst.to_html(max_rows=15)}
    </div>
    </details>
    <p>The following tables only include players who played in 10 or more games. (~64.5% game requirement)</p>
    <p> - Only inlcudes fantasy regular season (weeks 1-14)</p>
    <details>
    <summary><strong>Biggest OVERALL Steals (Injury adjusted)</strong></summary>
    <div class="table-scroll">
        {styler_best_no_inj.to_html(max_rows=15)}
    </div>
    </details>
    <details>
    <summary><strong>Biggest OVERALL Busts (Injury adjusted)</strong></summary>
    <div class="table-scroll">
        {styler_worst_no_inj.to_html(max_rows=15)}
    </div>
    </details>
    '''

page = htmb.add_front_matter(df_html, 'Draft')
with open('docs/draft.html', "w", encoding="utf-8") as f:
    f.write(page)

def byTeam(df):
    grouped = df.groupby(by=['Owner', 'Pos']).agg(
        pos_delt = ("Pos Δ", "sum"),
        ovr_delt = ("Overall Δ", "sum")
    )
    grouped['pos_delt'] = grouped['pos_delt'].fillna(0)
    grouped['ovr_delt'] = grouped['ovr_delt'].fillna(0)
    grouped_tot = df.groupby(by=['Owner']).agg(
        ovr_delt = ("Overall Δ", 'sum')
    )
    grouped_tot['ovr_delt'] = grouped_tot['ovr_delt'].fillna(0)
    df_result = grouped.reset_index()
    df_result = df_result.rename(columns={'pos_delt':'Total Pos Δ', 'ovr_delt':' Total Ovr Δ'})
    qb = df_result[df_result['Pos'] == 'QB'].sort_values(by='Total Pos Δ', ascending=False)
    rb = df_result[df_result['Pos'] == 'RB'].sort_values(by='Total Pos Δ', ascending=False)
    wr = df_result[df_result['Pos'] == 'WR'].sort_values(by='Total Pos Δ', ascending=False)
    te = df_result[df_result['Pos'] == 'TE'].sort_values(by='Total Pos Δ', ascending=False)

    grouped_tot = df.groupby(by=['Owner']).agg(
        ovr_delt = ("Overall Δ", 'sum')
    )
    grouped_tot['ovr_delt'] = grouped_tot['ovr_delt'].fillna(0)
    
    df_result2 = grouped_tot.reset_index()
    df_result2 = df_result2.rename(columns={'ovr_delt':' Total Ovr Δ'})

    return [qb, rb, wr, te, df_result2]

qb_all, rb_all, wr_all, te_all, ovr_all = byTeam(team_breakdown)
qb, rb, wr, te, ovr = byTeam(team_breakdown_noinj)

qb = pd.merge(qb_all, qb, 'left', on='Owner')
rb = pd.merge(rb_all, rb, 'left', on='Owner')
wr = pd.merge(wr_all, wr, 'left', on='Owner')
te = pd.merge(te_all, te, 'left', on='Owner')
ovr = pd.merge(ovr_all, ovr, 'left', on='Owner')

html = ''

missing = team_breakdown.groupby(by=['Owner']).agg(
        num_games = ("# G", 'sum'),
        tot_players = ("# G", 'count')
    )
missing['tot_games'] = missing['tot_players'] * 14
missing['Games Missed'] = missing['tot_games'] - missing['num_games']
missing = missing.sort_values(by='Games Missed', ascending=False)
missing = missing.drop(columns=['tot_players'])
missing = missing.rename(columns={'num_games':'G Played', 'tot_games':'G Tot'})
missing = missing[['Games Missed', 'G Tot', 'G Played']].copy()
styler = (
        missing
        .style
        .background_gradient(cmap="RdYlGn_r", subset=["Games Missed"]) 
        )
html += "<p>Number of games drafted players missed over the course of the 14 week regular season.</p>"
html += styler.to_html()
for df in [qb, rb, wr, te, ovr]:
    df = df.rename(columns={
        "Pos_x" : "Pos",
        "Total Pos Δ_x": "Sum Pos Δ",
        " Total Ovr Δ_x": "Sum Δ",
        "Total Pos Δ_y": "No Injury Sum Pos Δ",
        " Total Ovr Δ_y": "No Injury Sum Δ"
    })
    df = df.reset_index(drop=True)
    if 'Pos_y' in df.columns:
        df = df.drop(columns=['Pos_y', 'No Injury Sum Δ', 'Sum Δ'])
        pos = list(df['Pos'])[0]
        df = df.drop(columns=['Pos'])
        df = df.sort_values(by='Sum Pos Δ', ascending=False)
        styler = (
        df
        .style
        .hide(axis="index") 
        .background_gradient(cmap="RdYlGn", subset=["Sum Pos Δ"]) 
        .background_gradient(cmap="RdYlGn", subset=["No Injury Sum Pos Δ"])
        )
        html += f'<h2>{pos}</h2>'
    else:
        df = df.sort_values(by='Sum Δ', ascending=False)
        styler = (
        df
        .style
        .hide(axis="index") 
        .background_gradient(cmap="RdYlGn", subset=["Sum Δ"]) 
        .background_gradient(cmap="RdYlGn", subset=["No Injury Sum Δ"])
        )
        html += f'<h2>Overall</h2>'
    html += styler.to_html()

page = htmb.add_front_matter(html, 'Draft - Team Breakdown')
with open('docs/draft_team.html', "w", encoding="utf-8") as f:
    f.write(page)