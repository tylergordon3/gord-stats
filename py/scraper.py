'''
    Scraping Torvik and Kenpom
'''
import time
import utils
import re
import pandas as pd
import requests
from bs4 import BeautifulSoup
import utils
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from datetime import datetime
import os
from io import StringIO
import random


from playwright.sync_api import sync_playwright

import os

TORVIK_PRE = "https://barttorvik.com/trankpre.php"
KENPOM = "https://kenpom.com/"
TORVIK = "https://barttorvik.com/#"

def getMasterTeams():
    df_back = pd.read_json(utils.get_path('data/teams/master.json'))
    return df_back

def saveMasterTeams(df):
    df.to_json(utils.get_path('data/teams/master.json'))

def getHTML(link, retries=5, base_delay=1.0):
    for attempt in range(retries):
        response = requests.get(link)
        if response.status_code == 429 : 
            if attempt < retries - 1:
                delay = base_delay * (2 ** attempt) + random.uniform(0, 0.2)
                print(f'Sleeping for: {delay} seconds.')
                time.sleep(delay)
                continue
        if response.status_code == 200:
            content = response.text
            return BeautifulSoup(content, "lxml")
    print('getHTML returning None')
    return None  # if all retries fail

def get_rank1(row, rank_df, master):
    [index, code_name] = getNameFromCode(row.code1, master)

    rank_row = rank_df.loc[
        (rank_df['Team'] == row.team1) | (rank_df['Team'] == code_name) | (rank_df['index'] == index)
    ]

    if rank_row.empty:
        pass
    else:
        return list(rank_row['Overall'])[0]


def get_rank2(row, rank_df, master):
    [index, code_name]  = getNameFromCode(row.code2, master)
    rank_row = rank_df.loc[
        (rank_df['Team'] == row.team2) | (rank_df['Team'] == code_name) | (rank_df['index'] == index)
    ]
 
    if rank_row.empty:
        return 
    else:
        return list(rank_row['Overall'])[0]

def getNameFromCode(code, master):
    s_exploded = master['names'].explode()
    boolean_mask_exploded = s_exploded == code
    # To get the row IDs where the value is present:
    #matching_ids = s_exploded[boolean_mask_exploded].index.unique()
    boolean_mask_original = boolean_mask_exploded.groupby(level=0).any()
    df_result = master[boolean_mask_original]
    if df_result.empty:
        return [None, None]
    else:
        return [list(df_result['index'])[0], list(df_result['team'])[0]]
    
    
def today_games(rank_df):
    rank_df['index'] = (
        rank_df['Team']
       .rank(method="dense")
        .astype(int)
    ) - 1
    base_link = 'https://www.cbssports.com/college-basketball/schedule/'
    soup = getHTML(base_link)

    names = soup.find_all("span", class_="TeamName")
                  
    games = soup.find_all("div", class_ = "CellGame")
    times = [game.find('a').text.strip() for game in games]
    code_names = []
    for name in names:
        atag = name.find('a')
        if atag is None:
            code_names.append('NA')
        else:
            url = atag['href']
            look_for = 'college-basketball/teams/'
            idx = url.find(look_for) + len(look_for)
            team_code = url[idx:].split('/')[0]
            code_names.append(team_code)
 
    names_1 = names[::2]
    names_2 = names[1::2]
    codes_1 = code_names[::2]
    codes_2 = code_names[1::2]

    sched_df = pd.DataFrame()
    for team1, team2, time, codes_1, codes_2 in zip(names_1, names_2, times, codes_1, codes_2):
        dict = {'team1' : team1.text.strip(), 'code1' : codes_1, 'team2' : team2.text.strip(), 'code2': codes_2, 'time' : time}
        add = pd.DataFrame([dict])
        sched_df = pd.concat([sched_df, add], ignore_index=True)
    master = getMasterTeams()
    
    sched_df['team1_rank'] = sched_df.apply(lambda x: get_rank1(x, rank_df, master), axis = 1)
    sched_df['team2_rank'] = sched_df.apply(lambda x: get_rank2(x, rank_df, master), axis = 1)
    sched_df["team1_rank"] = sched_df["team1_rank"].apply(
        lambda x: int(x) if pd.notna(x) else "N/A"
    )
    sched_df["team2_rank"] = sched_df["team2_rank"].apply(
        lambda x: int(x) if pd.notna(x) else "N/A"
    )

    output_df = sched_df[['team1_rank', 'team1', 'team2', 'team2_rank', 'time']]
    output_df = output_df.rename(columns={"team1_rank" : "A Rank", "team1" : "Away", "team2" : "Home", "team2_rank" : "H Rank", "time" : "Time/Final"})

    def fmt_team(team, rank):
        if rank == "N/A":
            return team
        return f"<strong>#{rank}</strong> {team}"
    
    def meta_class(val):
        val = str(val).lower()
        if "final" in val:
            return "meta final"
        if ":" not in val:
            return "meta live"
        return "meta"
    
    output_df["matchup_html"] = output_df.apply(
        lambda r: f"""
        <div class="matchup">
        <div class="teams">
            <span class="team">{fmt_team(r['Away'], r['A Rank'])}</span>
            <span class="at">@</span>
            <span class="team">{fmt_team(r['Home'], r['H Rank'])}</span>
        </div>
        <div class="{meta_class(r['Time/Final'])}">
            {r['Time/Final']}
        </div>
        </div>
        """,
        axis=1
    )

    html = "\n".join(output_df["matchup_html"])

    return html

def update_master():
    master = getMasterTeams()
    path = utils.get_path('data/teams/redditCFB.html')
    with open(path, 'r', encoding='utf-8') as f:
        html_content = f.read()
    soup = BeautifulSoup(html_content, 'lxml') 
    rows = soup.find_all('tr')
    team_data = pd.DataFrame()
    for team in rows:
        data = team.find_all('td')
        name = data[0].text
        abbr = data[1].text
        team_add = {
            "team" : name.strip(),
            "names" : [name.strip(), abbr.strip()]
        }
        new = pd.DataFrame([team_add])
        team_data = pd.concat([team_data, new], ignore_index=True)
    df = team_data.sort_values(by='team')
    df = df.reset_index(drop=True)
    df['Index'] = df.index
    merged = pd.merge(master, df, how='left', on='team')
    merged['names'] = merged.apply(lambda x: list(set(x.names_x + x.names_y)) 
                                if isinstance(x.names_x, list) and isinstance(x.names_y, list) else x.names_x, axis=1)
    merged = merged.drop(columns=['names_x', 'names_y', 'Index_y'])
    merged = merged.rename(columns={'Index_x' : 'index'})
    saveMasterTeams(merged)

def init_master_dict():
    path = utils.get_path('data/teams/team_table.html')
    with open(path, 'r', encoding='utf-8') as f:
        html_content = f.read()
    soup = BeautifulSoup(html_content, 'lxml') 
    rows = soup.find_all('tr')
    team_data = pd.DataFrame()
    for team in rows:
        data = team.find_all('td')
        name = data[0].text
        mascot = data[1].text
        abbr = data[2].text
 
        team_add = {
            "team" : name,
            "names" : [name, mascot, abbr]
        }

        new = pd.DataFrame([team_add])
        team_data = pd.concat([team_data, new], ignore_index=True)
    df = team_data.sort_values(by='team')
    df = df.reset_index(drop=True)
    df['Index'] = df.index
    saveMasterTeams(df)


    
def pull_sportsDB():
    strLeague = 'NCAA_Division_I_Basketball_Mens'
    teams = pd.read_json(utils.get_path('data/team_list.json'))
    link = 'https://www.thesportsdb.com/api/v1/json/123/searchteams.php?t='

    for team in list(teams[0]):
        check = utils.get_path(f'docs/assets/images/{team}.png')
        if not os.path.exists(check):
            print(f'Querying for: {team}')
            web = link + team
            try:
                pattern = r'\"strBadge\":\"(https:\\\/\\\/r2\.thesportsdb\.com\\\/images\\\/media\\\/team\\\/badge\\\/[A-Za-z0-9]+\.png)\"'
                badge =  re.findall(pattern,  requests.get(web).text)
                cl = badge[0].replace('\\/', '/')
                img_data = requests.get(cl).content
                with open(utils.get_path(f'docs/assets/images/{team}.png'), 'wb') as handler:
                    handler.write(img_data)
                print(f'Done for: {team}')
            except:
                print(f'Error for: {team}')
            print(f'Sleeping for 8 seconds')
            time.sleep(8)
        


def kenpom_historic():
    # https://kenpom.com/index.php?y=2025
    all = []
    for year in range(2013, 2026):
        file = f'model_data/kenpom/kenpom{year}.html'
        with open(file) as fp:
            soup = BeautifulSoup(fp, 'html.parser')
        table = soup.find("table")

        # --- Extract headers considering multi-row and colspan ---
        header_rows = table.find_all("tr")[:2]  # first two rows usually contain headers
        header_matrix = []

        for hr in header_rows:
            row_headers = []
            for cell in hr.find_all(["th", "td"]):
                text = cell.get_text(strip=True)
                colspan = int(cell.get("colspan", 1))
                row_headers.extend([text]*colspan if text else [""]*colspan)
            header_matrix.append(row_headers)
        
        # --- Merge multi-row headers and handle ranking columns ---
        num_cols = max(len(r) for r in header_matrix)
        final_headers = []
        seen = {}  # track occurrences for rank columns

        # Define replacements for readability
        replacements = {
            "Strength of Schedule": "SOS",
            "NCSOS": "NCSOS"
        }

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
        for row in table.find_all("tr")[len(header_rows):]:
            cols = [col.get_text(strip=True) for col in row.find_all("td")]
            if any(cols):
                rows.append(cols)

        # --- Convert to strings ---
        final_headers = [str(h) for h in final_headers]
        rows = [[str(c) for c in r] for r in rows]
        def sep_names(row):
            team = row[1]
            rm_space = team.replace(" ", "")
            pat="(\D+)([0-9]{1,2})"
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
        final_headers.insert(2, 'Seed')
        final_headers.insert(3, 'Tourney')
        final_headers.insert(4, 'Year')
        # --- Save to JSON ---
        output = {
            "headers": final_headers,
            "rows": rows
        }
        [all.append(row) for row in rows]
        # Save to JSON file
        path = utils.get_path(f"model_data/kenpom{year}.json")
        utils.save_json_data(output, path)
    path = utils.get_path(f"model_data/kenpom_all.json")
    utils.save_json_data(all, path)

def kenpom(date):
    kenpom_resp = requests.get(KENPOM, timeout=10).text
    #torvik_pre_resp = requests.get(TORVIK_PRE, timeout=10).text
    

    kenpom_soup = BeautifulSoup(kenpom_resp, 'html.parser')
    #torvik_soup = BeautifulSoup(torvik_pre_resp, 'html.parser')


    table = kenpom_soup.find("table")

    # --- Extract headers considering multi-row and colspan ---
    header_rows = table.find_all("tr")[:2]  # first two rows usually contain headers
    header_matrix = []

    for hr in header_rows:
        row_headers = []
        for cell in hr.find_all(["th", "td"]):
            text = cell.get_text(strip=True)
            colspan = int(cell.get("colspan", 1))
            row_headers.extend([text]*colspan if text else [""]*colspan)
        header_matrix.append(row_headers)

    # --- Merge multi-row headers and handle ranking columns ---
    num_cols = max(len(r) for r in header_matrix)
    final_headers = []
    seen = {}  # track occurrences for rank columns

    # Define replacements for readability
    replacements = {
        "Strength of Schedule": "SOS",
        "NCSOS": "NCSOS"
    }

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
    for row in table.find_all("tr")[len(header_rows):]:
        cols = [col.get_text(strip=True) for col in row.find_all("td")]
        if any(cols):
            rows.append(cols)

    # --- Convert to strings ---
    final_headers = [str(h) for h in final_headers]
    rows = [[str(c) for c in r] for r in rows]

    # --- Save to JSON ---
    output = {
        "headers": final_headers,
        "rows": rows
    }

    # Save to JSON file
    path = utils.get_path(f"data/kenpom{date}.json")
    utils.save_json_data(output, path)

def torvik(date):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True) # Runs without a UI
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
            headers = [cell.get_text(strip=True) for cell in header_row.find_all(["th", "td"])]
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
        output = {
            "headers": headers,
            "rows": rows
        }
        path = utils.get_path(f"data/torvik{date}.json")
        utils.save_json_data(output, path)
        browser.close()