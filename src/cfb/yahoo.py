"""
Yahoo College Fantasy Football, over the public read-only API.

No OAuth: pub-api-ro.fantasysports.yahoo.com serves the game's player pool
(with draft_analysis - Yahoo's own ADP) and this league's settings and
standings without a token, the same endpoint fantasy.league.adp_board already
uses for the NFL board. Yahoo's JSON is a list of single-key dicts at every
level, so each parser here starts by folding that shape flat.

Both fetches cache under data/cfb/ and refetch once the cache is older than
MAX_AGE_HOURS (ADP moves daily in draft season; the league settings barely
move, but the standings will once games start). Every ADP pull is also
archived to data/cfb/adp_history/, so movement columns can be added later
the way the NFL board's were.

    python -m cfb.yahoo             # print the top of the board
    python -m cfb.yahoo --refresh
"""
import json
import time
from datetime import datetime, timezone

import pandas as pd
import requests

from cfb.config import DATA_DIR, GAME_CODE, LEAGUE_KEY, LEAGUE_TEAMS, SEASON

_API = "https://pub-api-ro.fantasysports.yahoo.com/fantasy/v2"
_HEADERS = {"User-Agent": "Mozilla/5.0"}
_TIMEOUT = 25

MAX_AGE_HOURS = 12

# Paging depth. Yahoo publishes an average_pick only for players actually
# being drafted; for the 2026 college game that runs ~370 players deep, and
# sort=AR keeps returning undrafted players in rank order after it. The walk
# stops at the first page with no ADP rows at all, or here, whichever is first.
_MAX_PLAYERS = 500
_PAGE = 25


def _is_fresh(path, max_age_hours) -> bool:
    if max_age_hours is None:
        return True
    return (time.time() - path.stat().st_mtime) < max_age_hours * 3600


def _fold(fields) -> dict:
    """Yahoo's list-of-single-key-dicts -> one dict (stray lists ignored)."""
    out = {}
    for f in fields:
        if isinstance(f, dict):
            out.update(f)
    return out


def _get(path: str) -> dict:
    r = requests.get(f"{_API}/{path}?format=json", headers=_HEADERS, timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json()


# --------------------------------------------------------------------------- #
# ADP board
# --------------------------------------------------------------------------- #

def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _player_row(entry) -> dict | None:
    """One players-collection entry -> a flat row, or None if malformed."""
    parts = entry.get("player")
    if not parts:
        return None
    meta = _fold(parts[0])
    analysis = {}
    for part in parts[1:]:
        if isinstance(part, dict) and "draft_analysis" in part:
            analysis = _fold(part["draft_analysis"])
    name = (meta.get("name") or {}).get("full")
    if not name:
        return None
    bye = (meta.get("bye_weeks") or {}).get("week")
    return {
        "player": name,
        "pos": meta.get("display_position") or "",
        "team": meta.get("editorial_team_abbr") or "",
        "team_full": meta.get("editorial_team_full_name") or "",
        "bye": _num(bye),
        "adp": _num(analysis.get("average_pick")),
        "avg_round": _num(analysis.get("average_round")),
        "pct_drafted": _num(analysis.get("percent_drafted")),
        "yahoo_id": meta.get("player_id"),
    }


def _fetch_board() -> pd.DataFrame:
    rows = []
    for start in range(0, _MAX_PLAYERS, _PAGE):
        data = _get(f"game/{GAME_CODE}/players;sort=AR;start={start};count={_PAGE}"
                    ";out=draft_analysis")
        players = {}
        for item in data.get("fantasy_content", {}).get("game", []):
            if isinstance(item, dict) and "players" in item:
                players = item["players"]
        page_rows = [r for k, e in players.items() if k != "count"
                     if (r := _player_row(e))]
        if not page_rows:
            break
        rows.extend(page_rows)
        if not any(r["adp"] is not None for r in page_rows):
            break                       # past the drafted pool; stop walking

    df = pd.DataFrame(rows).drop_duplicates("yahoo_id", keep="first")
    # AR order is Yahoo's board order, ADP or not; it is the board's spine.
    df["rank"] = range(1, len(df) + 1)
    df["pos_rank"] = df.groupby("pos")["rank"].rank(method="first").astype(int)
    return df


def board(refresh: bool = False, max_age_hours: float = MAX_AGE_HOURS) -> pd.DataFrame:
    """Yahoo's CFB draft board, in average-rank order.

    Columns: rank, player, pos, team, team_full, bye, adp (average_pick,
    NaN once past the drafted pool), avg_round, pct_drafted, pos_rank.
    """
    cache = DATA_DIR / f"adp_{SEASON}.parquet"
    if cache.exists() and not refresh and _is_fresh(cache, max_age_hours):
        return pd.read_parquet(cache)

    df = _fetch_board()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache, index=False)
    hist = DATA_DIR / "adp_history"
    hist.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    df.to_parquet(hist / f"{SEASON}_{stamp}.parquet", index=False)
    return df


def board_updated() -> datetime | None:
    """When the cached board was last pulled (UTC), or None before any pull."""
    cache = DATA_DIR / f"adp_{SEASON}.parquet"
    if not cache.exists():
        return None
    return datetime.fromtimestamp(cache.stat().st_mtime, tz=timezone.utc)


# --------------------------------------------------------------------------- #
# League settings + standings
# --------------------------------------------------------------------------- #

def _parse_league(raw: dict) -> dict:
    blocks = raw["fantasy_content"]["league"]
    meta = blocks[0]
    settings, teams = {}, []
    for item in blocks[1:]:
        if not isinstance(item, dict):
            continue
        if "settings" in item:
            settings = _fold(item["settings"])
        if "standings" in item:
            for k, v in item["standings"][0]["teams"].items():
                if k == "count":
                    continue
                t = _fold(v["team"][0])
                managers = t.get("managers") or []
                nick = ""
                if managers:
                    nick = (managers[0].get("manager") or {}).get("nickname") or ""
                teams.append({"name": t.get("name"), "manager": nick,
                              "logo": (t.get("team_logos") or [{}])[0]
                              .get("team_logo", {}).get("url", "")})

    roster = []
    for rp in settings.get("roster_positions", []):
        r = rp.get("roster_position", {})
        roster.append({"position": r.get("position"), "count": int(r.get("count", 0))})

    stat_names = {}
    for st in (settings.get("stat_categories") or {}).get("stats", []):
        s = st.get("stat", {})
        stat_names[str(s.get("stat_id"))] = s.get("display_name")
    modifiers = []
    for st in (settings.get("stat_modifiers") or {}).get("stats", []):
        s = st.get("stat", {})
        modifiers.append({"stat_id": str(s.get("stat_id")),
                          "name": stat_names.get(str(s.get("stat_id")), ""),
                          "value": _num(s.get("value"))})

    return {
        "name": meta.get("name"),
        "url": meta.get("url"),
        "num_teams": int(meta.get("num_teams", 0)),
        "scoring_label": meta.get("scoring_label"),
        "draft_status": meta.get("draft_status"),
        "draft_time": _num(settings.get("draft_time")),
        "draft_pick_seconds": _num(settings.get("draft_pick_time")),
        "start_week": int(meta.get("start_week", 1)),
        "end_week": int(meta.get("end_week", 0)),
        "start_date": meta.get("start_date"),
        "end_date": meta.get("end_date"),
        "playoff_start_week": int(settings.get("playoff_start_week", 0) or 0),
        "roster": roster,
        "modifiers": modifiers,
        "teams": teams,
    }


def league(refresh: bool = False, max_age_hours: float = MAX_AGE_HOURS) -> dict:
    """This league's settings, roster shape, scoring, and teams."""
    cache = DATA_DIR / f"league_{SEASON}.json"
    if cache.exists() and not refresh and _is_fresh(cache, max_age_hours):
        return json.loads(cache.read_text())

    parsed = _parse_league(_get(f"league/{LEAGUE_KEY};out=settings,standings"))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(parsed, indent=1))
    return parsed


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--refresh", action="store_true")
    args = p.parse_args()
    lg = league(refresh=args.refresh)
    print(f"{lg['name']} — {lg['num_teams']} teams, {lg['scoring_label']}, "
          f"weeks {lg['start_week']}-{lg['end_week']}")
    df = board(refresh=args.refresh)
    with_adp = int(df["adp"].notna().sum())
    print(f"board: {len(df)} players, {with_adp} with a Yahoo ADP "
          f"({LEAGUE_TEAMS}-team league)")
    print(df.head(20).to_string(index=False))
