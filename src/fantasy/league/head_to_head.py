"""
Lifetime head-to-head records between every pair of managers.

Two books, kept apart because they are different contests:
  * Regular season - every week-1..14 game: past seasons from the season files
    (data/fantasy/season/{code}.json), the season in progress from the matchup
    archive's finished weeks. The weekly median game is not head-to-head and
    is not counted.
  * Playoffs - the winners bracket only, and only its elimination games: the
    3rd- and 5th-place games Sleeper also files under the winners bracket
    (`p` 3 / 5) are placement games, not playoff games, and the losers
    (consolation) bracket is never read. Round r is played in week
    playoff_week_start + r - 1; scores come from that week's matchups.

roster_id is the same manager in every season (checked against Sleeper's
rosters 2026-09-13; roster 3 changed accounts, not hands), so records join on
it and ROSTER_NAMES names them.

    python -m fantasy.league.head_to_head
"""
import json
from functools import lru_cache
from itertools import combinations

import pandas as pd
from sleeper_wrapper import League

from fantasy import paths
from fantasy.config import FANTASY_REG_WEEKS, LEAGUE_IDS, ROSTER_NAMES, UPCOMING_YEAR
from fantasy.league import matchups as matchups_mod

PLAYOFF_CACHE = paths.DATA_DIR / "head_to_head_playoffs.json"
PLACEMENT_GAMES = {3, 5}


def _season_code(year: int) -> str:
    return f"{year % 100:02d}{(year + 1) % 100:02d}"


def _regular_from_files() -> list[dict]:
    out = []
    for path in sorted(paths.SEASON_DIR.glob("*.json")):
        df = pd.read_json(path)
        df = df[df["week"] <= FANTASY_REG_WEEKS]
        for r in df.itertuples(index=False):
            if int(r.roster_id) < int(r.opp):           # each game once
                out.append({"season": path.stem, "week": int(r.week), "kind": "regular",
                            "a": int(r.roster_id), "b": int(r.opp),
                            "a_pts": float(r.points), "b_pts": float(r.opp_points)})
    return out


def _regular_from_archive(have: set) -> list[dict]:
    """Finished weeks of the season in progress, unless a season file has it."""
    code = _season_code(int(UPCOMING_YEAR))
    if code in have:
        return []
    out = []
    for week in matchups_mod.archived_weeks(int(UPCOMING_YEAR)):
        if week > FANTASY_REG_WEEKS:
            continue
        data = json.loads(matchups_mod._path(week, int(UPCOMING_YEAR)).read_text())
        if not matchups_mod.week_final(data):
            continue
        for m in data.get("matchups") or []:
            sides = m.get("sides") or []
            if len(sides) != 2:
                continue
            x, y = sorted(sides, key=lambda s: int(s["roster_id"]))
            out.append({"season": code, "week": week, "kind": "regular",
                        "a": int(x["roster_id"]), "b": int(y["roster_id"]),
                        "a_pts": float(x.get("points") or 0), "b_pts": float(y.get("points") or 0)})
    return out


def _fetch_playoffs(league_id: str, season: str) -> list[dict] | None:
    """The winners bracket's elimination games with scores, or None while the
    bracket is unfinished (no champion yet)."""
    league = League(league_id)
    bracket = league.get_playoff_winners_bracket() or []
    final = next((g for g in bracket if g.get("p") == 1), None)
    if not final or not final.get("w"):
        return None
    start = int(league.get_league()["settings"].get("playoff_week_start") or FANTASY_REG_WEEKS + 1)
    points = {}
    out = []
    for g in bracket:
        if g.get("p") in PLACEMENT_GAMES or not (g.get("t1") and g.get("t2")):
            continue
        week = start + int(g["r"]) - 1
        if week not in points:
            points[week] = {int(s["roster_id"]): float(s.get("points") or 0)
                            for s in league.get_matchups(week) or []}
        a, b = sorted((int(g["t1"]), int(g["t2"])))
        out.append({"season": season, "week": week, "kind": "playoff", "round": int(g["r"]),
                    "final": g.get("p") == 1, "a": a, "b": b,
                    "a_pts": points[week].get(a), "b_pts": points[week].get(b),
                    "winner": int(g["w"])})
    return out


def _playoffs(refresh: bool = False) -> list[dict]:
    """Every finished winners bracket. A finished bracket never changes, so
    each season is fetched once and kept in PLAYOFF_CACHE."""
    cache = json.loads(PLAYOFF_CACHE.read_text()) if PLAYOFF_CACHE.exists() else {}
    leagues = dict(LEAGUE_IDS)
    from fantasy.config import UPCOMING_LEAGUE_ID
    leagues.setdefault(_season_code(int(UPCOMING_YEAR)), UPCOMING_LEAGUE_ID)
    changed = False
    for season, league_id in leagues.items():
        if season in cache and not refresh:
            continue
        try:
            games = _fetch_playoffs(league_id, season)
        except Exception as exc:                          # noqa: BLE001
            print(f"[h2h] {season} bracket unavailable ({exc})")
            continue
        if games is not None:
            cache[season] = games
            changed = True
    if changed:
        PLAYOFF_CACHE.write_text(json.dumps(cache, indent=1, sort_keys=True))
    return [g for season in sorted(cache) for g in cache[season]]


@lru_cache(maxsize=1)
def games() -> pd.DataFrame:
    """Every counted game: season, week, kind, a < b (roster ids), a_pts, b_pts,
    winner (roster id, or None for a tie)."""
    regular = _regular_from_files()
    regular += _regular_from_archive({g["season"] for g in regular})
    for g in regular:
        g["winner"] = (g["a"] if g["a_pts"] > g["b_pts"]
                       else g["b"] if g["b_pts"] > g["a_pts"] else None)
    return pd.DataFrame(regular + _playoffs())


def record(a: int, b: int, kind: str = "regular") -> dict:
    """a's lifetime record against b: wins, losses, ties, points for/against,
    last meeting (season, week)."""
    df = games()
    if df.empty:
        return {"w": 0, "l": 0, "t": 0, "pf": 0.0, "pa": 0.0, "games": 0, "last": None}
    lo, hi = sorted((int(a), int(b)))
    g = df[(df["kind"] == kind) & (df["a"] == lo) & (df["b"] == hi)]
    mine, theirs = ("a_pts", "b_pts") if int(a) == lo else ("b_pts", "a_pts")
    w = int((g["winner"] == int(a)).sum())
    l = int((g["winner"] == int(b)).sum())
    last = g.sort_values(["season", "week"]).iloc[-1] if len(g) else None
    return {"w": w, "l": l, "t": len(g) - w - l, "games": len(g),
            "pf": float(g[mine].fillna(0).sum()), "pa": float(g[theirs].fillna(0).sum()),
            "last": (last["season"], int(last["week"])) if last is not None else None}


def matrix(kind: str = "regular") -> pd.DataFrame:
    """Row manager's record against the column manager, "W-L" (or "W-L-T")."""
    ids = sorted(ROSTER_NAMES)
    names = [ROSTER_NAMES[i] for i in ids]
    out = pd.DataFrame("", index=names, columns=names)
    for a, b in combinations(ids, 2):
        for x, y in ((a, b), (b, a)):
            r = record(x, y, kind)
            if r["games"]:
                out.loc[ROSTER_NAMES[x], ROSTER_NAMES[y]] = (
                    f"{r['w']}-{r['l']}" + (f"-{r['t']}" if r["t"] else ""))
    return out


def totals(kind: str = "regular") -> pd.DataFrame:
    """Each manager's lifetime W-L in that book, for the matrix's last column."""
    df = games()
    rows = []
    for rid, name in sorted(ROSTER_NAMES.items()):
        g = df[(df["kind"] == kind) & ((df["a"] == rid) | (df["b"] == rid))] if len(df) else df
        w = int((g["winner"] == rid).sum()) if len(g) else 0
        t = int(g["winner"].isna().sum()) if len(g) else 0
        rows.append({"manager": name, "w": w, "l": len(g) - w - t, "t": t})
    return pd.DataFrame(rows).set_index("manager")


if __name__ == "__main__":
    print(matrix("regular"))
    print(matrix("playoff"))
