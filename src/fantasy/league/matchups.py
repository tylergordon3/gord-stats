"""
The league's weekly matchups, roster by roster, with the week's NFL games.

Three feeds, all keyless:

  * Sleeper's league endpoints: who plays whom, each side's starters in slot
    order, every rostered player's points for the week (live while games are
    on), the teams' names, avatars and records.
  * Sleeper's projection and stats feeds (the ones its app reads, unversioned
    but stable for years): a per-player projection for the week, and the stat
    line behind each score.
  * ESPN's NFL scoreboard: kickoff, state and score of every game, and the
    DraftKings spread and total, which give an implied team total - the one
    piece of matchup context a season projection does not have.

One JSON per week under data/fantasy/matchups/<year>/. A week is final once
every NFL game in it is over and every side has points; final weeks never
refetch. Everything else is a cache with a short life, because the current
week is the one being looked at while it scores.
"""
import json
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import requests

from fantasy import paths
from fantasy import sleeper_retry
from fantasy.config import LEAGUE_TZ, ROSTER_NAMES, UPCOMING_LEAGUE_ID, UPCOMING_YEAR

AVATAR_THUMB = "https://sleepercdn.com/avatars/thumbs/{id}"

SLEEPER_API = "https://api.sleeper.app/v1"
SLEEPER_ROOT = "https://api.sleeper.app"
ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
_TIMEOUT = 25

MATCHUPS_DIR = paths.DATA_DIR / "matchups"
MAX_AGE_HOURS = 3

# ESPN and Sleeper spell one team differently.
ESPN_TO_SLEEPER = {"WSH": "WAS"}

POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF"]
FLEX_POSITIONS = ("RB", "WR", "TE")
BENCH_SLOTS = {"BN", "IR", "TAXI"}

# Sleeper stat keys worth keeping from a weekly line - the ones a stat line
# is written from, plus the points under the three common scoring bases.
STAT_KEYS = ["pass_yd", "pass_td", "pass_int", "rush_att", "rush_yd", "rush_td",
             "rec", "rec_tgt", "rec_yd", "rec_td", "fum_lost", "fgm", "fga", "xpm", "xpa",
             "pts_allow", "sack", "int", "fum_rec", "def_td", "safe", "blk_kick",
             "pts_ppr", "pts_half_ppr", "pts_std", "gp"]

# How far this week's implied team total is allowed to move a projection: the
# exponent on (implied / league-average implied) and the band around 1.
GAME_WEIGHT = 0.6
GAME_CAP = 0.30

# Kickoff within this many minutes counts as live for the tick's gate.
PREGAME_BUFFER_MIN = 30


def _get(url: str, params: dict = None, headers: dict = None):
    """GET JSON, retrying a dropped connection.

    ESPN 403s browser-like User-Agents from python-requests, so calls to it
    send none (requests' own default is what it answers) - which is why the
    headers go through untouched.

    The retry matters: Sleeper drops the occasional TLS handshake, and this
    one bare call took the whole matchups page - and with it the fantasy
    section of the daily run - down with it on 2026-09-25.
    """
    return sleeper_retry.get_json(url, params=params, headers=headers,
                                  timeout=_TIMEOUT)


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# Sleeper
# --------------------------------------------------------------------------- #

def nfl_state() -> dict:
    """Sleeper's view of the NFL calendar: week, season, season_type."""
    return _get(f"{SLEEPER_ROOT}/v1/state/nfl")


def league(league_id: str = UPCOMING_LEAGUE_ID) -> dict:
    lg = _get(f"{SLEEPER_API}/league/{league_id}")
    return {"name": lg.get("name"), "season": lg.get("season"), "status": lg.get("status"),
            "roster_positions": lg.get("roster_positions") or [],
            "playoff_week_start": int((lg.get("settings") or {}).get("playoff_week_start") or 0),
            "total_rosters": int(lg.get("total_rosters") or 0)}


def teams(league_id: str = UPCOMING_LEAGUE_ID) -> dict:
    """{roster_id: {name, manager, avatar, wins, losses, ties, fpts, reserve}}.

    `avatar` is a full image URL: the team's own picture where the manager
    set one for this league (Sleeper keeps it in the user's league metadata,
    as a URL), else the manager's profile picture, which Sleeper serves by
    id from its avatar CDN.
    """
    users = {u["user_id"]: u for u in _get(f"{SLEEPER_API}/league/{league_id}/users") or []}
    out = {}
    for r in _get(f"{SLEEPER_API}/league/{league_id}/rosters") or []:
        rid = int(r["roster_id"])
        u = users.get(r.get("owner_id")) or {}
        st = r.get("settings") or {}
        name = ((u.get("metadata") or {}).get("team_name") or u.get("display_name")
                or f"Team {rid}")
        out[rid] = {
            "name": name, "manager": ROSTER_NAMES.get(rid, u.get("display_name") or ""),
            "avatar": ((u.get("metadata") or {}).get("avatar")
                       or (AVATAR_THUMB.format(id=u["avatar"]) if u.get("avatar") else "")),
            "wins": int(st.get("wins") or 0), "losses": int(st.get("losses") or 0),
            "ties": int(st.get("ties") or 0),
            "fpts": float(st.get("fpts") or 0) + float(st.get("fpts_decimal") or 0) / 100,
            "reserve": [str(p) for p in (r.get("reserve") or [])],
        }
    return out


def sleeper_matchups(week: int, league_id: str = UPCOMING_LEAGUE_ID) -> list[dict]:
    """Sleeper's rows for the week: one per roster, paired by matchup_id."""
    rows = _get(f"{SLEEPER_API}/league/{league_id}/matchups/{week}") or []
    return [{"roster_id": int(r["roster_id"]), "matchup_id": r.get("matchup_id"),
             "points": _num(r.get("points")) or 0.0,
             "starters": [str(p) for p in (r.get("starters") or [])],
             "players": [str(p) for p in (r.get("players") or [])],
             "players_points": {str(k): _num(v) for k, v in (r.get("players_points") or {}).items()}}
            for r in rows if r.get("matchup_id") is not None]


def _positions_param() -> str:
    return "&".join(f"position[]={p}" for p in POSITIONS)


def sleeper_projections(week: int, year: int = UPCOMING_YEAR, only: set = None) -> dict:
    """{player_id: {pts, opp, team, injury}} - Sleeper's own weekly projection
    (PPR basis, which is this league's), for `only` players or all."""
    rows = _get(f"{SLEEPER_ROOT}/projections/nfl/{year}/{week}?season_type=regular&"
                f"{_positions_param()}&order_by=pts_ppr") or []
    out = {}
    for r in rows:
        pid = str(r.get("player_id") or "")
        if not pid or (only is not None and pid not in only):
            continue
        st = r.get("stats") or {}
        pl = r.get("player") or {}
        out[pid] = {"pts": _num(st.get("pts_ppr")), "opp": r.get("opponent"),
                    "team": r.get("team"), "injury": pl.get("injury_status") or "",
                    "name": " ".join(x for x in (pl.get("first_name"), pl.get("last_name")) if x),
                    "pos": pl.get("position") or ""}
    return out


NFL_GAMES = 17


def sleeper_season_projections(year: int = UPCOMING_YEAR) -> dict:
    """{player_id: {pts, gp, ppg, name, pos, team}} - Sleeper's full-season
    projection (PPR, Rotowire's numbers), refetched every call and kept on disk
    so a build with Sleeper down still has last known figures."""
    cache = paths.DATA_DIR / "projections" / f"sleeper_season_{year}.json"
    try:
        rows = _get(f"{SLEEPER_ROOT}/projections/nfl/{year}?season_type=regular&"
                    f"{_positions_param()}&order_by=pts_ppr") or []
        out = {}
        for r in rows:
            pid, st, pl = str(r.get("player_id") or ""), r.get("stats") or {}, r.get("player") or {}
            pts, gp = _num(st.get("pts_ppr")), _num(st.get("gp"))
            if not pid or pts is None:
                continue
            # Per game over the 17-game schedule, not Sleeper's `gp`: it says 18
            # for players (weeks, byes included) and 1 for every defence.
            out[pid] = {"pts": pts, "gp": gp, "ppg": pts / NFL_GAMES,
                        "name": " ".join(x for x in (pl.get("first_name"), pl.get("last_name")) if x),
                        "pos": pl.get("position") or "", "team": r.get("team")}
        assert out, "no season projections"
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(out), encoding="utf-8")
        return out
    except Exception as exc:
        if not cache.exists():
            print(f"  ! Sleeper season projections unavailable ({exc})")
            return {}
        print(f"  ! Sleeper season projections failed ({exc}); using the cached copy")
        return json.loads(cache.read_text(encoding="utf-8"))


def sleeper_stats(week: int, year: int = UPCOMING_YEAR, only: set = None) -> dict:
    """{player_id: {stat: value}} for the week, empty before games are played."""
    try:
        rows = _get(f"{SLEEPER_ROOT}/stats/nfl/{year}/{week}?season_type=regular&"
                    f"{_positions_param()}&order_by=pts_ppr") or []
    except requests.RequestException:
        return {}
    out = {}
    for r in rows:
        pid = str(r.get("player_id") or "")
        if not pid or (only is not None and pid not in only):
            continue
        st = r.get("stats") or {}
        keep = {k: st[k] for k in STAT_KEYS if st.get(k)}
        if keep:
            out[pid] = keep
    return out


# --------------------------------------------------------------------------- #
# ESPN: the week's games
# --------------------------------------------------------------------------- #

def _implied(odds: dict) -> tuple:
    """(home implied, away implied) from a spread and total, or (None, None).
    ESPN's `spread` is the home line - negative when the home side is favoured."""
    total, spread = _num(odds.get("overUnder")), _num(odds.get("spread"))
    if total is None or spread is None:
        return None, None
    return (total - spread) / 2, (total + spread) / 2


def _weather(ev: dict, comp: dict) -> dict | None:
    """{temp, cond (AccuWeather icon code), text, indoors} off a scoreboard
    event. ESPN only carries it for the days before kickoff, and on game day
    swaps the two fields - the code turns up in `displayValue` and the words
    in `conditionId` - so whichever one is a number is the code."""
    wx = ev.get("weather") or {}
    indoors = bool((comp.get("venue") or {}).get("indoor"))
    if not wx and not indoors:
        return None
    a, b = str(wx.get("conditionId") or ""), str(wx.get("displayValue") or "")
    code, text = (a, b) if a.isdigit() else ((b, a) if b.isdigit() else ("", a or b))
    return {"temp": _num(wx.get("temperature")), "cond": int(code) if code else None,
            "text": text, "indoors": indoors}


def parse_scoreboard(data: dict) -> list[dict]:
    games = []
    for ev in data.get("events") or []:
        comps = ev.get("competitions") or []
        if not comps:
            continue
        c = comps[0]
        sides = {t.get("homeAway"): t for t in c.get("competitors") or []}
        home, away = sides.get("home") or {}, sides.get("away") or {}
        if not home or not away:
            continue
        odds = (c.get("odds") or [{}])[0]
        hi, ai = _implied(odds)
        status = (ev.get("status") or {}).get("type") or {}
        abbr = lambda t: ESPN_TO_SLEEPER.get(t["team"].get("abbreviation"),   # noqa: E731
                                             t["team"].get("abbreviation"))
        games.append({
            "game_id": str(ev.get("id")), "date": ev.get("date"),
            "state": status.get("state") or "pre", "detail": status.get("shortDetail") or "",
            "period": status.get("period"), "clock": status.get("displayClock"),
            "home": abbr(home), "away": abbr(away),
            "home_score": _num(home.get("score")), "away_score": _num(away.get("score")),
            "home_implied": hi, "away_implied": ai,
            "spread": odds.get("details"), "total": _num(odds.get("overUnder")),
            "tv": ", ".join(b.get("names", [""])[0] for b in c.get("broadcasts") or []
                            if b.get("names")),
            "weather": _weather(ev, c),
        })
    return games


def espn_games(week: int, year: int = UPCOMING_YEAR) -> list[dict]:
    return parse_scoreboard(_get(ESPN_SCOREBOARD, {"week": week, "dates": year,
                                                   "seasontype": 2}))


def elapsed(game: dict) -> float:
    """The share of a game already played: 0 before kickoff, 1 once final,
    and in between from the period and the clock (fifteen-minute quarters;
    overtime counts as nearly done). An archive from before the period was
    kept reads a live game as half over."""
    state = game.get("state") or "pre"
    if state == "pre":
        return 0.0
    if state == "post":
        return 1.0
    period = game.get("period")
    clock = game.get("clock") or ""
    if not period:
        return 0.5
    if int(period) > 4:
        return 0.95
    try:
        m, sec = clock.split(":")
        left = int(m) + int(sec) / 60
    except (ValueError, AttributeError):
        left = 0.0
    return min(max(((int(period) - 1) * 15 + (15 - left)) / 60, 0.0), 1.0)


def team_games(games: list[dict]) -> dict:
    """{team: game dict from that team's side} - a team plays at most once a week."""
    out = {}
    for g in games:
        for side, other in (("home", "away"), ("away", "home")):
            out[g[side]] = {
                "game_id": g["game_id"], "date": g["date"], "home": side == "home",
                "opp": g[other], "state": g["state"], "detail": g["detail"],
                "elapsed": elapsed(g),
                "score_for": g[f"{side}_score"], "score_against": g[f"{other}_score"],
                "implied_for": g[f"{side}_implied"], "implied_against": g[f"{other}_implied"],
                "spread": g.get("spread"), "total": g.get("total"), "tv": g.get("tv"),
            }
    return out


def active(games: list[dict], now: datetime = None) -> bool:
    """A game in progress, or kicking off within the buffer - the live tick's gate."""
    now = now or datetime.now(timezone.utc)
    for g in games:
        if g["state"] == "in":
            return True
        if g["state"] == "pre" and g.get("date"):
            try:
                kick = datetime.fromisoformat(g["date"].replace("Z", "+00:00"))
            except ValueError:
                continue
            if 0 <= (kick - now).total_seconds() <= PREGAME_BUFFER_MIN * 60:
                return True
    return False


# --------------------------------------------------------------------------- #
# The week, archived
# --------------------------------------------------------------------------- #

def _fetch_week(week: int, year: int, league_id: str) -> dict:
    rows = sleeper_matchups(week, league_id)
    by_id = {}
    for r in rows:
        by_id.setdefault(r["matchup_id"], []).append(r)
    rostered = {p for r in rows for p in r["players"]}
    try:
        games = espn_games(week, year)
    except requests.RequestException as exc:
        print(f"  ! espn scoreboard week {week}: {exc}")
        games = []
    try:
        proj = sleeper_projections(week, year, only=rostered)
    except requests.RequestException as exc:
        print(f"  ! sleeper projections week {week}: {exc}")
        proj = {}
    from fantasy.league import ext_projections
    external = ext_projections.fetch_week(week, year, only=rostered)
    return {
        "week": week, "year": year,
        "fetched": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "teams": teams(league_id),
        "matchups": [{"matchup_id": mid, "sides": sides} for mid, sides in sorted(
            by_id.items(), key=lambda kv: str(kv[0]))],
        "projections": proj,
        # ESPN's and FantasyPros' weekly numbers, {source: {player_id: pts}},
        # kept beside Sleeper's so each source can be scored against the
        # points once the week is final.
        "external": external,
        "stats": sleeper_stats(week, year, only=rostered),
        "games": games,
    }


def week_final(data: dict) -> bool:
    """Every NFL game over and every side scored: nothing left to change."""
    games = data.get("games") or []
    sides = [s for m in data.get("matchups") or [] for s in m["sides"]]
    return (bool(games) and all(g["state"] == "post" for g in games)
            and bool(sides) and all((s.get("points") or 0) > 0 for s in sides))


def week_started(data: dict) -> bool:
    return any(g["state"] != "pre" for g in data.get("games") or []) or any(
        (s.get("points") or 0) > 0 for m in data.get("matchups") or [] for s in m["sides"])


def _path(week: int, year: int):
    return MATCHUPS_DIR / str(year) / f"week_{int(week):02d}.json"


def week_matchups(week: int, year: int = UPCOMING_YEAR, league_id: str = UPCOMING_LEAGUE_ID,
                  refresh: bool = False, max_age_hours: float = MAX_AGE_HOURS) -> dict:
    """One week: Sleeper matchups and rosters, projections, stats, NFL games."""
    cache = _path(week, year)
    if cache.exists():
        data = json.loads(cache.read_text())
        fresh = (time.time() - cache.stat().st_mtime) < max_age_hours * 3600
        if week_final(data) or (not refresh and fresh):
            return data
    data = _fetch_week(int(week), year, league_id)
    if not data["matchups"]:
        raise RuntimeError(f"Sleeper has no matchups for week {week}")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data, indent=1))
    return data


def archived_weeks(year: int = UPCOMING_YEAR) -> list[int]:
    return sorted(int(p.stem.split("_")[1]) for p in (MATCHUPS_DIR / str(year)).glob("week_*.json"))


def current_week(year: int = UPCOMING_YEAR) -> int:
    """Sleeper's display week for the season, 1 before kickoff."""
    st = nfl_state()
    if str(st.get("season")) != str(year) or st.get("season_type") == "pre":
        return 1
    return max(1, int(st.get("display_week") or st.get("week") or 1))


def capture(refresh: bool = False, year: int = UPCOMING_YEAR,
            league_id: str = UPCOMING_LEAGUE_ID) -> list[int]:
    """Weeks 1 through the current one on disk; only the current week refetches."""
    current = current_week(year)
    weeks = []
    for w in range(1, current + 1):
        try:
            week_matchups(w, year, league_id, refresh=refresh and w == current)
            weeks.append(w)
        except Exception as exc:                        # noqa: BLE001
            print(f"  ! matchups week {w} fetch failed ({exc})")
    return weeks


# --------------------------------------------------------------------------- #
# This week's projection
# --------------------------------------------------------------------------- #

# Sleeper's injury designations and what they are worth this week. A player
# ruled out, on a reserve list or not with the team scores nothing; Doubtful
# players play about one week in four; Questionable ones mostly play, and
# the projection stands.
INJURY_FACTOR = {"Out": 0.0, "IR": 0.0, "PUP": 0.0, "NA": 0.0, "Sus": 0.0, "COV": 0.0,
                 "DNR": 0.0, "Doubtful": 0.25}


def week_projections(board: pd.DataFrame, games: list[dict],
                     injuries: dict = None) -> pd.DataFrame:
    """Every board player's projection for the week, indexed by sleeper_id.

    `mu` is the projection model's points per game. This week's number is
    mu tilted by the market's implied total for his team against the average
    implied total across the slate - the opponent, the venue and the
    expected pace all folded into one number - capped so a mismatch cannot
    double anyone. A defense is tilted the other way, on what its opponent is
    expected to score. No game this week is a bye, and a bye is zero.

    `injuries` is {sleeper_id: Sleeper injury status} as the week's archive
    carries it; a player ruled out projects zero (INJURY_FACTOR). Without it
    the season number stood for a player every other source had at nothing,
    and the disagreements list was a list of the injured.
    """
    by_team = team_games(games)
    injuries = injuries or {}
    implied = [v for g in games for v in (g["home_implied"], g["away_implied"]) if v]
    avg = float(np.mean(implied)) if implied else None
    rows = {}
    for _, p in board.drop_duplicates("sleeper_id").iterrows():
        g = by_team.get(p["team"])
        if g is None:
            rows[str(p["sleeper_id"])] = {"proj_week": 0.0, "n_games": 0}
            continue
        mu = float(p["mu"]) if not pd.isna(p["mu"]) else np.nan
        basis = g["implied_against"] if p["pos"] == "DEF" else g["implied_for"]
        tilt = 1.0
        if avg and basis:
            ratio = (avg / basis) if p["pos"] == "DEF" else (basis / avg)
            tilt = float(np.clip(ratio ** GAME_WEIGHT, 1 - GAME_CAP, 1 + GAME_CAP))
        factor = INJURY_FACTOR.get(injuries.get(str(p["sleeper_id"])) or "", 1.0)
        rows[str(p["sleeper_id"])] = {"proj_week": mu * tilt * factor, "n_games": 1,
                                      "tilt": tilt, "injury_factor": factor, **g}
    out = pd.DataFrame.from_dict(rows, orient="index")
    out.index.name = "sleeper_id"
    return out


if __name__ == "__main__":
    weeks = capture()
    print("weeks on disk:", weeks)
    data = week_matchups(weeks[-1])
    print(f"week {data['week']}: {len(data['matchups'])} matchups, "
          f"{len(data['projections'])} projections, {len(data['stats'])} stat lines, "
          f"{len(data['games'])} games")
