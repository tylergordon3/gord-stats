"""
How good the weekly college projections actually are.

The NFL side scores its projections against what happened; this is the same
for the college league, and it can now compare three columns because the week
archive carries Yahoo's own per-player projection beside ours:

    GordStats   cfb.weekly.week_projections - the season projection spread over
                the school's games, tilted by the game model
    Yahoo       Rotowire's number, read off the league's team pages
    actual      what Yahoo scored the player

Only players who were in somebody's lineup that week are counted, because a
projection for a player nobody started is not a claim anybody acted on, and
only finished weeks are scored.

    python -m cfb.audit
"""
import argparse

import numpy as np
import pandas as pd

from cfb import predict, projections, weekly, yahoo
from cfb.config import SEASON

BENCH = {"BN", "IL", "IR"}


def rows(season: int = SEASON) -> pd.DataFrame:
    """One row per started player-week: our projection, Yahoo's, and the score."""
    lg = yahoo.league()
    frame, _model, _names = predict.season()
    board = projections.value_board(frame=frame)
    out = []
    for week in yahoo.archived_weeks():
        data = yahoo.week_matchups(week)
        if not yahoo.week_final(data):
            continue
        statuses = {p["yahoo_id"]: p["status"] for roster in data["rosters"].values()
                    for p in roster if p.get("status")}
        wk = weekly.week_projections(data["week_start"], data["week_end"], board=board,
                                     league=lg, frame=frame, injuries=statuses)
        y_proj = data.get("yahoo_proj") or {}
        for roster in data["rosters"].values():
            for p in roster:
                if p["slot"] in BENCH or p.get("points") is None:
                    continue
                pid = p["yahoo_id"]
                ours = (float(wk.loc[pid, "proj_week"])
                        if pid in wk.index and pd.notna(wk.loc[pid, "proj_week"]) else None)
                out.append({"week": week, "pos": p["pos"], "player": p["player"],
                            "actual": float(p["points"]),
                            "gs": ours, "yahoo": y_proj.get(pid)})
    return pd.DataFrame(out)


def score(frame: pd.DataFrame) -> pd.DataFrame:
    """Mean absolute error and bias per position, for each source."""
    out = []
    for pos, group in list(frame.groupby("pos")) + [("ALL", frame)]:
        row = {"pos": pos, "n": len(group)}
        for source in ("gs", "yahoo"):
            got = group.dropna(subset=[source])
            if got.empty:
                row[f"{source}_mae"] = row[f"{source}_bias"] = np.nan
                continue
            err = got[source] - got["actual"]
            row[f"{source}_n"] = len(got)
            row[f"{source}_mae"] = err.abs().mean()
            row[f"{source}_bias"] = err.mean()
            row[f"{source}_corr"] = got[source].corr(got["actual"])
        out.append(row)
    return pd.DataFrame(out)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Score the weekly college projections.")
    p.add_argument("--by-week", action="store_true")
    args = p.parse_args()
    frame = rows()
    if frame.empty:
        print("no finished weeks to score yet")
    else:
        print(score(frame).round(2).to_string(index=False))
        if args.by_week:
            for week, block in frame.groupby("week"):
                print(f"\nweek {week}")
                print(score(block).round(2).to_string(index=False))
