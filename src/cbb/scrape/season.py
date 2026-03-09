import json
from datetime import date, timedelta, datetime
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
        print(f"Done saving for: {league_key}")


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
            home_win,
            away_win,
        ]
    except:
        return [None]

def parse(gender="M"):
    file = paths.SCHEDULE_DATA / Path(f"wcbk_season.json")
    with open(file, "r") as f:
        data = json.load(f)

    filtered = {}
    for day in data:
        filtered[day["id"]] = day["event_ids"]

    file = paths.SCHEDULE_DATA / Path(f"women_season.json")
    with open(file, "r") as f:
        all = json.load(f)

    for key in filtered:
        games = fetch_events_by_ids(filtered[key], "wcbk")
        today= date.today()
        key_as_date = datetime.fromisoformat(key)
        for g in games:

            elements = parse_g(g)
            if len(elements) > 1 and key_as_date.date() < today:
                home = elements[0]
                away = elements[1]
                home_check = elements[2]
                away_check = elements[3]
                
                # 4 - home score
                # 5 - away score
                # 6 - home win
                # 7 - away win
                if home_check != None:
                    home = home_check
                
                if away_check != None:
                    away = away_check
                
                if home_check != None:
                    all[home_check][key] = {
                        "win" : elements[6],
                        "location" : "home",
                        "score" : elements[4],
                        "opponent" : away,
                        "opponent_score" : elements[5]
                    }
                    
                if away_check != None:
                    all[away_check][key] = {
                        "win" : elements[7],
                        "location" : "away",
                        "score" : elements[5],
                        "opponent" : home,
                        "opponent_score" : elements[4]
                    }

    file = paths.SCHEDULE_DATA / Path(f"women_season.json")
    with open(file, "w") as f:
        json.dump(all, f, indent=4)

def last_night_results(gender="M"):
    save_all()
    yesterday = date.today() - timedelta(days=1)
    yesterday_str = yesterday.isoformat()
    if gender == "M":
        file_name = "men_season.json"
        league = "ncaab"
    elif gender == "W":
        file_name = "women_season.json"
        league = "wcbk"

    file = paths.SCHEDULE_DATA / Path(file_name)
    with open(file, "r") as f:
        all = json.load(f)

    web_file = paths.SCHEDULE_DATA / Path(f"{league}_season.json")
    with open(web_file, "r") as f:
        web_data = json.load(f)
    ids = []
    for day in web_data:
        if day['id'] == yesterday_str:
            ids = day['event_ids']
            break
   
    games = fetch_events_by_ids(ids, league)
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
                all[home_check][yesterday_str] = {
                    "win" : elements[6],
                    "location" : "home",
                    "score" : elements[4],
                    "opponent" : away,
                    "opponent_score" : elements[5]
                }
                
            if away_check != None:
                all[away_check][yesterday_str] = {
                    "win" : elements[7],
                    "location" : "away",
                    "score" : elements[5],
                    "opponent" : home,
                    "opponent_score" : elements[4]
                }
    with open(file, "w") as f:
        json.dump(all, f, indent=4)
    return