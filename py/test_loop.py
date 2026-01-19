import scraper_pro
import utils
import time
import json
import random
import push_scores
import polling


def task():
    payload = scraper_pro.get_current_live_dataset()
    path = utils.get_path('data/live_scores.json')
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)

    print(
        f"Snapshot saved — {len(payload['games'])} games @ {payload['generated']}"
    )
    
    push_scores.push(payload)

BASE_INTERVAL = 30        # always wait this after success
BASE_BACKOFF = 30         # starting backoff on failure
MAX_BACKOFF = 1200        # cap at 20 minutes

attempt = 0

while True:
    try:
        task()

        # success → reset backoff and wait normal interval
        attempt = 0
        poll_rate = polling.calculate_rate()
        time.sleep(poll_rate)

    except Exception as e:
        # failure → exponential backoff
        delay = min(BASE_BACKOFF * (2 ** attempt), MAX_BACKOFF)
        delay += random.uniform(0, 1)  # jitter

        print(f"❌ {e} — retrying in {delay:.1f}s")

        time.sleep(delay)
        attempt += 1
