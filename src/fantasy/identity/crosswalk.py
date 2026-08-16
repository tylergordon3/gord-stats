"""
Player matching logic.

The strategy, in priority order:
  1. Direct gsis_id  - the row already carries the universal key.
  2. ID crosswalk    - recover gsis_id from any other shared ID (sleeper_id,
                       espn_id, ...) using the nflverse reference table.
  3. Name fallback   - match on (normalized name, position) for the residual
                       (mostly brand-new rookies not yet in the crosswalk).
Anything left is reported as unmatched (team defenses are tagged separately).
"""
import pandas as pd

from src.config import ID_COLS, TEAMS

# Other IDs we can use to look up a gsis_id, best-first.
_LOOKUP_IDS = ["sleeper_id", "espn_id", "yahoo_id", "sportradar_id",
               "stats_id", "fantasy_data_id", "rotowire_id", "pfr_id"]


def build_gsis_lookup(reference: pd.DataFrame) -> dict:
    """From a frame that has gsis_id + other IDs, build {id_col: {value: gsis_id}}."""
    lookups = {}
    ref = reference.dropna(subset=["gsis_id"])
    for col in _LOOKUP_IDS:
        if col not in ref.columns:
            continue
        pairs = ref[[col, "gsis_id"]].dropna(subset=[col])
        pairs = pairs.drop_duplicates(subset=[col])
        lookups[col] = dict(zip(pairs[col], pairs["gsis_id"]))
    return lookups


def resolve_gsis(df: pd.DataFrame, lookups: dict, reference: pd.DataFrame) -> pd.DataFrame:
    """Return df with gsis_id filled where possible, plus a `match_method` column.

    match_method is one of: gsis, xwalk:<idcol>, name, team_def, none.
    """
    df = df.copy()
    method = pd.Series(pd.NA, index=df.index, dtype="object")

    # 1. Rows that already have a gsis_id.
    have = df["gsis_id"].notna()
    method[have] = "gsis"

    # 2. Crosswalk from other IDs.
    for col in _LOOKUP_IDS:
        need = df["gsis_id"].isna()
        if not need.any() or col not in df.columns:
            continue
        mapped = df.loc[need, col].map(lookups.get(col, {}))
        hit = mapped.notna()
        idx = mapped.index[hit]
        df.loc[idx, "gsis_id"] = mapped[hit]
        method[idx] = f"xwalk:{col}"

    # 3. Name + position fallback against the reference.
    ref = reference.dropna(subset=["gsis_id", "merge_name"])
    ref_key = ref[["merge_name", "position", "gsis_id"]].drop_duplicates(
        subset=["merge_name", "position"], keep=False  # only unambiguous keys
    )
    name_map = {(r.merge_name, r.position): r.gsis_id for r in ref_key.itertuples()}

    need = df["gsis_id"].isna() & df["merge_name"].notna()
    for i in df.index[need]:
        key = (df.at[i, "merge_name"], df.at[i, "position"])
        gsis = name_map.get(key)
        if gsis is not None:
            df.at[i, "gsis_id"] = gsis
            method[i] = "name"

    # 4. Classify the leftovers.
    still_missing = df["gsis_id"].isna()
    is_def = df["source_id"].isin(TEAMS) | df["position"].eq("DEF")
    method[still_missing & is_def] = "team_def"
    method[still_missing & ~is_def] = "none"

    df["match_method"] = method
    return df


def assign_uid(df: pd.DataFrame) -> pd.DataFrame:
    """Assign a stable player_uid: gsis_id when known, else a synthetic key."""
    df = df.copy()
    synthetic = df["source"] + ":" + df["source_id"].astype(str)
    df["player_uid"] = df["gsis_id"].where(df["gsis_id"].notna(), synthetic)
    return df
