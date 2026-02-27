import json
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from cbb import utils

# -----------------------------
# Constants
# -----------------------------

ET = ZoneInfo("America/New_York")

ZONE_GAP = timedelta(hours=2, minutes=30)
BASELINE_WRITES_PER_DAY = 24

# -----------------------------
# Free plan calc
# -----------------------------
FREE_WRITE_LIMIT = 1000
MAX_POLL_WRITES_PER_DAY = FREE_WRITE_LIMIT - BASELINE_WRITES_PER_DAY  # 976
POLL_OPTIONS = [15, 30, 45, 60]  # seconds (fast → slow)

# -----------------------------
# Paid plan calc
# -----------------------------
PAID_WRITE_LIMIT = 20000
MAX_WRITES_PER_DAY = PAID_WRITE_LIMIT - BASELINE_WRITES_PER_DAY

MIN_LIVE_INTERVAL = 10
MAX_LIVE_INTERVAL = 120

# -----------------------------
# Time normalization
# -----------------------------


def normalize_times(dt_list):
    """Convert UTC datetimes to ET, shift midnight games, dedupe, sort."""
    out = []

    for dt in dt_list:
        dt_et = dt.astimezone(ET)

        # shift exact midnight back
        if dt_et.hour == 0 and dt_et.minute == 0:
            dt_et -= timedelta(minutes=1)

        out.append(dt_et)

    return sorted(set(out))


# -----------------------------
# Polling zone construction
# -----------------------------


def calculate_polling_zones(times):
    """Build continuous polling zones across full ET timeline."""
    if not times:
        return []

    zones = []
    zone_start = last_time = times[0]

    for current in times[1:]:
        if current - last_time <= ZONE_GAP:
            last_time = current
        else:
            zones.append((zone_start, last_time + ZONE_GAP))
            zone_start = last_time = current

    zones.append((zone_start, last_time + ZONE_GAP))
    return zones


def zone_hours(start, end):
    return (end - start).total_seconds() / 3600


# -----------------------------
# Live time per day
# -----------------------------


def live_seconds_per_day(zones):
    """Return total live seconds per ET day (midnight-safe)."""
    seconds = defaultdict(float)

    for start, end in zones:
        day = start.date()
        while day <= end.date():
            day_start = datetime.combine(day, datetime.min.time(), tzinfo=ET)
            day_end = datetime.combine(
                day + timedelta(days=1), datetime.min.time(), tzinfo=ET
            )

            seg_start = max(start, day_start)
            seg_end = min(end, day_end)

            if seg_end > seg_start:
                seconds[day] += (seg_end - seg_start).total_seconds()

            day += timedelta(days=1)

    return dict(seconds)


# -----------------------------
# Polling interval selection
# -----------------------------


def min_interval_seconds(live_seconds):
    """Minimum polling interval (seconds) to stay under daily cap."""
    if live_seconds <= 0:
        return None
    return live_seconds / MAX_POLL_WRITES_PER_DAY


def choose_poll_interval(min_required):
    """Fastest polling interval that fits free tier."""
    if min_required is None:
        return None

    for opt in POLL_OPTIONS:
        if opt >= min_required:
            return opt

    return None  # even 60s is too fast


def daily_polling_plan(zones):
    """Determine dynamic polling interval per day."""
    live_secs = live_seconds_per_day(zones)
    plan = {}

    for day, secs in live_secs.items():
        interval = dynamic_interval_seconds(secs)

        plan[day] = {
            "live_hours": secs / 3600,
            "live_seconds": secs,
            "poll_interval_sec": interval,
            "fits_limit": interval is not None,
        }

    return plan


def dynamic_interval_seconds(live_seconds):
    """
    Compute polling interval (seconds) to stay under daily cap.
    Returns None if no live time.
    """
    if live_seconds <= 0:
        return None

    interval = live_seconds / MAX_WRITES_PER_DAY

    # Clamp to sane bounds
    return max(MIN_LIVE_INTERVAL, min(interval, MAX_LIVE_INTERVAL))


def polling_rate_now(now, zones, daily_plan, default_idle=3600):
    """
    returns: polling interval in seconds
    """

    for start, end in zones:
        if start <= now <= end:
            plan = daily_plan.get(now.date())

            if not plan or not plan["fits_limit"]:
                return default_idle  # fail safe

            return int(plan["poll_interval_sec"])

    # Not live
    return default_idle


def calculate_rate():
    with open(utils.get_path("data/live_scores.json")) as f:
        data = json.load(f)

    leagues = data.get("leagues", {})

    # ---- merge all games across leagues ----
    games = {}
    for league_games in leagues.values():
        games.update(league_games)

    # ---- extract start times ----
    utc_times = [
        datetime.fromisoformat(g["start_time_utc"])
        for g in games.values()
        if g.get("start_time_utc")
    ]

    # No upcoming games → idle polling
    if not utc_times:
        return 1800  # 30 min

    # Normalize to ET, build zones
    dt_et = normalize_times(utc_times)
    zones = calculate_polling_zones(dt_et)
    plan = daily_polling_plan(zones)

    now = datetime.now(ET)

    interval = polling_rate_now(
        now=now, zones=zones, daily_plan=plan, default_idle=1800  # 1 hour when idle
    )
    return interval
