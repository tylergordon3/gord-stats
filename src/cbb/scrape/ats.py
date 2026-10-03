import json
import re
from datetime import datetime

import pandas as pd
import pytz
import requests
from bs4 import BeautifulSoup

from cbb import paths, url, utils


def season_shown(soup) -> int | None:
    """The season TeamRankings' table is for, as the year it ends in (2026
    for "2025-2026"): the page's selected `yearly_2025_2026` option."""
    yearly = re.compile(r"^yearly_\d{4}_\d{4}$")
    opt = soup.find("option", attrs={"selected": True, "value": yearly})
    return int(opt["value"][-4:]) if opt else None


def parse_to_df(url, season: int = None):
    """The page's table. With `season`, refuses (net.NotReleased) a page that
    shows another: until TeamRankings turns to the new season it serves last
    season's final records, and those were filed under November's dates and
    shown on the scoreboard as this season's (the 2026-10-03 rehearsal)."""
    resp = requests.get(url, timeout=30)
    soup = BeautifulSoup(resp.content, "html.parser")
    if season is not None:
        shown = season_shown(soup)
        if shown != season:
            from cbb.scrape.net import NotReleased
            raise NotReleased(f"ATS records not out for {season - 1}-{str(season)[2:]} yet "
                              f"(TeamRankings shows {shown - 1}-{shown})" if shown else
                              f"ATS records: TeamRankings names no season ({url})")
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
    now = datetime.now().replace(tzinfo=pytz.timezone("US/Eastern"))
    season = utils.season_year(now.date())
    df_ats = parse_to_df(url.NCAAM_ATS, season)
    df_ou = parse_to_df(url.NCAAM_OU, season)

    df = pd.merge(df_ats, df_ou, how="inner", on="Team")

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
