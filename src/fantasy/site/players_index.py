"""
Two small files the browser fetches when someone is looking at their own
league: a player index, and this week's projections.

docs/fantasy/players-index.json - Sleeper player id -> [name, position].

The matchups page can show a reader's own league, and a league's rosters are
just player ids. Names have to come from somewhere, and Sleeper's own player
endpoint is about 5 MB, which is not a thing to download on a phone to read a
scoreboard.

So the index is written here instead, from the player table the build already
keeps: every active player at a fantasy position, about 3,200 of them and
under 100 KB. It is fetched lazily by the browser and only when someone is
actually looking at their own league, so it costs a normal reader nothing.

docs/fantasy/week-projections.json - Sleeper player id -> this week's points.

Sleeper's own projections endpoint cannot be used from a browser: it answers a
cross-origin request with every player id mapped to an empty object, stats
stripped, where the same URL from a server returns the numbers. The build
already downloads the full set anyway - `sleeper_projections` fetches
everything and then filters to the rostered players - so the unfiltered copy
is written out here at about 40 KB instead.

    python -m fantasy.site.players_index
"""
import json

import pandas as pd

from fantasy import paths
from fantasy.config import UPCOMING_YEAR

FANTASY_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")
OUT = paths.WEB_FANTASY_DIR / "players-index.json"
PROJ_OUT = paths.WEB_FANTASY_DIR / "week-projections.json"


def build() -> dict:
    frame = pd.read_parquet(paths.DATA_DIR / "players" / "sleeper.parquet")
    keep = frame[frame["position"].isin(FANTASY_POSITIONS)]
    if "active" in keep.columns:
        keep = keep[keep["active"].fillna(False).astype(bool)]
    out = {}
    for row in keep.itertuples():
        pid = getattr(row, "sleeper_id", None)
        name = getattr(row, "full_name", None)
        if pid is None or pd.isna(pid) or not name or pd.isna(name):
            continue
        out[str(pid)] = [str(name), str(row.position)]
    return out


def projections(week: int = None, year: int = UPCOMING_YEAR) -> dict:
    """{player_id: points} for every player Sleeper prices this week."""
    from fantasy.league import matchups as matchups_mod
    if week is None:
        weeks = matchups_mod.archived_weeks(year)
        if not weeks:
            return {}
        week = weeks[-1]
    rows = matchups_mod.sleeper_projections(week, year)      # no `only`: all of them
    return {pid: round(float(v["pts"]), 2)
            for pid, v in rows.items() if v.get("pts") is not None}


def generate():
    index = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    # Compact: these are fetched, not read.
    OUT.write_text(json.dumps(index, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote player index ({len(index)} players) -> {OUT}")

    try:
        proj = projections()
    except Exception as exc:                                # noqa: BLE001
        print(f"  ! week projections unavailable ({exc}); keeping the last copy")
        return
    if proj:
        PROJ_OUT.write_text(json.dumps(proj, separators=(",", ":")), encoding="utf-8")
        print(f"Wrote week projections ({len(proj)} players) -> {PROJ_OUT}")


if __name__ == "__main__":
    generate()
