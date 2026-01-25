"""
Scraping Torvik and Kenpom
"""
import json
from pathlib import Path
import utils
import os
import random
import time
import json
import re
from datetime import date, timedelta, datetime
import pandas as pd
from bs4 import BeautifulSoup
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from playwright.sync_api import sync_playwright
from tqdm import tqdm

TORVIK_PRE = "https://barttorvik.com/trankpre.php"
KENPOM = "https://kenpom.com/"
TORVIK = "https://barttorvik.com/#"

def fmt_team(team, rank):
    if rank == "N/A":
        return team
    return f"<strong>#{rank}</strong> {team}"

def meta_class(val):
    val = str(val).lower()

    if ":" in val:
        return "meta meta-upcoming"  # GREEN
    if "," not in val:
        return "meta meta-final"  # GREEN
    return "meta meta-live"  # scheduled

def getUrl(name):
    if name is None:
        return f'/assets/images/default.png' 
    link = f'/assets/images/{name}' 
    return link

def image_formatter(url):
    if url is None:
        return ''
    return f'<img src="{url}" class="team-logo" >'

def getTeamRanks():
    path = Path(utils.get_path("docs/assets/data/ranks.json"))

    if not path.exists():
        return {}

    with open(path, "r") as f:
        return json.load(f)

def saveTeamRanks(data):
    path = Path(utils.get_path("docs/assets/data/ranks.json"))

    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        
def getWTeamRanks():
    path = Path(utils.get_path("docs/assets/data/wranks.json"))

    if not path.exists():
        return {}

    with open(path, "r") as f:
        return json.load(f)

def saveWTeamRanks(data):
    path = Path(utils.get_path("docs/assets/data/wranks.json"))

    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def getMasterTeams():
    '''
    Helper function for getting master teams DF

    :return: Master DataFrame
    :rtype: DataFrame
    '''
    df_back = pd.read_json(utils.get_path("docs/assets/data/master.json"))
    return df_back

def saveMasterTeams(df):
    '''
    Helper function for saving master teams DF
    
    :param df: Master DF to save
    :type df: DataFrame
    '''
    df.to_json(utils.get_path("docs/assets/data/master.json"))

def get_image_name(team):
    '''
    Returns file path for logo
    
    :param team: Name of team
    :type team: str
    :return: Path to image
    :rtype: str
    '''
    master = getMasterTeams()
    try:
        s_exploded = master["names"].explode()
        boolean_mask_exploded = s_exploded == team
        # To get the row IDs where the value is present:
        # matching_ids = s_exploded[boolean_mask_exploded].index.unique()
        boolean_mask_original = boolean_mask_exploded.groupby(level=0).any()
        df_result = master[boolean_mask_original]
        if df_result.empty:
            print(f'get_image_name::df result empty for: {team}')
            return None
        else:
            names = list(df_result.names)[0]
    except:
        print(f'get_image_name::names list invalid for: {team}')
        return None
    img_path = utils.get_path('docs/assets/images')
    files = os.listdir(img_path)
    files_strip = [x[:-4] for x in files]
    master['path'] = ''
    for index, file in enumerate(files_strip):
        if file in names:
            return files[index]

def getHTML(link, retries=5, base_delay=1.0):
    '''
    Retrieves HTML for provided link
    
    :param link: Link to request
    :type link: str
    :param retries: Max # of retries allowed
    :type retries: int
    :param base_delay: Starting delay, randomly increments each retry 
    :type base_delay: float
    :return: Parsed HTML for webpage | None
    :rtype: BeautiulSoup | NoneType
    '''
    for attempt in range(retries):
        response = requests.get(link)
        if response.status_code == 429:
            if attempt < retries - 1:
                delay = base_delay * (2**attempt) + random.uniform(0, 0.2)
                print(f"Sleeping for: {delay} seconds.")
                time.sleep(delay)
                continue
        if response.status_code == 200:
            content = response.text
            return BeautifulSoup(content, "lxml")
    print("getHTML returning None")
    return None


def get_rank(row, rank_df, master, bin):
    if bin == 1:
        [index, code_name] = getNameFromCode(row.code1, master)

        rank_row = rank_df.loc[
            (rank_df["Team"] == row.team1)
            | (rank_df["Team"] == code_name)
            | (rank_df["index"] == index)
        ]

        if rank_row.empty:
            pass
        else:
            return list(rank_row["Ovr"])[0]
    else:
        [index, code_name] = getNameFromCode(row.code2, master)
        rank_row = rank_df.loc[
            (rank_df["Team"] == row.team2)
            | (rank_df["Team"] == code_name)
            | (rank_df["index"] == index)
        ]

        if rank_row.empty:
            return
        else:
            return list(rank_row["Ovr"])[0]

def get_record_men(team, rank_df, master):
    
    [index, code_name] = getNameFromCode(team, master)

    rank_row = rank_df.loc[
        (rank_df["Team"] == team)
        | (rank_df["Team"] == code_name)
        | (rank_df["index"] == index)
    ]

    if rank_row.empty:
        pass
    else:
        return list(rank_row["Record"])[0]

    return None
def get_rank_men(team, rank_df, master):

    [index, code_name] = getNameFromCode(team, master)

    rank_row = rank_df.loc[
        (rank_df["Team"] == team)
        | (rank_df["Team"] == code_name)
        | (rank_df["index"] == index)
    ]

    if rank_row.empty:
        pass
    else:
        return list(rank_row["Ovr"])[0]

    return None

def get_rank_women(team, rank_df, master):

    [index, code_name] = getNameFromCode(team, master)

    rank_row = rank_df.loc[
        (rank_df["Team"] == team)
        | (rank_df["Team"] == code_name)
        | (rank_df["index"] == index)
    ]

    if rank_row.empty:
        pass
    else:
        return list(rank_row["Ovr"])[0]

    return None

def parse_arena_gender(team):
    if pd.isna(team):
        return pd.NA, True, True

    team_lower = team.lower()

    if " men" in team_lower:
        return team.replace(" men", ""), True, False
    elif " women" in team_lower:
        return team.replace(" women", ""), False, True
    else:
        return team, True, True

# ARENAS
def arenas():
    
    path = utils.get_path('arenas.html')
    dfs = pd.read_html(path)
    active = dfs[1]
    offsite = dfs[3]
    combo = pd.concat([active, offsite])
    combo = combo.reset_index(drop=True)
    combo["City"] = combo["City"].str.replace(r"\[.*?\]", "", regex=True).str.strip()
    combo["Arena"] = combo["Arena"].str.replace(r"\[.*?\]", "", regex=True).str.strip()
    combo["Team"] = combo["Team"].str.replace(r"\[.*?\]", "", regex=True).str.strip()
    combo = combo.drop(columns=['Image', 'Conference', 'Opened', 'Capacity'])
    combo[["Team", "men_home", "women_home"]] = (
        combo["Team"]
        .apply(lambda x: pd.Series(parse_arena_gender(x)))
    )
    combo.to_json(utils.get_path('data/teams/arenas.json'))

ESPN_W_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/"
    "basketball/womens-college-basketball/scoreboard"
)

def fetch_espn_women_scoreboard(params=None, timeout=20):
    session = requests.Session()

    retries = Retry(
        total=5,
        backoff_factor=0.7,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )

    session.mount("https://", HTTPAdapter(max_retries=retries))

    r = session.get(
        ESPN_W_URL,
        params=params or {},
        timeout=timeout,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    r.raise_for_status()
    return r.json()

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

def get_conf_women(team, rank_df, master):
    [index, code_name] = getNameFromCode(team, master)
    rank_row = rank_df.loc[
        (rank_df["Team"] == team)
        | (rank_df["Team"] == code_name)
        #| (rank_df["index"] == index)
    ]
    if rank_row.empty:
        return
    else:
        return list(rank_row["Conf"])[0]

def getConf(row, rank_df, master, bin):
    if bin == 1:
        [index, code_name] = getNameFromCode(row.code1, master)
        rank_row = rank_df.loc[
            (rank_df["Team"] == row.team1)
            | (rank_df["Team"] == code_name)
            #| (rank_df["index"] == index)
        ]
        if rank_row.empty:
            return
        else:
            return list(rank_row["Conf"])[0]
    else:
        [index, code_name] = getNameFromCode(row.code2, master)
        rank_row = rank_df.loc[
            (rank_df["Team"] == row.team2)
            | (rank_df["Team"] == code_name)
            | (rank_df["index"] == index)
        ]
        if rank_row.empty:
            return
        else:
            return list(rank_row["Conf"])[0]

def getConference(team, rank_df):
    master = getMasterTeams()
    [index, code_name] = getNameFromCode(team, master)
    rank_row = rank_df.loc[
            (rank_df["Team"] == team)
            | (rank_df["Team"] == code_name)]
    if rank_row.empty:
        return
    else:
        return list(rank_row["Conf"])[0]

def slow_scrape_times():
    time_dict = {}

    today = date.today()
    day_iter = today + timedelta(days=0)
    end_date = date(2026, 3, 8)
    
    total_size = (end_date-today).days

    with tqdm(total=total_size, desc="Scraping times") as pbar:
        prev_day = None

        while day_iter <= end_date:
            
            str_iter = day_iter.strftime(f'%Y%m%d')
            time.sleep(1)
            url = f'https://www.cbssports.com/college-basketball/schedule/ALL/{str_iter}'
            soup = getHTML(url)

            if soup is None:
                print(f"Skipping {str_iter} - Error with getting HTML")
                day_iter += timedelta(days=1)
                pbar.update(1)
                continue
            
            times = [a.get_text(strip=True)
                for a in soup.select('a[href="/college-basketball/scoreboard/"]')]
            
            if len(times) == 0:
                day_iter += timedelta(days=1)
                pbar.update(1)
                continue

            times = [t for t in times if t != "TBA"]

            has_midnight = "12:00 am" in times
            times = [t for t in times if t != "12:00 am"]

             # If midnight exists, patch previous day
            if has_midnight and prev_day in time_dict:
                time_dict[prev_day][1] = "11:59 pm"
            
            if len(times) == 0:
                day_iter += timedelta(days=1)
                pbar.update(1)
                continue

            sorted_times = sorted(
                times,
                key=lambda t: datetime.strptime(t, "%I:%M %p")
            )

            time_dict[day_iter] = [sorted_times[0], sorted_times[-1]]
            prev_day = day_iter

            day_iter += timedelta(days=1)
            pbar.update(1)

        json_ready = {
            d.isoformat(): v
            for d, v in time_dict.items()
        }
        with open(utils.get_path('data/times.json'), "w") as f:
            json.dump(json_ready, f, indent=2)

def getNameFromCode(code, master, ret_abbrev=False):
    s_exploded = master["names"].explode()
    boolean_mask_exploded = s_exploded == code
    # To get the row IDs where the value is present:
    # matching_ids = s_exploded[boolean_mask_exploded].index.unique()
    boolean_mask_original = boolean_mask_exploded.groupby(level=0).any()
    df_result = master[boolean_mask_original]
    if df_result.empty:
        if ret_abbrev:
            return [None, None, None]
        return [None, None]
    else:
        if ret_abbrev:
            return [list(df_result["index"])[0], list(df_result["team"])[0], list(df_result["short"])[0]]
        return [list(df_result["index"])[0], list(df_result["team"])[0]]

def game_status(soup, gender):
    if gender == "M":
        games = soup.find_all("div", class_="CellGame")
        times = [
                game.find("a").text.strip() for game in games if game.find("a") is not None
            ]
        return times
    elif gender == "W":
        GAME_STATES = {"pregame", "ingame", "postgame"}
        cards = soup.select("div.single-score-card.womenscollegebasketball")
        ordered_games = []

        for idx, card in enumerate(cards):
            classes = set(card.get("class", []))
            state = next((c for c in classes if c in GAME_STATES), "unknown")

            if (state == 'postgame') | (state == 'ingame'):
                totals = [total.text for total in card.find_all("td", class_='total')]
                teams = [name.text for name in card.find_all("span", class_='team-name-link')]
                if (state == 'postgame'):
                    ordered_games.append(f'{teams[0]} {totals[0]} - {teams[1]} {totals[1]}')
                elif (state == 'ingame'):
                    time = card.find("div", class_='game-status emphasis').text
                    ordered_games.append(f'{teams[0]} {totals[0]}, {teams[1]} {totals[1]} - {time}')
            else: 
                time = card.find("span", class_='formatter').text
                ordered_games.append(time)
        return ordered_games

def parse_rank(team):
    """
    Returns (clean_team_name, rank or None)
    """
    if pd.isna(team):
        return team, None

    match = re.match(r"^\s*(\d+)\s+(.*)", team)
    if match:
        return match.group(2), int(match.group(1))
    else:
        return team, None

def parse_live(row, master):
    if pd.isna(row['Time/TV']):
        return None, None, None

    # Extract the two scores
    # MORGAN 66, SCST 63 - 2nd  ESP+
    # ARKPB 60, TEXSO 52 - 2nd
    pattern = r"([A-Z]+)\s(\d+),\s([A-Z]+)\s(\d+)\s-\s(\w+)(?:\s\s(.+))?$"
    match = re.search(pattern, row['Time/TV'])

    if not match:
        return None, None, None, None

    code1 = match.group(1)
    score1 = int(match.group(2))
    code2 = match.group(3)
    score2 = int(match.group(4))
    status = match.group(5)

    tv = match.group(6) if match.group(6) else ''

    team1 = getNameFromCode(code1, master)
    team2 = getNameFromCode(code2, master)
    team1_name = team1[1]
    team2_name = team2[1]
    home = row['Home']
    away = row['Away']

    home_check = getNameFromCode(home, master)[1]
    away_check = getNameFromCode(away, master)[1]

    if (team1_name == home_check) | (team2_name == away_check):
        home_score = score1
        away_score = score2
    elif (team1_name == away_check) | (team2_name == home_check):
        home_score = score2
        away_score = score1
    else:
        print(f'Err: Team1N: {team1_name}, Team2N: {team2_name}, Home: {home}, Away: {away}')
        return None, None, None, None
 
    return away_score, home_score, status, tv


def parse_results(row, master):
    if pd.isna(row['Result']):
        return None, None, None, None
    
    # Extract the two scores
    match = re.search(r"(\D*)\s([0-9]+)\s-\s(\D*)\s([0-9]+)",row['Result'])

    if not match:
        return None, None, None, None
    
    code1 = match.group(1)
    score1 = int(match.group(2))
    code2 = match.group(3)
    score2 = int(match.group(4))
    
    team1 = getNameFromCode(code1, master)
    team2 = getNameFromCode(code2, master)
    team1_name = team1[1]
    team2_name = team2[1]
    home = row['Home']
    away = row['Away']

    home_check = getNameFromCode(home, master)[1]
    away_check = getNameFromCode(away, master)[1]

    if (team1_name == home_check) | (team2_name == away_check):
        home_score = score1
        away_score = score2
    elif (team1_name == away_check) | (team2_name == home_check):
        home_score = score2
        away_score = score1
    else:
        print(f'Err: Team1N: {team1_name}, Team2N: {team2_name}, Home: {home}, Away: {away}')
    # Home team is listed first in your Result column
    home_win = home_score > away_score
    away_win = away_score > home_score

    return away_score, home_score, away_win, home_win

def get_p5(df):
    power_conf = ["ACC", "B10", "B12", "SEC", "BE"]
    specific = ['Gonzaga']
    
    p5 = df[
        (((df["Away Conf"].isin(power_conf)) | df['Away'].isin(specific))
        & (df["Home Conf"].isin(power_conf) | df['Home'].isin(specific))) |
        ((pd.notna(df['Away Rank'])) | (pd.notna(df['Home Rank'])))
    ]

    return p5

def check(row, arenas):
    dict_path = utils.get_path('data/teams/neutral.json')
    with open(dict_path, 'r') as file:
        data_dict = json.load(file)
    venue = row['Venue']
    team = row['Home']
    match = arenas[arenas['Arena'] == venue]
    neutral = data_dict.get(venue)
    # {'City': 'St. Louis', 'State': 'MO'}
    if not match.empty:
        city = list(match['City'])[0]
        state = list(match['State'])[0]
        return f'{city}, {state}'
    elif neutral is not None:
        city = neutral['City']
        state = neutral['State']
        return f'{city}, {state}'
    else:
        print(f'No match for: {venue}, team: {team}')
        data_dict[row['Venue']] = {"City" : None, "State" : None}
    
        with open(dict_path, "w") as json_file:
            json.dump(data_dict, json_file, indent=4)

        return None
    
def parse_mens_cbs(soup: BeautifulSoup, master: pd.DataFrame, rank_df):
    arenas = pd.read_json(utils.get_path('data/teams/arenas.json'))

    # if empty -> empty list
    tables = soup.find_all('table')

    if tables:
        dfs = pd.read_html(str(tables))
    else:
        dfs = []
        print('parse_mens_cbs::No tables found in soup.')

    def getDone(done):
        # df[0] - finished games
        # Away, Home, Results w AP Rank
        done[["Away", "Away Rank"]] = (
            done["Away"]
            .apply(lambda x: pd.Series(parse_rank(x)))
        )
        done[["Home", "Home Rank"]] = (
            done["Home"]
            .apply(lambda x: pd.Series(parse_rank(x)))
        )
        done["Away Rank"] = done["Away Rank"].astype("Int64")
        done["Home Rank"] = done["Home Rank"].astype("Int64")

        done[["Away Score", "Home Score", "Away Win", "Home Win"]] = (
            done.apply(lambda x: pd.Series(parse_results(x, master)), axis=1)
        )
        done["Away Score"] = done["Away Score"].astype("Int64")
        done["Home Score"] = done["Home Score"].astype("Int64")

        done["Away Win"] = done["Away Win"].astype("boolean")
        done["Home Win"] = done["Home Win"].astype("boolean")

        done['Model Home'] = done.apply(lambda x: get_rank_men(x['Home'], rank_df, master), axis=1)
        done['Model Away'] = done.apply(lambda x: get_rank_men(x['Away'], rank_df, master), axis=1)

        done['Record Home'] = done.apply(lambda x: get_record_men(x['Home'], rank_df, master), axis=1)
        done['Record Away'] = done.apply(lambda x: get_record_men(x['Away'], rank_df, master), axis=1)

        done['Model Home'] = done['Model Home'].astype("Int64") 
        done['Model Away'] = done['Model Away'].astype("Int64") 
        done["Model Home"] = done["Model Home"].astype("string").fillna("")
        done["Model Away"] = done["Model Away"].astype("string").fillna("")
        done["Home Conf"] = done['Home'].apply(lambda x: getConference(x, rank_df))
        done["Away Conf"] = done['Away'].apply(lambda x: getConference(x, rank_df))
        p5_done = get_p5(done)
        done = done.drop(index=p5_done.index)
        return [p5_done, done]

    def getLive(live_upcoming):
        # df[1] - active & upcoming
        # Away, Home, Time/TV, Streaming, Venue, Tickets
        live_upcoming = live_upcoming.drop(columns=['Buy Tickets'])
        live_upcoming [["Away", "Away Rank"]] = (
            live_upcoming ["Away"]
            .apply(lambda x: pd.Series(parse_rank(x)))
        )
        live_upcoming [["Home", "Home Rank"]] = (
            live_upcoming ["Home"]
            .apply(lambda x: pd.Series(parse_rank(x)))
        )
        live_upcoming["Away Rank"] = live_upcoming["Away Rank"].astype("Int64")
        live_upcoming["Home Rank"] = live_upcoming["Home Rank"].astype("Int64")
        live_upcoming[["Away Score", "Home Score", "Status", "TV"]] = (
            live_upcoming
            .apply(lambda x: pd.Series(parse_live(x, master)), axis=1)
        )
        live_upcoming["Away Score"] = live_upcoming["Away Score"].astype("Int64")
        live_upcoming["Home Score"] = live_upcoming["Home Score"].astype("Int64")

        live_upcoming['Location'] = live_upcoming.apply(lambda x: check(x, arenas), axis=1 )

        live_upcoming["Home Conf"] = live_upcoming['Home'].apply(lambda x: getConference(x, rank_df))
        live_upcoming["Away Conf"] = live_upcoming['Away'].apply(lambda x: getConference(x, rank_df))

        live_upcoming['Model Home'] = live_upcoming.apply(lambda x: get_rank_men(x['Home'], rank_df, master), axis=1)
        live_upcoming['Model Away'] = live_upcoming.apply(lambda x: get_rank_men(x['Away'], rank_df, master), axis=1)

        live_upcoming['Record Home'] = live_upcoming.apply(lambda x: get_record_men(x['Home'], rank_df, master), axis=1)
        live_upcoming['Record Away'] = live_upcoming.apply(lambda x: get_record_men(x['Away'], rank_df, master), axis=1)

        live_upcoming['Model Home'] = live_upcoming['Model Home'].astype("Int64") 
        live_upcoming['Model Away'] = live_upcoming['Model Away'].astype("Int64") 
        live_upcoming["Model Home"] = live_upcoming["Model Home"].astype("string").fillna("")
        live_upcoming["Model Away"] = live_upcoming["Model Away"].astype("string").fillna("")

        p5_live = get_p5(live_upcoming)
        live_upcoming = live_upcoming.drop(index=p5_live.index)
        return [p5_live, live_upcoming]

    if len(dfs) == 2:
        [p5done, done] = getDone(dfs[0])
        [p5live, live_upcoming] = getLive(dfs[1])
    elif len(dfs) == 1:
        if 'Time/TV' in dfs[0].columns:
            [p5done, done] = [pd.DataFrame(), pd.DataFrame()]
            [p5live, live_upcoming] = getLive(dfs[0])
        else:
            [p5done, done] = getDone(dfs[0])
            [p5live, live_upcoming] = [pd.DataFrame(), pd.DataFrame()]
    elif len(dfs) > 2:
        print('parse_mens_cbs::More than two tables found in soup. Err.')
    elif len(dfs) < 1:
        print('parse_mens_cbs::No tables found in soup. Err.')
    else:
        print('parse_mens_cbs::Hit else statement. Err.')
    return [p5live, p5done, done, live_upcoming]

def today_games_help_women(rank_df, master):
    json = fetch_espn_women_scoreboard()

    parsed = parse_espn_teams_and_times(json)
   
    def getName(code, master):
        [_, team] = getNameFromCode(code, master)
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

    df = parsed.copy()
    sort_map = {"in" : 0, "pre" : 1, "post" : 2}
    df = df.sort_values(by="State", key=lambda s: s.map(sort_map))
    if len(df) > 0:
        df["matchup_html"] = df.apply(
                lambda r: f"""
                <article class="game-card">
                    <div class="game-meta">
                        <div><span class="arena">{r['Status']}</span></div>
                    </div>
                    <div class="game-main">
                        <div class="teams">
                        <div class="team-row {format_result(r['Away Win'])}">
                                <div class="team-left">
                                    {image_formatter(getUrl(get_image_name(r['Away'])))}
                                    <span class="team-name">{rank_formatter(r['Model Rank Away'], r['Away'], r['Away AP'])}  ({r['Away Record']})</span>
                                </div>
                                <div class="team-right">
                                    <span class="score">{r['Away Score']}</span>
                                </div>
                            </div>
                            <div class="team-row {format_result(r['Home Win'])}">
                                <div class="team-left">
                                    {image_formatter(getUrl(get_image_name(r['Home'])))}
                                    <span class="team-name">{rank_formatter(r['Model Rank Home'], r['Home'], r['Home AP'])}  ({r['Home Record']})</span>
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

def fmt_team_live(ap_rank, team, score, model_rank):
    if ap_rank == "":
        ap_rank_html = ""
    else:
        ap_rank_html = f" <strong> ({ap_rank})</strong>"

    if model_rank == "":
        model_rank_html = ""
    else:
        model_rank_html = f"<strong> #{model_rank}</strong>"
    html = model_rank_html + ' ' + ap_rank_html + ' ' + team 
    return html

def rank_formatter(model, team, ap):
    if model == "":
        model_html = ""
    else: 
        model_html = f" <strong>#{model}</strong>"

    if ap == "":
        ap_html = ""
    else: 
        ap_html = f" <strong>({ap})</strong> "

    return ap_html + team + model_html

def format_result(res):
    if res:
        return 'winner'
    elif res == False:
        return 'loser'
    else:
        return ''

def fmt_live(row):
    # live game -> Status, Tv
    # upcoming -> Status/TV None, use TIme/TV
    if (row['Status'] is None) & (row['TV'] is None):
        html = row['Time/TV']
    else: 
        html = f"{row['Status']} {row['TV']}"
    return html

def today_games_help_men(p5live, p5done, done, live):
    '''
    DONE COLS: 
    Away, Home, Result, Away Rank, Home Rank, Away Score, Home Score, 
    Away Win, Home Win, Home Conf, Away Conf
    
    LIVE COLS:
    Away, Home, Time/TV, Streaming, Venue, Away Rank, Home Rank, Away Score, Home Score,
    Status, TV, Location, Home Conf, Away Conf
    '''
    html_live = ''
    html_done = ''
    html_p5live = ''
    html_p5done = ''
    if len(live) > 0:
        live["Home Rank"] = live["Home Rank"].astype("string").fillna("")
        live["Away Rank"] = live["Away Rank"].astype("string").fillna("")
        live["matchup_html"] = live.apply(
            lambda r: f"""
            <article class="game-card">
                <div class="game-meta">
                    <div><span class="arena">{fmt_live(r)}</span></div>
                </div>
                <div class="game-main">
                    <div class="teams">
                        <div class="team-row">
                            <div class="team-left">
                                {image_formatter(getUrl(get_image_name(r['Away'])))}
                                <span class="team-name">{rank_formatter(r['Model Away'], r['Away'], r['Away Rank'])} ({r['Record Away']})</span>
                            </div>
                            <div class="team-right">
                                <span class="score">{r['Away Score']}</span>
                            </div>
                        </div>
                        <div class="team-row">
                            <div class="team-left">
                                {image_formatter(getUrl(get_image_name(r['Home'])))}
                                <span class="team-name">{rank_formatter(r['Model Home'], r['Home'], r['Home Rank'])} ({r['Record Home']})</span>
                            </div>
                            <div class="team-right">
                                <span class="score">{r['Home Score']}</span>
                            </div>
                        </div>
                    </div>
                    <div class="game-meta">
                        <div><span class="arena">{r['Venue']}, {r['Location']}</span></div>
                    </div>
                </div>
            </article>
            """,
            axis=1,
        )
        html_live = "<div class=\"scoreboard\">" + "\n".join(live["matchup_html"]) + "</div>"

    if len(p5live) > 0:
        p5live["Home Rank"] = p5live["Home Rank"].astype("string").fillna("")
        p5live["Away Rank"] = p5live["Away Rank"].astype("string").fillna("")
        p5live["matchup_html"] = p5live.apply(
            lambda r: f"""
            <article class="game-card">
                <div class="game-meta">
                    <div><span class="arena">{fmt_live(r)}</span></div>
                </div>
                <div class="game-main">
                    <div class="teams">
                        <div class="team-row">
                            <div class="team-left">
                                {image_formatter(getUrl(get_image_name(r['Away'])))}
                                <span class="team-name">{rank_formatter(r['Model Away'], r['Away'], r['Away Rank'])} ({r['Record Away']})</span>
                            </div>
                            <div class="team-right">
                                <span class="score">{r['Away Score']}</span>
                            </div>
                        </div>
                        <div class="team-row">
                            <div class="team-left">
                                {image_formatter(getUrl(get_image_name(r['Home'])))}
                                <span class="team-name">{rank_formatter(r['Model Home'], r['Home'], r['Home Rank'])} ({r['Record Home']})</span>
                            </div>
                            <div class="team-right">
                                <span class="score">{r['Home Score']}</span>
                            </div>
                        </div>
                    </div>
                    <div class="game-meta">
                        <div><span class="arena">{r['Venue']}, {r['Location']}</span></div>
                    </div>
                </div>
            </article>
            """,
            axis=1,
        )
        html_p5live = "<div class=\"scoreboard\">" + "\n".join(p5live["matchup_html"]) + "</div>"

    if len(done) > 0:
        done["Home Rank"] = done["Home Rank"].astype("string").fillna("")
        done["Away Rank"] = done["Away Rank"].astype("string").fillna("")
        done["matchup_html"] = done.apply(
            lambda r: f"""
            <article class="game-card">
                <div class="game-main">
                    <div class="teams">
                        <div class="team-row {format_result(r['Away Win'])}">
                            <div class="team-left">
                                {image_formatter(getUrl(get_image_name(r['Away'])))}
                                <span class="team-name">{rank_formatter(r['Model Away'], r['Away'], r['Away Rank'])} ({r['Record Away']})</span>
                            </div>
                            <div class="team-right">
                                <span class="score">{r['Away Score']}</span>
                            </div>
                        </div>
                        <div class="team-row {format_result(r['Home Win'])}">
                            <div class="team-left">
                                {image_formatter(getUrl(get_image_name(r['Home'])))}
                                <span class="team-name">{rank_formatter(r['Model Home'], r['Home'], r['Home Rank'])} ({r['Record Home']})</span>
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
        html_done = "<div class=\"scoreboard\">" + "\n".join(done["matchup_html"]) + "</div>"
    
    if len(p5done) > 0:
        p5done["Home Rank"] = p5done["Home Rank"].astype("string").fillna("")
        p5done["Away Rank"] = p5done["Away Rank"].astype("string").fillna("")
        p5done["matchup_html"] = p5done.apply(
            lambda r: f"""
            <article class="game-card">
                <div class="game-main">
                    <div class="teams">
                        <div class="team-row {format_result(r['Away Win'])}">
                            <div class="team-left">
                                {image_formatter(getUrl(get_image_name(r['Away'])))}
                                <span class="team-name">{rank_formatter(r['Model Away'], r['Away'], r['Away Rank'])} ({r['Record Away']})</span>
                            </div>
                            <div class="team-right">
                                <span class="score">{r['Away Score']}</span>
                            </div>
                        </div>
                        <div class="team-row {format_result(r['Home Win'])}">
                            <div class="team-left">
                                {image_formatter(getUrl(get_image_name(r['Home'])))}
                                <span class="team-name">{rank_formatter(r['Model Home'], r['Home'], r['Home Rank'])} ({r['Record Home']})</span>
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
        html_p5done = "<div class=\"scoreboard\">" + "\n".join(p5done["matchup_html"]) + "</div>"
    
    html = f'''
    <h3>Power 5 Matchups & Top 25 Teams</h3>
    {html_p5live}<br>
    {html_p5done}
    <h3>All Other Games</h3>
    {html_live}<br>
    {html_done}
    '''
    return html

def today_games(rank_df, gender):
    rank_df["index"] = (rank_df["Team"].rank(method="dense").astype(int)) - 1
    master = getMasterTeams()

    if gender == 'M':
        soup = getHTML("https://www.cbssports.com/college-basketball/schedule/")
        
        # Optional: Use prettify() for a nicely formatted, readable HTML output
        html_content = soup.prettify("utf-8")

        # Write the content to a file   
        with open("output_page.html", "wb") as file:
            file.write(html_content)
        [p5live, p5done, done, live] = parse_mens_cbs(soup, master, rank_df)
        html = today_games_help_men(p5live, p5done, done, live)

    elif gender == 'W':
        html = today_games_help_women(rank_df, master)
    
    return html

def update_master():
    master = getMasterTeams()
    path = utils.get_path("data/teams/redditCFB.html")
    with open(path, "r", encoding="utf-8") as f:
        html_content = f.read()
    soup = BeautifulSoup(html_content, "lxml")
    rows = soup.find_all("tr")
    team_data = pd.DataFrame()
    for team in rows:
        data = team.find_all("td")
        name = data[0].text
        abbr = data[1].text
        team_add = {"team": name.strip(), "names": [name.strip(), abbr.strip()]}
        new = pd.DataFrame([team_add])
        team_data = pd.concat([team_data, new], ignore_index=True)
    df = team_data.sort_values(by="team")
    df = df.reset_index(drop=True)
    df["Index"] = df.index
    merged = pd.merge(master, df, how="left", on="team")
    merged["names"] = merged.apply(
        lambda x: (
            list(set(x.names_x + x.names_y))
            if isinstance(x.names_x, list) and isinstance(x.names_y, list)
            else x.names_x
        ),
        axis=1,
    )
    merged = merged.drop(columns=["names_x", "names_y", "Index_y"])
    merged = merged.rename(columns={"Index_x": "index"})
    saveMasterTeams(merged)

def init_master_dict():
    path = utils.get_path("data/teams/team_table.html")
    with open(path, "r", encoding="utf-8") as f:
        html_content = f.read()
    soup = BeautifulSoup(html_content, "lxml")
    rows = soup.find_all("tr")
    team_data = pd.DataFrame()
    for team in rows:
        data = team.find_all("td")
        name = data[0].text
        mascot = data[1].text
        abbr = data[2].text

        team_add = {"team": name, "names": [name, mascot, abbr]}

        new = pd.DataFrame([team_add])
        team_data = pd.concat([team_data, new], ignore_index=True)
    df = team_data.sort_values(by="team")
    df = df.reset_index(drop=True)
    df["Index"] = df.index
    saveMasterTeams(df)

def kenpom_historic():
    # https://kenpom.com/index.php?y=2025
    all = []
    for year in range(2013, 2026):
        file = f"model_data/kenpom/kenpom{year}.html"
        with open(file) as fp:
            soup = BeautifulSoup(fp, "html.parser")
        table = soup.find("table")

        # --- Extract headers considering multi-row and colspan ---
        header_rows = table.find_all("tr")[:2]  # first two rows usually contain headers
        header_matrix = []

        for hr in header_rows:
            row_headers = []
            for cell in hr.find_all(["th", "td"]):
                text = cell.get_text(strip=True)
                colspan = int(cell.get("colspan", 1))
                row_headers.extend([text] * colspan if text else [""] * colspan)
            header_matrix.append(row_headers)

        # --- Merge multi-row headers and handle ranking columns ---
        num_cols = max(len(r) for r in header_matrix)
        final_headers = []
        seen = {}  # track occurrences for rank columns

        # Define replacements for readability
        replacements = {"Strength of Schedule": "SOS", "NCSOS": "NCSOS"}

        for col_idx in range(num_cols):
            parts = []
            for row in header_matrix:
                if col_idx < len(row) and row[col_idx]:
                    parts.append(row[col_idx])
            base_header = "_".join(parts) if parts else ""

            # Apply replacements for readability
            for long_name, short_name in replacements.items():
                base_header = base_header.replace(long_name, short_name)
            # Handle rank duplicates
            if base_header in seen:
                final_headers.append(f"{base_header}_Rk")
                seen[base_header] += 1
            else:
                final_headers.append(base_header)
                seen[base_header] = 1

        # --- Extract table rows ---
        rows = []
        for row in table.find_all("tr")[len(header_rows) :]:
            cols = [col.get_text(strip=True) for col in row.find_all("td")]
            if any(cols):
                rows.append(cols)

        # --- Convert to strings ---
        final_headers = [str(h) for h in final_headers]
        rows = [[str(c) for c in r] for r in rows]

        def sep_names(row):
            team = row[1]
            rm_space = team.replace(" ", "")
            pat = "(\D+)([0-9]{1,2})"
            match = re.match(pat, rm_space)

            if match != None:
                seed = match.group(2)
                if int(seed) > 9:
                    team = team[:-2]
                else:
                    team = team[:-1]
                row.insert(2, seed)
                row.insert(3, True)
                row.insert(4, year)
                row[1] = team
            else:
                row.insert(2, -1)
                row.insert(3, False)
                row.insert(4, year)
            return row

        [[sep_names(row) for row in rows]]
        final_headers.insert(2, "Seed")
        final_headers.insert(3, "Tourney")
        final_headers.insert(4, "Year")
        # --- Save to JSON ---
        output = {"headers": final_headers, "rows": rows}
        [all.append(row) for row in rows]
        # Save to JSON file
        path = utils.get_path(f"model_data/kenpom{year}.json")
        utils.save_json_data(output, path)
    path = utils.get_path(f"model_data/kenpom_all.json")
    utils.save_json_data(all, path)

# Get Kenpom data for TODAY   
def kenpom(date):
    #kenpom_resp = requests.get(KENPOM, timeout=10).text
    # torvik_pre_resp = requests.get(TORVIK_PRE, timeout=10).text
    with open(utils.get_path('kenpom_12126.html'), 'r', encoding='utf-8') as f:
            html = f.read()
    kenpom_soup = BeautifulSoup(html, "html.parser")
    # torvik_soup = BeautifulSoup(torvik_pre_resp, 'html.parser')

    table = kenpom_soup.find("table")

    # --- Extract headers considering multi-row and colspan ---
    header_rows = table.find_all("tr")[:2]  # first two rows usually contain headers
    header_matrix = []

    for hr in header_rows:
        row_headers = []
        for cell in hr.find_all(["th", "td"]):
            text = cell.get_text(strip=True)
            colspan = int(cell.get("colspan", 1))
            row_headers.extend([text] * colspan if text else [""] * colspan)
        header_matrix.append(row_headers)

    # --- Merge multi-row headers and handle ranking columns ---
    num_cols = max(len(r) for r in header_matrix)
    final_headers = []
    seen = {}  # track occurrences for rank columns

    # Define replacements for readability
    replacements = {"Strength of Schedule": "SOS", "NCSOS": "NCSOS"}

    for col_idx in range(num_cols):
        parts = []
        for row in header_matrix:
            if col_idx < len(row) and row[col_idx]:
                parts.append(row[col_idx])
        base_header = "_".join(parts) if parts else ""

        # Apply replacements for readability
        for long_name, short_name in replacements.items():
            base_header = base_header.replace(long_name, short_name)
        # Handle rank duplicates
        if base_header in seen:
            final_headers.append(f"{base_header}_Rk")
            seen[base_header] += 1
        else:
            final_headers.append(base_header)
            seen[base_header] = 1

    # --- Extract table rows ---
    rows = []
    for row in table.find_all("tr")[len(header_rows) :]:
        cols = [col.get_text(strip=True) for col in row.find_all("td")]
        if any(cols):
            rows.append(cols)

    # --- Convert to strings ---
    final_headers = [str(h) for h in final_headers]
    rows = [[str(c) for c in r] for r in rows]

    # --- Save to JSON ---
    output = {"headers": final_headers, "rows": rows}

    # Save to JSON file
    path = utils.get_path(f"data/men/kenpom/kenpom{date}.json")
    utils.save_json_data(output, path)

# Get Torvik data for TODAY
def torvik(date):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)  # Runs without a UI
        page = browser.new_page()
        page.goto("https://barttorvik.com/#")
        time.sleep(5)
        # --- Get the page source and parse with BeautifulSoup ---
        html = page.content()
        soup = BeautifulSoup(html, "html.parser")
        # --- Extract table headers ---
        table = soup.find("table")  # assumes one main table; adjust if multiple
        headers = []

        # Try <th> first
        table_rows = table.find_all("tr")
        header_row = table_rows[1]
        if header_row:
            # Grab text from either <th> or <td>
            headers = [
                cell.get_text(strip=True) for cell in header_row.find_all(["th", "td"])
            ]
        # --- Extract table rows ---
        rows = []
        for row in table.find_all("tr"):
            cols = [col.get_text(strip=True) for col in row.find_all("td")]
            if any(cols):  # skip empty rows
                rows.append(cols)

        # Remove first row from rows if it was used as headers
        if rows and rows[0] == headers:
            rows = rows[1:]

        # --- Convert everything to strings to avoid JSON errors ---
        headers = [str(h) for h in headers]
        rows = [[str(c) for c in r] for r in rows]

        # --- Save to JSON ---
        output = {"headers": headers, "rows": rows}
        path = utils.get_path(f"data/men/torvik/torvik{date}.json")
        utils.save_json_data(output, path)
        browser.close()

# Get women's Torvik data TODAY
def torvik_w(date):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)  # Runs without a UI
        page = browser.new_page()
        page.goto("https://barttorvik.com/ncaaw/#")
        time.sleep(5)
        # --- Get the page source and parse with BeautifulSoup ---
        html = page.content()
        soup = BeautifulSoup(html, "html.parser")
        # --- Extract table headers ---
        table = soup.find("table")  # assumes one main table; adjust if multiple
        headers = []

        # Try <th> first
        table_rows = table.find_all("tr")
        header_row = table_rows[1]
        if header_row:
            # Grab text from either <th> or <td>
            headers = [
                cell.get_text(strip=True) for cell in header_row.find_all(["th", "td"])
            ]
        # --- Extract table rows ---
        rows = []
        for row in table.find_all("tr"):
            cols = [col.get_text(strip=True) for col in row.find_all("td")]
            if any(cols):  # skip empty rows
                pattern = r"(^[^\\(]+)"
                match = re.findall(pattern, cols[1])
                if any(match):
                    cols[1] = match[0]
                rows.append(cols)

        # Remove first row from rows if it was used as headers
        if rows and rows[0] == headers:
            rows = rows[1:]

        # --- Convert everything to strings to avoid JSON errors ---
        headers = [str(h) for h in headers]
        rows = [[str(c) for c in r] for r in rows]

        # --- Save to JSON ---
        output = {"headers": headers, "rows": rows}
        path = utils.get_path(f"data/women/torvik{date}.json")
        utils.save_json_data(output, path)
        browser.close()

# Get HISTORICAL Women's Torvik Data
def torvik_w_hist():
    years = [2021, 2022, 2023, 2024, 2025]
    all = []
    for year in years:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)  # Runs without a UI
            page = browser.new_page()
            link = f"https://barttorvik.com/ncaaw/trank.php?year={year}#"
            page.goto(link)
            time.sleep(5)
            # --- Get the page source and parse with BeautifulSoup ---
            html = page.content()
            soup = BeautifulSoup(html, "html.parser")
            # --- Extract table headers ---
            table = soup.find("table")  # assumes one main table; adjust if multiple
            headers = []

            # Try <th> first
            table_rows = table.find_all("tr")
            header_row = table_rows[1]
            if header_row:
                # Grab text from either <th> or <td>
                headers = [
                    cell.get_text(strip=True)
                    for cell in header_row.find_all(["th", "td"])
                ]
                if any(headers):
                    headers.insert(2, "Seed")
                    headers.insert(3, "Finish")
                    headers.insert(4, "Tourney")
                    headers.insert(5, "Year")
            # --- Extract table rows ---
            rows = []
            for row in table.find_all("tr"):
                cols = [col.get_text(strip=True) for col in row.find_all("td")]
                if any(cols):  # skip empty rows
                    pattern = r"^([^\d]*)(\d{1,2}) seed,([A-Za-z]*)"
                    match = re.findall(pattern, cols[1])
                    if any(match):
                        cols[1] = match[0][0]
                        cols.insert(2, match[0][1])
                        cols.insert(3, match[0][2])
                        cols.insert(4, True)
                        cols.insert(5, year)
                    else:
                        cols.insert(2, False)
                        cols.insert(3, False)
                        cols.insert(4, False)
                        cols.insert(5, year)
                    rows.append(cols)

            # Remove first row from rows if it was used as headers
            if rows and rows[0] == headers:
                rows = rows[1:]

            # --- Convert everything to strings to avoid JSON errors ---
            headers = [str(h) for h in headers]
            rows = [[str(c) for c in r] for r in rows]

            # --- Save to JSON ---
            output = {"headers": headers, "rows": rows}
            [all.append(row) for row in rows]

            path = utils.get_path(f"model_data_w/torvik_w{year}.json")
            utils.save_json_data(output, path)
            browser.close()

    path = utils.get_path(f"model_data_w/torvik_w_all.json")
    utils.save_json_data(all, path)