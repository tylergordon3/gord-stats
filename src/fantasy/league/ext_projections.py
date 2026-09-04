"""
Other people's weekly projections, keyed to Sleeper ids.

Two sources beside Sleeper's own (fantasy.league.matchups.sleeper_projections):

  * ESPN - the fantasy API behind its league pages, read anonymously with the
    default PPR scoring (leaguedefaults/3). A header-borne filter narrows the
    payload to one week's projection per player.
  * FantasyPros - the consensus of the experts it aggregates, read from the
    JSON its weekly rankings pages embed (one page per position, PPR): the
    consensus projected points, the ECR rank and the start/sit grade. The
    projection tables themselves render only ten rows server-side now.

Neither is documented, both have held their shape for years, and both are
treated the way the FantasyPros league-analyzer column is: a source that is
unreachable or has changed shape yields nothing for the week, never an error,
so the page it feeds still builds.

Matching to Sleeper ids goes through the player registry - ESPN ids where the
registry has them (most of the board), otherwise the normalized name at the
same position; defenses by team code.
"""
import json
import re

import pandas as pd
import requests

from fantasy import paths
from fantasy.normalize import normalize_name

ESPN_API = ("https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{year}"
            "/segments/0/leaguedefaults/3")
FP_PAGE = "https://www.fantasypros.com/nfl/rankings/{page}.php"
_TIMEOUT = 40
_UA = {"User-Agent": "Mozilla/5.0"}

SOURCES = {"sleeper": "Sleeper", "espn": "ESPN", "fp": "FantasyPros"}

# ESPN's proTeamId -> Sleeper's team code, and its position ids.
ESPN_TEAMS = {22: "ARI", 1: "ATL", 33: "BAL", 2: "BUF", 29: "CAR", 3: "CHI", 4: "CIN",
              5: "CLE", 6: "DAL", 7: "DEN", 8: "DET", 9: "GB", 34: "HOU", 11: "IND",
              30: "JAX", 12: "KC", 13: "LV", 24: "LAC", 14: "LAR", 15: "MIA", 16: "MIN",
              17: "NE", 18: "NO", 19: "NYG", 20: "NYJ", 21: "PHI", 23: "PIT", 25: "SF",
              26: "SEA", 27: "TB", 10: "TEN", 28: "WAS"}
ESPN_POSITIONS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DEF"}

# FantasyPros names a defense by its franchise.
FP_TEAMS = {"Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL",
            "Buffalo Bills": "BUF", "Carolina Panthers": "CAR", "Chicago Bears": "CHI",
            "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE", "Dallas Cowboys": "DAL",
            "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
            "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX",
            "Kansas City Chiefs": "KC", "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC",
            "Los Angeles Rams": "LAR", "Miami Dolphins": "MIA", "Minnesota Vikings": "MIN",
            "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
            "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT",
            "San Francisco 49ers": "SF", "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB",
            "Tennessee Titans": "TEN", "Washington Commanders": "WAS"}
FP_PAGES = {"qb": "QB", "ppr-rb": "RB", "ppr-wr": "WR", "ppr-te": "TE", "k": "K", "dst": "DEF"}


# --------------------------------------------------------------------------- #
# ESPN
# --------------------------------------------------------------------------- #

def espn_filter(week: int, year: int, limit: int = 1500) -> str:
    """The X-Fantasy-Filter that asks for one week's projection only. The
    period id is "11{year}{week}": source 1 (projected), split 1 (weekly)."""
    return json.dumps({"players": {
        "limit": limit,
        "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
        "filterStatsForTopScoringPeriodIds": {"value": 1, "additionalValue": [f"11{year}{week}"]},
    }})


def parse_espn(payload: dict, week: int, year: int) -> list[dict]:
    """[{espn_id, name, pos, team, pts}] for every player with that week's projection."""
    out = []
    for entry in payload.get("players") or []:
        p = entry.get("player") or {}
        pts = None
        for s in p.get("stats") or []:
            if (s.get("statSourceId") == 1 and s.get("statSplitTypeId") == 1
                    and int(s.get("scoringPeriodId") or 0) == week
                    and int(s.get("seasonId") or 0) == year):
                pts = float(s.get("appliedTotal") or 0.0)
        if pts is None:
            continue
        out.append({"espn_id": str(p.get("id")), "name": p.get("fullName") or "",
                    "pos": ESPN_POSITIONS.get(p.get("defaultPositionId"), ""),
                    "team": ESPN_TEAMS.get(p.get("proTeamId"), ""), "pts": pts})
    return out


def espn_week(week: int, year: int) -> list[dict]:
    r = requests.get(ESPN_API.format(year=year), params={"view": "kona_player_info"},
                     timeout=_TIMEOUT, headers={"X-Fantasy-Filter": espn_filter(week, year)})
    r.raise_for_status()
    return parse_espn(r.json(), week, year)


# --------------------------------------------------------------------------- #
# FantasyPros
# --------------------------------------------------------------------------- #

_ECR = re.compile(r"var ecrData = (\{.*?\});\s*\n", re.S)


def parse_fantasypros(html: str, pos: str) -> list[dict]:
    """[{name, pos, team, pts, ecr, grade}] from a weekly rankings page's
    embedded ecrData. `r2p_pts` is the consensus projection; a player the
    experts rank but nobody projects has none and is skipped."""
    m = _ECR.search(html)
    if not m:
        return []
    data = json.loads(m.group(1))
    out = []
    for p in data.get("players") or []:
        pts = p.get("r2p_pts")
        try:
            pts = float(pts)
        except (TypeError, ValueError):
            continue
        name = p.get("player_name") or ""
        team = p.get("player_team_id") or ""
        if pos == "DEF":
            team = FP_TEAMS.get(name, team)
        out.append({"name": name, "pos": pos, "team": team, "pts": pts,
                    "ecr": p.get("rank_ecr"), "grade": p.get("start_sit_grade") or ""})
    return out


def fantasypros_week(week: int) -> list[dict]:
    out = []
    for page, pos in FP_PAGES.items():
        r = requests.get(FP_PAGE.format(page=page), params={"week": week},
                         headers=_UA, timeout=_TIMEOUT)
        r.raise_for_status()
        out.extend(parse_fantasypros(r.text, pos))
    return out


# --------------------------------------------------------------------------- #
# Matching
# --------------------------------------------------------------------------- #

class Lookup:
    """Sleeper ids by ESPN id and by (normalized name, position), from the
    player registry. A defense's Sleeper id is its team code."""

    def __init__(self, frame: pd.DataFrame = None):
        if frame is None:
            path = paths.PLAYERS_DIR / "registry.parquet"
            cols = ["sleeper_id", "espn_id", "full_name", "position"]
            frame = (pd.read_parquet(path, columns=cols) if path.exists()
                     else pd.DataFrame(columns=cols))
        frame = frame.dropna(subset=["sleeper_id"])
        self.by_espn = {}
        self.by_name = {}
        for r in frame.itertuples(index=False):
            sid = str(r.sleeper_id)
            if isinstance(r.espn_id, str) and r.espn_id:
                self.by_espn.setdefault(str(int(float(r.espn_id))), sid)
            key = (normalize_name(r.full_name), r.position)
            if key[0]:
                self.by_name.setdefault(key, sid)

    def sleeper_id(self, row: dict) -> str | None:
        if row.get("pos") == "DEF":
            return row.get("team") or None
        if row.get("espn_id") and row["espn_id"] in self.by_espn:
            return self.by_espn[row["espn_id"]]
        return self.by_name.get((normalize_name(row.get("name")), row.get("pos")))


def to_sleeper(rows: list[dict], lookup: Lookup, only: set = None,
               field: str = "pts") -> dict:
    """{sleeper_id: row[field]} for the rows that match (and are in `only`)."""
    out = {}
    for r in rows:
        sid = lookup.sleeper_id(r)
        if sid and (only is None or sid in only) and sid not in out:
            out[sid] = r[field] if field else r
    return out


def fetch_week(week: int, year: int, only: set = None, lookup: Lookup = None) -> dict:
    """{"espn": {sleeper_id: pts}, "fp": {...}, "fp_rank": {sleeper_id: {ecr, grade}}}
    - a source that fails is simply absent."""
    lookup = lookup or Lookup()
    out = {}
    try:
        out["espn"] = to_sleeper(espn_week(week, year), lookup, only)
    except Exception as exc:                            # noqa: BLE001
        print(f"  ! ESPN projections week {week}: {exc}")
    try:
        rows = fantasypros_week(week)
        out["fp"] = to_sleeper(rows, lookup, only)
        out["fp_rank"] = {sid: {"ecr": r["ecr"], "grade": r["grade"]}
                          for sid, r in to_sleeper(rows, lookup, only, field=None).items()}
    except Exception as exc:                            # noqa: BLE001
        print(f"  ! FantasyPros rankings week {week}: {exc}")
    return out


def consensus(*sources: dict) -> dict:
    """Per player, the mean of whichever sources have him."""
    ids = set().union(*(s.keys() for s in sources if s))
    out = {}
    for pid in ids:
        vals = [s[pid] for s in sources if s and s.get(pid) is not None]
        if vals:
            out[pid] = sum(vals) / len(vals)
    return out


if __name__ == "__main__":
    import sys
    week = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    from fantasy.config import UPCOMING_YEAR
    got = fetch_week(week, UPCOMING_YEAR)
    for k, v in got.items():
        top = sorted(v.items(), key=lambda kv: -kv[1])[:5]
        print(SOURCES[k], len(v), "matched;", top)
