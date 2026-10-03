"""
Used to collect daily needed data
"""

import time
from datetime import datetime
from pathlib import Path

import pytz

from cbb import paths
from cbb.scrape import ats, bpi, kenpom, net, torvik, season

RETRY_SLEEP = 300
MAX_RETRIES = 5


def check_scrape(path):
    return path.exists()


# Which league's predictions each feed is an input to (cbb.predictions): a
# women's feed that is late holds back the women's predictions only. In
# 2025-26 the women's Torvik tables started five weeks after the men's
# (data/women/torvik from Dec 17), and Torvik's 2027 women's files were not
# up a month before tip-off.
LEAGUE = {"Men's Torvik": "M", "Men's ATS": "M", "KenPom": "M", "Men's Net Rankings": "M",
          "ESPN BPI": "M", "Men's Schedules": "M",
          "Women's Net Rankings": "W", "Women's Torvik": "W", "Women's Schedules": "W"}


def main():
    """True when every feed scraped (or is not out for the season yet)."""
    return not failures()


def failures() -> list:
    """Scrape the day's feeds; the names (LEAGUE's keys) of those that failed."""
    now = datetime.now().replace(tzinfo=pytz.timezone("US/Eastern"))
    today = now.strftime("%Y-%m-%d")
    fp = Path(f"{today}.json")
    targets = {
        # Back on (2026-09-27) from Torvik's plain CSVs - see cbb.scrape.torvik.
        # Off, the men's Torvik model and the whole women's model scored the
        # last file there was, 2026-03-15, all season.
        "Men's Torvik": (paths.M_TOR_DIR / fp, lambda: torvik.mens_tor(today)),
        "Men's ATS": (paths.M_ATS_DIR / fp, lambda: ats.main()),
        "KenPom": (paths.M_KEN_DIR / fp, kenpom.kenpom_now),
        "Men's Net Rankings": (paths.M_NET_DIR / fp, lambda: net.main("M")),
        "ESPN BPI": (paths.M_ESPN_DIR / fp, bpi.main),
        "Men's Schedules" : (paths.M_SCHEDULE, lambda: season.last_night_results("M")),
        "Women's Net Rankings": (paths.W_NET_DIR / fp, lambda: net.main("W")),
        "Women's Torvik": (paths.W_TOR_DIR / fp, lambda: torvik.womens_tor(today)),
        "Women's Schedules" : (paths.W_SCHEDULE, lambda: season.last_night_results("W"))
    }

    failed = []

    for name, (path, func) in targets.items():
        if path == paths.W_SCHEDULE:
            if season.check_last_night("W") == True:
                continue
        elif path == paths.M_SCHEDULE:
            if season.check_last_night("M") == True:
                continue
        elif check_scrape(path):
            continue

        try:
            func()
        except net.NotReleased as e:
            # Not a failure: until early December there is nothing to fetch,
            # and the predictions blend without NET until there is.
            print(f"{name}: {e}")
            continue
        except Exception as e:
            print(f"Error scraping {name} : {e}")
            failed.append(name)
            continue
        if check_scrape(path):
            print(f"Scraped {name} for {today}.")
        else:
            print(f"Ran {name} for {today} but encountered an error.")
            failed.append(name)
    return failed


def get_data():
    attempts = 0

    while attempts < MAX_RETRIES:
        ok = main()

        if ok:
            print(f"Daily file collection complete.")
            break

        attempts += 1
        print(f"Retry {attempts}/{MAX_RETRIES} in {RETRY_SLEEP} seconds.")
        time.sleep(RETRY_SLEEP)

    if attempts == MAX_RETRIES:
        print("Max retries reached, some data may be missing.")
