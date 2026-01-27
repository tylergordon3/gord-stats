'''
Docstring for py.kenpom
Documentation:
    https://kenpom.com/api-documentation.php
'''
import kenpom_wrapper
import pandas as pd
import utils
from dotenv import load_dotenv
from datetime import datetime
import pytz
from tqdm import tqdm

load_dotenv() 
kenpom = kenpom_wrapper.KenpomData()

def kenpom_now():
    now = datetime.now().replace(tzinfo=pytz.timezone("US/Eastern")).strftime('%Y-%m-%d')
    ratings = pd.DataFrame(kenpom.get_ratings(2026))
    ff = pd.DataFrame(kenpom.get_four_factors(2026))
    dist = pd.DataFrame(kenpom.get_point_distribution(2026))
    height = pd.DataFrame(kenpom.get_point_distribution(2026))
    misc = pd.DataFrame(kenpom.get_misc_stats(2026))

    merge1 = pd.merge(ratings, ff, how='outer')
    merge2 = pd.merge(merge1, dist, how='outer')
    merge3 = pd.merge(merge2, height, how='outer')
    combo = pd.merge(merge3, misc, how='outer')
    path = utils.get_path(f"data/men/kenpom_api/{now}.json")
    utils.save_json_data(combo.to_json(), path)

def kenpom_by_year(year):
    ratings = pd.DataFrame(kenpom.get_ratings(year=year))
    ff = pd.DataFrame(kenpom.get_four_factors(year=year))
    dist = pd.DataFrame(kenpom.get_point_distribution(year=year))
    height = pd.DataFrame(kenpom.get_point_distribution(year=year))
    misc = pd.DataFrame(kenpom.get_misc_stats(year=year))

    merge1 = pd.merge(ratings, ff, how='outer')
    merge2 = pd.merge(merge1, dist, how='outer')
    merge3 = pd.merge(merge2, height, how='outer')
    combo = pd.merge(merge3, misc, how='outer')
    path = utils.get_path(f"model_data/kenpom_api/{year}.json")
    utils.save_json_data(combo.to_json(), path)
    return combo

def update_all(start=2010, end=2026):
    all = pd.DataFrame()
    with tqdm(total=end-start, desc="Pestering Ken Pomeroy...") as pbar:
        for i in range(start, end):
            df = kenpom_by_year(i)
            all = pd.concat([all, df])
            pbar.update(1)
    all = all.reset_index(drop=True)
    path = utils.get_path(f"model_data/kenpom_api/all.json")
    utils.save_json_data(all.to_json(), path)