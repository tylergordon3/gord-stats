import json
from pathlib import Path

import requests

from cbb.lib import paths, teams

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
        json.dump(sched["current_season"], f, indent=4)


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


def parse_g(game):
    try:
        away = game["away_team"]["medium_name"]
        home = game["home_team"]["medium_name"]

        away_check = teams.getTeamOfficialName(away, debug=False)
        home_check = teams.getTeamOfficialName(home, debug=False)

        home_score = game["box_score"]["score"]["home"]["score"]
        away_score = game["box_score"]["score"]["away"]["score"]

        if home_score > away_score:
            home_win = True
            away_win = False
        else:
            home_win = False
            away_win = True

        return [
            home,
            away,
            home_check,
            away_check,
            home_score,
            away_score,
            home_score,
            away_score,
            home_win,
            away_win,
        ]
    except:
        return [None]

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
        filtered[day["id"]] = day["event_ids"]

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

    file = paths.SCHEDULE_DATA / Path(f"men_season.json")
    with open(file, "r") as f:
        all = json.load(f)

    for key in filtered:
        games = fetch_events_by_ids(filtered[key], "ncaab")
        for g in games:

            elements = parse_g(g)
            if len(elements) > 1:
                home = elements[0]
                away = elements[1]
                home_check = elements[2]
                away_check = elements[3]
                
                if home_check != None:
                    home = home_check
                
                if away_check != None:
                    away = away_check
                
                if home_check != None:
                    all[home_check][key] = {
                        "win" : elements[8],
                        "location" : "home",
                        "score" : elements[6],
                        "opponent" : away,
                        "opponent_score" : elements[4]
                    }
                    
                if away_check != None:
                    all[away_check][key] = {
                        "win" : elements[9],
                        "location" : "away",
                        "score" : elements[7],
                        "opponent" : home,
                        "opponent_score" : elements[5]
                    }

    file = paths.SCHEDULE_DATA / Path(f"men_season.json")
    with open(file, "w") as f:
        json.dump(all, f, indent=4)
save_all()
parse()