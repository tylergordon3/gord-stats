"""
Weekly NFL injury-report scraping (ported from py/injuries).

Scrapes nfl.com's per-week league injury report and keeps players ruled 'Out'.
"""
import time
from io import StringIO

import pandas as pd
import requests
from tqdm import tqdm

_TIMEOUT = 25       # seconds; nfl.com can be slow
_RETRIES = 3


def _fetch(url: str) -> str:
    """GET with a few retries so a single slow response doesn't kill the run."""
    last_err = None
    for attempt in range(_RETRIES):
        try:
            return requests.get(url, timeout=_TIMEOUT).text
        except requests.RequestException as e:
            last_err = e
            time.sleep(3 * (attempt + 1))  # back off before retrying
    raise last_err


def scrape_week(year, week: int) -> pd.DataFrame:
    url = f"https://www.nfl.com/injuries/league/{year}/reg{week}"
    tables = pd.read_html(StringIO(_fetch(url)))
    time.sleep(3)  # be polite to nfl.com
    df = pd.concat(tables).reset_index(drop=True)
    df = df[df["Game Status"] == "Out"]
    df["Cleaned Name"] = df["Player"].str.split().apply(
        lambda parts: "".join(parts[:2]) if len(parts) >= 2 else "".join(parts))
    df["Week"] = week
    return df


def scrape_all(year, start_week: int, end_week: int) -> pd.DataFrame:
    start_week = max(1, start_week)
    end_week = min(18, end_week)
    out = pd.DataFrame()
    for week in tqdm(range(start_week, end_week + 1), desc="Scraping injuries"):
        out = pd.concat([out, scrape_week(year, week)])
    return out
