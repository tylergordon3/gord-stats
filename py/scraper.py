"""
Scraping Torvik and Kenpom
"""

import utils
import os
import random
import time
import re
from datetime import date
import pandas as pd
from bs4 import BeautifulSoup
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from playwright.sync_api import sync_playwright

TORVIK_PRE = "https://barttorvik.com/trankpre.php"
KENPOM = "https://kenpom.com/"
TORVIK = "https://barttorvik.com/#"


def getMasterTeams():
    '''
    Helper function for getting master teams DF

    :return: Master DataFrame
    :rtype: DataFrame
    '''
    df_back = pd.read_json(utils.get_path("data/teams/master.json"))
    return df_back

def saveMasterTeams(df):
    '''
    Helper function for saving master teams DF
    
    :param df: Master DF to save
    :type df: DataFrame
    '''
    df.to_json(utils.get_path("data/teams/master.json"))

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
            return list(rank_row["Overall"])[0]
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
            return list(rank_row["Overall"])[0]

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
    teams = []
    times_scores = []

    for event in data.get("events", []):
        competition = event["competitions"][0]
        status = competition["status"]["type"]
        state = status["state"]  # pre / in / post

        competitors = competition["competitors"]
        away = next(c for c in competitors if c["homeAway"] == "away")
        home = next(c for c in competitors if c["homeAway"] == "home")

        away_name = away["team"]["abbreviation"]
        home_name = home["team"]["abbreviation"]

        teams.extend([away_name, home_name])

        # Decide time / score display
        if state == "pre":
            # Scheduled
            time_str = status.get("shortDetail")  # "7:00 PM"
            times_scores.extend([time_str, time_str])

        elif state == "post":
            # Final
            away_score = away.get("score")
            home_score = home.get("score")
            score_str = f"{away_score}-{home_score}"
            times_scores.extend([score_str, score_str])

        else:
            # In progress
            live_str = status.get("shortDetail")  # "3Q 4:21"
            times_scores.extend([live_str, live_str])
    return teams, times_scores

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


def getNameFromCode(code, master):
    s_exploded = master["names"].explode()
    boolean_mask_exploded = s_exploded == code
    # To get the row IDs where the value is present:
    # matching_ids = s_exploded[boolean_mask_exploded].index.unique()
    boolean_mask_original = boolean_mask_exploded.groupby(level=0).any()
    df_result = master[boolean_mask_original]
    if df_result.empty:
        return [None, None]
    else:
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

def today_games(rank_df, gender):
    rank_df["index"] = (rank_df["Team"].rank(method="dense").astype(int)) - 1
    master = getMasterTeams()
    if gender == 'M':
        look_for = "college-basketball/teams/"
        name_class = "TeamName"
        soup = getHTML("https://www.cbssports.com/college-basketball/schedule/")
        names = soup.find_all("span", class_=name_class)
        times = game_status(soup, gender)
    elif gender == 'W':
        look_for = "womens-college-basketball/teams/"
        name_class = "team-name-link"
        json = fetch_espn_women_scoreboard()
        [names, times] = parse_espn_teams_and_times(json)

    code_names = []
    if gender == "M":
        for name in names:
            atag = name.find("a")
            if atag is None:
                code_names.append("NA")
            else:
                url = atag["href"]
                idx = url.find(look_for) + len(look_for)
                team_code = url[idx:].split("/")[0]
                code_names.append(team_code)

    if gender == 'W':
        for name in names:
            [_, team] = getNameFromCode(name, master)
            if team is None:
                code_names.append("NA")
            else:
                code_names.append(team)

    names_1 = names[::2]
    names_2 = names[1::2]
    codes_1 = code_names[::2]
    codes_2 = code_names[1::2]
   
        
    sched_df = pd.DataFrame()
    for team1, team2, time, codes_1, codes_2 in zip(
        names_1, names_2, times, codes_1, codes_2
    ):
        if gender == 'M':
            team1 = team1.text.strip()
            team2 = team2.text.strip()
        dict = {
            "team1": team1,
            "code1": codes_1,
            "team2": team2,
            "code2": codes_2,
            "time": time,
        }
        add = pd.DataFrame([dict])
        sched_df = pd.concat([sched_df, add], ignore_index=True)
   
    sched_df["team1_rank"] = sched_df.apply(
        lambda x: get_rank(x, rank_df, master, 1), axis=1
    )
    sched_df["team2_rank"] = sched_df.apply(
        lambda x: get_rank(x, rank_df, master, 2), axis=1
    )
    sched_df["team1_rank"] = sched_df["team1_rank"].apply(
        lambda x: int(x) if pd.notna(x) else "N/A"
    )
    sched_df["team2_rank"] = sched_df["team2_rank"].apply(
        lambda x: int(x) if pd.notna(x) else "N/A"
    )
    sched_df["team1_conf"] = sched_df.apply(
        lambda x: getConf(x, rank_df, master, 1), axis=1
    )
    sched_df["team2_conf"] = sched_df.apply(
        lambda x: getConf(x, rank_df, master, 2), axis=1
    )
    power_conf = ["ACC", "B10", "B12", "SEC", "BE"]

    p5_df = sched_df[
        (sched_df["team1_conf"].isin(power_conf))
        & (sched_df["team2_conf"].isin(power_conf))
    ]
    sched_df = sched_df.drop(index=p5_df.index)

    output_df = sched_df[["team1_rank", "team1", "team2", "team2_rank", "time"]]
    output_df = output_df.rename(
        columns={
            "team1_rank": "A Rank",
            "team1": "Away",
            "team2": "Home",
            "team2_rank": "H Rank",
            "time": "Time/Final",
        }
    )

    p5_df = p5_df[["team1_rank", "team1", "team2", "team2_rank", "time"]]
    p5_df = p5_df.rename(
        columns={
            "team1_rank": "A Rank",
            "team1": "Away",
            "team2": "Home",
            "team2_rank": "H Rank",
            "time": "Time/Final",
        }
    )

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
            return None
        link = f'/assets/images/{name}' 
        return link
    
    def image_formatter(url):
        if url is None:
            return ''
        return f'<img src="{url}" class="team-logo" >'
    
    output_df["matchup_html"] = output_df.apply(
        lambda r: f"""
        <div class="matchup">
        <div class="teams">
            <span class="team">{image_formatter(getUrl(get_image_name(r['Away'])))}{fmt_team(r['Away'], r['A Rank'])}</span>
            <span class="at">@</span>
            <span class="team">{image_formatter(getUrl(get_image_name(r['Home'])))}{fmt_team(r['Home'], r['H Rank'])}</span>
        </div>
        <div class="{meta_class(r['Time/Final'])}">
            {r['Time/Final']}
        </div>
        </div>
        """,
        axis=1,
    )

    p5_df["matchup_html"] = p5_df.apply(
        lambda r: f"""
        <div class="matchup">
        <div class="teams">
            <span class="team">{image_formatter(getUrl(get_image_name(r['Away'])))}{fmt_team(r['Away'], r['A Rank'])}</span>
            <span class="at">@</span>
            <span class="team">{image_formatter(getUrl(get_image_name(r['Home'])))}{fmt_team(r['Home'], r['H Rank'])}</span>
        </div>
        <div class="{meta_class(r['Time/Final'])}">
            {r['Time/Final']}
        </div>
        </div>
        """,
        axis=1,
    )

    html_other = "\n".join(output_df["matchup_html"])
    html_p5 = "\n".join(p5_df["matchup_html"])

    html = f"""
    <h3>Power 5 Games</h3>
    {html_p5}
    <h3>All Other D1 Games</h3>
    {html_other}
    """
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
    kenpom_resp = requests.get(KENPOM, timeout=10).text
    # torvik_pre_resp = requests.get(TORVIK_PRE, timeout=10).text

    kenpom_soup = BeautifulSoup(kenpom_resp, "html.parser")
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
    path = utils.get_path(f"data/kenpom{date}.json")
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
        path = utils.get_path(f"data/torvik{date}.json")
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
        path = utils.get_path(f"data_w/torvik_w{date}.json")
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