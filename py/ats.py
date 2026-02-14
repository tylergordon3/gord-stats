import requests
import pandas as pd
from bs4 import BeautifulSoup
import utils
import json
from datetime import datetime
import pytz
from lib import paths, url

URL="https://www.teamrankings.com/ncb/trends/ats_trends/"

def parse_to_df(url):
    resp = requests.get(url)
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
    return df
    
def main():
    df_ats = parse_to_df(url.NCAAM_ATS)
    df_ou = parse_to_df(url.NCAAM_OU)
    
    df = pd.merge(df_ats, df_ou, how="inner", on='Team')

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