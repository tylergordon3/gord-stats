import requests
import json
from ..lib import paths
from pathlib import Path
# =========================
# CONFIG
# =========================

BASE = "https://api.thescore.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Referer": "https://www.thescore.com/",
}

UTC_OFFSET_SECONDS = -18000  # EST
POLL_INTERVAL = 25  # seconds
BATCH_SIZE = 90

LIVE_STATUSES = {"in_progress", "halftime", "delay"}

SKIP_CONFERENCES = {"All Conferences"}

LEAGUES = {
    "men": {"path": "ncaab", "label": "men"},
    "women": {"path": "wcbk", "label": "women"},
}

def get_all_events(league_path):

    resp = requests.get(
        f"{BASE}/{league_path}/schedule",
        params={"utc_offset": UTC_OFFSET_SECONDS},
        headers=HEADERS,
        timeout=10,
    )

    resp.raise_for_status()
    sched = resp.json()
    file = paths.SCHEDULE_DATA / Path(f"{league_path}_season.json")
    with open(file, "w") as f:
        json.dump(sched['current_season'], f, indent=4)

def save_all():
    for league_key in ("men", "women"):
        cfg = LEAGUES[league_key]
        league_path = cfg["path"]
        get_all_events(league_path)


def parse(gender="M"):
    file = paths.SCHEDULE_DATA / Path(f"ncaab_season.json")
    with open(file, "r") as f:
        data = json.load(f)

    # guid        : ncaab:2025-11-03
    # id          : 2025-11-03
    # label       : Nov 3
    # start_date  : 2025-11-03T08:00:00-05:00
    # end_date    : 2025-11-04T07:59:59-05:00
    # season_type : regular
    # event_ids   : [nums]
    # print(data[0].keys())
    filtered = {}
    for day in data:
        filtered[day['id']] = day['event_ids']

parse()