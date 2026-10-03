"""
The NFL model's record: every prediction archived before kickoff, graded
against the final - data/nfl/predictions/{season}/<capture day>.parquet, the
college archive's shape (cfb.results) with ESPN's book line beside each one.
Every run captures every game still to play (~250 rows), so one file per
capture day (cfb.partitions) is what keeps a run from rewriting the season.

    python -m nfl.results              # capture this week's board, then score
    python -m nfl.results --score
"""
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from cfb import partitions, results as _college
from nfl import games as games_mod, predict
from nfl.config import DATA_DIR, SEASON
from gordstats import bet_record

PRED_DIR = DATA_DIR / "predictions"
_COLS = _college._COLS + ["seasontype"]
KEY = ["game_id"]                 # one row per game per capture day


def season_path(season: int = SEASON):
    """The season's single file from before the split (read if present);
    the archive is the folder beside it."""
    return PRED_DIR / f"{season}.parquet"


def load(season: int = SEASON):
    """Every capture this season, oldest first; None when there are none."""
    return partitions.read(season_path(season), KEY)


def capture(season: int = SEASON) -> pd.DataFrame:
    """Append the prediction for every game still to kick off to the archive.

    Still to kick off, not merely unfinished. A game in progress was captured
    too, and since one capture per game per UTC day is kept, the 17:30 ET
    Sunday run - mid-game for the 4:25 slate, and the same UTC day as the
    morning's run - replaced that morning's pre-kickoff prediction with one
    on_record() then threw away, leaving the game graded on Saturday's line
    or on nothing.

    And only games that are real yet: not a playoff slot whose teams are
    ESPN's TBD placeholders (207 of those had been archived, predictions for
    nobody), nor a game whose kickoff ESPN files as a midnight TBD - its
    archived kickoff would be a time the game is not played at.
    """
    board, _model, _names = predict.season()
    now = pd.Timestamp.now(tz="UTC")
    kick = pd.to_datetime(board["date"], utc=True)
    real = [not games_mod.tbd(g) and games_mod.time_known(g) for _, g in board.iterrows()]
    games = board[~board["played"] & (kick > now) & pd.Series(real, index=board.index, dtype=bool)]
    if games.empty:
        return pd.DataFrame(columns=_COLS)
    fresh = pd.DataFrame({
        "captured": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "season": season, "week": games["week"].astype(int),
        "seasontype": games["seasontype"].astype(int),
        "game_id": games["game_id"].astype(str), "kickoff": games["date"],
        "home_id": games["home_id"].astype(str), "away_id": games["away_id"].astype(str),
        "home": games["home"], "away": games["away"],
        "neutral": games["neutral"].astype(bool),
        "pred_margin": games["pred_margin"].astype(float),
        "pred_total": games["pred_total"].astype(float),
        "home_win_prob": games["home_win_prob"].astype(float),
        "market_spread": games["book_spread"].astype(float),
        "market_total": games["book_total"].astype(float),
    })
    # Into today's file only; unchanged same-day captures keep the row
    # already there (cfb.results).
    return partitions.record(season_path(season), fresh, KEY)


def on_record(season: int = SEASON) -> pd.DataFrame:
    """The last prediction archived before each game's kickoff."""
    archive = load(season)
    if archive is None or archive.empty:
        return pd.DataFrame(columns=_COLS)
    for col in _COLS:
        if col not in archive.columns:
            archive[col] = np.nan
    archive["captured_at"] = pd.to_datetime(archive["captured"], utc=True, format="ISO8601")
    archive["kickoff"] = pd.to_datetime(archive["kickoff"], utc=True)
    # The TBD-v-TBD captures already on file (capture() no longer adds them)
    # are a call on nobody: never the one on record for the game ESPN later
    # fills in under the same id.
    placeholder = (archive["home_id"].astype(str).str.startswith("-")
                   | archive["away_id"].astype(str).str.startswith("-"))
    before = archive[(archive["captured_at"] < archive["kickoff"]) & ~placeholder]
    return (before.sort_values("captured_at").drop_duplicates(subset="game_id", keep="last")
            .reset_index(drop=True))


def scored(season: int = SEASON) -> pd.DataFrame:
    latest = on_record(season)
    done = games_mod.played(games_mod.schedule())
    if latest.empty or done.empty:
        return pd.DataFrame()
    finals = pd.DataFrame({
        "game_id": done["game_id"].astype(str),
        "actual_margin": done["home_score"] - done["away_score"],
        "actual_total": done["home_score"] + done["away_score"],
        "home_score": done["home_score"], "away_score": done["away_score"],
    })
    return _college.grade(latest.merge(finals, on="game_id", how="inner"))


summary = _college.summary


def line_moves(season: int = SEASON) -> pd.DataFrame:
    """The college archive's line_moves, on this one - the TBD-v-TBD
    captures (on_record) left out."""
    archive = load(season)
    if archive is not None and {"home_id", "away_id"} <= set(archive.columns):
        archive = archive[~(archive["home_id"].astype(str).str.startswith("-")
                            | archive["away_id"].astype(str).str.startswith("-"))]
    return bet_record.moves(archive, _college.BET_MIN)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--score", action="store_true")
    args = p.parse_args()
    if not args.score:
        print(f"{len(capture())} predictions in the archive")
    frame = scored()
    if frame.empty:
        print("nothing to score yet")
    else:
        got = summary(frame)
        print(f"{got['games']} scored: winners {got['correct']}/{got['games']}, "
              f"margin MAE {got['margin_mae']:.2f}, book MAE {got['market_margin_mae']}")
