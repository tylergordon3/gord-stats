import os
import requests
import utils
import json
from datetime import date, timedelta
from dotenv import load_dotenv
from bs4 import BeautifulSoup

load_dotenv() 

KENPOM_KEY = os.getenv("KENPOM")
BASE_URL = "https://kenpom.com/api.php"

def norm_team(name: str) -> str:
    return (
        name.lower()
        .replace("&", "and")
        .replace(".", "")
        .replace("'", "")
        .strip()
    )

def load_html_ranks_for_date(date):
    """
    Loads team -> rank from local KenPom HTML archive for a given date.
    """
    path = utils.get_path(f"data/men/kenpom{date}html.html")

    if not os.path.exists(path):
        return {}

    with open(path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "html.parser")

    table = soup.find("table", id="ratings-table")
    if not table:
        return {}

    ranks = {}

    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue

        rank = tds[0].get_text(strip=True)
        team = tds[1].get_text(strip=True)

        if rank.isdigit() and team:
            ranks[norm_team(team)] = rank

    return ranks

from datetime import date as dt_date

HTML_START = dt_date(2026, 1, 21)
HTML_END   = dt_date(2026, 1, 25)

def get_prev_ranks_for_date(date_str):
    d = dt_date.fromisoformat(date_str)

    # ✅ Use HTML for 1/21–1/25
    if HTML_START <= d <= HTML_END:
        return load_html_ranks_for_date(date_str)

    # ✅ Otherwise use kenpom_old JSON
    return load_old_ranks_for_date(date_str)

def load_old_ranks_for_date(date):
    """
    Load team -> rank mapping from kenpom_old for the SAME date.
    """
    path = utils.get_path(f"data/men/kenpom_old/kenpom{date}.json")

    if not os.path.exists(path):
        return {}

    with open(path, "r") as f:
        data = json.load(f)

    headers = data["headers"]
    rows = data["rows"]

    team_idx = headers.index("Team")
    rk_idx = headers.index("Rk")

    return {
        norm_team(row[team_idx]): row[rk_idx]
        for row in rows
    }

def parse(data, prev_ranks):
    headers = list(data[0].keys())
    headers.append("PrevRk")

    rows = []
    for row in data:
        team_key = norm_team(row["TeamName"])
        prev_rank = prev_ranks.get(team_key)

        vals = list(row.values())
        vals.append(prev_rank)

        rows.append(vals)

    return {
        "headers": headers,
        "rows": rows
    }

def kenpom_for_date(date):
    params = {
        "endpoint": "archive",
        "d": date
    }

    headers = {
        "Authorization": f"Bearer {KENPOM_KEY}",
        "Accept": "application/json"
    }

    res = requests.get(BASE_URL, params=params, headers=headers)

    if res.status_code == 404:
        print(f"⏭️  No data for {date}")
        return

    res.raise_for_status()

    data = res.json()

    # 🔑 NEW: date-aware rank source
    prev_ranks = get_prev_ranks_for_date(date)

    parsed = parse(data, prev_ranks)

    path = utils.get_path(f"data/men/kenpom/kenpom{date}.json")
    utils.save_json_data(parsed, path)


def kenpom_historic():
    start = date(2025, 11, 3)
    end = date.today()
    d = start
    while d < end:
        print(d.isoformat())  # YYYY-MM-DD
        kenpom_for_date(d.isoformat())
        d += timedelta(days=1)