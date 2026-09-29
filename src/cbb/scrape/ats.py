import json
from datetime import datetime

import pandas as pd
import pytz
import requests
from bs4 import BeautifulSoup

from cbb import paths, url, utils

def parse_to_df(url):
    resp = requests.get(url, timeout=30)
    soup = BeautifulSoup(resp.content, "html.parser")
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

    df = pd.merge(df_ats, df_ou, how="inner", on="Team")

    now = datetime.now().replace(tzinfo=pytz.timezone("US/Eastern"))
    str = now.strftime("%Y-%m-%d")
    payload = {
        "headers": list(df.columns),
        "rows": df.values.tolist(),
    }

    path = paths.M_ATS_DIR / f"{str}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=4)

def get_today_ats():
    ats_dir = paths.M_ATS_DIR

    # This season's newest, never last season's (utils.latest_this_season).
    target_file = utils.latest_this_season(ats_dir)
    if target_file is None:
        return None

    # Load JSON
    with open(target_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data
