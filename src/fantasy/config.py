"""
Shared paths and constants for the new player-database pipeline (src/).

Kept intentionally free of any dependency on the legacy py/ package so the
new structure can evolve independently.
"""
from pathlib import Path

# Project root = fantasy_insights/  (this file lives at src/config.py)
ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
PLAYERS_DIR = DATA_DIR / "players"

# The canonical, cross-source identity schema every source normalizes into.
# Adding a new ID column here (and populating it in an adapter) is all that is
# needed to teach the matcher about a new source's identifiers.
ID_COLS = [
    "gsis_id",        # nflverse / NFL GSIS - our universal join key
    "sleeper_id",
    "espn_id",
    "yahoo_id",
    "sportradar_id",
    "pfr_id",         # pro-football-reference
    "rotowire_id",
    "fantasy_data_id",
    "stats_id",
]

# Descriptive fields carried alongside the IDs.
IDENTITY_COLS = [
    "full_name",
    "first_name",
    "last_name",
    "position",
    "team",
    "birth_date",
    "active",
    "status",
]

# Columns a normalized source frame must expose.
SPINE_COLS = ["source", "source_id"] + ID_COLS + IDENTITY_COLS + ["merge_name"]

# The 32 team codes (used to recognize Sleeper DEF "players", which are keyed by
# team abbreviation and have no gsis_id).
TEAMS = [
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET",
    "GB", "HOU", "IND", "JAX", "KC", "LAC", "LAR", "LV", "MIA", "MIN", "NE",
    "NO", "NYG", "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS",
]
