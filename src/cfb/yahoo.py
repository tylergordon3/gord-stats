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
from datetime import datetime, timedelta, timezone

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


# --------------------------------------------------------------------------- #
# ADP movement
# --------------------------------------------------------------------------- #
#
# Every board pull is archived to data/cfb/adp_history/, and movement is the
# current ADP against the newest archived snapshot old enough to serve as the
# window's baseline. Same idea as the NFL board's tracker; single-source, so
# the delta is Yahoo's average_pick with itself over time.

# The "since last update" baseline must be at least this old, so repeated
# refreshes in one sitting don't collapse the Move column to zeros. Shorter
# than the NFL board's 6h because this board refreshes once a day, not thrice.
MIN_SNAPSHOT_HOURS = 2

WINDOWS = {
    "last": {"label": "Since last update", "hours": None},
    "1d": {"label": "Last 24 hours", "hours": 24},
    "3d": {"label": "Last 3 days", "hours": 72},
    "7d": {"label": "Last 7 days", "hours": 168},
}


def _snapshots() -> list[tuple]:
    """Archived board pulls as (UTC stamp, path), oldest first."""
    out = []
    for p in sorted((DATA_DIR / "adp_history").glob(f"{SEASON}_*.parquet")):
        stamp = (datetime.strptime(p.stem.split("_", 1)[1], "%Y%m%dT%H%M%SZ")
                 .replace(tzinfo=timezone.utc))
        out.append((stamp, p))
    return out


def movement(current: pd.DataFrame) -> dict:
    """ADP drift per window: {key: {"stamp": baseline UTC, "moves": Series}}.

    moves is keyed by yahoo_id, value = baseline ADP - current ADP, so
    positive = going earlier = rising. Windows with no old-enough snapshot are
    simply absent - the page renders whatever windows the history can support.
    """
    now = board_updated() or datetime.now(timezone.utc)
    cur = current.set_index("yahoo_id")["adp"]
    out = {}
    for key, spec in WINDOWS.items():
        age = spec["hours"] if spec["hours"] is not None else MIN_SNAPSHOT_HOURS
        eligible = [(t, p) for t, p in _snapshots()
                    if t <= now - timedelta(hours=age)]
        if not eligible:
            continue
        stamp, path = eligible[-1]
        base = (pd.read_parquet(path)
                .drop_duplicates("yahoo_id").set_index("yahoo_id")["adp"])
        moves = (base - cur).dropna()
        out[key] = {"stamp": stamp, "moves": moves}
    return out


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
                standings = _fold(v["team"][1:]).get("team_standings", {})
                outcomes = standings.get("outcome_totals") or {}
                managers = t.get("managers") or []
                nick = ""
                if managers:
                    nick = (managers[0].get("manager") or {}).get("nickname") or ""
                if nick == "--hidden--":   # Yahoo masks nicknames for signed-out reads
                    nick = ""
                teams.append({
                    "team_key": t.get("team_key"),
                    "name": t.get("name"), "manager": nick,
                    "logo": (t.get("team_logos") or [{}])[0]
                    .get("team_logo", {}).get("url", ""),
                    "faab": _num(t.get("faab_balance")),
                    "moves": _num(t.get("number_of_moves")),
                    "trades": _num(t.get("number_of_trades")),
                    "rank": _num(standings.get("rank")),
                    "wins": _num(outcomes.get("wins")),
                    "losses": _num(outcomes.get("losses")),
                    "ties": _num(outcomes.get("ties")),
                    "points_for": _num(standings.get("points_for")),
                    "points_against": _num(standings.get("points_against")),
                })

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


# --------------------------------------------------------------------------- #
# Scoreboard, transactions, draft results
# --------------------------------------------------------------------------- #
#
# All three come off the same league endpoint family as league() and share its
# caching. They are thin before the draft — scheduled matchups with no points,
# commissioner-only transactions, an empty pick list — and the parsers accept
# that as normal, so the league page can be built now and fill in as the
# season generates the data.

def _league_block(raw: dict, key: str):
    for item in raw["fantasy_content"]["league"][1:]:
        if isinstance(item, dict) and key in item:
            return item[key]
    return None


def _cached(name: str, fetch, refresh: bool, max_age_hours: float):
    cache = DATA_DIR / f"{name}_{SEASON}.json"
    if cache.exists() and not refresh and _is_fresh(cache, max_age_hours):
        return json.loads(cache.read_text())
    data = fetch()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data, indent=1))
    return data


def _team_meta(entry) -> dict:
    """A teams-collection team entry -> {team_key, name, points, projected}."""
    parts = entry["team"]
    meta = _fold(parts[0])
    rest = _fold(parts[1:])
    return {
        "team_key": meta.get("team_key"),
        "name": meta.get("name"),
        "points": _num((rest.get("team_points") or {}).get("total")),
        "projected": _num((rest.get("team_projected_points") or {}).get("total")),
    }


def _parse_scoreboard(raw: dict) -> dict:
    sb = _league_block(raw, "scoreboard") or {}
    matchups = []
    for k, v in ((sb.get("0") or {}).get("matchups") or {}).items():
        if k == "count":
            continue
        mu = v["matchup"]
        teams = [_team_meta(t) for tk, t in mu["0"]["teams"].items() if tk != "count"]
        matchups.append({
            "week": _num(mu.get("week")),
            "week_start": mu.get("week_start"),
            "week_end": mu.get("week_end"),
            "status": mu.get("status"),
            "is_playoffs": mu.get("is_playoffs") == "1",
            "teams": teams,
        })
    return {"week": _num(sb.get("week")), "matchups": matchups}


def scoreboard(refresh: bool = False, max_age_hours: float = MAX_AGE_HOURS) -> dict:
    """The current week's matchups: {week, matchups: [{teams: [..], ...}]}."""
    return _cached("scoreboard",
                   lambda: _parse_scoreboard(_get(f"league/{LEAGUE_KEY}/scoreboard")),
                   refresh, max_age_hours)


def _parse_transactions(raw: dict) -> list[dict]:
    out = []
    for k, v in (_league_block(raw, "transactions") or {}).items():
        if k == "count":
            continue
        parts = v["transaction"]
        meta = _fold(parts[:1]) if isinstance(parts, list) else parts
        players = []
        for part in (parts[1:] if isinstance(parts, list) else []):
            if not (isinstance(part, dict) and "players" in part):
                continue
            for pk, pv in part["players"].items():
                if pk == "count":
                    continue
                pparts = pv["player"]
                pmeta = _fold(pparts[0])
                tdata = _fold(pparts[1:]).get("transaction_data")
                if isinstance(tdata, list):
                    tdata = _fold(tdata)
                tdata = tdata or {}
                players.append({
                    "player": (pmeta.get("name") or {}).get("full"),
                    "pos": pmeta.get("display_position"),
                    "team": pmeta.get("editorial_team_abbr"),
                    "type": tdata.get("type"),
                    "source": tdata.get("source_team_name"),
                    "destination": tdata.get("destination_team_name"),
                })
        out.append({
            "id": _num(meta.get("transaction_id")),
            "type": meta.get("type"),
            "status": meta.get("status"),
            "timestamp": _num(meta.get("timestamp")),
            "faab_bid": _num(meta.get("faab_bid")),
            "players": players,
        })
    return sorted(out, key=lambda t: t["timestamp"] or 0, reverse=True)


def transactions(refresh: bool = False, max_age_hours: float = MAX_AGE_HOURS) -> list[dict]:
    """Every league transaction, newest first. Commissioner actions included —
    the page filters to player moves; this keeps the raw record complete."""
    return _cached("transactions",
                   lambda: _parse_transactions(_get(f"league/{LEAGUE_KEY}/transactions")),
                   refresh, max_age_hours)


def _parse_draft(raw: dict) -> list[dict]:
    block = _league_block(raw, "draft_results")
    if not isinstance(block, dict):        # an empty list before the draft
        return []
    picks = []
    for k, v in block.items():
        if k == "count":
            continue
        r = v["draft_result"]
        picks.append({"pick": _num(r.get("pick")), "round": _num(r.get("round")),
                      "team_key": r.get("team_key"),
                      "player_key": r.get("player_key")})
    return sorted(picks, key=lambda p: p["pick"] or 0)


def draft_results(refresh: bool = False, max_age_hours: float = MAX_AGE_HOURS) -> list[dict]:
    """Every pick of the league's draft; [] until the draft has happened."""
    return _cached("draft",
                   lambda: _parse_draft(_get(f"league/{LEAGUE_KEY}/draftresults")),
                   refresh, max_age_hours)


def predraft_board() -> pd.DataFrame:
    """The board to grade draft picks against: the last ADP snapshot taken
    before the draft started, so post-draft ADP drift can't rewrite the grades.
    Falls back to the current board when no such snapshot exists."""
    lg = league()
    hist = sorted((DATA_DIR / "adp_history").glob(f"{SEASON}_*.parquet"))
    if lg.get("draft_time"):
        cutoff = datetime.fromtimestamp(lg["draft_time"], tz=timezone.utc)
        before = [p for p in hist
                  if datetime.strptime(p.stem.split("_")[1], "%Y%m%dT%H%M%SZ")
                  .replace(tzinfo=timezone.utc) <= cutoff]
        if before:
            return pd.read_parquet(before[-1])
    return board()


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
