"""
Historical consensus ADP (Average Draft Position) from FantasyPros.

Uses FantasyPros' public partners JSON API, which returns the consensus ADP
aggregated across platforms (ESPN, Sleeper, Yahoo, CBS, NFL, ...) plus the
spread (min / max / std), for any past season. Cached per year (immutable).

Note: this gives the *consensus* ADP and its cross-platform spread, not each
platform's individual ADP (that is gated behind FantasyPros' developer API).
"""
import time

import pandas as pd
import requests

from src.config import DATA_DIR
from src.normalize import normalize_name

ADP_DIR = DATA_DIR / "adp"
_URL = ("https://partners.fantasypros.com/api/v1/consensus-rankings.php"
        "?sport=NFL&year={year}&position=ALL&type=adp&scoring=PPR")
_HEADERS = {"User-Agent": "Mozilla/5.0"}


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_fresh(cache, max_age_hours) -> bool:
    """True if `cache` is younger than max_age_hours (None = never expires)."""
    if max_age_hours is None:
        return True
    age = time.time() - cache.stat().st_mtime
    return age < max_age_hours * 3600


def get_adp(year, refresh: bool = False, max_age_hours: float = None) -> pd.DataFrame:
    """Consensus ADP for a season.

    Columns: player, pos, team, bye, adp, adp_min, adp_max, adp_std, pos_rank,
    platforms (# of sources aggregated), merge_name.

    Past seasons are immutable, so the cache never expires by default. Pass
    `max_age_hours` for the in-progress season, where ADP still moves daily.
    """
    cache = ADP_DIR / f"{year}.parquet"
    if cache.exists() and not refresh and _is_fresh(cache, max_age_hours):
        return pd.read_parquet(cache)

    data = requests.get(_URL.format(year=year), headers=_HEADERS, timeout=25).json()
    platforms = data.get("total_experts")
    rows = []
    for p in data.get("players", []):
        if not p.get("player_name"):
            continue  # skip malformed / empty entries
        rows.append({
            "player": p["player_name"],
            "pos": p.get("player_position_id"),
            "team": p.get("player_team_id"),
            "bye": p.get("player_bye_week"),
            "adp": _num(p.get("rank_ave")),
            "adp_min": _num(p.get("rank_min")),
            "adp_max": _num(p.get("rank_max")),
            "adp_std": _num(p.get("rank_std")),
            "pos_rank": p.get("pos_rank"),
            "platforms": platforms,
        })

    df = pd.DataFrame(rows)
    df = df[df["adp"].notna()].reset_index(drop=True)
    df["merge_name"] = df["player"].map(normalize_name)

    ADP_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache, index=False)
    return df
