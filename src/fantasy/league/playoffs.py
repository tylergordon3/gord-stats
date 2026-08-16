"""
Playoff results from Sleeper's winners bracket.

The season files under data/season/ stop at the fantasy regular season (week 14),
so who actually won the title isn't in them. Sleeper's winners-bracket endpoint
has it: the match carrying `p: 1` is the championship game, and its `w` / `l` are
the winning / losing roster_ids. `p: 3` is the third-place game.
"""
from functools import lru_cache

from sleeper_wrapper import League

from fantasy.config import LEAGUE_IDS, ROSTER_NAMES


@lru_cache(maxsize=None)
def _bracket(season_str: str) -> tuple:
    return tuple(League(LEAGUE_IDS[season_str]).get_playoff_winners_bracket() or ())


def _placement(season_str: str, place: int):
    """The match deciding `place` (1 = final, 3 = third-place game), or None."""
    return next((m for m in _bracket(season_str) if m.get("p") == place), None)


def champion_roster(season_str: str):
    """roster_id of the season's champion, or None if the bracket isn't final."""
    final = _placement(season_str, 1)
    return final.get("w") if final else None


def podium(season_str: str) -> dict:
    """{'champion': roster_id, 'runner_up': roster_id, 'third': roster_id}."""
    final, third = _placement(season_str, 1), _placement(season_str, 3)
    return {
        "champion": final.get("w") if final else None,
        "runner_up": final.get("l") if final else None,
        "third": third.get("w") if third else None,
    }


def champions() -> dict:
    """{season_str: manager name} for every season with a completed bracket."""
    out = {}
    for season_str in LEAGUE_IDS:
        roster = champion_roster(season_str)
        if roster is not None:
            out[season_str] = ROSTER_NAMES.get(roster)
    return out


if __name__ == "__main__":
    for season, name in champions().items():
        print(f"{season}: {name}")
