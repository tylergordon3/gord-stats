"""
GordStats' college projections as they stood before each kickoff.

    data/cfb/gs_proj/<season>/week_NN.json    {yahoo_id: projected points}

See gordstats.pregame for why, and for the rule.
"""
import pandas as pd

from cfb.config import DATA_DIR, SEASON
from gordstats.pregame import complete, freeze_at  # noqa: F401  (complete re-exported)

ARCHIVE = DATA_DIR / "gs_proj"


def path(week: int, season: int = SEASON):
    return ARCHIVE / str(season) / f"week_{int(week):02d}.json"


def freeze(week: int, wk: pd.DataFrame, season: int = SEASON) -> pd.DataFrame:
    return freeze_at(path(week, season), wk)
