"""
GordStats' NFL projections as they stood before each kickoff.

    data/fantasy/gs_proj/<year>/week_NN.json    {sleeper_id: projected points}

See gordstats.pregame for why, and for the rule.
"""
import pandas as pd

from fantasy.config import DATA_DIR, UPCOMING_YEAR
from gordstats.pregame import complete, freeze_at  # noqa: F401  (complete re-exported)

ARCHIVE = DATA_DIR / "gs_proj"


def path(week: int, year: int = UPCOMING_YEAR):
    return ARCHIVE / str(year) / f"week_{int(week):02d}.json"


def freeze(week: int, wk: pd.DataFrame, year: int = UPCOMING_YEAR) -> pd.DataFrame:
    return freeze_at(path(week, year), wk)
