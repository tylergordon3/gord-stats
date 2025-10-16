import nflreadpy as nfl
import pandas as pd
import constants as c
import fantasy_stats

week = nfl.get_current_week()
week = week -1
stats = fantasy_stats.get(week)
print(stats.describe().round(2))
