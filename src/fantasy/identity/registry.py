"""
Builds the canonical player registry: one row per real-world player, carrying
every source's IDs plus a coalesced identity. This is the table everything else
(stats joins, rosters, the website) should key off of.

Output: data/players/registry.parquet
"""
import pandas as pd

from fantasy.config import ID_COLS, IDENTITY_COLS, PLAYERS_DIR
from fantasy.identity.crosswalk import assign_uid, build_gsis_lookup, resolve_gsis
from fantasy.sources.nflverse import NflverseSource
from fantasy.sources.sleeper import SleeperSource

REGISTRY_PATH = PLAYERS_DIR / "registry.parquet"

# Which source wins when both supply a value for a column.
# nflverse is authoritative for stable identity; Sleeper for live NFL status.
_SLEEPER_FIRST = {"sleeper_id", "team", "active", "status", "match_method"}


def _coalesce(df: pd.DataFrame, cols, order) -> pd.DataFrame:
    """Per player_uid, take the first non-null value of each col in source `order`."""
    cat = pd.Categorical(df["source"], categories=order, ordered=True)
    ordered = df.assign(_o=cat).sort_values("_o", kind="stable")
    return ordered.groupby("player_uid")[cols].first()


def build_registry(refresh: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch, match, and merge all sources. Returns (registry, unmatched_report)."""
    sleeper = SleeperSource().load(refresh=refresh)
    nflverse = NflverseSource().load(refresh=refresh)

    # nflverse is our reference for recovering gsis_id and for name fallback.
    lookups = build_gsis_lookup(nflverse)
    sleeper = resolve_gsis(sleeper, lookups, reference=nflverse)
    nflverse = resolve_gsis(nflverse, lookups, reference=nflverse)

    sleeper = assign_uid(sleeper)
    nflverse = assign_uid(nflverse)

    allp = pd.concat([nflverse, sleeper], ignore_index=True)
    # Guard against a source emitting the same player twice.
    allp = allp.drop_duplicates(subset=["player_uid", "source"], keep="first")

    all_cols = ID_COLS + IDENTITY_COLS + ["merge_name", "match_method"]
    nfl_first = [c for c in all_cols if c not in _SLEEPER_FIRST]
    slp_first = [c for c in all_cols if c in _SLEEPER_FIRST]

    merged = _coalesce(allp, nfl_first, ["nflverse", "sleeper"])
    merged = merged.join(_coalesce(allp, slp_first, ["sleeper", "nflverse"]))

    # Which sources contributed to each player.
    contrib = allp.groupby("player_uid")["source"].agg(
        lambda s: ",".join(sorted(set(s)))
    ).rename("sources")
    merged = merged.join(contrib).reset_index()

    ordered_cols = ["player_uid"] + ID_COLS + IDENTITY_COLS + ["sources", "match_method"]
    registry = merged[ordered_cols]

    PLAYERS_DIR.mkdir(parents=True, exist_ok=True)
    registry.to_parquet(REGISTRY_PATH, index=False)

    report = _summarize(registry)
    return registry, report


def _summarize(registry: pd.DataFrame) -> pd.DataFrame:
    """Print a names.py-style summary and return the unmatched-players report."""
    both = registry["sources"].eq("nflverse,sleeper")
    nfl_only = registry["sources"].eq("nflverse")
    slp_only = registry["sources"].eq("sleeper")
    unmatched = registry[slp_only & registry["match_method"].eq("none")]
    team_def = registry["match_method"].eq("team_def")

    print(f"{both.sum()} players matched across both sources.")
    print(f"{nfl_only.sum()} players only in nflverse (no Sleeper row).")
    print(f"{slp_only.sum()} players only in Sleeper "
          f"({unmatched.shape[0]} truly unmatched, {team_def.sum()} team defenses).")
    print(f"Registry written to {REGISTRY_PATH} ({len(registry)} rows).")

    return unmatched[["player_uid", "full_name", "position", "team"]].reset_index(drop=True)


def load_registry() -> pd.DataFrame:
    """Read the cached registry (build it first if missing)."""
    if not REGISTRY_PATH.exists():
        return build_registry()[0]
    return pd.read_parquet(REGISTRY_PATH)
