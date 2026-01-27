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
kenpom_now()