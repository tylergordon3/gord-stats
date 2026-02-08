"""
Scraping ESPN BPI Data
Source: https://github.com/pseudo-r/Public-ESPN-API?tab=readme-ov-file#base-urls
"""

import requests
import json
import pandas as pd
import utils
from datetime import datetime
import pytz


def save_id(dict):
    with open(utils.get_path('docs/assets/data/espn_id.json'), 'w') as file:
        json.dump(dict, file, indent=4)
        return dict

BASE = "https://site.web.api.espn.com/apis/fitt/v3/sports/basketball/mens-college-basketball/powerindex"

params = {
    "groups": 50,
    "limit": 50,
    "sort": "bpi.bpi:desc",
    "lang": "en",
    "region": "us"
}

BPI_COLUMNS = [
    "bpi",
    "bpi_rank",
    "conf_rank",
    "off_eff",
    "def_eff",
    "proj_win_pct",
    "sos_rank",
    "wins",
    "losses",
    "off_rating",
    "def_rating",
    "conf_wins",
    "conf_losses",
    "adj_margin",
    "adj_margin_conf"
]

RESUME_COLUMNS = [
    "resume_rank",
    "q1_wins",
    "q2_wins",
    "bad_losses",
    "top50_wins",
    "sor_rank",
    "rpi_rank"
]

def parse_team_entry(entry):
    team = entry["team"]
    row = {
        "team_id": team["id"],
        "team": team["nickname"],
        "abbr": team.get("abbreviation"),
        "conference": team["group"]["name"],
        "conference_abbr": team["group"]["abbreviation"],
        "rank": team["rankValue"],
    }

    for cat in entry["categories"]:
        name = cat["name"]
        values = cat["values"]

        if name == "bpi":
            row.update(dict(zip(BPI_COLUMNS, values)))

        elif name == "resume":
            row.update(dict(zip(RESUME_COLUMNS, values)))

    return row


def main():
    teams = []

    r = requests.get(BASE, params={**params, "page": 1})
    data = r.json()

    pages = data["pagination"]["pages"]
    teams.extend(data["teams"])

    for page in range(2, pages + 1):
        r = requests.get(BASE, params={**params, "page": page})
        teams.extend(r.json()["teams"])

    rows = [parse_team_entry(t) for t in teams]
    df = pd.DataFrame(rows)

    now = datetime.now().replace(tzinfo=pytz.timezone("US/Eastern"))
    str = now.strftime("%Y-%m-%d")

    payload = {
            "headers": list(df.columns),
            "rows": df.values.tolist(),
        }

    path = utils.get_path(f"data/men/espn/{str}.json")

    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        print(f'Scraped ESPN data for: {str}')
