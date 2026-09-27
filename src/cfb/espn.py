"""
The real college football schedule, from ESPN's public scoreboard API.

One request per regular-season week (groups=80 = FBS), flattened to a row per
game with kickoff, teams, AP ranks, TV, venue, and - once games are played -
the score. Cached to data/cfb/schedule_{season}.parquet; the daily rebuild
refetches it, which is also what will keep scores and TV listings current
through the season.

    python -m cfb.espn              # print a summary per week
    python -m cfb.espn --refresh
"""
import json
import time
from datetime import datetime

import pandas as pd
import requests

from cfb.config import DATA_DIR, SEASON

_SCOREBOARD = ("https://site.api.espn.com/apis/site/v2/sports/football/"
               "college-football/scoreboard")
# No browser User-Agent here on purpose: ESPN's edge 403s a browser UA coming
# from a non-browser TLS stack, and answers requests' own UA normally.
_HEADERS = {}
_TIMEOUT = 25
_FBS = 80                      # ESPN group id for the FBS slate

MAX_AGE_HOURS = 12


def _is_fresh(path, max_age_hours) -> bool:
    if max_age_hours is None:
        return True
    return (time.time() - path.stat().st_mtime) < max_age_hours * 3600


def _get(params: dict) -> dict:
    r = requests.get(_SCOREBOARD, params=params, headers=_HEADERS, timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json()


# The postseason - every bowl and CFP game - kept as one more week of the
# season. ESPN files it all as seasontype 3, week 1 (mid-December to the title
# game in January); here it is week 20, after any regular-season week and
# inside what the scores proxy accepts, and query() translates it back.
# Without it the section stopped at the conference title games.
POSTSEASON_WEEK = 20
POSTSEASON_LABEL = "Bowls"


def query(week: int) -> dict:
    """ESPN's scoreboard parameters for one of this site's weeks."""
    if int(week) == POSTSEASON_WEEK:
        return {"week": 1, "seasontype": 3}
    return {"week": int(week), "seasontype": 2}


def week_label(week: int) -> str:
    return POSTSEASON_LABEL if int(week) == POSTSEASON_WEEK else f"Week {int(week)}"


def short_week_label(week: int) -> str:
    return POSTSEASON_LABEL if int(week) == POSTSEASON_WEEK else f"Wk {int(week)}"


def weeks() -> list[dict]:
    """The season's week list from ESPN's calendar - the regular season, then
    the postseason as POSTSEASON_WEEK: value, label, start, end."""
    data = _get({"groups": _FBS, "limit": 1, "dates": SEASON})
    out = []
    for block in data["leagues"][0].get("calendar", []):
        if block.get("label") == "Regular Season":
            out += [{"week": int(e["value"]), "label": e["label"],
                     "start": e["startDate"], "end": e["endDate"]}
                    for e in block.get("entries", [])]
        elif block.get("label") == "Postseason":
            bowls = [e for e in block.get("entries", []) if str(e.get("value")) == "1"]
            if bowls:
                out.append({"week": POSTSEASON_WEEK, "label": POSTSEASON_LABEL,
                            "start": bowls[0]["startDate"], "end": bowls[0]["endDate"]})
    return out


def _rank(competitor) -> float | None:
    rank = (competitor.get("curatedRank") or {}).get("current")
    return None if rank in (None, 99) else float(rank)


def _game_row(event: dict, week: int) -> dict:
    comp = event["competitions"][0]
    sides = {c["homeAway"]: c for c in comp["competitors"]}
    home, away = sides["home"], sides["away"]
    status = comp.get("status", {}).get("type", {})
    broadcasts = comp.get("broadcasts") or []
    tv = ", ".join(n for b in broadcasts for n in (b.get("names") or []))
    venue = comp.get("venue") or {}
    address = venue.get("address") or {}
    place = ", ".join(x for x in (address.get("city"), address.get("state")) if x)
    if address.get("country") not in (None, "USA"):
        place = ", ".join(x for x in (place, address.get("country")) if x)
    return {
        "week": week,
        # ESPN's event id. CollegeFootballData keys its own game records on the
        # same number, so carrying it makes joining betting lines to results an
        # exact match rather than a fight over team-name spellings.
        "game_id": str(event.get("id", "")),
        "date_utc": event["date"],
        # False until a kickoff time is set. ESPN files those games at 04:00
        # UTC - midnight Eastern - which the schedule showed as "12:00 AM" (37
        # games of week 6) and the homepage clock counted down to.
        "time_valid": bool(comp.get("timeValid", True)),
        # ESPN's numeric team id, not the name: display names and abbreviations
        # get rewritten and reused between seasons, and a ratings model that
        # loses track of who is who silently rates two teams as one.
        "home_id": str(home["team"].get("id", "")),
        "away_id": str(away["team"].get("id", "")),
        "home": home["team"].get("shortDisplayName") or home["team"]["displayName"],
        "home_abbr": home["team"].get("abbreviation", ""),
        "home_rank": _rank(home),
        "home_score": float(home["score"]) if home.get("score") not in (None, "") else None,
        "away": away["team"].get("shortDisplayName") or away["team"]["displayName"],
        "away_abbr": away["team"].get("abbreviation", ""),
        "away_rank": _rank(away),
        # ESPN's conference (group) id per side. Named through conferences()
        # rather than here: the FBS names come from the FPI pull, which is the
        # one feed that spells them the way the site already does.
        "home_conf_id": str(home["team"].get("conferenceId") or ""),
        "away_conf_id": str(away["team"].get("conferenceId") or ""),
        "away_score": float(away["score"]) if away.get("score") not in (None, "") else None,
        "neutral": bool(comp.get("neutralSite")),
        "conference_game": bool(comp.get("conferenceCompetition")),
        "venue": venue.get("fullName", ""),
        # The bowl's name ("Rose Bowl", "CFP Semifinal ..."); empty in the
        # regular season except for the odd neutral-site classic.
        "note": ((comp.get("notes") or [{}])[0] or {}).get("headline", ""),
        "place": place,
        "tv": tv,
        "state": status.get("state", "pre"),          # pre / in / post
        "detail": status.get("shortDetail", ""),
        # The clock itself, not just its rendering: the median tracker needs to
        # know how much of a game is left to play, and "3rd Qtr" is a string.
        "period": int((comp.get("status") or {}).get("period") or 0),
        "clock": str((comp.get("status") or {}).get("displayClock") or ""),
    }


def schedule(refresh: bool = False, max_age_hours: float = MAX_AGE_HOURS) -> pd.DataFrame:
    """Every FBS game of the season, one row per game - bowls and the CFP as
    POSTSEASON_WEEK."""
    cache = DATA_DIR / f"schedule_{SEASON}.parquet"
    if cache.exists() and not refresh and _is_fresh(cache, max_age_hours):
        return pd.read_parquet(cache)

    rows = []
    for wk in weeks():
        data = _get({"groups": _FBS, "dates": SEASON, "limit": 500, **query(wk["week"])})
        for event in data.get("events", []):
            # ESPN's 2026 feeds slip empty stub events (no id, no
            # competitions) into some weeks; a row can't be built from one.
            if event.get("competitions"):
                rows.append(_game_row(event, wk["week"]))

    df = pd.DataFrame(rows).sort_values(["week", "date_utc"]).reset_index(drop=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache, index=False)
    return df


def week_spans(df: pd.DataFrame = None) -> list[tuple]:
    """(week, first kickoff, last game over) per week, in the machine's local
    clock - the clock the snapshot archives (gordstats.rankmoves) are named
    in, so a page can offer "change since the end of Week 3". A game is
    called over four hours after kickoff.
    """
    if df is None:
        df = schedule()
    if not len(df):
        return []
    when = pd.to_datetime(df["date_utc"], utc=True)
    local = when.dt.tz_convert(datetime.now().astimezone().tzinfo).dt.tz_localize(None)
    spans = local.groupby(df["week"]).agg(["min", "max"])
    return [(int(week), row["min"].to_pydatetime(),
             (row["max"] + pd.Timedelta(hours=4)).to_pydatetime())
            for week, row in spans.iterrows()]


def conferences() -> dict:
    """ESPN team id -> conference short name, from the cached FPI pull.

    FPI covers exactly the FBS, which is exactly who the filters are for; FCS
    visitors map to nothing and their games ride on the FBS side's badge.
    The Sun Belt's East/West halves fold together - nobody filters by
    division - and ESPN's "FBS Indep." reads better as "Independent".
    cfb.site.power refreshes the file twice a day and builds before any page
    that asks.
    """
    path = DATA_DIR / f"fpi_{SEASON}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out = {}
    for entry in data.get("teams", []):
        team = entry.get("team") or {}
        conf = (team.get("group") or {}).get("shortName")
        if not conf or team.get("id") is None:
            continue
        if conf.startswith("Sun Belt"):
            conf = "Sun Belt"
        elif conf == "FBS Indep.":
            conf = "Independent"
        out[str(team["id"])] = conf
    return out


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--refresh", action="store_true")
    args = p.parse_args()
    df = schedule(refresh=args.refresh)
    print(f"{len(df)} games across {df['week'].nunique()} weeks")
    print(df.groupby("week").size().to_string())
