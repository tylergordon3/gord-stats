"""
Scraping ESPN BPI Data
Source:
https://github.com/pseudo-r/Public-ESPN-API?tab=readme-ov-file#base-urls
"""

import json
from datetime import datetime

import pandas as pd
import pytz
import requests

from cbb import utils
from cbb import paths, url, teams


def save_id(dict):
    with open(utils.get_path("docs/assets/data/espn_id.json"), "w") as file:
        json.dump(dict, file, indent=4)
        return dict


params = {
    "groups": 50,
    "limit": 50,
    "sort": "bpi.bpi:desc",
    "lang": "en",
    "region": "us",
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
    "adj_margin_conf",
]

RESUME_COLUMNS = [
    "resume_rank",
    "q1_wins",
    "q2_wins",
    "bad_losses",
    "top50_wins",
    "sor_rank",
    "rpi_rank",
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

    r = requests.get(url.NCAAM_BPI, params={**params, "page": 1}, timeout=30)
    data = r.json()
    # Until ESPN publishes the new season's index it serves the last one
    # (requestedSeason 2026 under currentSeason 2027 in late September), and
    # filing that under today's date made it this season's BPI - blended into
    # the power rating and read as this season's conference records.
    have = (data.get("requestedSeason") or {}).get("year")
    want = (data.get("currentSeason") or {}).get("year")
    if have and want and have != want:
        from cbb.scrape.net import NotReleased
        raise NotReleased(f"BPI not out for {want} yet (ESPN serves {have})")

    pages = data["pagination"]["pages"]
    teams.extend(data["teams"])

    for page in range(2, pages + 1):
        r = requests.get(url.NCAAM_BPI, params={**params, "page": page}, timeout=30)
        teams.extend(r.json()["teams"])

    rows = [parse_team_entry(t) for t in teams]
    df = pd.DataFrame(rows)

    now = datetime.now().replace(tzinfo=pytz.timezone("US/Eastern"))
    str = now.strftime("%Y-%m-%d")

    payload = {
        "headers": list(df.columns),
        "rows": df.values.tolist(),
    }

    path = paths.M_ESPN_DIR / f"{str}.json"

    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def get_today_bpi():
    bpi_dir = paths.M_ESPN_DIR

    # This season's newest, never last season's (utils.latest_this_season).
    target_file = utils.latest_this_season(bpi_dir)
    if target_file is None:
        return None

    # Load JSON
    with open(target_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data


def get_conf_records():
    bpi = get_today_bpi()
    if bpi is None:
        return {}                           # this season's table not out yet
    conf_records = {teams.getTeamOfficialName(row[1]): f"{int(row[17])}-{int(row[18])}" for row in bpi["rows"]}
    return conf_records
 
    
    