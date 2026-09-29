"""
The college league's power rankings as they would have stood before each week
already played - written into the history the page's chart and Move columns
read (data/cfb/league_power_history/), so the season's story starts at the
draft rather than on the day the current method arrived (2026-09-27).

Each week is priced from what was known then, not now:

    rosters      that week's, from Yahoo's weekly archive
    player value the draft-day board blended only with the box scores and
                 Yahoo points of the weeks before (cfb.in_season, before_week)
    game model   fitted on games before the week began, and every later game
                 treated as unplayed (predict.season(asof), results hidden)
    standings    rebuilt from the weeks before (league_sim.regular_season)

Two things cannot be taken back: a player first rostered after the draft is
priced at Yahoo's current value, and injury tags were not archived, so a past
week carries none.

Snapshots made the old ways (rank alone; season lineup value) move to
superseded/ beside the history: kept, but out of a series they are not on the
scale of.

    python -m cfb.league_backfill            # the weeks before the current one
    python -m cfb.league_backfill --dry-run  # print, write nothing
"""
import argparse
import shutil
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from cfb import in_season, league_sim, predict, yahoo
from cfb.config import LEAGUE_TZ
from cfb.site.league_power import HISTORY_DIR
from gordstats import rankmoves

COLUMNS = ["key", "rank", "team", "per_week", "wk_vs_avg", "playoffs", "title"]


def asof(week: int, lg: dict) -> datetime:
    """When that week's ranking would have been built (Eastern, naive, as the
    snapshots are named): the morning its window opened - the day after the
    week before ended - or, for the first week, the day before it began."""
    data = yahoo.week_matchups(week)
    start = datetime.strptime(data["week_start"], "%Y-%m-%d")
    if week <= int(lg.get("start_week") or 1):
        return start - timedelta(hours=12)
    return start.replace(hour=5)


def frame_asof(when: datetime) -> pd.DataFrame:
    """Every game, predicted by the model as it stood `when`, with nothing
    after it counted as played."""
    ts = pd.Timestamp(when, tz=LEAGUE_TZ).tz_convert("UTC")
    frame, _model, _names = predict.season(asof=ts)
    later = frame["date"] >= ts
    frame.loc[later, "state"] = "pre"
    for col in ("home_score", "away_score", "actual_margin"):
        if col in frame:
            frame.loc[later, col] = np.nan
    if "played" in frame:
        frame.loc[later, "played"] = False
    return frame


def league_asof(lg: dict, week: int) -> dict:
    """The league as it stood at the start of `week`: its standings from the
    weeks before."""
    record = league_sim.regular_season(lg, before=week)
    teams = [{**t, "wins": record.get(t["team_key"], (0, 0, 0))[0],
              "losses": record.get(t["team_key"], (0, 0, 0))[2], "ties": 0,
              "points_for": record.get(t["team_key"], (0, 0, 0))[1]} for t in lg["teams"]]
    return {**lg, "current_week": week, "teams": teams}


def ranking(lg: dict, week: int) -> tuple:
    """(when, frame of COLUMNS) for the start of `week`."""
    when = asof(week, lg)
    frame = frame_asof(when)
    board = in_season.board(frame=frame, before_week=week)
    rosters = {k: [str(p["yahoo_id"]) for p in r]
               for k, r in yahoo.week_matchups(week)["rosters"].items()}
    past = league_asof(lg, week)
    sim = league_sim.run(past, rosters, board=board, frame=frame, live=False)
    sim = sim.sort_values("per_week", ascending=False).reset_index(drop=True)
    names = {t["team_key"]: t.get("name") for t in lg["teams"]}
    avg = sim["per_week"].mean()
    out = pd.DataFrame({
        "key": sim["team_key"], "rank": range(1, len(sim) + 1),
        "team": sim["team_key"].map(names),
        "per_week": sim["per_week"].round(1),
        "wk_vs_avg": (sim["per_week"] - avg).round(1),
        "playoffs": sim["playoffs"].round(4) if "playoffs" in sim else None,
        "title": sim["title"].round(4) if "title" in sim else None,
    })
    return when, out[COLUMNS]


def _method(path) -> str:
    with open(path, encoding="utf-8") as f:
        return f.readline().strip()


def supersede_old() -> list:
    """Move snapshots not on the current method (no per_week column) aside."""
    moved = []
    aside = HISTORY_DIR / "superseded"
    for _, path in rankmoves._snaps(HISTORY_DIR):
        if "per_week" not in _method(path).split(","):
            aside.mkdir(exist_ok=True)
            shutil.move(str(path), aside / path.name)
            moved.append(path.name)
    return moved


def backfill(weeks=None, dry_run: bool = False) -> list:
    lg = yahoo.league()
    current = int(lg["current_week"])
    weeks = weeks or [w for w in yahoo.archived_weeks()
                      if int(lg.get("start_week") or 1) <= w < current]
    written = []
    for week in weeks:
        when, table = ranking(lg, week)
        print(f"week {week} as of {when:%a %b %-d %H:%M}:")
        print(table[["rank", "team", "per_week", "playoffs", "title"]].to_string(index=False))
        if not dry_run:
            HISTORY_DIR.mkdir(parents=True, exist_ok=True)
            path = HISTORY_DIR / f"{when:{rankmoves._FMT}}.csv"
            table.to_csv(path, index=False)
            written.append(path.name)
    if not dry_run:
        moved = supersede_old()
        print(f"wrote {len(written)}; moved {len(moved)} old-method snapshots to superseded/")
    return written


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Backfill the college league's power history.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--week", type=int, action="append")
    args = ap.parse_args()
    backfill(args.week, args.dry_run)
