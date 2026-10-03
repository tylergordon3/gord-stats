"""
Per-game player box scores (data/cfb/cache/boxscores_{season}.parquet).

Everything on the fantasy side of this section runs on season projections
divided by games. That cannot answer the two questions the league actually
argues about: which back is getting the carries, and which defences give up
points to which positions. Both are per-game facts, and ESPN publishes them
free on the same summary endpoint cfb.gameinfo already uses:

    summary?event=ID -> boxscore.players[team].statistics[passing|rushing|...]

One request per finished game, and a finished box score never changes, so a
game is fetched once and then read from the parquet forever. There is no CFBD
call here at all - the key's monthly quota is spoken for by lines and ratings.

Positions do not appear in the box score, so they come from each team's ESPN
roster (one request per team, cached for a month). A player the roster does
not name is typed from where he shows up: a passer is a QB, a runner an RB,
a receiver a WR - which is right often enough for a defence's totals and is
marked `guessed` so nothing downstream mistakes it for a fact.

A cache, not an archive, so it is not in git (data/cfb/cache/ is ignored):
every finished game's box score is still on ESPN, keyless, and a run fetches
whatever the file lacks - so a fresh clone, or a Pi that lost the file,
rebuilds the season in one run (~70 requests a played week, six at a time).
Tracked, it was rewritten whole after every finished game, ~0.3-0.9 MB of
history a day that git deltas poorly (62 versions came to 2.4 MB even fully
repacked). Positions come from the tracked roster cache either way.

    python -m cfb.boxscores              # fetch what's missing, print coverage
    python -m cfb.boxscores --refresh    # refetch every finished game
"""
import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

from cfb import espn, partitions
from cfb.config import DATA_DIR, SEASON

_SUMMARY = ("https://site.api.espn.com/apis/site/v2/sports/football/"
            "college-football/summary")
_ROSTER = ("https://site.api.espn.com/apis/site/v2/sports/football/"
           "college-football/teams/{team_id}/roster")
_TIMEOUT = 25
_WORKERS = 6
ROSTER_AGE_DAYS = 30

# ESPN's stat keys per category, against the columns cfb.players scores.
_CATEGORIES = {
    "passing": {"passingYards": "pass_yds", "passingTouchdowns": "pass_td",
                "interceptions": "pass_int"},
    "rushing": {"rushingAttempts": "rush_att", "rushingYards": "rush_yds",
                "rushingTouchdowns": "rush_td"},
    "receiving": {"receptions": "rec", "receivingYards": "rec_yds",
                  "receivingTouchdowns": "rec_td"},
    "fumbles": {"fumblesLost": "fum_lost"},
    "kickReturns": {"kickReturnTouchdowns": "kr_td"},
    "puntReturns": {"puntReturnTouchdowns": "pr_td"},
}
# Where a player turns up, when the roster does not name his position.
_IMPLIED = {"passing": "QB", "rushing": "RB", "receiving": "WR"}
STAT_COLS = sorted({c for m in _CATEGORIES.values() for c in m.values()})


def path(season: int = SEASON):
    return DATA_DIR / "cache" / f"boxscores_{season}.parquet"


def _read(out) -> pd.DataFrame:
    """The cache, or an empty frame when it is missing or unreadable - an
    untracked file is not put back by `git checkout`, so a torn one must
    mean "fetch it all again", not "fail every run"."""
    if not out.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(out)
    except Exception as exc:                            # noqa: BLE001
        print(f"  ! {out.name} unreadable ({exc}); refetching")
        return pd.DataFrame()


def _roster_path(season: int = SEASON):
    return DATA_DIR / f"espn_rosters_{season}.json"


def _num(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def rosters(season: int = SEASON, refresh: bool = False) -> dict:
    """{espn athlete id: position} for every FBS roster, cached for a month."""
    cache = _roster_path(season)
    if cache.exists() and not refresh:
        age = (time.time() - cache.stat().st_mtime) / 86400
        if age < ROSTER_AGE_DAYS:
            return json.loads(cache.read_text(encoding="utf-8"))

    def one(team_id):
        try:
            r = requests.get(_ROSTER.format(team_id=team_id), timeout=_TIMEOUT)
            r.raise_for_status()
            out = {}
            for group in r.json().get("athletes") or []:
                pos = (group.get("position") or "")
                for item in group.get("items") or []:
                    # The group's own label is the position for every player in
                    # it; the per-player object repeats it where it exists.
                    own = ((item.get("position") or {}).get("abbreviation")
                           if isinstance(item.get("position"), dict) else None)
                    out[str(item.get("id"))] = str(own or pos or "").upper()
            return out
        except Exception:                               # noqa: BLE001
            return {}

    known = {}
    with ThreadPoolExecutor(_WORKERS) as pool:
        for got in pool.map(one, list(espn.conferences())):
            known.update(got)
    if known:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(known), encoding="utf-8")
    elif cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    return known


def _parse(payload: dict, game_id: str, week: int, positions: dict) -> list:
    """One summary payload -> a row per player who did something."""
    teams = payload.get("boxscore", {}).get("players") or []
    ids = [str((t.get("team") or {}).get("id") or "") for t in teams]
    rows = {}
    for i, side in enumerate(teams):
        team_id = ids[i]
        opp_id = ids[1 - i] if len(ids) == 2 else ""
        for cat in side.get("statistics") or []:
            mapping = _CATEGORIES.get(cat.get("name"))
            if not mapping:
                continue
            keys = cat.get("keys") or []
            for athlete in cat.get("athletes") or []:
                who = athlete.get("athlete") or {}
                aid = str(who.get("id") or "")
                if not aid:
                    continue
                row = rows.setdefault((team_id, aid), {
                    "game_id": str(game_id), "week": int(week), "team_id": team_id,
                    "opp_id": opp_id, "athlete_id": aid,
                    "player": who.get("displayName") or "",
                    "pos": "", "guessed": False,
                    **{c: 0.0 for c in STAT_COLS}})
                for key, col in mapping.items():
                    if key in keys:
                        row[col] += _num((athlete.get("stats") or [])[keys.index(key)]
                                         if len(athlete.get("stats") or []) > keys.index(key)
                                         else 0)
                if not row["pos"]:
                    known = positions.get(aid)
                    row["pos"] = known or _IMPLIED.get(cat.get("name"), "")
                    row["guessed"] = not known
    return list(rows.values())


def _fetch(game: tuple) -> list:
    game_id, week, positions = game
    try:
        r = requests.get(_SUMMARY, params={"event": game_id}, timeout=_TIMEOUT)
        r.raise_for_status()
        return _parse(r.json(), game_id, week, positions)
    except Exception as exc:                            # noqa: BLE001
        print(f"  ! box score {game_id} failed ({exc})")
        return []


def capture(season: int = SEASON, refresh: bool = False,
            limit: int = None) -> pd.DataFrame:
    """Every finished game's box score, fetching only what is missing.

    `refresh` re-pulls the latest finished week too, where late stat
    corrections land. It used to throw the archive away and refetch every
    game of the season (330 ESPN calls in week 5, ~850 by November, four
    times a day) - and then write back only what that run got, so one failed
    request silently dropped a game from the defence-vs-position table.
    Archived games are only ever replaced by a fresh copy of themselves.
    """
    schedule = espn.schedule()
    done = schedule[(schedule["state"] == "post")
                    & (schedule["home_score"].fillna(0) + schedule["away_score"].fillna(0) > 0)]
    out = path(season)
    have = _read(out)
    seen = set(have["game_id"].astype(str)) if len(have) else set()
    latest = int(done["week"].max()) if len(done) else None
    todo = [(str(g["game_id"]), int(g["week"])) for _, g in done.iterrows()
            if str(g["game_id"]) not in seen or (refresh and int(g["week"]) == latest)]
    if limit:
        todo = todo[:limit]
    if not todo:
        return have

    positions = rosters(season)
    print(f"[boxscores] fetching {len(todo)} game(s)")
    rows = []
    with ThreadPoolExecutor(_WORKERS) as pool:
        for got in pool.map(_fetch, [(gid, wk, positions) for gid, wk in todo]):
            rows.extend(got)
    if not rows:
        return have
    new = pd.DataFrame(rows)
    if len(have):
        # A game that came back replaces its old rows whole; one that failed
        # keeps them.
        have = have[~have["game_id"].astype(str).isin(set(new["game_id"].astype(str)))]
    frame = pd.concat([have, new], ignore_index=True) if len(have) else new
    frame = frame.drop_duplicates(subset=["game_id", "team_id", "athlete_id"], keep="last")
    partitions.write_parquet(frame, out)
    return frame


def load(season: int = SEASON) -> pd.DataFrame:
    return _read(path(season))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Archive college box scores.")
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args()
    frame = capture(refresh=args.refresh, limit=args.limit)
    if frame.empty:
        print("nothing archived yet")
    else:
        print(f"{len(frame)} player-games, {frame['game_id'].nunique()} games, "
              f"{frame['guessed'].mean():.0%} positions guessed")
        print(frame.nlargest(5, "rush_yds")[["player", "pos", "team_id", "rush_att",
                                             "rush_yds", "rush_td"]].to_string(index=False))
