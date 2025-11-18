'''
    Scraping Torvik and Kenpom
'''
import json
import time
import utils
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from datetime import datetime

from playwright.sync_api import sync_playwright

TORVIK_PRE = "https://barttorvik.com/trankpre.php"
KENPOM = "https://kenpom.com/"
TORVIK = "https://barttorvik.com/#"

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
    utils.save_json_data(output, f"data/kenpom{date}.json")

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
        utils.save_json_data(output, f"data/torvik{date}.json")
        browser.close()