"""
nflverse player source (via nflreadpy).

Combines two nflverse tables:
  * load_players()      - the canonical player table, keyed on gsis_id
  * load_ff_playerids() - DynastyProcess crosswalk that adds sleeper_id,
                          yahoo_id, rotowire_id, stats_id, ... per gsis_id

Together these give a fully cross-referenced identity row for essentially every
fantasy-relevant player, which is what makes ID-based matching possible.
"""
import nflreadpy as nfl
import pandas as pd

from fantasy.sources.base import PlayerSource


class NflverseSource(PlayerSource):
    name = "nflverse"

    def fetch(self) -> pd.DataFrame:
        players = nfl.load_players().to_pandas()
        ids = nfl.load_ff_playerids().to_pandas()

        # Crosswalk IDs that load_players() does not carry, joined on gsis_id.
        cross_cols = [
            "gsis_id", "sleeper_id", "yahoo_id", "sportradar_id",
            "rotowire_id", "fantasy_data_id", "stats_id",
        ]
        ids = ids[[c for c in cross_cols if c in ids.columns]].dropna(subset=["gsis_id"])
        ids = ids.drop_duplicates(subset=["gsis_id"])

        return players.merge(ids, on="gsis_id", how="left")

    def normalize(self, raw: pd.DataFrame) -> pd.DataFrame:
        df = raw
        out = pd.DataFrame({
            "source_id": df["gsis_id"],
            "gsis_id": df["gsis_id"],
            "sleeper_id": df.get("sleeper_id"),
            "espn_id": df.get("espn_id"),
            "yahoo_id": df.get("yahoo_id"),
            "sportradar_id": df.get("sportradar_id"),
            "pfr_id": df.get("pfr_id"),
            "rotowire_id": df.get("rotowire_id"),
            "fantasy_data_id": df.get("fantasy_data_id"),
            "stats_id": df.get("stats_id"),
            "full_name": df.get("display_name"),
            "first_name": df.get("first_name"),
            "last_name": df.get("last_name"),
            "position": df.get("position"),
            "team": df.get("latest_team"),
            "birth_date": df.get("birth_date"),
            "status": df.get("status"),
        })
        out["active"] = out["status"].eq("ACT")
        return out
