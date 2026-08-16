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
cache goes stale (ADP moves daily during draft season). Every pull is also
archived to data/adp/history/{year}/, and those snapshots are what the Move
columns on the homepage measure against - see WINDOWS and _with_movement.

    python -m src.league.adp_board          # print the top of the board
    python -m src.league.adp_board --refresh
"""
import math
from datetime import datetime, timedelta

import pandas as pd
import requests

from src.config import LEAGUE_TEAMS, UPCOMING_YEAR
from src.league.adp import ADP_DIR, _is_fresh, get_adp
from src.normalize import normalize_name

MAX_AGE_HOURS = 12
# The "since last update" baseline only rolls forward once it is this old, so
# repeated --refresh runs in one sitting don't collapse Move to a column of zeros.
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
    return _with_ranks(base.sort_values("Avg").reset_index(drop=True))


# --------------------------------------------------------------------------- #
# Draft slots - where the board's own ordering puts each player
# --------------------------------------------------------------------------- #

def _with_ranks(df: pd.DataFrame) -> pd.DataFrame:
    """Turn Avg into the three ways a draft board names a pick.

      * Ovr   - overall pick off this board: 1, 2, 3, ...
      * Pick  - that pick as round.pick for our league size: 1.3, 2.10, ...
      * PosRk - rank within the position: RB1 is stored as pos + PosRk.

    Positional rank is recomputed here rather than taken from FantasyPros'
    pos_rank, so all three agree with the Avg column the table is sorted on.
    """
    df = df.copy()
    df["Ovr"] = df["Avg"].rank(method="first").astype("Int64")
    df["PosRk"] = df.groupby("pos")["Avg"].rank(method="first").astype("Int64")
    df["Pick"] = [_pick(o) for o in df["Ovr"]]
    return df


def _pick(overall, teams: int = LEAGUE_TEAMS) -> str:
    """Overall pick -> 'round.pick-in-round' ('13' -> '2.3' in a 10-team league)."""
    if pd.isna(overall):
        return ""
    overall = int(overall)
    return f"{math.ceil(overall / teams)}.{(overall - 1) % teams + 1}"


def _ensure_ranks(df: pd.DataFrame) -> pd.DataFrame:
    """Add the slot columns to boards cached before they existed."""
    return df if "Ovr" in df.columns else _with_ranks(df)


def _cache_path(year):
    return ADP_DIR / f"board_{year}.parquet"


def _prev_path(year):
    """Pre-history movement baseline; still read once to seed data/adp/history."""
    return ADP_DIR / f"board_{year}_prev.parquet"


def last_updated(year=UPCOMING_YEAR):
    """When the board data was last pulled, or None if it has never been built."""
    cache = _cache_path(year)
    return datetime.fromtimestamp(cache.stat().st_mtime) if cache.exists() else None


# --------------------------------------------------------------------------- #
# Snapshot history
# --------------------------------------------------------------------------- #
# Every pull is archived under data/adp/history/{year}/{timestamp}.parquet so the
# board can be compared against any point in the past, not just the previous
# pull. Snapshots keep only what movement needs (three columns), so a season's
# worth costs a few hundred KB.

HISTORY_DIR = ADP_DIR / "history"
HISTORY_KEEP_DAYS = 60      # comfortably past the widest window below
SNAPSHOT_GAP_HOURS = 3      # don't archive the same afternoon twice
_SNAP_FMT = "%Y%m%d-%H%M%S"
_SNAP_COLS = ["merge_name", "Avg", "Sites"]

# The movement windows shown on the board, each measured against the newest
# snapshot at or before its cutoff. "last" has no fixed span: it is simply the
# previous pull, as long as that pull is old enough to mean something. `label`
# names the window's button, `short` the table column while it is selected.
WINDOWS = {
    "last": {"prev": "Prev", "move": "Move", "delta": None,
             "label": "Since last update", "short": "Move"},
    "3d": {"prev": "Prev3d", "move": "Move3d", "delta": timedelta(days=3),
           "label": "Last 3 days", "short": "Move 3d"},
    "7d": {"prev": "Prev7d", "move": "Move7d", "delta": timedelta(days=7),
           "label": "Last week", "short": "Move 7d"},
}
_MOVE_COLS = [c for w in WINDOWS.values() for c in (w["prev"], w["move"])]


def _history_dir(year):
    return HISTORY_DIR / str(year)


def _snapshots(year) -> list:
    """[(taken_at, path)] for every archived pull, oldest first."""
    out = []
    for path in _history_dir(year).glob("*.parquet"):
        try:
            out.append((datetime.strptime(path.stem, _SNAP_FMT), path))
        except ValueError:
            continue                                  # not one of ours
    return sorted(out)


def _seed_history(year):
    """Backfill the history from the two boards kept before it existed.

    Without this the 3-day and week windows would read empty until the archive
    had built itself up over a week of rebuilds.
    """
    if _snapshots(year):
        return
    for path in (_prev_path(year), _cache_path(year)):
        if path.exists():
            when = datetime.fromtimestamp(path.stat().st_mtime)
            _write_snapshot(pd.read_parquet(path), year, when)


def _write_snapshot(df: pd.DataFrame, year, when=None):
    """Archive a board, unless one was already taken in the last few hours."""
    when = when or datetime.now()
    snaps = _snapshots(year)
    if snaps and when - snaps[-1][0] < timedelta(hours=SNAPSHOT_GAP_HOURS):
        return
    out = _history_dir(year)
    out.mkdir(parents=True, exist_ok=True)
    cols = [c for c in _SNAP_COLS if c in df.columns]
    df[cols].to_parquet(out / f"{when:{_SNAP_FMT}}.parquet", index=False)

    cutoff = when - timedelta(days=HISTORY_KEEP_DAYS)
    for taken, path in snaps:
        if taken < cutoff:
            path.unlink()


def _baseline(snaps: list, delta):
    """The snapshot a window measures against: newest at or before its cutoff.

    Falls back to the oldest snapshot on hand when the archive doesn't reach
    back that far yet, so a 3-day-old board still reports *something* for the
    week window - the timestamp reported alongside it says how far back it
    actually goes (see baseline_times).
    """
    if not snaps:
        return None
    cutoff = datetime.now() - (delta or timedelta(hours=MIN_SNAPSHOT_HOURS))
    older = [s for s in snaps if s[0] <= cutoff]
    return older[-1] if older else snaps[0]


def baseline_times(year=UPCOMING_YEAR) -> dict:
    """Window key -> when its baseline board was pulled (None if unavailable)."""
    snaps = _snapshots(year)
    times = {}
    for key, spec in WINDOWS.items():
        base = _baseline(snaps, spec["delta"])
        times[key] = base[0] if base else None
    return times


# --------------------------------------------------------------------------- #
# Movement
# --------------------------------------------------------------------------- #

def _attach_window(df: pd.DataFrame, base, spec) -> pd.DataFrame:
    """Attach one window's Prev (baseline Avg) and Move (picks climbed).

    Move is positive when a player is going *earlier* than he was at the
    baseline, i.e. rising up boards; NA for anyone the baseline didn't rank.

    Two kinds of fake movement are blanked out rather than reported:

      * Avg is a mean over whichever sites rank the player, so a site picking him
        up (or dropping him) shifts it without anyone's opinion changing - Deebo
        Samuel "rose" 29 picks the day ESPN added him.
      * Past pick TRACKED_MAX the boards are ranking different pools of names,
        and a 150-pick swing is a fifth-stringer drifting around the part of the
        board nobody drafts from (same reason Spread stops at COMPARABLE_MAX).
    """
    prev_col, move_col = spec["prev"], spec["move"]
    if base is None:
        df[prev_col] = float("nan")
        df[move_col] = float("nan")
        return df

    cols = {"Avg": prev_col, "Sites": "_prev_sites"}
    old = (pd.read_parquet(base[1])[["merge_name"] + list(cols)].rename(columns=cols)
           .drop_duplicates("merge_name", keep="first"))
    df = df.merge(old, on="merge_name", how="left")

    move = (df[prev_col] - df["Avg"]).round(1)
    same_sites = df["Sites"] == df["_prev_sites"]
    draftable = df[["Avg", prev_col]].min(axis=1) <= TRACKED_MAX
    df[move_col] = move.where(same_sites & draftable)
    return df.drop(columns="_prev_sites")


def _with_movement(df: pd.DataFrame, year) -> pd.DataFrame:
    """Attach every window's Prev / Move against the archived snapshots."""
    snaps = _snapshots(year)
    for spec in WINDOWS.values():
        df = _attach_window(df, _baseline(snaps, spec["delta"]), spec)
    return df


def _blank_movement(df: pd.DataFrame) -> pd.DataFrame:
    """Fill in the Prev / Move columns a cached board predates."""
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
    _seed_history(year)                           # first run after the rewrite
    if cache.exists() and not refresh and _is_fresh(cache, MAX_AGE_HOURS):
        return _ensure_ranks(_blank_movement(pd.read_parquet(cache)))

    try:
        df = _fetch_board(year)
    except Exception as exc:                      # network / feed shape changed
        if not cache.exists():
            raise
        print(f"  ADP board fetch failed ({exc}); using cached {cache.name}")
        return _ensure_ranks(_blank_movement(pd.read_parquet(cache)))

    df = _with_movement(df, year)                 # against history as it stands
    _write_snapshot(df, year)                     # then add this pull to it
    ADP_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache, index=False)
    return df


def movers(year=UPCOMING_YEAR, n: int = 10, min_move: float = 0.5,
           window: str = "last") -> tuple:
    """(risers, fallers): the n biggest swings over one of the WINDOWS."""
    col = WINDOWS[window]["move"]
    df = board(year)
    moved = df[df[col].notna() & (df[col].abs() >= min_move)]
    risers = moved.sort_values(col, ascending=False).head(n)
    fallers = moved.sort_values(col).head(n)
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
    for key, when in baseline_times(args.year).items():
        stamp = f"{when:%b %d %I:%M %p}" if when else "none yet"
        print(f"{WINDOWS[key]['label']:<20} baseline: {stamp}")
    print(b[["Ovr", "Pick", "player", "pos", "PosRk", "team", "bye"] + _SITE_COLS
            + ["Avg", "Spread"] + [w["move"] for w in WINDOWS.values()]].head(25).to_string(index=False))
