from sleeper_wrapper import League
import constants as c
import fantasy_rosters as fr
import player_db as pdb
import pandas as pd
import os
import nflreadpy as nfl
import json
from io import StringIO

league = League(c.LEAGUEID)
rosters = fr.get(league)

def bestball(week):
    # Filter matchups to what we need
    matchup_df = pd.DataFrame.from_dict(league.get_matchups(week))

    db = pdb.get(week)
    df = matchup_df[['roster_id', 'players_points', 'matchup_id']]

    combined = pd.DataFrame()
    # Iterate through roster to find best ball lineup
    for roster_id in df['roster_id']:
        # Team info we need
        team = df[df.roster_id == roster_id]
        key = roster_id - 1

        # Get the dict of teams players
        ps = team.players_points.get(key)
        raw_df = pd.DataFrame(ps.items())
        raw_df.columns = ['id', 'points']

        # Call to cleanup data frame
        valid_df = createDataframe(raw_df, db)
        # Find lineup and return as a DF with players
        best_df = findBestball(valid_df)

        # Add roster_id to each player for safety
        best_df['roster_id'] = roster_id
        best_df['week'] = week
        # Add players to data frame with all players
        combined = pd.concat([combined, best_df])
    # end roster iteration
    # Send to HTML and return
    #bestball_to_html(combined, matchups, week)
    return combined

def getMatchups(matchup_df):
    num_matches = max(matchup_df['matchup_id'])

    matchups = []
    for i in range(num_matches):
        vals = matchup_df[matchup_df['matchup_id'] == (i+1)]['roster_id']
        matchups.append(list(vals))
    return matchups


def createDataframe(df,db):
    df['obj'] = df['id'].apply(lambda x: pdb.getFromID(x, db))
    df['name'] = df['obj'].apply(lambda y: y.cleaned_name.item() if not y.cleaned_name.empty else "err")
    df['position'] = df['obj'].apply(lambda y: y.position.item() if not y.position.empty else "err")
    valididated_df = df[(df['name'] != "err") | (df['id'].isin(c.TEAMS))]
    valididated_df = valididated_df.drop(columns=['obj'])
    return valididated_df

def findBestball(df):
    lineup = { "QB"   : 1,
               "RB"   : 2,
               "WR"   : 2,
               "TE"   : 1,
               "FLEX" : 2,
               "DEF"  : 1,
               "K"    : 1}
    bestball = pd.DataFrame()
    for pos, amt in lineup.items():
        if pos == 'FLEX':
            pos_df = df[df['position'].isin(["RB", "TE", "WR"])].copy()
            pos_df['position'] = 'FLEX'
        else:
            pos_df = df[df['position'] == pos]
        pos_df = pos_df.sort_values(by='points', ascending=False)
        bestball = pd.concat([bestball, pos_df.iloc[0:amt]])
        df = df.drop(pos_df.iloc[0:amt].index)

    return bestball

def bestball_to_html(results, matchups, week):
    file = f"week{week}_bestball.html"
    median_path = "docs/bestball/"
    filename = os.path.join(median_path, file)
    index_link = '<a href="../bestball">BestBall Home</a>'
  
    formatted = formatMatchups(results, matchups, week)
    html = index_link + "<br>" + formatted

    with open(filename, 'w') as f:
        f.write(html)
        print("Wrote to ", filename)


def formatMatchups(results, matchups, week):
    css_style = """
        <style>
            .flex-container {
                display: flex;
                justify-content: space-around; /* Distributes space evenly */
                flex-wrap: wrap; /* Allows items to wrap if screen is too small */
            }
            .flex-item {
                margin: 10px; /* Adds space between tables */
                border: 1px solid #ddd;
                padding: 10px;
            }
            /* Optional: Basic table styling */
            .flex-item table {
                border-collapse: collapse;
                width: 100%;
            }
            .flex-item th, .flex-item td {
                border: 1px solid #ddd;
                padding: 8px;
                text-align: center;
            }
        </style>
        """
    formatted = css_style
    for match_id, teams in matchups.items():
        matchup_df = pd.DataFrame.from_dict(league.get_matchups(week))
        teamA = results[results['roster_id'] == teams[0]]
        teamB = results[results['roster_id'] == teams[1]]
        teamAName = fr.getTeamName(league, teams[0])
        teamBName = fr.getTeamName(league, teams[1])
        teamA_total = teamA['points'].sum()
        teamB_total = teamB['points'].sum()
        originalA = list(matchup_df[matchup_df['roster_id'] == teams[0]]['points'])[0]
        originalB = list(matchup_df[matchup_df['roster_id'] == teams[1]]['points'])[0]
        teamA = teamA.reset_index(drop=True)
        teamB = teamB.reset_index(drop=True)
        teamA = teamA.drop(columns=['id', 'roster_id'],axis=0)
        teamB = teamB.drop(columns=['id', 'roster_id'],axis=0)
        teamA = teamA.iloc[:, [2, 1, 0]]
        teamB = teamB.iloc[:, [0, 1, 2]]
        
        html_df1 = teamA.to_html(index=False)
        html_df2 = teamB.to_html(index=False)
        full_html = f"""
            {css_style}
            <div class="flex-container">
                <div class="flex-item">
                    <div style="text-align: center;">
                    <p><strong>{teamAName} </strong></p>
                    <p>Best Lineup: <strong>{teamA_total:.2f} pts</strong></p>
                    <p>Original:  {originalA:.2f} </p>
                        {html_df1}
                    </div>
                </div>
                <div class="flex-item">
                    <div style="text-align: center;">
                    <p><strong>{teamBName}</strong></p> 
                    <p>Best Lineup: <strong>{teamB_total:.2f} pts</strong></p>
                    <p>Original: {originalB:.2f} </p>
                        {html_df2}
                    </div>
                </div>
            </div>
            """
        formatted = formatted + full_html
    return formatted

def bestball_season():
    season_combined = pd.DataFrame()
    szn_matchups = {}
    for week in range(1,nfl.get_current_week()):
        print(f'Getting bestball results for week {week}')
        weekly_results = bestball(week)
        season_combined = pd.concat([season_combined, weekly_results])
        matchup_df = pd.DataFrame.from_dict(league.get_matchups(week))
        matchups = getMatchups(matchup_df)
        szn_matchups[week] = matchups
        
    updateSummary(season_combined, szn_matchups)

#def bestball_week_html(week):
#    matchup_df = pd.DataFrame.from_dict(league.get_matchups(week))
#    matchups = getMatchups(matchup_df)
    
#    with open('data/bestball_season.json', 'r', encoding='utf-8') as file:
#            data = json.load(file)
#            all = pd.read_json(StringIO(data))
#    bestball_to_html(all[all['week'] == week], matchups, week)

def weeklyTeam(results, roster_id, matchup_df):
    # too lazy, return as array
    team_df = results[results['roster_id'] == roster_id]
    name = fr.getTeamName(league, roster_id)
    new_total = round(float(team_df['points'].sum()),2)
    original_total = list(matchup_df[matchup_df['roster_id'] == roster_id]['points'])[0]
    return [name, new_total, original_total]

def getResults(season_df, matchups_dict):
    last_week = season_df['week'].max() + 1
    outcomes = pd.DataFrame()
    for week in range(1, last_week):
        matchups_arr = matchups_dict.get(week)
        matchup_df = pd.DataFrame.from_dict(league.get_matchups(week))
        week_df = season_df[season_df['week'] == week]
        for teams in matchups_arr:
            teamA = weeklyTeam(week_df, teams[0], matchup_df)
            teamB = weeklyTeam(week_df, teams[1], matchup_df)
            new_winner = teamA[0] if int(teamA[1]) > int(teamB[1]) else teamB[0]
            old_winner = teamA[0] if int(teamA[2]) > int(teamB[2]) else teamB[0]
            to_add = {'week' : week, 'roster_id' : teams, 'names': [teamA[0], teamB[0]],
                      'score' : [teamA[2], teamB[2]], 'bb_score' : [teamA[1], teamB[1]],
                      'winner' : old_winner, 'bb_winner' : new_winner}
            to_add_df = pd.DataFrame(to_add)
            outcomes = pd.concat([outcomes, to_add_df])
    outcomes = outcomes.reset_index(drop=True)

    def calcMedian(group):
        median = group.median()
        return group.apply(lambda x: 1 if x > median else 0)
    outcomes['median'] = outcomes.groupby('week')['score'].transform(calcMedian)
    outcomes['bb_median'] = outcomes.groupby('week')['bb_score'].transform(calcMedian)

    return outcomes
   

def updateSummary(season, matchups):
    outcomes = getResults(season, matchups)
    with open('data/bestball.json', 'w', encoding="utf-8") as f:
        json.dump(outcomes.to_json(), f, indent=4)
        print(f"Bestball data successfully saved to data/outcomes.json")

bestball_season()
