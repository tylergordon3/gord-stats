"""
League roster / owner info from Sleeper (ported from py/fantasy_rosters).
"""
import pandas as pd
from sleeper_wrapper import League

from fantasy.config import LEAGUE_IDS, ROSTER_NAMES


def league_for(season_str: str) -> League:
    return League(LEAGUE_IDS[season_str])


def get(league: League) -> pd.DataFrame:
    """Roster + owner info: owner_id, roster_id, team_name, wins, PF, PA, ..."""
    users = league.map_users_to_team_name(league.get_users())
    users = pd.Series(users).rename_axis("owner_id").reset_index(name="team_name")

    rosters = pd.DataFrame.from_dict(league.get_rosters())
    rosters = rosters.drop(columns=["keepers", "co_owners", "league_id", "metadata",
                                    "taxi", "player_map"], errors="ignore")
    details = rosters["settings"].apply(pd.Series)
    details["roster_id"] = rosters["roster_id"]
    rosters = rosters.merge(details, on="roster_id", how="inner")
    rosters = rosters.drop(columns=["settings", "waiver_position"], errors="ignore")

    rosters["PF"] = rosters["fpts"] + rosters["fpts_decimal"] / 10
    rosters["PA"] = rosters["fpts_against"] + rosters["fpts_against_decimal"] / 10
    rosters = rosters.merge(users, on="owner_id", how="inner")
    return rosters.drop(columns=["fpts", "fpts_decimal", "fpts_against", "fpts_against_decimal"],
                        errors="ignore")


def team_name(league: League, roster_id: int) -> str:
    r = get(league)
    return r[r["roster_id"] == roster_id]["team_name"].iloc[0]


def name_from_id(roster_id: int) -> str:
    """Owner display name for a roster_id (stable across seasons)."""
    return ROSTER_NAMES[int(roster_id)]
