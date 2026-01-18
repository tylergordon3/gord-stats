import scraper_pro
import utils
import time
import json
import random
import push_scores


def task():
    payload = scraper_pro.get_current_live_dataset()
    path = utils.get_path('data/live_scores.json')
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)

    print(
        f"Snapshot saved — {len(payload['games'])} games @ {payload['generated']}"
    )
    
    push_scores.push(payload)

BASE_DELAY = 30
MAX_DELAY = 1200  # cap at 20 minutes
attempt = 0

while True:
    try:
        task()
        attempt = 0  # reset on success
        time.sleep(60)
    except Exception as e:
        delay = min(BASE_DELAY * (2 ** attempt), MAX_DELAY)
        delay += random.uniform(0, 1)  # jitter
        print(f"❌ {e} — retrying in {delay:.1f}s")
        time.sleep(delay)
        attempt += 1
