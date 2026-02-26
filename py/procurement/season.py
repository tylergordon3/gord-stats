import requests
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

def get_all_events(league_path, conference_strings):
    all_ids = set()

    for conf in conference_strings:
        if conf in SKIP_CONFERENCES:
            continue

        resp = requests.get(
            f"{BASE}/{league_path}/schedule",
            params={"utc_offset": UTC_OFFSET_SECONDS},
            headers=HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        sched = resp.json()

        print(sched)

def main():
    league_key = "men"
    cfg = LEAGUES[league_key]
    league_path = cfg["path"]
    conferences = get_conference_strings(league_path)
    events = get_all_events(league_path, conferences)

if __name__ == "__main__":
    main()