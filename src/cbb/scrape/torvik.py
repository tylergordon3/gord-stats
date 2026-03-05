import re
import time
import json
from datetime import datetime

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from cbb import utils
from cbb.lib import paths, url

def get_today_tor(gender="M"):
    if gender == "M":
        dir = paths.M_TOR_DIR
    elif gender == "W":
        dir = paths.W_TOR_DIR
    
     # Today's filename
    today_str = datetime.now().strftime("%Y-%m-%d")
    today_file = dir / f"{today_str}.json"

    # If today's file exists, return it
    if today_file.exists():
        target_file = today_file

    # Otherwise get most recent file
    files = sorted(
        dir.glob("*.json"),
        key=lambda f: f.name,
        reverse=True,
    )

    if not files:
        return None

    target_file = files[0]

    # Load JSON
    with open(target_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data

def mens_tor(date):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url.NCAAM_TOR)
        time.sleep(5)

        html = page.content()
        soup = BeautifulSoup(html, "html.parser")

        table = soup.find("table")
        headers = []

        table_rows = table.find_all("tr")
        header_row = table_rows[1]
        if header_row:
            headers = [
                cell.get_text(strip=True) for cell in header_row.find_all(["th", "td"])
            ]
        rows = []
        for row in table.find_all("tr"):
            cols = [col.get_text(strip=True) for col in row.find_all("td")]
            if any(cols):
                rows.append(cols)
        if rows and rows[0] == headers:
            rows = rows[1:]

        headers = [str(h) for h in headers]
        rows = [[str(c) for c in r] for r in rows]

        output = {"headers": headers, "rows": rows}
        path = paths.M_TOR_DIR / f"{date}.json"
        utils.save_json_data(output, path)
        browser.close()


def womens_tor(date):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url.NCAAW_TOR, wait_until="domcontentloaded")
        time.sleep(5)

        html = page.content()
        soup = BeautifulSoup(html, "html.parser")

        table = soup.find("table")
        headers = []

        table_rows = table.find_all("tr")
        header_row = table_rows[1]
        if header_row:

            headers = [
                cell.get_text(strip=True) for cell in header_row.find_all(["th", "td"])
            ]

        rows = []
        for row in table.find_all("tr"):
            cols = [col.get_text(strip=True) for col in row.find_all("td")]
            if any(cols):
                pattern = r"(^[^\\(]+)"
                match = re.findall(pattern, cols[1])
                if any(match):
                    cols[1] = match[0]
                rows.append(cols)

        if rows and rows[0] == headers:
            rows = rows[1:]

        headers = [str(h) for h in headers]
        rows = [[str(c) for c in r] for r in rows]

        output = {"headers": headers, "rows": rows}
        path = paths.W_TOR_DIR / f"{date}.json"
        utils.save_json_data(output, path)
        browser.close()
