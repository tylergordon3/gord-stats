'''
    This module is used for gathering draft data for a league.
'''

import pandas as pd
import re
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
    pts = players[players['sleeper_id'] == sleeper]['fantasy_points_ppr'].count()
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

df_no_inj = df[~((df['# G'] < 8))]
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

full_html = f'''
    <p>Note: Does not include defenses or kickers.</p>
    <details>
    <summary><strong>All Draft Stats</strong></summary>
    <div class="table-scroll">
        {styler.to_html()}
    </div>
    </details>
    <details>
    <summary><strong>Biggest Draft Steals</strong></summary>
    <div class="table-scroll">
        {styler_best.to_html(max_rows=40)}
    </div>
    </details>
    <details>
    <summary><strong>Biggest Draft Misses</strong></summary>
    <div class="table-scroll">
        {styler_worst.to_html(max_rows=40)}
    </div>
    </details>
    <p>Note: Does not include defenses or kickers, <strong>OR</strong> players who played in less than 8 games. (~57% of regular season)</p>
    <details>
    <summary><strong>All Draft Stats</strong></summary>
    <div class="table-scroll">
        {styler_no_inj.to_html()}
    </div>
    </details>
    <details>
    <summary><strong>Biggest Draft Steals</strong></summary>
    <div class="table-scroll">
        {styler_best_no_inj.to_html(max_rows=40)}
    </div>
    </details>
    <details>
    <summary><strong>Biggest Draft Misses</strong></summary>
    <div class="table-scroll">
        {styler_worst_no_inj.to_html(max_rows=40)}
    </div>
    </details>
    '''

tz = timezone("EST")
time_obj = datetime.datetime.now(tz)
time = time_obj.strftime("Last Update: %A %m/%d/%y %I:%M %p")
df_html = f"<p>{time}</p>"
df_html +=  f'''
            <div class="type-toggle">
                <button data-key="all" onclick="setChangeT('all', this)" class="active type-toggle">All</button>
                <button data-key="best" onclick="setChangeT('best', this)" class="type-toggle>Best</button>
                <button data-key="worst" onclick="setChangeT('worst', this)" class="type-toggle>Worst</button>
            </div>
            <div class="injury-toggle">
            <button data-key="injuries" class="active injury-toggle">Injuries</button>
            <button data-key="noinjuries class="injury-toggle">No Injuries</button>
            </div>'''
df_html += f'''
        <div id="all" class="table-scroll all inj">{styler.to_html()}</div>
        <div id="best" class="table-scroll best inj hidden-div">{styler_best.to_html(max_rows=40)}</div>
        <div id="worst" class="table-scroll worst inj hidden-div">{styler_worst.to_html(max_rows=40)}</div>
        <div id="all-noinj" class="table-scroll all noinj hidden-div">{styler_no_inj.to_html()}</div>
        <div id="best-noinj" class="table-scroll best noinj hidden-div">{styler_best_no_inj.to_html(max_rows=40)}</div>
        <div id="worst-noinj" class="table-scroll worst noinj hidden-div">{styler_worst_no_inj.to_html(max_rows=40)}</div>
        <script src='/assets/js/rank-toggle.js'></script>
        '''

page = htmb.add_front_matter(df_html, 'Draft')
with open('docs/draft.html', "w", encoding="utf-8") as f:
    f.write(page)