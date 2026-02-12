import requests
import time
import json
from datetime import datetime
from push_scores import push
import utils
import pytz
import pandas as pd
import scraper
import ats

# =========================
# CONFIG
# =========================

BASE = "https://api.thescore.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Referer": "https://www.thescore.com/"
}

UTC_OFFSET_SECONDS = -18000      # EST
POLL_INTERVAL = 25               # seconds
BATCH_SIZE = 90

LIVE_STATUSES = {"in_progress", "halftime", "delay"}

SKIP_CONFERENCES = {"All Conferences"}

LEAGUES = {
    "men": {
        "path": "ncaab",
        "label": "men"
    },
    "women": {
        "path": "wcbk",
        "label": "women"
    }
}

# =========================
# UTILS
# =========================

def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]
        
def get_rank_dict_for_league(league):
    if league == "men":
        return scraper.getTeamRanks()
    elif league == "women":
        return scraper.getWTeamRanks()
    else:
        raise ValueError(f"Unknown league: {league}")

def safe_float(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None
    
# =========================
# CONFERENCE DISCOVERY
# =========================

def get_conference_strings(league_path):
    resp = requests.get(
        f"{BASE}/{league_path}/events/conferences",
        headers=HEADERS,
        timeout=10
    )
    resp.raise_for_status()

    payload = resp.json()
    confs = set()

    for block in payload:
        for c in block.get("conferences", []):
            confs.add(c)

    return sorted(confs)

# =========================
# SCHEDULE → EVENT IDS
# =========================

def get_today_event_ids(conference_strings, league_path):
    all_ids = set()

    for conf in conference_strings:
        if conf in SKIP_CONFERENCES:
            continue

        resp = requests.get(
            f"{BASE}/{league_path}/schedule",
            params={
                "conference": conf,
                "utc_offset": UTC_OFFSET_SECONDS
            },
            headers=HEADERS,
            timeout=10
        )
        resp.raise_for_status()
        sched = resp.json()

        current = sched.get("current_group")
        if not current:
            continue

        all_ids.update(current.get("event_ids", []))

    return sorted(all_ids)


# =========================
# EVENT HYDRATION
# =========================

def fetch_events_by_ids(event_ids, league_path):
    events = []

    for batch in chunks(event_ids, BATCH_SIZE):
        resp = requests.get(
            f"{BASE}/{league_path}/events",
            params={"id.in": ",".join(map(str, batch))},
            headers=HEADERS,
            timeout=10
        )
        resp.raise_for_status()
        events.extend(resp.json())

    return events

# =========================
# EVENT FORMATTER
# =========================

from datetime import datetime
import pytz

EASTERN = pytz.timezone("US/Eastern")

def format_event(g, ranks, master, ats):
    # ---- parse datetime ----
    dt = None
    if g.get("game_date"):
        dt = datetime.strptime(
            g["game_date"], "%a, %d %b %Y %H:%M:%S %z"
        )

    dt_local = dt.astimezone(EASTERN) if dt else None

    game_date = dt_local.date().isoformat() if dt_local else None
    start_time = (
        dt_local.strftime("%I:%M %p").lstrip("0")
        if dt_local else None
    )

    ats_lookup = {
        row[0]: {
            "ats_record": row[1],
            "cover_pct": row[2],
            "mov": row[3],
            "ats_plus_minus": row[4]
        }
        for row in ats["rows"]
    }
    
    # ---- teams ----
    home = g["home_team"]
    away = g["away_team"]
    
    [_, home_name, home_abb] = scraper.getNameFromCode(home.get("abbreviation"), master, True)
    [_, away_name, away_abb]= scraper.getNameFromCode(away.get("abbreviation"), master, True)

    home_model = ranks[home_name]['Ovr'] if home_name else ''
    away_model = ranks[away_name]['Ovr'] if away_name else ''

    home_record = ranks[home_name]['Record'] if home_name else ''
    away_record = ranks[away_name]['Record'] if away_name else ''
    
    home_ats_name = master["team"][str(home_name)]
    away_ats_name = master["team"][str(away_name)]
    
    def safe_float(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    hm = safe_float(home_model)
    am = safe_float(away_model)

    rating = (hm + am) / 2 if hm is not None and am is not None else None
        
     # ranks
    home_ap = g.get("home_ranking")
    away_ap =  g.get("away_ranking")
    is_ap = bool(home_ap or away_ap)

    # conferences
    home_conf = g.get("home_conference")
    away_conf = g.get("away_conference")
    is_p5 = utils.check_p5(home_conf, away_conf)
    
    # ---- score / progress ----
    box = g.get("box_score") or {}
    score = box.get("score") or {}
    progress = box.get("progress") or {}

    home_score = score.get("home", {}).get("score")
    away_score = score.get("away", {}).get("score")
    
    ats_home = ats_lookup.get(home_ats_name)
    ats_away = ats_lookup.get(away_ats_name)
    
    clock = progress.get("clock")
    period = progress.get("segment_string")
    overtime = progress.get("overtime", False)

    # ---- odds ----
    odd = g.get("odd") or {}
    spread_close = odd.get("line")

    ou_raw = odd.get("over_under")
    try:
        total_close = float(ou_raw)
    except (TypeError, ValueError):
        total_close = None

    return {
        # timing
        "date": game_date,
        "start_time": start_time,
        "start_time_utc": dt.isoformat() if dt else None,

        # status
        "status": g.get("status"),

        "rating":rating,
        # teams
        "home_team": home_name,
        "away_team": away_name,

        "home_abb": home_abb,
        "away_abb": away_abb,   
        
        "is_p5":is_p5,
        "home_record":home_record,
        "away_record":away_record,
        
        # scores
        "home_score": home_score,
        "away_score": away_score,
        
        "away_model" : away_model ,
        "home_model" : home_model,

        "ats_away": ats_away,
        "ats_home": ats_home,
        
        # live info
        "clock": clock,
        "period": period,
        "overtime": overtime,

        # ranks
        "home_rank": home_ap,
        "away_rank": away_ap,
        "is_ap" : is_ap,

        # meta
        "conference": g.get("home_conference"),
        "venue": g.get("stadium"),
        "location": g.get("location")[:-5],

        # betting
        "spread_close": spread_close,
        "total_close": total_close,
    }

# =========================
# LIVE SNAPSHOT + DELTA
# =========================

def live_snapshot(g):
    box = g.get("box_score") or {}
    score = box.get("score") or {}
    progress = box.get("progress") or {}

    return {
        "home_score": score.get("home", {}).get("score"),
        "away_score": score.get("away", {}).get("score"),
        "clock": progress.get("clock"),
        "period": progress.get("segment_string"),
        "overtime": progress.get("overtime", False),
        "status": g.get("status"),
    }

def diff_snapshots(prev, curr):
    delta = {}

    for k in curr:
        prev_val = None if prev is None else prev.get(k)
        curr_val = curr.get(k)

        if prev is None or prev_val != curr_val:
            delta[k] = (prev_val, curr_val)

    return delta if delta else None


# =========================
# LIVE POLLER
# =========================

def live_poller(initial_events):
    live_ids = {
        g["id"] for g in initial_events
        if g["status"] in LIVE_STATUSES
    }

    print(f"Live games at start: {len(live_ids)}")

    snapshots = {}

    while live_ids:
        time.sleep(POLL_INTERVAL)

        events = fetch_events_by_ids(sorted(live_ids))
        now = datetime.utcnow().isoformat()

        for g in events:
            game_id = g["id"]
            snap = live_snapshot(g)
            delta = diff_snapshots(snapshots.get(game_id), snap)

            snapshots[game_id] = snap

            if delta:
                print(f"[{now}] Game {game_id} update:")
                for k, (a, b) in delta.items():
                    print(f"  {k}: {a} → {b}")

            if g["status"] == "final":
                print(f"🔴 Game {game_id} FINAL")
                live_ids.remove(game_id)

        print(f"Live games remaining: {len(live_ids)}")

    print("All games final — poller exiting")


def get_current_live_dataset(league_key):
    cfg = LEAGUES[league_key]
    league_path = cfg["path"]

    conferences = get_conference_strings(league_path)
    event_ids = get_today_event_ids(conferences, league_path)

    if not event_ids:
        return {
            "league": league_key,
            "generated": datetime.utcnow().isoformat(),
            "games": {}
        }

    events = fetch_events_by_ids(event_ids, league_path)

    games = {}
    ranks_dict = get_rank_dict_for_league(league_key)

    today = datetime.today().date().isoformat()

    if today in ranks_dict:
        ranks_date = today
    else:
        # fallback to most recent available date
        ranks_date = max(ranks_dict.keys())

    ranks = ranks_dict.get(ranks_date, {})

    master = scraper.getMasterTeams()
    
    ats_dict = ats.get_today_ats()
    
    for g in events:
        game_id = g.get("id")
        if not game_id:
            continue

        games[str(game_id)] = format_event(g, ranks, master, ats_dict)
    
    return {
        "league": league_key,
        "generated": datetime.utcnow().isoformat(),
        "games": games
    }

# =========================
# MAIN
# =========================

if __name__ == "__main__":
    snapshots = {}
    for league_key in ("men", "women"):
        snapshots[league_key] = get_current_live_dataset(league_key)

        payload = {
            "generated": datetime.utcnow().isoformat(),
            "leagues": {
                "men": snapshots["men"]["games"],
                "women": snapshots["women"]["games"],
            }
        }
        
        path = utils.get_path(f"data/live_scores_{league_key}.json")
        with open(path, "w") as f:
            json.dump(payload, f, indent=2)

        print(
            f"{league_key.upper()} snapshot — "
            f"{len(payload['leagues'][league_key])} games @ {payload['generated']}"
        )

        push(payload)
