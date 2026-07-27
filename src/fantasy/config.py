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

# --------------------------------------------------------------------------- #
# League-specific config (roster_id -> owner is stable across seasons here).
# --------------------------------------------------------------------------- #
SEASON_DIR = DATA_DIR / "season"
FANTASY_REG_WEEKS = 14           # fantasy regular season length
EXPW_RATIO = 2.37                # Pythagorean exponent for expected wins

ROSTER_NAMES = {
    1: "Colin", 2: "Tyler", 3: "Jackson", 4: "Max", 5: "Austin",
    6: "Trevor", 7: "Padgett", 8: "Mark", 9: "George", 10: "Everett",
}

# Owners with at least one championship (drives the crown column).
CHAMPIONS = {"Colin", "Jackson", "Austin"}

# Per-season identifiers, keyed by the 4-digit season string (e.g. "2526").
LEAGUE_IDS = {
    "2526": "1257466498994143232",
    "2425": "1121158268379820032",
    "2324": "994410685717102592",
}
DRAFT_IDS = {
    "2526": "1257466498994143233",
    "2425": "1121158268379820033",
    "2324": "994410687084507136",
}
FORMAL_SEASON = {"2526": "2025-2026", "2425": "2024-2025", "2324": "2023-2024"}
SEASON_YEAR = {"2526": 2025, "2425": 2024, "2324": 2023}

# Highest fantasy points at each position since 2020 (used by the median race's
# hypothetical-max calculation).
MAX_POINTS = {
    "QB": 51.9,   # Josh Allen 2024
    "RB": 56.2,   # Alvin Kamara 2020
    "WR": 57.9,   # Tyreek Hill 2020
    "TE": 45.0,   # Darren Waller 2020
    "DEF": 32.0,  # Buffalo D/ST 2023
    "K": 26.0,    # Jake Moody 2024
}

# The 32 team codes (used to recognize Sleeper DEF "players", which are keyed by
# team abbreviation and have no gsis_id).
TEAMS = [
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET",
    "GB", "HOU", "IND", "JAX", "KC", "LAC", "LAR", "LV", "MIA", "MIN", "NE",
    "NO", "NYG", "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS",
]
