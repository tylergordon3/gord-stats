"""
PlayerSource: the contract every data source implements.

A source knows how to (1) fetch its raw player data and (2) normalize it into
the shared identity schema (config.SPINE_COLS). Everything downstream - the
crosswalk and the registry - only ever sees normalized frames, so adding a new
site is a matter of writing one subclass. No matcher code changes.
"""
from abc import ABC, abstractmethod

import pandas as pd

from src.config import PLAYERS_DIR, SPINE_COLS, ID_COLS
from src.normalize import clean_id_series, normalize_name


class PlayerSource(ABC):
    #: Short, stable key identifying the source (e.g. "sleeper"). Used for the
    #: cache filename and the `source` column.
    name: str = ""

    @abstractmethod
    def fetch(self):
        """Return this source's raw player data (dict, DataFrame, ...)."""

    @abstractmethod
    def normalize(self, raw) -> pd.DataFrame:
        """Map raw data to the identity spine.

        Subclasses should populate whatever SPINE_COLS they can and leave the
        rest as None; `_finalize` fills the gaps and enforces the schema.
        """

    # ------------------------------------------------------------------ #

    @property
    def cache_path(self):
        return PLAYERS_DIR / f"{self.name}.parquet"

    def load(self, refresh: bool = False) -> pd.DataFrame:
        """Return the normalized frame, using the on-disk cache when present."""
        if not refresh and self.cache_path.exists():
            return pd.read_parquet(self.cache_path)
        df = self._finalize(self.normalize(self.fetch()))
        PLAYERS_DIR.mkdir(parents=True, exist_ok=True)
        df.to_parquet(self.cache_path, index=False)
        return df

    def _finalize(self, df: pd.DataFrame) -> pd.DataFrame:
        """Enforce the schema: fill missing columns, clean IDs, derive keys."""
        df = df.copy()
        df["source"] = self.name

        # Guarantee every spine column exists.
        for col in SPINE_COLS:
            if col not in df.columns:
                df[col] = None

        # Normalize every ID column to a stable string.
        for col in ID_COLS:
            df[col] = clean_id_series(df[col])

        # source_id defaults to the source's own primary key if not set.
        df["source_id"] = clean_id_series(df["source_id"])

        # Fill a display name from parts when missing (e.g. team defenses).
        missing_name = df["full_name"].isna() | (df["full_name"].astype(str).str.strip() == "")
        parts = (df["first_name"].fillna("") + " " + df["last_name"].fillna("")).str.strip()
        df.loc[missing_name, "full_name"] = parts[missing_name].replace("", None)

        # Match key for the name-fallback path.
        df["merge_name"] = df["full_name"].map(normalize_name)

        return df[SPINE_COLS]
