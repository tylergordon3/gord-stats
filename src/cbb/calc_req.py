from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from cbb import utils

# -----------------------------
# Constants
# -----------------------------

ET = ZoneInfo("America/New_York")

ZONE_GAP = timedelta(hours=2, minutes=30)

FREE_WRITE_LIMIT = 1000
BASELINE_WRITES_PER_DAY = 24
MAX_POLL_WRITES_PER_DAY = FREE_WRITE_LIMIT - BASELINE_WRITES_PER_DAY  # 976

POLL_OPTIONS = [15, 30, 45, 60]  # seconds (fast → slow)

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
    """Determine fastest safe polling interval per day."""
    live_secs = live_seconds_per_day(zones)
    plan = {}

    for day, secs in live_secs.items():
        min_req = min_interval_seconds(secs)
        chosen = choose_poll_interval(min_req)

        plan[day] = {
            "live_hours": secs / 3600,
            "min_interval_sec": min_req,
            "chosen_interval_sec": chosen,
            "fits_free_tier": chosen is not None,
        }

    return plan


# -----------------------------
# Printing helpers
# -----------------------------


def print_zones(zones):
    for i, (start, end) in enumerate(zones, 1):
        hours = zone_hours(start, end)
        crosses = " (crosses midnight)" if start.date() != end.date() else ""

        print(
            f"Zone {i}: "
            f"{start.strftime('%Y-%m-%d %I:%M %p')} ET → "
            f"{end.strftime('%Y-%m-%d %I:%M %p')} ET | "
            f"{hours:.2f} hrs"
            f"{crosses}"
        )


def print_polling_plan(plan):
    print("Date       | Live hrs | Min interval | Chosen | Status")
    print("-" * 60)

    for day in sorted(plan):
        row = plan[day]

        min_int = f"{row['min_interval_sec']:.1f}s" if row["min_interval_sec"] else "-"
        chosen = f"{row['chosen_interval_sec']}s" if row["chosen_interval_sec"] else "-"
        status = "OK" if row["fits_free_tier"] else "OVER LIMIT"

        print(
            f"{day} | "
            f"{row['live_hours']:8.2f} | "
            f"{min_int:12} | "
            f"{chosen:6} | "
            f"{status}"
        )


# -----------------------------
# Main execution
# -----------------------------

data = pd.read_json(utils.get_path("data/live_scores.json"))
games = data["games"]

utc_times = [datetime.fromisoformat(g["start_time_utc"]) for g in games]

dt_et = normalize_times(utc_times)
zones = calculate_polling_zones(dt_et)

print_zones(zones)

live_hrs = [zone_hours(s, e) for s, e in zones]
total_hours = sum(live_hrs)
avg_hours = total_hours / len(zones) if zones else 0

print(f"\nTotal live polling hours: {total_hours:.2f}")
print(f"Average zone length: {avg_hours:.2f} hrs\n")

plan = daily_polling_plan(zones)
print_polling_plan(plan)
