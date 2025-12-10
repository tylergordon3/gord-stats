'''
    This module is used for gathering draft data for a league.
'''

import pandas as pd
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

def final_rank(row, df):
    this_rank = row.total_pts
    return len(df[df['total_pts'] > this_rank]) + 1

def final_pos_rank(row, df):
    this_rank = row.total_pts
    return len(df[df['total_pts'] > this_rank]) + 1

df['total_pts'] = df.apply(lambda x: sum_pts(x['player_id']), axis=1)
df['final_rank'] = df.apply(lambda x: final_rank(x, df), axis=1)
df['final_pos_rank'] = df.apply(lambda x: final_pos_rank(x, df[df['position'] == x.position]), axis=1)
df['overall_diff'] = df['pick_no'] - df['final_rank']
df['pos_diff'] = df['pos_rank'] - df['final_pos_rank']
df['name'] = df['first_name'] + df['last_name']
df = df.drop(columns=['player_id', 'roster_id', 'first_name', 'last_name'])
df = df.rename(columns={
        "pos_diff" : "Pos Δ",
        "overall_diff" : "Final Δ",
        "final_pos_rank" : "PosFinal",
        "pos_rank" : "PosStart",
        "pick_no" : "Pick",
        "position" : "Pos",
        "team_name" : "Owner",
        "final_rank" : "Final",
        "total_pts" : "Pts",
        "name" : "Name",
        "team" : "Team"
    })

df['Pick'] = df.apply(lambda x: f'{x['round']}.{x['Pick']}', axis=1)
df = df[['Pick', 'Owner', 
         'Name', 'Pos', 'Team', 'PosStart', 'PosFinal', 'Pos Δ', 'Final', 'Final Δ' ]]

df_best = df.sort_values(by='Final Δ', ascending=False)
df_worst = df.sort_values(by='Final Δ')

styler = (
        df
        .style
        .hide(axis="index") 
        .background_gradient(cmap="RdYlGn", subset=["Pos Δ"]) 
        .background_gradient(cmap="RdYlGn", subset=["Final Δ"])
        )

styler_best = (
        df_best
        .style
        .hide(axis="index")
        .background_gradient(cmap="RdYlGn", subset=["Final Δ"]) 
        )

styler_worst = (
        df_worst
        .style
        .hide(axis="index") 
        .background_gradient(cmap="RdYlGn", subset=["Final Δ"]) 
        )

html = f'''
    <details>
    <summary><h3>All Draft Stats</h3></summary>
    <div class="table-scroll">
        {styler.to_html()}
    </div>
    </details>
    <h3>Biggest Draft Steals</h3>
    <div class="table-scroll">
        {styler_best.to_html(max_rows=40)}
    </div>
    <h3>Biggest Draft Misses</h3>
    <div class="table-scroll">
        {styler_worst.to_html(max_rows=40)}
    </div>
    '''

page = htmb.add_front_matter(html, 'Draft')
with open('docs/draft.html', "w", encoding="utf-8") as f:
    f.write(page)