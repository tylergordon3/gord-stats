import scraper_pro
import utils
import time
import json
import random
import push_scores
import polling
import subprocess
from datetime import datetime, timedelta, timezone

DEPLOY_WINDOW_START = 6   # 06:00 UTC
DEPLOY_WINDOW_END = 9     # 09:00 UTC
DEPLOY_RETRY_INTERVAL = 300  # 5 minutes between deploy attempts

deploy_success_date = None
last_deploy_attempt = None

def safe_push(payload):
    try:
        res = push_scores.push(payload)

        if not res:
            raise RuntimeError("No response from ingest")

        if hasattr(res, "status_code") and res.status_code >= 500:
            print("Worker 5xx — skipping retry this cycle")
            return False

        return True

    except Exception as e:
        print(f"Push failed: {e}")
        return False
    
def seconds_until_next_boundary(interval_sec):
    """
    Returns seconds until the next wall-clock-aligned boundary
    (e.g. :00, :30, etc depending on interval)
    """
    now = datetime.now(timezone.utc)
    epoch = int(now.timestamp())
    return interval_sec - (epoch % interval_sec)

def seconds_until_next_game():
    """
    Returns seconds until the next scheduled game start,
    or None if no upcoming games.
    """
    try:
        with open(utils.get_path("data/live_scores.json")) as f:
            data = json.load(f)

        leagues = data.get("leagues", {})
        now = datetime.now(timezone.utc)

        starts = []

        for league_games in leagues.values():
            for g in league_games.values():
                ts = g.get("start_time_utc")
                if not ts:
                    continue

                start = datetime.fromisoformat(ts)
                if start > now:
                    starts.append((start - now).total_seconds())

        if not starts:
            return None

        return min(starts)

    except Exception:
        return None

def in_deploy_window(now):
    return DEPLOY_WINDOW_START <= now.hour < DEPLOY_WINDOW_END

    
def task(poll_rate):
    # --- scrape both leagues ---
    men = scraper_pro.get_current_live_dataset("men")
    women = scraper_pro.get_current_live_dataset("women")

    # --- combine into ONE payload ---
    payload = {
        "generated": datetime.utcnow().isoformat(),
        "leagues": {
            "men": men["games"],
            "women": women["games"]
        },
        "meta": {
            "poll_interval_sec": poll_rate
        }
    }

    # --- save locally (optional) ---
    path = utils.get_path("data/live_scores.json")
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)

    total_games = len(men["games"]) + len(women["games"])

    print(
        f"Snapshot saved — {total_games} games "
        f"(men={len(men['games'])}, women={len(women['games'])}) "
        f"@ {payload['generated']}"
    )
    push_scores.push(payload)

def maybe_deploy():
    global deploy_success_date, last_deploy_attempt

    now = datetime.now(timezone.utc)
    today = now.date()

    # Only operate inside deploy window
    if not in_deploy_window(now):
        return

    # If already deployed successfully today, stop
    if deploy_success_date == today:
        return

    # Prevent retry spam (wait 5 min between attempts)
    if last_deploy_attempt:
        seconds_since_last = (now - last_deploy_attempt).total_seconds()
        if seconds_since_last < DEPLOY_RETRY_INTERVAL:
            return

    print(f"Deploy attempt @ {now.strftime('%H:%M:%S UTC')}")

    last_deploy_attempt = now

    try:
        subprocess.run(
            [DEPLOY_SCRIPT],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        print("✅ Deploy successful")
        deploy_success_date = today

    except subprocess.CalledProcessError as e:
        print("❌ Deploy failed — will retry within window")
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
        maybe_deploy()

        sleep_for = seconds_until_next_boundary(poll_rate)

        next_game_in = seconds_until_next_game()
        if next_game_in is not None:
            sleep_for = min(sleep_for, max(5, next_game_in - 60))

        print(f"Sleeping {int(sleep_for)}s")
        time.sleep(sleep_for)

    except Exception as e:
        delay = min(BASE_BACKOFF * (2 ** attempt), MAX_BACKOFF)
        delay += random.uniform(0, 1)

        print(f"{e} — retrying in {delay:.1f}s")
        time.sleep(delay)
        attempt += 1

