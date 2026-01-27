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
import json
from tqdm import tqdm
from io import StringIO

load_dotenv() 
kenpom = kenpom_wrapper.KenpomData()

def kenpom_now():
    now = datetime.now().replace(tzinfo=pytz.timezone("US/Eastern"))
    str = now.strftime('%Y-%m-%d')
    ratings = pd.DataFrame(kenpom.get_ratings(2026))
    ff = pd.DataFrame(kenpom.get_four_factors(2026))
    dist = pd.DataFrame(kenpom.get_point_distribution(2026))
    height = pd.DataFrame(kenpom.get_point_distribution(2026))
    misc = pd.DataFrame(kenpom.get_misc_stats(2026))

    merge1 = pd.merge(ratings, ff, how='outer')
    merge2 = pd.merge(merge1, dist, how='outer')
    merge3 = pd.merge(merge2, height, how='outer')
    combo = pd.merge(merge3, misc, how='outer')
    path = utils.get_path(f"data/men/kenpom_api/{str}.json")
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
            df['Tourney'] = df.apply(lambda x: True if x['Seed'] > 0 else False, axis=1)
            all = pd.concat([all, df])
            pbar.update(1)
    all = all.reset_index(drop=True)
    arr = all.dtypes
    path = utils.get_path(f"model_data/kenpom_api/all.json")
    utils.save_json_data(all.to_json(), path)
    return arr

with open(utils.get_path(f"model_data/kenpom_api/all.json"), 'r') as f:
    data = json.load(f)

df = pd.read_json(StringIO(data))
sorted_column_names = df.dtypes.sort_values().index.tolist()
df_sorted_by_type = df[sorted_column_names]

for col in df.columns:
    print(f"{col}: {df[col].dtype}")

    '''
    DataThrough: object
Season: int64
TeamName: object
Seed: int64
ConfShort: object
Coach: object
Wins: int64
Losses: int64
AdjEM: float64
RankAdjEM: int64
Pythag: float64
RankPythag: int64
AdjOE: float64
RankAdjOE: int64
OE: float64
RankOE: int64
AdjDE: float64
RankAdjDE: int64
DE: float64
RankDE: int64
Tempo: float64
RankTempo: int64
AdjTempo: float64
RankAdjTempo: int64
Luck: float64
RankLuck: int64
SOS: float64
RankSOS: int64
SOSO: float64
RankSOSO: int64
SOSD: float64
RankSOSD: int64
NCSOS: float64
RankNCSOS: int64
Event: object
APL_Off: float64
RankAPL_Off: int64
APL_Def: float64
RankAPL_Def: int64
ConfAPL_Off: float64
RankConfAPL_Off: int64
ConfAPL_Def: float64
RankConfAPL_Def: int64
ConfOnly: object
eFG_Pct: float64
RankeFG_Pct: int64
TO_Pct: float64
RankTO_Pct: int64
OR_Pct: float64
RankOR_Pct: int64
FT_Rate: float64
RankFT_Rate: int64
DeFG_Pct: float64
RankDeFG_Pct: int64
DTO_Pct: float64
RankDTO_Pct: int64
DOR_Pct: float64
RankDOR_Pct: int64
DFT_Rate: float64
RankDFT_Rate: int64
OffFt: float64
RankOffFt: int64
OffFg2: float64
RankOffFg2: int64
OffFg3: float64
RankOffFg3: int64
DefFt: float64
RankDefFt: int64
DefFg2: float64
RankDefFg2: int64
DefFg3: float64
RankDefFg3: int64
FG3Pct: float64
RankFG3Pct: int64
FG2Pct: float64
RankFG2Pct: int64
FTPct: float64
RankFTPct: int64
BlockPct: float64
RankBlockPct: int64
StlRate: float64
RankStlRate: int64
NSTRate: float64
RankNSTRate: int64
ARate: float64
RankARate: int64
F3GRate: float64
RankF3GRate: int64
Avg2PADist: float64
RankAvg2PADist: int64
OppFG3Pct: float64
RankOppFG3Pct: int64
OppFG2Pct: float64
RankOppFG2Pct: int64
OppFTPct: float64
RankOppFTPct: int64
OppBlockPct: float64
RankOppBlockPct: int64
OppStlRate: float64
RankOppStlRate: int64
OppNSTRate: float64
RankOppNSTRate: int64
OppARate: float64
RankOppARate: int64
OppF3GRate: float64
RankOppF3GRate: int64
OppAvg2PADist: float64
RankOppAvg2PADist: int64
Tourney: bool'''