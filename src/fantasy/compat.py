"""
TEMPORARY compatibility bridge for the legacy py/ scripts.

The old code (player_db, nfl_stats, sleepy, names) reads data/players.json and
relies on Sleeper's full native schema (search_full_name, injury_status, weight,
college, ...). That file is gone; this module returns the same shape - a
DataFrame indexed by Sleeper player_id with every native column - but sourced
through the new src/ pipeline and cached under data/players/.

Remove once py/ is migrated into src/, which matches on the gsis_id registry
instead of Sleeper's fuzzy name fields.
"""
import json

import pandas as pd

from src.config import PLAYERS_DIR
from src.sources.sleeper import SleeperSource

_RAW_CACHE = PLAYERS_DIR / "sleeper_raw.json"


def sleeper_players(refresh: bool = False) -> pd.DataFrame:
    """Return the full Sleeper player table in the legacy players.json shape.

    :param refresh: re-fetch from the Sleeper API instead of using the cache.
    """
    if refresh or not _RAW_CACHE.exists():
        raw = SleeperSource().fetch()
        PLAYERS_DIR.mkdir(parents=True, exist_ok=True)
        with open(_RAW_CACHE, "w", encoding="utf-8") as f:
            json.dump(raw, f)

    with open(_RAW_CACHE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return pd.DataFrame.from_dict(data, orient="index")
