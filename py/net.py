import requests
import pandas as pd
from bs4 import BeautifulSoup
import utils
import json
from datetime import datetime
import pytz

URL="https://www.ncaa.com/rankings/basketball-men/d1/ncaa-mens-basketball-net-rankings"

def net_ranks():
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

    path = utils.get_path(f"data/men/net/{str}.json")

    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=4)
        print(f'Scraped NET data for: {str}')
