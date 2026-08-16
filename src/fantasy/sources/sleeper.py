"""
Sleeper player source.

Replaces the old py/player.py json dump: instead of writing raw Sleeper JSON to
disk and re-parsing it elsewhere, we fetch and normalize in one place.
"""
import pandas as pd
from sleeper_wrapper import Players

from fantasy.sources.base import PlayerSource

# Sleeper field  ->  our spine column.
_FIELD_MAP = {
    "player_id": "sleeper_id",
    "gsis_id": "gsis_id",
    "espn_id": "espn_id",
    "yahoo_id": "yahoo_id",
    "sportradar_id": "sportradar_id",
    "rotowire_id": "rotowire_id",
    "fantasy_data_id": "fantasy_data_id",
    "stats_id": "stats_id",
    "full_name": "full_name",
    "first_name": "first_name",
    "last_name": "last_name",
    "position": "position",
    "team": "team",
    "birth_date": "birth_date",
    "active": "active",
    "status": "status",
}


class SleeperSource(PlayerSource):
    name = "sleeper"

    def fetch(self) -> dict:
        return Players().get_all_players(sport="nfl")

    def normalize(self, raw: dict) -> pd.DataFrame:
        df = pd.DataFrame.from_dict(raw, orient="index")

        # Keep only the columns we know how to map (present ones).
        present = {src: dst for src, dst in _FIELD_MAP.items() if src in df.columns}
        out = df[list(present)].rename(columns=present)

        # Sleeper's primary key is player_id, which we also expose as sleeper_id.
        out["source_id"] = out["sleeper_id"]
        return out
