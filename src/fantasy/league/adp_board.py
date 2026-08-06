"""
Live, multi-site ADP board for the season currently being drafted.

src/league/adp.py gives the FantasyPros *consensus* ADP (one averaged number).
For the pre-draft board we also want to see where the individual sites disagree,
so this module pulls each site that exposes a public JSON feed and merges them
into one row per player:

  * FantasyPros - consensus average across ESPN / Sleeper / CBS / NFL / RTSports.
  * ESPN        - live ADP from ESPN's public PPR league-defaults feed.
  * FFC         - Fantasy Football Calculator, from real 12-team PPR mock drafts.

Sleeper and NFL.com have no public ADP endpoint; both are folded into the
FantasyPros consensus column instead.

Everything is cached to data/adp/board_{year}.parquet and refetched once the
cache goes stale (ADP moves daily during draft season). The board it replaces is
kept as data/adp/board_{year}_prev.parquet, which is what the Move column on the
homepage measures against - see _with_movement.

    python -m src.league.adp_board          # print the top of the board
    python -m src.league.adp_board --refresh
"""
import shutil
from datetime import datetime

import pandas as pd
import requests

from src.config import UPCOMING_YEAR
from src.league.adp import ADP_DIR, _is_fresh, get_adp
from src.normalize import normalize_name

MAX_AGE_HOURS = 12
# The movement baseline only rolls forward once it is this old, so repeated
# --refresh runs in one sitting don't collapse Move to a column of zeros.
MIN_SNAPSHOT_HOURS = 6
# Overall pick through which a move means something: deeper than any 12-team
# draft goes, but well short of the 595-name tail FantasyPros ranks (see Move
# in _with_movement).
TRACKED_MAX = 200
# Overall pick through which every site's board is dense enough to compare
# (see the Spread note in _fetch_board).
COMPARABLE_MAX = 150
_HEADERS = {"User-Agent": "Mozilla/5.0"}
_TIMEOUT = 30

# Column label -> short description, shown as the table's source legend.
SOURCES = {
    "Consensus": "FantasyPros consensus (ESPN / Sleeper / CBS / NFL / RTSports, PPR)",
    "ESPN": "ESPN public PPR league ADP",
    "FFC": "Fantasy Football Calculator, 12-team PPR mock drafts",
}

_ESPN_URL = ("https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{year}"
             "/segments/0/leaguedefaults/3?view=kona_player_info")
# ESPN's default league is 10 teams x 17 rounds = 170 picks, so every player who
# usually goes undrafted piles up just under that ceiling (~190 of the top 400
# sit at 169.5-171.3). Those aren't real ADPs, so we drop them rather than let
# them masquerade as a site disagreement.
_ESPN_UNDRAFTED = 169.5
_ESPN_FILTER = ('{"players":{"limit":%d,"sortDraftRanks":'
                '{"sortPriority":100,"sortAsc":true,"value":"PPR"}}}')
_ESPN_POS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DST"}
# ESPN's proTeamId -> abbreviation (needed to key defenses, which every site
# names differently: "Houston Texans" / "Texans D/ST" / "Houston Defense").
_ESPN_TEAMS = {
    1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL", 7: "DEN", 8: "DET",
    9: "GB", 10: "TEN", 11: "IND", 12: "KC", 13: "LV", 14: "LAR", 15: "MIA", 16: "MIN",
    17: "NE", 18: "NO", 19: "NYG", 20: "NYJ", 21: "PHI", 22: "ARI", 23: "PIT", 24: "LAC",
    25: "SF", 26: "SEA", 27: "TB", 28: "WAS", 29: "CAR", 30: "JAX", 33: "BAL", 34: "HOU",
}

_FFC_URL = "https://fantasyfootballcalculator.com/api/v1/adp/{scoring}?teams={teams}&year={year}"


# --------------------------------------------------------------------------- #
# Per-site fetchers - each returns [merge_name, player, adp] (+ extras)
# --------------------------------------------------------------------------- #

def _key(df: pd.DataFrame) -> pd.Series:
    """Cross-site join key: normalized name, except defenses key on team code."""
    names = df["player"].map(normalize_name)
    is_dst = df["pos"].isin(["DST", "DEF", "D/ST"])
    return names.mask(is_dst, "dst" + df["team"].fillna("").str.upper())


def fantasypros(year, refresh: bool = False) -> pd.DataFrame:
    """Consensus ADP plus the cross-site spread (min / max / std)."""
    df = get_adp(year, refresh=refresh, max_age_hours=MAX_AGE_HOURS).copy()
    # `bye` post-dates the original cache format, so tolerate parquets without it.
    bye = df["bye"] if "bye" in df.columns else pd.Series(index=df.index, dtype="object")
    df["bye"] = pd.to_numeric(bye, errors="coerce").astype("Int64")
    df["merge_name"] = _key(df)
    return df[["merge_name", "player", "pos", "team", "bye", "adp",
               "adp_min", "adp_max", "adp_std", "pos_rank"]]


def espn(year, limit: int = 400) -> pd.DataFrame:
    """ESPN's own average draft position (public PPR league defaults)."""
    headers = dict(_HEADERS, **{"x-fantasy-filter": _ESPN_FILTER % limit})
    data = requests.get(_ESPN_URL.format(year=year), headers=headers, timeout=_TIMEOUT).json()

    rows = []
    for entry in data.get("players", []):
        p = entry.get("player") or {}
        adp = (p.get("ownership") or {}).get("averageDraftPosition")
        # 0.0 = never drafted; anything at the ceiling is effectively the same.
        if not p.get("fullName") or not adp or adp >= _ESPN_UNDRAFTED:
            continue
        rows.append({
            "player": p["fullName"],
            "pos": _ESPN_POS.get(p.get("defaultPositionId")),
            "team": _ESPN_TEAMS.get(p.get("proTeamId")),
            "adp": round(float(adp), 1),
        })

    df = pd.DataFrame(rows)
    df["merge_name"] = _key(df)
    return df.dropna(subset=["merge_name"]).drop_duplicates("merge_name", keep="first")


def ffc(year, scoring: str = "ppr", teams: int = 12) -> pd.DataFrame:
    """Fantasy Football Calculator ADP, aggregated from real mock drafts."""
    url = _FFC_URL.format(scoring=scoring, teams=teams, year=year)
    data = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT).json()

    rows = [{
        "player": p["name"],
        "pos": p.get("position"),
        "team": p.get("team"),
        "adp": p.get("adp"),
        "ffc_drafts": p.get("times_drafted"),
    } for p in data.get("players", []) if p.get("name") and p.get("adp")]

    df = pd.DataFrame(rows)
    df["merge_name"] = _key(df)
    return df.dropna(subset=["merge_name"]).drop_duplicates("merge_name", keep="first")


# --------------------------------------------------------------------------- #
# Merge
# --------------------------------------------------------------------------- #

_SITE_COLS = list(SOURCES)


def _fetch_board(year) -> pd.DataFrame:
    """Join every site onto the FantasyPros spine (the most complete list)."""
    base = fantasypros(year).rename(columns={"adp": "Consensus"})

    for label, frame in (("ESPN", espn(year)), ("FFC", ffc(year))):
        cols = ["merge_name", "adp"] + [c for c in frame.columns if c.startswith("ffc_")]
        base = base.merge(frame[cols].rename(columns={"adp": label}), on="merge_name", how="left")

    sites = base[_SITE_COLS]
    base["Avg"] = sites.mean(axis=1).round(1)
    base["Sites"] = sites.notna().sum(axis=1)

    # How far apart the sites are on this player. Only meaningful where all three
    # rank him well inside their own board: each site covers a different pool
    # (ESPN stops at ~170 picks, FFC at ~245, FantasyPros ranks 595), so late-board
    # gaps measure pool size rather than real disagreement.
    base["Spread"] = (sites.max(axis=1) - sites.min(axis=1)).round(1)
    comparable = sites.notna().all(axis=1) & (sites.max(axis=1) <= COMPARABLE_MAX)
    base.loc[~comparable, "Spread"] = pd.NA

    base["pos"] = base["pos"].fillna("").str.upper().replace({"DEF": "DST"})
    return base.sort_values("Avg").reset_index(drop=True)


def _cache_path(year):
    return ADP_DIR / f"board_{year}.parquet"


def _prev_path(year):
    """The board this one replaced - the baseline the Move column reads against."""
    return ADP_DIR / f"board_{year}_prev.parquet"


def last_updated(year=UPCOMING_YEAR):
    """When the board data was last pulled, or None if it has never been built."""
    cache = _cache_path(year)
    return datetime.fromtimestamp(cache.stat().st_mtime) if cache.exists() else None


def previous_updated(year=UPCOMING_YEAR):
    """When the movement baseline was pulled, or None before the first rollover."""
    prev = _prev_path(year)
    return datetime.fromtimestamp(prev.stat().st_mtime) if prev.exists() else None


# --------------------------------------------------------------------------- #
# Movement since the last pull
# --------------------------------------------------------------------------- #

_MOVE_COLS = ["Prev", "Move"]


def _roll_snapshot(year):
    """Promote the board we're about to overwrite to the movement baseline.

    Skipped while the existing baseline is still standing and the cache is only
    hours old (two --refresh runs back to back), so Move always spans a real
    stretch of draft season instead of the gap between two manual rebuilds.
    """
    cache, prev = _cache_path(year), _prev_path(year)
    if not cache.exists():
        return
    if prev.exists() and _is_fresh(cache, MIN_SNAPSHOT_HOURS):
        return
    shutil.copy2(cache, prev)     # copy2 keeps mtime = when that board was pulled


def _with_movement(df: pd.DataFrame, year) -> pd.DataFrame:
    """Attach Prev (baseline Avg) and Move (how far the player has climbed).

    Move is positive when a player is going *earlier* than he was at the last
    pull, i.e. rising up boards; NA for anyone the baseline didn't rank.

    Two kinds of fake movement are blanked out rather than reported:

      * Avg is a mean over whichever sites rank the player, so a site picking him
        up (or dropping him) shifts it without anyone's opinion changing - Deebo
        Samuel "rose" 29 picks the day ESPN added him.
      * Past pick TRACKED_MAX the boards are ranking different pools of names,
        and a 150-pick swing is a fifth-stringer drifting around the part of the
        board nobody drafts from (same reason Spread stops at COMPARABLE_MAX).
    """
    prev = _prev_path(year)
    if not prev.exists():
        df["Prev"] = float("nan")
        df["Move"] = float("nan")
        return df

    old = pd.read_parquet(prev)
    cols = {"Avg": "Prev", "Sites": "PrevSites"}
    old = (old[["merge_name"] + list(cols)].rename(columns=cols)
           .drop_duplicates("merge_name", keep="first"))
    df = df.merge(old, on="merge_name", how="left")

    move = (df["Prev"] - df["Avg"]).round(1)
    same_sites = df["Sites"] == df["PrevSites"]
    draftable = df[["Avg", "Prev"]].min(axis=1) <= TRACKED_MAX
    df["Move"] = move.where(same_sites & draftable)
    return df.drop(columns="PrevSites")


def _blank_movement(df: pd.DataFrame) -> pd.DataFrame:
    """Fill in Prev / Move for boards cached before movement was tracked."""
    for col in _MOVE_COLS:
        if col not in df.columns:
            df[col] = float("nan")
    return df


def board(year=UPCOMING_YEAR, refresh: bool = False) -> pd.DataFrame:
    """Merged multi-site ADP board, cached to data/adp/board_{year}.parquet.

    Falls back to the cached copy (however stale) if the fetch fails, so a
    site build never breaks on a flaky feed.
    """
    cache = _cache_path(year)
    if cache.exists() and not refresh and _is_fresh(cache, MAX_AGE_HOURS):
        return _blank_movement(pd.read_parquet(cache))

    try:
        df = _fetch_board(year)
    except Exception as exc:                      # network / feed shape changed
        if not cache.exists():
            raise
        print(f"  ADP board fetch failed ({exc}); using cached {cache.name}")
        return _blank_movement(pd.read_parquet(cache))

    _roll_snapshot(year)                          # before the cache is overwritten
    df = _with_movement(df, year)
    ADP_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache, index=False)
    return df


def movers(year=UPCOMING_YEAR, n: int = 10, min_move: float = 0.5) -> tuple:
    """(risers, fallers): the n biggest Move swings since the baseline pull."""
    df = board(year)
    moved = df[df["Move"].notna() & (df["Move"].abs() >= min_move)]
    risers = moved.sort_values("Move", ascending=False).head(n)
    fallers = moved.sort_values("Move").head(n)
    return risers, fallers


def _parse_args():
    import argparse
    p = argparse.ArgumentParser(description="Multi-site ADP board.")
    p.add_argument("--year", type=int, default=UPCOMING_YEAR)
    p.add_argument("--refresh", action="store_true", help="Ignore the cache.")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    b = board(args.year, refresh=args.refresh)
    print(f"{len(b)} players, {b['ESPN'].notna().sum()} with ESPN, {b['FFC'].notna().sum()} with FFC")
    since = previous_updated(args.year)
    print(f"Movement baseline: {since:%b %d %I:%M %p}" if since else "Movement baseline: none yet")
    print(b[["player", "pos", "team", "bye"] + _SITE_COLS
            + ["Avg", "Spread", "Move"]].head(25).to_string(index=False))
