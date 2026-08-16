"""
Docstring for py.kenpom
Documentation:
    https://kenpom.com/api-documentation.php
"""

import json
from datetime import datetime

import kenpom_wrapper
import pandas as pd
import pytz
from dotenv import load_dotenv
from tqdm import tqdm

from cbb import utils
from cbb import paths

load_dotenv()
kenpom = kenpom_wrapper.KenpomData()


def kenpom_now():
    now = datetime.now().replace(tzinfo=pytz.timezone("US/Eastern"))
    str = now.strftime("%Y-%m-%d")
    ratings = pd.DataFrame(kenpom.get_ratings(2026))
    ff = pd.DataFrame(kenpom.get_four_factors(2026))
    dist = pd.DataFrame(kenpom.get_point_distribution(2026))
    height = pd.DataFrame(kenpom.get_height(2026))
    misc = pd.DataFrame(kenpom.get_misc_stats(2026))

    merge1 = pd.merge(ratings, ff, how="outer")
    merge2 = pd.merge(merge1, dist, how="outer")
    merge3 = pd.merge(merge2, height, how="outer")
    combo = pd.merge(merge3, misc, how="outer")

    payload = {
        "headers": list(combo.columns),
        "rows": combo.values.tolist(),
    }
    path = paths.M_KEN_DIR / f"{str}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def kenpom_by_year(year):
    ratings = pd.DataFrame(kenpom.get_ratings(year=year))
    ff = pd.DataFrame(kenpom.get_four_factors(year=year))
    dist = pd.DataFrame(kenpom.get_point_distribution(year=year))
    height = pd.DataFrame(kenpom.get_height(year=year))
    misc = pd.DataFrame(kenpom.get_misc_stats(year=year))

    merge1 = pd.merge(ratings, ff, how="outer")
    merge2 = pd.merge(merge1, dist, how="outer")
    merge3 = pd.merge(merge2, height, how="outer")
    combo = pd.merge(merge3, misc, how="outer")
    path = utils.get_path(f"model_data/kenpom_api/{year}.json")
    utils.save_json_data(combo.to_json(), path)
    return combo


def update_all(start=2010, end=2026):
    all = pd.DataFrame()
    with tqdm(total=end - start, desc="Pestering Ken Pomeroy...") as pbar:
        for i in range(start, end):
            df = kenpom_by_year(i)
            df["Tourney"] = df.apply(lambda x: True if x["Seed"] > 0 else False, axis=1)
            all = pd.concat([all, df])
            pbar.update(1)
    all = all.reset_index(drop=True)
    path = utils.get_path(f"model_data/kenpom_api/all.json")
    utils.save_json_data(all.to_json(), path)

def get_today_ken(gender):
    if gender == "M":
        ken_dir = paths.M_KEN_DIR
    elif gender == "W":
        ken_dir = paths.W_KEN_DIR
    else:
        print("Invalid gender given to get_today_net.")
        return None

    # Today's filename
    today_str = datetime.now().strftime("%Y-%m-%d")
    today_file = ken_dir / f"{today_str}.json"

    # If today's file exists, return it
    if today_file.exists():
        target_file = today_file

    # Otherwise get most recent file
    files = sorted(
        ken_dir.glob("*.json"),
        key=lambda f: f.name,  # filenames are YYYY-MM-DD.json so this works
        reverse=True,
    )

    if not files:
        return None

    target_file = files[0]
    print(target_file)
    # Load JSON
    with open(target_file, "r", encoding="utf-8") as f:
       data = json.load(f)

    return data