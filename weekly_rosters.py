import json
from sleeper_wrapper import Players, League
import constants as c
import pandas as pd



league = League(c.LEAGUEID)

week1 = pd.DataFrame(league.get_matchups(1))
print(pd.DataFrame(week1))