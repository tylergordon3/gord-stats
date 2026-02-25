import requests
import pandas as pd
from bs4 import BeautifulSoup
import utils
import json
from datetime import datetime
import pytz
from lib import paths

URL = (
    "https://www.ncaa.com/rankings/basketball-men/d1/ncaa-mens-basketball-net-rankings"
)
URL_W = "https://www.ncaa.com/rankings/basketball-women/d1/ncaa-womens-basketball-net-rankings"


def main(gender):
    now = datetime.now().replace(tzinfo=pytz.timezone("US/Eastern"))
    str = now.strftime("%Y-%m-%d")
    if gender == "M":
        resp = requests.get(URL)
        path = utils.get_path(f"data/men/net/{str}.json")
    elif gender == "W":
        resp = requests.get(URL_W)
        path = utils.get_path(f"data/women/net/{str}.json")
    else:
        print("Invalid gender given to net.main()!")
        return None
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

    payload = {
        "headers": list(df.columns),
        "rows": df.values.tolist(),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=4)
        print(f"Scraped NET data for: {str}")


def get_today_net(gender):
    if gender == "M":
        net_dir = paths.M_NET_DIR
    elif gender == "W":
        net_dir = paths.W_NET_DIR
    else:
        print("Invalid gender given to get_today_net.")
        return None

    # Today's filename
    today_str = datetime.now().strftime("%Y-%m-%d")
    today_file = net_dir / f"{today_str}.json"

    # If today's file exists, return it
    if today_file.exists():
        target_file = today_file

    # Otherwise get most recent file
    files = sorted(
        net_dir.glob("*.json"),
        key=lambda f: f.name,  # filenames are YYYY-MM-DD.json so this works
        reverse=True,
    )

    if not files:
        return None

    target_file = files[0]

    # Load JSON
    with open(target_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data
