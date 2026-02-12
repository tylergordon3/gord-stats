import requests
import pandas as pd
from bs4 import BeautifulSoup
import utils
import json
from datetime import datetime
import pytz
from lib import paths

URL="https://www.teamrankings.com/ncb/trends/ats_trends/"

def main():
    resp = requests.get(URL)
    soup = BeautifulSoup(resp.content, 'html.parser')
    table = soup.find("table")

    headers = table.find_all("tr")[0]
    rows = table.find_all("tr")[1:]

    cols = []
    for hdr in headers:
        text = hdr.get_text(strip=True)
        if len(text) <= 0:
            continue
        cols.append(text)

    table_data = []
    for row in rows:
        row_data = []
        for td in row.find_all("td"):
            cell_text = td.get_text(strip=True)
            if len(cell_text) <= 0:
                continue
            row_data.append(cell_text)
        table_data.append(row_data)
    df = pd.DataFrame(columns=cols, data=table_data)

    now = datetime.now().replace(tzinfo=pytz.timezone("US/Eastern"))
    str = now.strftime("%Y-%m-%d")
    payload = {
            "headers": list(df.columns),
            "rows": df.values.tolist(),
        }

    path = utils.get_path(f"data/men/ats/{str}.json")

    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=4)
        
def get_today_ats():
    ats_dir = paths.M_ATS_DIR

    # Today's filename
    today_str = datetime.now().strftime("%Y-%m-%d")
    today_file = ats_dir / f"{today_str}.json"

    # If today's file exists, return it
    if today_file.exists():
        target_file = today_file

    # Otherwise get most recent file
    files = sorted(
        ats_dir.glob("*.json"),
        key=lambda f: f.name,   # filenames are YYYY-MM-DD.json so this works
        reverse=True
    )

    if not files:
            return None

    target_file = files[0]

    # Load JSON
    with open(target_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data

import scraper
dict = get_today_ats()
master = scraper.getMasterTeams()

for idx, team_name in master["team"].items():
    if "." in team_name:
        no_period = team_name.replace(".", "")

        # Add to names list if not already present
        if no_period not in master["names"][idx]:
            master["names"][idx].append(no_period)

scraper.saveMasterTeams(master)

for i in dict["rows"]:
   [index, team] = scraper.getNameFromCode(i[0], master)
   if not index or not team:
       print(i[0])