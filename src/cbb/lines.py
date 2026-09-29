"""
College basketball betting lines, kept: each game's closing spread and total
beside its final score, so picks can be graded against the line later.

Nothing kept them before. The only lines this section sees ride on the live
scoreboard (cbb.live_scraper, from theScore) and are overwritten every push,
so a season ended with no record of what the book said (the 2026-09-28 audit).

Two files, because the Pi's live tick resets tracked data it doesn't commit
and commits only when a page rebuilds:

  data/cbb/lines_live/<season>.json   written every tick by cbb.live (gitignored,
                                      so a reset never touches it)
  data/cbb/lines/<season>.json        the record: the daily run copies the live
                                      file here (publish), and commits it

Each game keeps the last line seen before tipoff - the closing line, to within
a tick - and the score once final. Keyed "<league>:<theScore event id>".
"""
import json
import os
from pathlib import Path

from cbb import paths, utils

LIVE_DIR = paths.DATA / "cbb" / "lines_live"
RECORD_DIR = paths.DATA / "cbb" / "lines"
_KEEP = ("date", "start_time_utc", "home_team", "away_team", "game_type", "game_description")


def _path(folder: Path, season: int) -> Path:
    return folder / f"{season}.json"


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(path: Path, data: dict) -> None:
    """Sorted and stable, so an unchanged archive is an unchanged file (no
    commit churn), and replaced in one step (a tick killed mid-write leaves
    the old file, not half a new one)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, sort_keys=True, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _pregame(status) -> bool:
    return str(status or "").lower() in ("pre_game", "scheduled", "")


def merge(archive: dict, leagues: dict) -> dict:
    """`archive` updated from one scoreboard snapshot {league: {id: game}}."""
    for league, games in leagues.items():
        for gid, g in (games or {}).items():
            row = archive.setdefault(f"{league}:{gid}", {"league": league})
            row.update({k: g.get(k) for k in _KEEP if g.get(k) is not None})
            if _pregame(g.get("status")):
                # Moves until tipoff; the last one before it is the close.
                if g.get("spread_close"):
                    row["spread"] = g["spread_close"]
                if g.get("total_close") is not None:
                    row["total"] = g["total_close"]
            elif str(g.get("status")).lower() == "final":
                row.update(home_score=g.get("home_score"), away_score=g.get("away_score"),
                           final=True)
    return archive


def record(leagues: dict, season: int = None) -> None:
    """Fold one tick's scoreboard into the live file."""
    from datetime import date
    season = season or utils.season_year(date.today())
    path = _path(LIVE_DIR, season)
    _write(path, merge(_load(path), leagues))


def publish(season: int = None) -> int:
    """Copy the live file over the record; returns how many games it holds.
    The live file only ever grows, so it is the whole season."""
    from datetime import date
    season = season or utils.season_year(date.today())
    live = _load(_path(LIVE_DIR, season))
    if not live:
        return 0
    path = _path(RECORD_DIR, season)
    if _load(path) != live:
        _write(path, live)
    return len(live)
