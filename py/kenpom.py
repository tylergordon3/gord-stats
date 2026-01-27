'''
Docstring for py.kenpom
Documentation:
    https://kenpom.com/api-documentation.php
'''
import kenpom_wrapper
import pandas as pd
from dotenv import load_dotenv
from functools import reduce

load_dotenv() 
kenpom = kenpom_wrapper.KenpomData()

def kenpom_now():
    ratings = pd.DataFrame(kenpom.get_ratings(2026))
    ff = pd.DataFrame(kenpom.get_four_factors(2026))
    dist = pd.DataFrame(kenpom.get_point_distribution(2026))
    height = pd.DataFrame(kenpom.get_point_distribution(2026))
    misc = pd.DataFrame(kenpom.get_misc_stats(2026))

    merge1 = pd.merge(ratings, ff, how='outer')
    merge2 = pd.merge(merge1, dist, how='outer')
    merge3 = pd.merge(merge2, height, how='outer')
    combo = pd.merge(merge3, misc, how='outer')
    print(combo.columns)
kenpom_now()