"""
Year-over-year player-season table: one row per (gsis_id, season).

Sourced from nflverse rosters and keyed on gsis_id, so it joins straight to
registry.parquet - but it is also self-contained (carries its own team,
position, status, IDs), so historical calculations work with or without the
identity registry.

Upsert semantics: each build refreshes only the requested seasons and preserves
any previously stored ones, so you can re-pull just the current year weekly while
past seasons accumulate untouched.
"""
import nflreadpy as nfl
import pandas as pd

from fantasy.config import PLAYERS_DIR
from fantasy.normalize import clean_id_series

PLAYER_SEASONS_PATH = PLAYERS_DIR / "player_seasons.parquet"

# Season-varying attributes worth keeping for historical calcs.
_KEEP = [
    "season", "gsis_id", "sleeper_id", "espn_id", "yahoo_id", "sportradar_id",
    "rotowire_id", "fantasy_data_id", "pfr_id",
    "team", "position", "depth_chart_position", "jersey_number", "status",
    "years_exp", "entry_year", "rookie_year", "draft_club", "draft_number",
    "birth_date", "full_name",
]


def _fetch(seasons) -> pd.DataFrame:
    df = nfl.load_rosters(list(seasons)).to_pandas()
    df = df[[c for c in _KEEP if c in df.columns]].copy()
    for col in [c for c in df.columns if c.endswith("_id")]:
        df[col] = clean_id_series(df[col])
    df = df.dropna(subset=["gsis_id"])
    df["season"] = df["season"].astype(int)
    # Collapse any weekly duplicates to one row per player-season.
    df = df.drop_duplicates(subset=["season", "gsis_id"], keep="last")
    return df


def build_player_seasons(seasons, refresh: bool = False) -> pd.DataFrame:
    """Refresh `seasons` in the player-seasons table, preserving other seasons."""
    seasons = [int(s) for s in seasons]
    if not seasons:
        return load_player_seasons()

    new = _fetch(seasons)
    if PLAYER_SEASONS_PATH.exists():
        existing = pd.read_parquet(PLAYER_SEASONS_PATH)
        existing = existing[~existing["season"].isin(seasons)]
        combined = pd.concat([existing, new], ignore_index=True)
    else:
        combined = new

    combined = combined.sort_values(["season", "team", "position"]).reset_index(drop=True)
    PLAYERS_DIR.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(PLAYER_SEASONS_PATH, index=False)

    stored = sorted(int(s) for s in combined["season"].unique())
    print(f"[history] refreshed {seasons} -> {PLAYER_SEASONS_PATH} "
          f"({len(combined)} rows, seasons {stored})")
    return combined


def load_player_seasons() -> pd.DataFrame:
    """Read the accumulated player-seasons table (empty frame if none yet)."""
    if not PLAYER_SEASONS_PATH.exists():
        return pd.DataFrame(columns=_KEEP)
    return pd.read_parquet(PLAYER_SEASONS_PATH)
