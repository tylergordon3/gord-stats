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
import random


from playwright.sync_api import sync_playwright

import os

TORVIK_PRE = "https://barttorvik.com/trankpre.php"
KENPOM = "https://kenpom.com/"
TORVIK = "https://barttorvik.com/#"


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
            return BeautifulSoup(content, "html.parser")
    return None  # if all retries fail

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