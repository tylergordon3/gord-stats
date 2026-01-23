import scraper_pro
import utils
import time
import json
import random
import push_scores
import polling
import subprocess
from datetime import datetime, timedelta

def task(poll_rate):
    payload = scraper_pro.get_current_live_dataset()

    payload['meta'] = {
        "poll_interval_sec" : poll_rate,
        "generated" : payload["generated"]
    }
    
    path = utils.get_path('data/live_scores.json')
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)

    print(
        f"Snapshot saved — {len(payload['games'])} games @ {payload['generated']}"
    )
    
    push_scores.push(payload)

def maybe_deploy():
    global last_deploy

    now = datetime.utcnow()

    if last_deploy is None or now - last_deploy >= DEPLOY_INTERVAL:
        print("🚀 Running scheduled deploy...")

        try:
            subprocess.run(
                [DEPLOY_SCRIPT],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

            last_deploy = now
            print("✅ Deploy finished successfully")

        except subprocess.CalledProcessError as e:
            print("❌ Deploy failed")
            print(e.stdout)

BASE_INTERVAL = 30        # always wait this after success
BASE_BACKOFF = 30         # starting backoff on failure
MAX_BACKOFF = 1200        # cap at 20 minutes
DEPLOY_INTERVAL = timedelta(hours=6)
DEPLOY_SCRIPT = "./deploy_pi.sh"

last_deploy = None
attempt = 0

while True:
    try:
        poll_rate = polling.calculate_rate()
        task(poll_rate)

        attempt = 0

        # maybe_deploy()  # 👈 add this

        print(f"Sleeping for {poll_rate}")
        time.sleep(poll_rate)

    except Exception as e:
        delay = min(BASE_BACKOFF * (2 ** attempt), MAX_BACKOFF)
        delay += random.uniform(0, 1)

        print(f"❌ {e} — retrying in {delay:.1f}s")
        time.sleep(delay)
        attempt += 1

