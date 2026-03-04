import json
import time
from datetime import datetime

import pytz
import requests

from cbb import scraper, utils
from cbb.push_scores import push
from cbb.scrape import ats, bpi, net

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

# =========================
# UTILS
# =========================


def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


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
        f"{BASE}/{league_path}/events/conferences", headers=HEADERS, timeout=10
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
            params={"conference": conf, "utc_offset": UTC_OFFSET_SECONDS},
            headers=HEADERS,
            timeout=10,
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
            timeout=10,
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


def format_event(g, ranks, master, ats, net, bpi):
    # ---- parse datetime ----
    dt = None
    if g.get("game_date"):
        dt = datetime.strptime(g["game_date"], "%a, %d %b %Y %H:%M:%S %z")

    dt_local = dt.astimezone(EASTERN) if dt else None

    game_date = dt_local.date().isoformat() if dt_local else None
    start_time = dt_local.strftime("%I:%M %p").lstrip("0") if dt_local else None

    ats_lookup = {}
    if ats:
        ats_lookup = {row[0]: row[2] for row in ats["rows"]}

    ou_lookup = {}
    if ats:
        ou_lookup = {row[0]: row[6] for row in ats["rows"]}

    bpi_lookup = {}
    if bpi:
        bpi_lookup = {row[1]: row[7] for row in bpi["rows"]}

    net_lookup = {row[1]: row[0] for row in net["rows"]}

    # ---- teams ----
    home = g["home_team"]
    away = g["away_team"]

    [home_idx, home_name, home_abb] = scraper.getNameFromCode(
        home.get("abbreviation"), master, True
    )
    [away_idx, away_name, away_abb] = scraper.getNameFromCode(
        away.get("abbreviation"), master, True
    )

    home_model = ranks[home_name]["Ovr"] if home_name else ""
    away_model = ranks[away_name]["Ovr"] if away_name else ""

    home_record = ranks[home_name]["Record"] if home_name else ""
    away_record = ranks[away_name]["Record"] if away_name else ""

    home_record_last_ten = g['standings']['home']['last_ten_games_record']
    away_record_last_ten = g['standings']['away']['last_ten_games_record']

    home_conf_seed = g['standings']['home']['conference_seed']
    away_conf_seed = g['standings']['away']['conference_seed']

    game_type = g['game_type']

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
    away_ap = g.get("away_ranking")
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

    def get_stat(idx, master, lookup):
        aliases = master["names"][idx]
        for alias in aliases:
            if alias in lookup:
                return lookup[alias]
        return None

    if ats_lookup:
        ats_home = get_stat(home_idx, master, ats_lookup)
        ats_away = get_stat(away_idx, master, ats_lookup)
        ou_home = get_stat(home_idx, master, ou_lookup)
        ou_away = get_stat(away_idx, master, ou_lookup)
        bpi_home = get_stat(home_idx, master, bpi_lookup)
        bpi_away = get_stat(away_idx, master, bpi_lookup)
    else:
        ats_home = None
        ats_away = None
        ou_home = None
        ou_away = None
        bpi_home = None
        bpi_away = None

    net_home = get_stat(home_idx, master, net_lookup)
    net_away = get_stat(away_idx, master, net_lookup)

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
        "rating": rating,
        # teams
        "home_team": home_name,
        "away_team": away_name,
        "home_abb": home_abb,
        "away_abb": away_abb,
        "is_p5": is_p5,
        "home_record": home_record,
        "away_record": away_record,
        # scores
        "home_score": home_score,
        "away_score": away_score,
        "away_model": away_model,
        "home_model": home_model,
        "ats_away": ats_away,
        "ats_home": ats_home,
        "ou_away": ou_away,
        "ou_home": ou_home,
        "net_away": net_away,
        "net_home": net_home,
        "bpi_away": bpi_away,
        "bpi_home": bpi_home,
        # live info
        "clock": clock,
        "period": period,
        "overtime": overtime,
        # ranks
        "home_rank": home_ap,
        "away_rank": away_ap,
        "is_ap": is_ap,
        # meta
        "conference_home": g.get("home_conference"),
        "conference_away": g.get("away_conference"),
        "venue": g.get("stadium"),
        "location": g.get("location")[:-5],
        # betting
        "spread_close": spread_close,
        "total_close": total_close,

        #standings/record
        "home_last_ten" : home_record_last_ten,
        "away_last_ten" : away_record_last_ten,
        "home_conf_seed" : home_conf_seed,
        "away_conf_seed" : away_conf_seed,
        "game_type" : game_type,
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
    live_ids = {g["id"] for g in initial_events if g["status"] in LIVE_STATUSES}

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
            "games": {},
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

    # Only load ATS for men
    if league_key == "men":
        ats_dict = ats.get_today_ats()
        net_dict = net.get_today_net("M")
        bpi_dict = bpi.get_today_bpi()
    else:
        ats_dict = None
        net_dict = net.get_today_net("W")
        bpi_dict = None

    for g in events:
        game_id = g.get("id")
        if not game_id:
            continue

        games[str(game_id)] = format_event(
            g, ranks, master, ats_dict, net_dict, bpi_dict
        )

    return {
        "league": league_key,
        "generated": datetime.utcnow().isoformat(),
        "games": games,
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
            },
        }

        path = utils.get_path(f"data/live_scores_{league_key}.json")
        with open(path, "w") as f:
            json.dump(payload, f, indent=2)

        print(
            f"{league_key.upper()} snapshot — "
            f"{len(payload['leagues'][league_key])} games @ {payload['generated']}"
        )

        push(payload)
