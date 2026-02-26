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

def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]

def fetch_events_by_ids(event_ids, league_path):
    events = []

    for batch in chunks(event_ids, BATCH_SIZE):
        resp = requests.get(
            f"{BASE}/{league_path}/events",
            params={"id.in": ",".join(map(str, batch))},
            headers=HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        events.extend(resp.json())

    return events

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
    
    events = fetch_events_by_ids(filtered["2025-11-03"], 'ncaab')
    # print(events[0].keys())
    # dict_keys(['box_score', 'important', 'slot', 'tournament_name', 
    # 'odd', 'subscribable_alerts', 'location', 'stadium', 
    # 'away_conference', 'home_conference', 'has_team_twitter_handles', 
    # 'standings', 'colours', 'conference_names', 'has_play_by_play_records', 
    # 'stubhub_url', 'away_team', 'home_team', 'league', 'if_necessary', 
    # 'away_ranking', 'home_ranking', 'top_25_rankings', 'id', 
    # 'event_status', 'game_date', 'game_type', 'game_description', 'tba', 
    # 'updated_at', 'bet_works_id', 'betradar_id', 'status', 'api_uri', 
    # 'resource_uri', 'top_match'])
    scores = events[0]['box_score']['score']
    home_score = events[0]['box_score']['score']['home']['score']
    away_score = events[0]['box_score']['score']['away']['score']
    away = events[0]['away_team']['medium_name']
    home = events[0]['home_team']['medium_name']
    print(f"{home} {home_score} - {away} {away_score} ")
parse()