"""
Somebody else's power rankings, next to ours.

The number this site publishes comes out of ten thousand simulated seasons
(`fantasy.league.power`). This module adds one column saying what an outside
source made of the same ten rosters — not to check our arithmetic, which no
outside source can do, but because a ranking nobody disagrees with is not
telling you much. The interesting rows are the ones where the two columns are
far apart, and those rows are the whole reason the column is here.

The source is the FantasyPros League Analyzer. Its page looks like it needs an
account — signed out, the browser renders "Sync a League" instead of the table
— but that gate is client-side only. The Vue bundle behind the page reads its
data from

    https://mpbnfl.fantasypros.com/api/getLeagueAnalysisJSON?key=<league key>

which answers in full to an anonymous GET. The league key is the bearer token;
nothing else is checked. `standings` in that payload is the rendered table, and
its `teamId` is the Sleeper roster_id, so the join needs no name matching.

The 0-100 the page shows is not a field. It is `vorpPerc` rescaled so the
leader reads 100 — verified against a hand-copy of the rendered table, all ten
rows exact. `vorpPerc` itself is the more useful number and is kept too: it is
already centred on 100 the same way our own power is, so the two are directly
comparable.

Every fetch rewrites `data/fantasy/power/{year}/external.json`, which doubles
as the fallback. That file, not this module, holds the league key and the
source's name, so pointing the column at a different league or a different
site is an edit to data rather than code. If the fetch fails the last good
copy renders with its own capture date; if there is no copy either, `load`
returns empty and the page renders as it did before the column existed.
"""
import json
import re
import unicodedata
from datetime import date

import pandas as pd
import requests

from fantasy import paths
from fantasy import sleeper_retry
from fantasy.config import UPCOMING_LEAGUE_ID, UPCOMING_YEAR

SLEEPER_API = "https://api.sleeper.app/v1"
ANALYZER_API = "https://mpbnfl.fantasypros.com/api/getLeagueAnalysisJSON"
# The API answers a bare GET, but it is a browser endpoint; identify as one.
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
_TIMEOUT = 20

_COLS = ["roster_id", "ext_rank", "ext_score", "ext_vorp"]


def snapshot_path(year: int = UPCOMING_YEAR):
    return paths.DATA_DIR / "power" / str(year) / "external.json"


def _read_snapshot(year: int) -> dict:
    path = snapshot_path(year)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[power] external snapshot unreadable ({exc})")
        return {}


def _key(name: str) -> str:
    """Fold a team name to something two sources can agree on.

    Only used to audit the roster_id join, never to make it — Sleeper and
    FantasyPros round-trip the same string through different encoders, and
    curly quotes, accents and doubled spaces survive one but not the other.
    """
    folded = unicodedata.normalize("NFKD", str(name))
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    folded = folded.replace("‘", "'").replace("’", "'")
    folded = folded.replace("“", '"').replace("”", '"')
    return re.sub(r"[^a-z0-9]+", "", folded.casefold())


def team_names(league_id: str = UPCOMING_LEAGUE_ID) -> dict:
    """roster_id -> the team name Sleeper shows, falling back to the handle."""
    users = sleeper_retry.get_json(f"{SLEEPER_API}/league/{league_id}/users",
                                   timeout=_TIMEOUT)
    rosters = sleeper_retry.get_json(f"{SLEEPER_API}/league/{league_id}/rosters",
                                     timeout=_TIMEOUT)

    by_user = {u["user_id"]: u for u in users}
    out = {}
    for roster in rosters:
        user = by_user.get(roster.get("owner_id")) or {}
        name = (user.get("metadata") or {}).get("team_name") or user.get("display_name")
        if name:
            out[int(roster["roster_id"])] = name
    return out


def _player_names() -> dict:
    """{sleeper_id: player name}, from the player table the build already keeps."""
    path = paths.PLAYERS_DIR / "sleeper.parquet"
    if not path.exists():
        return {}
    frame = pd.read_parquet(path, columns=["sleeper_id", "full_name"]).dropna()
    return {str(row.sleeper_id): str(row.full_name) for row in frame.itertuples()}


def _sleeper_rosters(league_id: str) -> dict:
    """{roster_id: folded names of the players on it}."""
    names = _player_names()
    if not names:
        return {}
    rosters = sleeper_retry.get_json(f"{SLEEPER_API}/league/{league_id}/rosters",
                                     timeout=_TIMEOUT)
    # Sleeper answers a league it does not know with something that is not a
    # list of rosters. The audit is a nicety and must never be the thing that
    # raises, so anything of the wrong shape is simply nothing to check.
    if not isinstance(rosters, list):
        return {}
    out = {}
    for roster in rosters:
        if not isinstance(roster, dict):
            continue
        held = {_key(names[str(p)]) for p in (roster.get("players") or [])
                if str(p) in names}
        if held:
            out[int(roster["roster_id"])] = held
    return out


def _upstream_rosters(payload: dict) -> dict:
    """{teamId: folded player names}, out of the analyzer's own position grid.

    The grid is a row per position, and every cell in it carries the player and
    the teamId holding him - which is the only part of the payload that says
    what a team actually *is*.
    """
    out = {}
    for row in payload.get("grid") or []:
        if row.get("position") == "Teams":
            continue                                  # the header row, not players
        for cell in row.get("cells") or []:
            team, name = cell.get("teamId"), cell.get("name")
            if team and name:
                out.setdefault(int(team), set()).add(_key(name))
    return out


def _audit(payload: dict, league_id: str):
    """Warn if a teamId is attached to a different roster than it claims.

    The join is on teamId because that is what the payload gives us. Nothing
    promises FantasyPros will keep numbering teams the way Sleeper does, and a
    silently transposed pair of rows would look like a real disagreement
    between the two models rather than a bug.

    This used to compare team *names*, and it cried wolf: three managers in
    this league renamed their teams, FantasyPros kept the names it last synced,
    and the build warned about all three on every run - for a join that was
    perfectly correct. A name is a label somebody can change at any moment; the
    roster is what the id means. So the check is now which Sleeper roster each
    upstream team's players actually match, and it stays quiet unless that is
    somebody else's.
    """
    try:
        mine = _sleeper_rosters(league_id)
        theirs = _upstream_rosters(payload)
    except (requests.RequestException, KeyError, TypeError, ValueError, OSError):
        return                        # the audit is a nicety; it never gates a build
    if not mine or not theirs:
        return

    for team_id, players in sorted(theirs.items()):
        overlap = {rid: len(players & held) for rid, held in mine.items()}
        if not overlap or max(overlap.values()) == 0:
            continue                  # nobody recognised: a stale player table, not drift
        best = max(overlap, key=lambda rid: (overlap[rid], -rid))
        if best != team_id:
            print(f"[power] external teamId {team_id} looks like Sleeper roster "
                  f"{best} ({overlap[best]} of {len(players)} players match, "
                  f"{overlap.get(team_id, 0)} on the roster it claims) — "
                  "the column may be attached to the wrong rosters")


def fetch(league_key: str, league_id: str = UPCOMING_LEAGUE_ID) -> list:
    """The analyzer's standings, as the rows a snapshot stores."""
    # Through the retrying helper like everything else in this module. It is
    # FantasyPros rather than Sleeper, but a dropped connection costs the power
    # page its external column either way, and it keeps the rule here absolute:
    # nothing that talks to Sleeper calls requests directly.
    payload = sleeper_retry.get_json(ANALYZER_API, params={"key": league_key},
                                     headers={"User-Agent": _UA}, timeout=_TIMEOUT)
    if "error" in payload:
        raise ValueError(payload["error"])

    standings = payload["standings"]
    top = max(float(t["vorpPerc"]) for t in standings)
    _audit(payload, league_id)
    return [{"team": t["teamName"],
             "team_id": int(t["teamId"]),
             "rank": int(t["rank"]),
             # What the page prints: vorpPerc rescaled so the leader reads 100.
             "score": round(float(t["vorpPerc"]) / top * 100),
             "vorp": round(float(t["vorpPerc"]), 2)}
            for t in sorted(standings, key=lambda t: t["rank"])]


def refresh(year: int = UPCOMING_YEAR, league_id: str = UPCOMING_LEAGUE_ID) -> dict:
    """Re-fetch and rewrite the snapshot. Returns the snapshot either way."""
    snap = _read_snapshot(year)
    league_key = snap.get("league_key")
    if not league_key:
        return snap

    try:
        teams = fetch(league_key, league_id)
    except (requests.RequestException, ValueError, KeyError) as exc:
        when = snap.get("captured", "an earlier build")
        print(f"[power] external ranking not refreshed ({exc}); using {when}")
        return snap

    snap["teams"] = teams
    snap["captured"] = date.today().isoformat()
    path = snapshot_path(year)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snap, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return snap


def load(year: int = UPCOMING_YEAR, league_id: str = UPCOMING_LEAGUE_ID,
         live: bool = True) -> pd.DataFrame:
    """The outside ranking as [roster_id, ext_rank, ext_score, ext_vorp].

    `.attrs` carries who said it and when, for the line under the table.
    Anything wrong — no snapshot, a season that has moved on, a fetch that
    fails with nothing cached — is a missing column, not an error.
    """
    empty = pd.DataFrame(columns=_COLS)
    snap = refresh(year, league_id) if live else _read_snapshot(year)
    if not snap or not snap.get("teams"):
        return empty
    if int(snap.get("season", year)) != int(year):
        return empty

    frame = pd.DataFrame([{"roster_id": int(t["team_id"]),
                           "ext_rank": int(t["rank"]),
                           "ext_score": float(t["score"]),
                           "ext_vorp": float(t.get("vorp", "nan"))}
                          for t in snap["teams"] if "team_id" in t])
    if frame.empty:
        return empty

    frame.attrs = {"source": snap.get("source", "an outside source"),
                   "short": snap.get("short", ""),
                   "label": snap.get("label", ""),
                   "url": snap.get("url", ""),
                   "captured": snap.get("captured", "")}
    return frame
