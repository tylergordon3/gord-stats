import requests
import time
import json
from datetime import datetime
from push_scores import push
import utils
import pytz

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
BATCH_SIZE = 60

LIVE_STATUSES = {"in_progress", "halftime", "delay"}

SKIP_CONFERENCES = {"All Conferences"}

# =========================
# UTILS
# =========================

def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

# =========================
# CONFERENCE DISCOVERY
# =========================

def get_conference_strings():
    resp = requests.get(
        f"{BASE}/ncaab/events/conferences",
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

def get_today_event_ids(conference_strings):
    all_ids = set()

    for conf in conference_strings:
        if conf in SKIP_CONFERENCES:
            continue

        resp = requests.get(
            f"{BASE}/ncaab/schedule",
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

        ids = current.get("event_ids", [])
        all_ids.update(ids)

    return sorted(all_ids)

# =========================
# EVENT HYDRATION
# =========================

def fetch_events_by_ids(event_ids):
    events = []

    for batch in chunks(event_ids, BATCH_SIZE):
        resp = requests.get(
            f"{BASE}/ncaab/events",
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

def format_event(g):
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

    # ---- teams ----
    home = g["home_team"]
    away = g["away_team"]

    # ---- score / progress ----
    box = g.get("box_score") or {}
    score = box.get("score") or {}
    progress = box.get("progress") or {}

    home_score = score.get("home", {}).get("score")
    away_score = score.get("away", {}).get("score")

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

        # teams
        "home_team": home.get("abbreviation"),
        "away_team": away.get("abbreviation"),

        # scores
        "home_score": home_score,
        "away_score": away_score,

        # live info
        "clock": clock,
        "period": period,
        "overtime": overtime,

        # ranks
        "home_rank": g.get("home_ranking"),
        "away_rank": g.get("away_ranking"),

        # meta
        "conference": g.get("home_conference"),
        "venue": g.get("stadium"),
        "location": g.get("location"),

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

    print(f"🟢 Live games at start: {len(live_ids)}")

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

        print(f"⏳ Live games remaining: {len(live_ids)}")

    print("✅ All games final — poller exiting")


def get_current_live_dataset():
    """
    One-shot snapshot of all current games.
    Safe to call repeatedly.
    """

    conferences = get_conference_strings()
    event_ids = get_today_event_ids(conferences)

    if not event_ids:
        return {
            "league": "men",
            "generated": datetime.utcnow().isoformat(),
            "games": {}
        }

    events = fetch_events_by_ids(event_ids)

    games = {}

    for g in events:
        game_id = g.get("id")
        if not game_id:
            continue

        games[str(game_id)] = format_event(g)

    return {
        "league": "men",
        "generated": datetime.utcnow().isoformat(),
        "games": games
    }

# =========================
# MAIN
# =========================

if __name__ == "__main__":
    payload = get_current_live_dataset()
    path = utils.get_path('data/live_scores.json')
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)

    print(
        f"Snapshot saved — {len(payload['games'])} games @ {payload['generated']}"
    )
    
    push(payload)