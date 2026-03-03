import json
import random
import subprocess
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from cbb import live_scraper, polling_rate, push_scores
from cbb.lib import paths

EASTERN = ZoneInfo("America/New_York")
DEPLOY_HOUR = 8  # 8 AM Eastern
DEPLOY_RETRY_INTERVAL = 300  # 5 minutes

DEPLOY_WINDOW_START = 6  # 06:00 UTC
DEPLOY_WINDOW_END = 9  # 09:00 UTC
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
        live_path = paths.DATA / "live_scores.json"

        if not live_path.exists():
            return None

        with open(live_path, "r", encoding="utf-8") as f:
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
    men = live_scraper.get_current_live_dataset("men")
    women = live_scraper.get_current_live_dataset("women")

    # --- combine into ONE payload ---
    payload = {
        "generated": datetime.utcnow().isoformat(),
        "leagues": {"men": men["games"], "women": women["games"]},
        "meta": {"poll_interval_sec": poll_rate},
    }

    # --- save locally (optional) ---
    path = paths.DATA / "live_scores.json"

    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
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

    now_utc = datetime.now(timezone.utc)
    now_et = now_utc.astimezone(EASTERN)
    today_et = now_et.date()

    # If already deployed successfully today (Eastern date), stop
    if deploy_success_date == today_et:
        return

    # Only trigger after 8:00 AM Eastern
    if not (DEPLOY_HOUR <= now_et.hour < DEPLOY_HOUR + 2):
        return

    # Prevent retry spam
    if last_deploy_attempt:
        seconds_since_last = (now_utc - last_deploy_attempt).total_seconds()
        if seconds_since_last < DEPLOY_RETRY_INTERVAL:
            return

    print(f"Deploy attempt @ {now_et.strftime('%Y-%m-%d %H:%M:%S %Z')}")

    last_deploy_attempt = now_utc

    try:
        subprocess.run(
            [str(DEPLOY_SCRIPT)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        print("✅ Deploy successful")
        deploy_success_date = today_et

    except subprocess.CalledProcessError as e:
        print("❌ Deploy failed — will retry")
        print(e.stdout)


BASE_INTERVAL = 30  # always wait this after success
BASE_BACKOFF = 30  # starting backoff on failure
MAX_BACKOFF = 1200  # cap at 20 minutes
DEPLOY_INTERVAL = timedelta(hours=6)
DEPLOY_SCRIPT = paths.ROOT / "deploy_pi.sh"

last_deploy = None
attempt = 0

while True:
    try:
        poll_rate = polling_rate.calculate_rate()
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
        delay = min(BASE_BACKOFF * (2**attempt), MAX_BACKOFF)
        delay += random.uniform(0, 1)

        print(f"{e} — retrying in {delay:.1f}s")
        time.sleep(delay)
        attempt += 1
