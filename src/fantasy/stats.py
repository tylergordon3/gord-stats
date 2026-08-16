"""
Player + team-defense fantasy points for a season, using the league's custom
kicker and DST scoring.

Canonical implementation: py/player_db.get() delegates here, and the src/ site
pages (draft, ...) build on it. Identity (sleeper_id) is attached via an exact
gsis_id join to the registry - no fuzzy name matching.
"""
import nflreadpy as nfl
import pandas as pd

from src.config import TEAMS
from src.identity.registry import load_registry

# Legacy special-case names, kept so the CamelCase key matches draft-pick names.
_NAME_RENAMES = {
    "Mike Badgley": "Michael Badgley",
    "Amon-Ra St. Brown": "AmonRa StBrown",
    "Chigoziem Okonkwo": "ChigOkonkwo",
    "Hollywood Brown": "Marquise Brown",
}


def cleaned_name(display_series: pd.Series) -> pd.Series:
    """CamelCase key from the first two name tokens (e.g. 'PatrickMahomes')."""
    s = display_series.replace(_NAME_RENAMES).str.replace(r"[.'-]", "", regex=True)

    def key(name):
        if not isinstance(name, str):
            return name
        parts = name.split()
        return "".join(parts[:2]) if len(parts) >= 2 else "".join(parts)

    return s.map(key)


# --------------------------------------------------------------------------- #
# Custom league scoring
# --------------------------------------------------------------------------- #

def kicker_points(df: pd.DataFrame) -> pd.Series:
    """Distance-weighted FG scoring: 0-39 = 3, 40-49 = 4, 50+ = 5, PAT +/-1."""
    return (
        3 * (df["fg_made_0_19"] + df["fg_made_20_29"] + df["fg_made_30_39"])
        + 4 * df["fg_made_40_49"]
        + 5 * (df["fg_made_50_59"] + df["fg_made_60_"])
        + df["pat_made"] + df["pat_missed"] - df["fg_missed"]
    )


def _points_allowed_points(pa) -> float:
    for lo, hi, pts in [(0, 0, 10), (1, 6, 7), (7, 13, 4), (14, 20, 1),
                        (21, 27, 0), (28, 34, -1)]:
        if lo <= pa <= hi:
            return pts
    return -4 if pa >= 35 else None


def _def_unit_points(row) -> float:
    return (
        row["def_sacks"]
        + 2 * row["def_interceptions"]
        + 2 * row["fumble_recovery_opp"]
        + row["def_fumbles_forced"]
        + 2 * row["def_safeties"]
        + 6 * (row["def_tds"] + row["special_teams_tds"])
    )


def defense_points(season) -> pd.DataFrame:
    """Per (week, team) DST fantasy points: defensive plays + points-allowed."""
    team_stats = nfl.load_team_stats(season, "week").to_pandas()
    team_stats["team"] = team_stats["team"].replace("LA", "LAR")
    unit = team_stats[["team", "week", "special_teams_tds", "def_fumbles_forced",
                       "def_sacks", "def_interceptions", "def_tds",
                       "fumble_recovery_opp", "def_safeties"]].copy()
    unit["fantasy_points"] = unit.apply(_def_unit_points, axis=1)

    sched = nfl.load_schedules(season).to_pandas()
    home = sched[["week", "home_team", "away_score"]].rename(
        columns={"home_team": "team", "away_score": "PA"})
    away = sched[["week", "away_team", "home_score"]].rename(
        columns={"away_team": "team", "home_score": "PA"})
    pa = pd.concat([home, away], ignore_index=True).dropna(subset=["PA"])
    pa["team"] = pa["team"].replace("LA", "LAR")
    pa["fantasy_points"] = pa["PA"].apply(_points_allowed_points)

    combined = pd.concat(
        [pa[["week", "team", "fantasy_points"]], unit[["week", "team", "fantasy_points"]]],
        ignore_index=True,
    ).dropna()
    pts = combined.groupby(["week", "team"], as_index=False)["fantasy_points"].sum()
    pts["position"] = "DEF"
    pts["fantasy_points_ppr"] = pts["fantasy_points"]
    pts["cleaned_name"] = pts["team"]      # DST keyed by team abbreviation
    pts["sleeper_id"] = pts["team"]
    return pts


def player_points(season=None) -> pd.DataFrame:
    """Weekly player + DST fantasy points for a season (default: current).

    Columns include sleeper_id, cleaned_name, position, team, week,
    fantasy_points, fantasy_points_ppr, plus the raw nflverse stat columns.
    """
    if season is None:
        season = nfl.get_current_season()

    players = nfl.load_player_stats(season, "week").to_pandas()
    players = players[~players["position_group"].isin(["LB", "DL", "OL", "DB", "None"])]
    players = players[~players["position"].isin(["P", "LS"])]
    players["team"] = players["team"].replace("LA", "LAR")
    players["cleaned_name"] = cleaned_name(players["player_display_name"])

    # Custom kicker scoring overrides nflverse standard points.
    is_k = players["position"] == "K"
    players.loc[is_k, "fantasy_points"] = kicker_points(players[is_k])
    players.loc[is_k, "fantasy_points_ppr"] = players.loc[is_k, "fantasy_points"]

    # Exact Sleeper id via gsis_id (nflverse player_id IS gsis_id).
    reg = load_registry()[["gsis_id", "sleeper_id"]]
    players["gsis_id"] = players["player_id"].astype(str)
    players = players.merge(reg, on="gsis_id", how="left").rename(
        columns={"player_id": "nflstats_id"})

    return pd.concat([players, defense_points(season)], ignore_index=True)


def get(week, season=None) -> pd.DataFrame:
    """player_points filtered to a week (week <= 0 returns the whole season)."""
    db = player_points(season)
    return db if week <= 0 else db[db["week"] == week]


def from_id(pid, db) -> pd.DataFrame:
    """Rows for a Sleeper player id, or a team defense (keyed by team abbrev)."""
    if pid in TEAMS:
        return db[db["cleaned_name"] == pid]
    return db[db["sleeper_id"] == pid]
