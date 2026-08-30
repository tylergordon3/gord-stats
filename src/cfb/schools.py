"""
One school, three names: Yahoo's, CFBD's, and ESPN's.

The draft model joins three feeds that agree about nothing. Yahoo calls a
player's school "Florida State Seminoles"; CFBD calls it "Florida State"; the
schedule this site already carries, which comes from ESPN, calls it "Florida
St" and keys it by the id 52. Matching those by hand, or by fuzzy string
distance, is how a model quietly ends up rating the wrong team.

There is an exact bridge instead, and it needs no guessing:

  * CFBD publishes each school with its mascot, so "school + mascot" reproduces
    Yahoo's full name character for character (one alias, below, for Miami).
  * CFBD keys its games on ESPN's own event id, so joining a finished season of
    CFBD games to the same season on disk (cfb.games) pairs every CFBD school
    with an ESPN team id, from real games rather than from spelling.

The map is built once from a completed season and cached; it only changes when
a school joins FBS or renames itself.

    python -m cfb.schools --refresh
"""
import json

import requests

from cfb.config import DATA_DIR
from cfb.lines import _key

CACHE = DATA_DIR / "schools.json"
_API = "https://api.collegefootballdata.com"
_TIMEOUT = 60

# The season the ESPN join is built from: finished, so every game has an id on
# both sides. Not the current one, which is still being played.
BRIDGE_SEASON = 2025

# Yahoo full names CFBD's "school + mascot" does not reproduce. Yahoo
# disambiguates Miami from Miami (OH); CFBD does it with the conference.
_ALIASES = {"Miami (FL) Hurricanes": "Miami"}


def _get(path: str, **params):
    r = requests.get(f"{_API}/{path}", timeout=_TIMEOUT, params=params,
                     headers={"Authorization": f"Bearer {_key()}"})
    r.raise_for_status()
    return r.json()


def _build() -> dict:
    from cfb import games as games_mod

    teams = _get("teams/fbs", year=BRIDGE_SEASON)
    yahoo_to_school = dict(_ALIASES)
    schools = {}
    for t in teams:
        school = t["school"]
        schools[school] = {"school": school, "conference": t.get("conference"),
                           "abbr": t.get("abbreviation")}
        if t.get("mascot"):
            yahoo_to_school[f"{school} {t['mascot']}"] = school

    # CFBD game id == ESPN event id, so the same game on both sides names the
    # same two teams; one finished season pairs every school with its ESPN id.
    cfbd_games = {str(g["id"]): (g.get("homeTeam"), g.get("awayTeam"))
                  for g in _get("games", year=BRIDGE_SEASON, seasonType="regular")}
    espn = games_mod.load(BRIDGE_SEASON, BRIDGE_SEASON)
    for row in espn.itertuples():
        pair = cfbd_games.get(str(row.game_id))
        if not pair:
            continue
        for school, team_id, name in ((pair[0], row.home_id, row.home),
                                      (pair[1], row.away_id, row.away)):
            if school in schools:
                schools[school]["espn_id"] = str(team_id)
                schools[school]["espn_name"] = name

    return {"season": BRIDGE_SEASON, "yahoo_to_school": yahoo_to_school,
            "schools": schools}


def load(refresh: bool = False) -> dict:
    if CACHE.exists() and not refresh:
        return json.loads(CACHE.read_text())
    data = _build()
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(data, indent=1))
    return data


def yahoo_school(refresh: bool = False) -> dict:
    """Yahoo's full team name -> CFBD school name."""
    return load(refresh)["yahoo_to_school"]


def espn_ids(refresh: bool = False) -> dict:
    """CFBD school name -> ESPN team id, for the schools that have one."""
    return {k: v["espn_id"] for k, v in load(refresh)["schools"].items()
            if v.get("espn_id")}


def conferences(refresh: bool = False) -> dict:
    """CFBD school name -> conference."""
    return {k: v.get("conference") for k, v in load(refresh)["schools"].items()}


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--refresh", action="store_true")
    args = p.parse_args()

    data = load(refresh=args.refresh)
    schools = data["schools"]
    with_id = sum(1 for v in schools.values() if v.get("espn_id"))
    print(f"{len(schools)} FBS schools, {with_id} with an ESPN id, "
          f"{len(data['yahoo_to_school'])} Yahoo names mapped "
          f"(bridge season {data['season']})")
    for name in ["Ohio State", "Miami", "Florida State", "Texas A&M"]:
        print(" ", name, schools.get(name))
