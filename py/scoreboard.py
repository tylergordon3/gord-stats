import scraper
import pandas as pd

from render import render_teams as teams
'''
Used to create and update live scores.
'''



def today_games(rank_df, gender):
    rank_df["index"] = (rank_df["Team"].rank(method="dense").astype(int)) - 1
    master = scraper.getMasterTeams()

    if gender == 'M':
        soup = scraper.getHTML("https://www.cbssports.com/college-basketball/schedule/")
        [p5live, p5done, done, live] = scraper.parse_mens_cbs(soup, master, rank_df)
        html = scraper.today_games_help_men(p5live, p5done, done, live)

    elif gender == 'W':
        html = today_games_help_women(rank_df, master)
    
    return html

def get_rank_women(team, rank_df, master):

    [index, code_name] = scraper.getNameFromCode(team, master)

    rank_row = rank_df.loc[
        (rank_df["Team"] == team)
        | (rank_df["Team"] == code_name)
        | (rank_df["index"] == index)
    ]

    if rank_row.empty:
        pass
    else:
        return list(rank_row["Overall"])[0]

    return None

def get_conf_women(team, rank_df, master):
    [_, code_name] = scraper.getNameFromCode(team, master)
    rank_row = rank_df.loc[
        (rank_df["Team"] == team)
        | (rank_df["Team"] == code_name)
        #| (rank_df["index"] == index)
    ]
    if rank_row.empty:
        return
    else:
        return list(rank_row["Conf"])[0]

def parse_espn_teams_and_times(data):
    parsed = pd.DataFrame()
    for event in data.get("events", []):
        competition = event["competitions"][0]
        status = competition["status"]["type"]
        state = status["state"]  # pre / in / post
        
        competitors = competition["competitors"]
        '''
            each competitor scores:
            uid
            type
            order
            homeAway
            winner
            team
            score
            linescores
            statistics
            leaders
            curatedRank
            records
        '''
        # DF -> State away, home , away score, home score
        away = next(c for c in competitors if c["homeAway"] == "away")
        home = next(c for c in competitors if c["homeAway"] == "home")
        
        away_name = away["team"]["abbreviation"]
        home_name = home["team"]["abbreviation"]
       
        away_score = away.get("score")
        home_score = home.get("score")

        time_str = status.get("shortDetail") 

        if state == 'post':
            if away_score > home_score:
                away_win = True
                home_win = False
            elif home_score > away_score:
                away_win = False
                home_win = True
        elif state == 'pre':
            away_win = None
            home_win = None
            away_score = ''
            home_score = ''
        else:
            away_win = None
            home_win = None

        home_rank = home.get("curatedRank")['current']
        away_rank = away.get("curatedRank")['current']
        if home_rank == 99:
            home_rank = ''
        
        if away_rank == 99:
            away_rank = ''

        try:
            home_record = home.get("records")[0]['summary']
        except:
            home_record = '0-0'

        try:
            away_record = away.get("records")[0]['summary']
        except:
            away_record = '0-0'
    
        row = {"State" : state, "Home Code": home_name, "Away Code": away_name, 
               "Home Score": home_score, "Away Score": away_score, "Status": time_str, 
               "Home Win" : home_win, "Away Win" : away_win, "Home AP" : home_rank, "Away AP" : away_rank,
               "Home Record" : home_record, "Away Record" : away_record}
        add = pd.DataFrame([row])
        parsed = pd.concat([parsed, add])
      
    return parsed

def today_games_help_women(rank_df, master):
    json = scraper.fetch_espn_women_scoreboard()

    parsed = parse_espn_teams_and_times(json)
   
    def getName(code, master):
        [_, team] = scraper.getNameFromCode(code, master)
        if team is None:
            return code
        else:
            return team

    parsed['Home'] = parsed.apply(lambda x: getName(x['Home Code'], master), axis=1)
    parsed['Away'] = parsed.apply(lambda x: getName(x['Away Code'], master), axis=1)

    parsed["Model Rank Home"] = parsed.apply(
        lambda x: get_rank_women(x['Home'], rank_df, master), axis=1
    )
    parsed["Model Rank Away"] = parsed.apply(
        lambda x: get_rank_women(x['Away'], rank_df, master), axis=1
    )
    
    parsed["Model Rank Home"] = parsed["Model Rank Home"].apply(
        lambda x: int(x) if pd.notna(x) else ""
    )
    parsed["Model Rank Away"] =  parsed["Model Rank Away"].apply(
        lambda x: int(x) if pd.notna(x) else ""
    )

    parsed["Home Conf"] = parsed.apply(
        lambda x: get_conf_women(x['Home'], rank_df, master), axis=1
    )
    parsed["Away Conf"] = parsed.apply(
        lambda x: get_conf_women(x['Away'], rank_df, master), axis=1
    )

    power_conf = ["ACC", "B10", "B12", "SEC", "BE"]

    df = parsed.copy()

    if len(df) > 0:
        df["matchup_html"] = df.apply(
                lambda r: f"""
                <article class="game-card">
                    <div class="game-meta">
                        <div><span class="arena">{r['Status']}</span></div>
                    </div>
                    <div class="game-main">
                        <div class="teams">
                        <div class="team-row {teams.format_result(r['Away Win'])}">
                                <div class="team-left">
                                    {teams.fmt_team_logo(r['Away'])}
                                    <span class="team-name">{teams.rank_formatter(r['Model Rank Away'], r['Away'], r['Away AP'])}  ({r['Away Record']})</span>
                                </div>
                                <div class="team-right">
                                    <span class="score">{r['Away Score']}</span>
                                </div>
                            </div>
                            <div class="team-row {teams.format_result(r['Home Win'])}">
                                <div class="team-left">
                                    {teams.fmt_team_logo(r['Home'])}
                                    <span class="team-name">{teams.rank_formatter(r['Model Rank Home'], r['Home'], r['Home AP'])}  ({r['Home Record']})</span>
                                </div>
                                <div class="team-right">
                                    <span class="score">{r['Home Score']}</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </article>
                """,
                axis=1,
            )
        html_other = "<div class=\"scoreboard\">" + "\n".join(df["matchup_html"]) + "</div>"
    else:
        html_other = 'No games today.'
   
    if not html_other:
        html_other = f"No other women's games today."

    html = f"""
    <h3>Women's Games</h3>
    {html_other}
    """
    return html