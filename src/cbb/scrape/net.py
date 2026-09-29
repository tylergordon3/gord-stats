import json
import re
from datetime import datetime

import pandas as pd
import pytz
import requests
from bs4 import BeautifulSoup

from cbb import paths, url, utils


class NotReleased(Exception):
    """The NCAA has not published this season's NET yet.

    The first release is in early December. Until then ncaa.com serves last
    season's final table under "Through Games Apr. 06 2026", and this used to
    file it as today's - so November's bracket blended in March's NET."""


def through(text: str):
    """The date on the page's "Through Games Apr. 06 2026" line, or None."""
    m = re.search(r"Through Games\s+([A-Z][a-z]{2})\.?\s+(\d{1,2}),?\s+(\d{4})", text)
    if not m:
        return None
    return datetime.strptime(" ".join(m.groups()), "%b %d %Y").date()


def main(gender):
    now = datetime.now().replace(tzinfo=pytz.timezone("US/Eastern"))
    str = now.strftime("%Y-%m-%d")
    if gender == "M":
        resp = requests.get(url.NCAAM_NET, timeout=30)
        path = paths.M_NET_DIR / f"{str}.json"
    elif gender == "W":
        resp = requests.get(url.NCAAW_NET, timeout=30)
        path = paths.W_NET_DIR / f"{str}.json"
    else:
        print("Invalid gender given to net.main()!")
        return None
    soup = BeautifulSoup(resp.content, "html.parser")
    as_of = through(soup.get_text(" ", strip=True))
    if as_of is None or utils.season_year(as_of) != utils.season_year(now.date()):
        raise NotReleased(f"NET not out for this season yet (the page is through {as_of})")
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

    # This season's newest, never last season's (utils.latest_this_season).
    target_file = utils.latest_this_season(net_dir)
    if target_file is None:
        return None

    # Load JSON
    with open(target_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data
