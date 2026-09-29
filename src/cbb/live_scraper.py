import json
import re
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytz
import requests

from cbb import game_model, scraper, utils
from cbb.push_scores import push
from cbb import paths
from cbb import teams, constants
from cbb.scrape import ats, bpi, net, torvik, season

# =========================
# CONFIG
# =========================

BASE = "https://api.thescore.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Referer": "https://www.thescore.com/",
}

UTC_OFFSET_SECONDS = -18000  # EST - kept for callers; see _utc_offset()


def _utc_offset() -> int:
    """US Eastern's offset now, in seconds: -18000 in winter, -14400 from the
    second Sunday of March, when a fixed EST put games an hour out."""
    from zoneinfo import ZoneInfo
    return int(datetime.now(ZoneInfo("America/New_York")).utcoffset().total_seconds())
POLL_INTERVAL = 25  # seconds
BATCH_SIZE = 120

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

def get_stat(idx, master, lookup):
    if idx is None:
        return None                     # a team the master list does not know
    aliases = master["names"][idx]
    for alias in aliases:
        if alias in lookup:
            return lookup[alias]
    return None


_DIVISION_I = re.compile(r"NCAA Division I( Women)?")


def resolve_team(obj: dict, master) -> tuple:
    """(master index, name, short name) for one of theScore's teams.

    Only a Division I school is the master list's to name. Below it theScore's
    codes collide with the list's aliases - its UMD is Michigan-Dearborn (NAIA),
    which the list files under Maryland (theScore's MD) - and a non-D1 opponent
    is not on the list at all, which used to end in a KeyError that took the
    whole scoreboard down: 56 of 172 men's and 67 of 160 women's games on the
    2026 opening slate (the 2026-09-28 audit). Those keep theScore's own name
    and no index, so every stat lookup is a blank.
    """
    division = obj.get("division")
    if not division or _DIVISION_I.fullmatch(division.strip()):
        idx, name, short = scraper.getNameFromCode(obj.get("abbreviation"), master, True)
        if name is not None:
            return idx, name, short
    own = (obj.get("medium_name") or obj.get("full_name") or obj.get("name")
           or obj.get("abbreviation") or "TBD").strip()
    return None, own, obj.get("abbreviation") or own


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


def normalize_conf_name(conf: str) -> str:
    # theScore sends no conference for some opponents (non-D1 schools early in
    # the season): None.strip() used to take the whole snapshot down.
    conf = (conf or "").strip()
    for name, vals in constants.CONF_MAP.items():
        if conf in vals:
            return name
    return conf


# =========================
# SCHEDULE → EVENT IDS
# =========================


def get_today_event_ids(league_path):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    ET = ZoneInfo("America/New_York")
    MAX_DAYS_AHEAD = 7
    MAX_DAYS_BEHIND = 2
    today_et = datetime.now(ET).date()
    yesterday_et = today_et - timedelta(days=MAX_DAYS_BEHIND)
    cutoff_et = today_et + timedelta(days=MAX_DAYS_AHEAD)

    all_ids = set()

    # One request. This used to sit inside a loop over the conferences, but the
    # conference was never part of it: the same schedule was fetched ~30 times
    # a league on every tick.
    resp = requests.get(
        f"{BASE}/{league_path}/schedule",
        params={"utc_offset": _utc_offset()},
        headers=HEADERS,
        timeout=10,
    )
    resp.raise_for_status()
    sched = resp.json()
    current = sched.get("current_group")
    if current:
        all_ids.update(current.get("event_ids", []))

    groups = sched.get("current_season", [])

    for group in groups:
        group_date = group.get("start_date")
        event_ids = group.get("event_ids", [])

        if not group_date or not event_ids:
            continue

        try:
            group_day = datetime.fromisoformat(group_date).date()
        except Exception:
            continue

        if yesterday_et <= group_day <= cutoff_et:
            all_ids.update(event_ids)

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


def format_event(g, ranks, master, ats, net, bpi, tor_dict, gender, model=None):
    # ---- parse datetime ----
    dt = None
    if g.get("game_date"):
        dt = datetime.strptime(g["game_date"], "%a, %d %b %Y %H:%M:%S %z")
    dt_local = dt.astimezone(EASTERN) if dt else None
    game_date = dt_local.date().isoformat() if dt_local else None
    start_time = dt_local.strftime("%I:%M %p").lstrip("0") if dt_local else None
    start_time_utc = dt.isoformat() if dt else None
   
    # ---- mens lookup dicts ----
    ats_lookup = {}
    ou_lookup = {}
    bpi_lookup = {}

    if ats:
        ats_lookup = {row[0]: row[2] for row in ats["rows"]}
        ou_lookup = {row[0]: row[6] for row in ats["rows"]}
    if bpi:
        bpi_lookup = {row[1]: row[7] for row in bpi["rows"]}

    # ---- both genders lookup dicts ----
    # Either may be missing: neither is published for a new season on day one.
    net_lookup = {row[1]: row[0] for row in net["rows"]} if net else {}
    wab_lookup = ({teams.cleanTorvikNames(row[1]): row[-1] for row in tor_dict["rows"]}
                  if tor_dict else {})
    # Not the whole Torvik table: it rode along on every game (22a3d95d7), ~92 KB
    # each that nothing reads - fine for a four-game tournament day, ~30 MB on
    # opening night, over KV's 25 MB value limit and downloaded by every phone
    # on /men/ and /women/ each poll.

    # ---- team objects ----
    home_obj = g["home_team"]
    away_obj = g["away_team"]

    # ---- get team info from master dict ----
    home_idx, home_name, home_abb = resolve_team(home_obj, master)
    away_idx, away_name, away_abb = resolve_team(away_obj, master)

    # ---- gord model rankings ----
    # .get: a team the model never ranked (a non-D1 opponent, a new program)
    # is a blank on the card, not a KeyError that loses the whole board.
    home_model = ranks.get(home_name, {}).get("Ovr", "") if home_name else ""
    away_model = ranks.get(away_name, {}).get("Ovr", "") if away_name else ""

    hm_safe = safe_float(home_model)
    am_safe = safe_float(away_model)
    rating = (
        (hm_safe + am_safe) / 2 if hm_safe is not None and am_safe is not None else None
    )

    # ---- basic team stats ----
    home_record = ranks.get(home_name, {}).get("Record", "") if home_name else ""
    away_record = ranks.get(away_name, {}).get("Record", "") if away_name else ""

    standings = g.get("standings") or {}
    home_standings_obj = standings.get("home") or {}
    away_standings_obj = standings.get("away") or {}

    home_conf_seed = home_standings_obj.get("conference_seed", "")
    away_conf_seed = away_standings_obj.get("conference_seed", "")

    home_record_last_ten = season.get_last_x(gender, home_name, 10)
    away_record_last_ten = season.get_last_x(gender, away_name, 10)

    home_conf = normalize_conf_name(g.get("home_conference"))
    away_conf = normalize_conf_name(g.get("away_conference"))
    is_p5 = utils.check_p5(home_conf, away_conf)

    # ---- ap rankings ----
    home_ap = g.get("home_ranking")
    away_ap = g.get("away_ranking")
    is_ap = bool(home_ap or away_ap)

    # ---- game info ----
    # theScore leaves both out of some events (exhibitions, early-season
    # tournaments): a missing description was `"NCAA Tournament" in None`
    # and took the whole snapshot down - found by the 2026-09-27 rehearsal.
    game_type = g.get("game_type") or ""
    game_descript = g.get("game_description") or ""
    status = g.get("status")
    stadium = g.get("stadium")

    is_mm = False
    is_nit = False
    if "NCAA Tournament" in game_descript:
        is_mm = True
    elif "NCAAW Tournament" in game_descript:
        is_mm = True
    elif "NIT" in game_descript:
        is_nit = True

    if g.get("location") != None:
        location = g.get("location")[:-5]
    else:
        location = ""

    # ---- score / progress ----
    box = g.get("box_score") or {}
    score = box.get("score") or {}
    progress = box.get("progress") or {}

    home_score = score.get("home", {}).get("score")
    away_score = score.get("away", {}).get("score")

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
    wab_home = get_stat(home_idx, master, wab_lookup)
    wab_away = get_stat(away_idx, master, wab_lookup)

    clock = progress.get("clock")
    period = progress.get("segment_string")
    overtime = progress.get("overtime", False)

    # ---- GordStats' call (cbb.game_model) ----
    # theScore marks no neutral sites: a named tournament is taken as one.
    neutral = bool(g.get("tournament_name")) or is_mm or is_nit or "Tournament" in game_descript
    pick = (game_model.predict(home_name, away_name, model, neutral=neutral, gender=gender)
            if model else None) or {}

    # ---- odds ----
    odd = g.get("odd") or {}
    spread_close = odd.get("line")
    ou_raw = odd.get("over_under")

    try:
        total_close = float(ou_raw)
    except (TypeError, ValueError):
        total_close = None

    return {
        "date": game_date,
        "start_time": start_time,
        "start_time_utc": start_time_utc,
        "status": status,
        "rating": rating,
        "home_team": home_name,
        "away_team": away_name,
        "home_abb": home_abb,
        "away_abb": away_abb,
        "is_p5": is_p5,
        "home_record": home_record,
        "away_record": away_record,
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
        "clock": clock,
        "period": period,
        "overtime": overtime,
        "home_rank": home_ap,
        "away_rank": away_ap,
        "is_ap": is_ap,
        "conference_home": home_conf,
        "conference_away": away_conf,
        "venue": stadium,
        "location": location,
        "spread_close": spread_close,
        "total_close": total_close,
        "home_last_ten": home_record_last_ten,
        "away_last_ten": away_record_last_ten,
        "home_conf_seed": home_conf_seed,
        "away_conf_seed": away_conf_seed,
        "game_type": game_type,
        "game_description": game_descript,
        "is_mm": is_mm,
        "is_nit": is_nit,
        "wab_home": wab_home,
        "wab_away": wab_away,
        "pred_home": pick.get("pred_home"),
        "pred_away": pick.get("pred_away"),
        "home_win_prob": pick.get("home_win_prob"),
        "neutral": neutral,
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

    event_ids = get_today_event_ids(league_path)

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

    # Today's ranks, else the newest from this season - never last season's,
    # which put "Duke #1 (35-3)" on the first night of the next one.
    this_season = [d for d in ranks_dict if utils.season_year(d) == utils.season_year(today)]
    ranks_date = today if today in ranks_dict else max(this_season, default=None)
    ranks = ranks_dict.get(ranks_date, {}) if ranks_date else {}

    master = scraper.getMasterTeams()

    # Only load ATS for men
    if league_key == "men":
        ats_dict = ats.get_today_ats()
        net_dict = net.get_today_net("M")
        bpi_dict = bpi.get_today_bpi()
        tor_dict = torvik.get_today_tor("M")
        gender = "M"
    else:
        ats_dict = None
        net_dict = net.get_today_net("W")
        bpi_dict = None
        tor_dict = torvik.get_today_tor("W")
        gender = "W"

    # This season's Torvik table for GordStats' calls; none before it exists.
    model = game_model.today_table(gender)

    for g in events:
        game_id = g.get("id")
        if not game_id:
            continue

        games[str(game_id)] = format_event(
            g, ranks, master, ats_dict, net_dict, bpi_dict, tor_dict, gender, model
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
            "games": snapshots[league_key]["games"],
        }

        if league_key == "women":
            path = paths.W_LIVE
        else:
            path = paths.M_LIVE

        with open(path, "w") as f:
            json.dump(payload, f, indent=2)

        print(
            f"{league_key.upper()} snapshot — "
            f"{len(payload['games'])} games @ {payload['generated']}"
        )

        push(payload)
