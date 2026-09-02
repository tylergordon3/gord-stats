"""
What the predictions were worth, once the games have been played.

The page can quote a backtest all it likes; a backtest is a claim about seasons
nobody watched. This scores the predictions this site actually published, which
is the only version a reader can check.

That requires archiving them *before* kickoff, because a prediction made after
a game is not a prediction. `capture()` appends the current board to
data/cfb/predictions/{season}.parquet with the moment it was taken, and
`scored()` keeps, for each game, the last capture stamped strictly earlier than
the kickoff it belongs to. Everything else is ignored -- including a capture
that landed mid-game, which is exactly the kind of thing that would flatter
these numbers without anyone noticing.

The market line captured alongside is scored the same way, so "we went 8 of 12"
always sits next to what the book managed on the same twelve games.

    python -m cfb.results              # capture, then report on what has finished
    python -m cfb.results --score      # report only
"""
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from cfb import espn, odds as odds_mod, predict
from cfb.config import DATA_DIR, SEASON

PRED_DIR = DATA_DIR / "predictions"

_COLS = ["captured", "season", "week", "game_id", "kickoff", "home_id", "away_id",
         "home", "away", "neutral", "pred_margin", "pred_total",
         "home_win_prob", "market_spread"]


def season_path(season: int = SEASON):
    return PRED_DIR / f"{season}.parquet"


def capture(season: int = SEASON) -> pd.DataFrame:
    """Append the current board to the archive. Returns what was added."""
    games = predict.week()
    if games.empty:
        return pd.DataFrame(columns=_COLS)

    board = odds_mod.latest(season)
    if not board.empty:
        # Rename before the merge, not after: `predict.week` already publishes a
        # `spread` of its own, and merging two of them silently yields
        # spread_x/spread_y and no column by either name.
        board = board[["home_id", "away_id", "spread"]].rename(
            columns={"spread": "market_spread"})
        games = games.merge(board, on=["home_id", "away_id"], how="left")
    else:
        games["market_spread"] = np.nan

    fresh = pd.DataFrame({
        "captured": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "season": season,
        "week": games["week"].astype(int),
        "game_id": games["game_id"].astype(str),
        "kickoff": games["date"],
        "home_id": games["home_id"].astype(str),
        "away_id": games["away_id"].astype(str),
        "home": games["home"], "away": games["away"],
        "neutral": games["neutral"].astype(bool),
        "pred_margin": games["pred_margin"].astype(float),
        "pred_total": games["pred_total"].astype(float),
        "home_win_prob": games["home_win_prob"].astype(float),
        "market_spread": games["market_spread"].astype(float),
    })

    PRED_DIR.mkdir(parents=True, exist_ok=True)
    path = season_path(season)
    if path.exists():
        fresh = pd.concat([pd.read_parquet(path), fresh], ignore_index=True)
    # One row per game per capture run; running twice in a day is not new data.
    fresh["day"] = fresh["captured"].str[:10]
    fresh = fresh.drop_duplicates(subset=["game_id", "day"], keep="last")
    fresh.drop(columns="day").to_parquet(path, index=False)
    return fresh


def _finals(season: int = SEASON) -> pd.DataFrame:
    """This season's finished games with their scores."""
    schedule = espn.schedule()
    if schedule.empty or "game_id" not in schedule.columns:
        return pd.DataFrame()
    done = schedule[(schedule["state"] == "post")
                    & schedule["home_score"].notna()
                    & schedule["away_score"].notna()]
    # A cancelled game is filed as 0-0 "post"; it was never played.
    done = done[(done["home_score"] > 0) | (done["away_score"] > 0)]
    return pd.DataFrame({
        "game_id": done["game_id"].astype(str),
        "actual_margin": done["home_score"] - done["away_score"],
        "actual_total": done["home_score"] + done["away_score"],
        "home_score": done["home_score"], "away_score": done["away_score"],
    })


def on_record(season: int = SEASON) -> pd.DataFrame:
    """The last prediction archived before each game's kickoff, one row a game.

    Nothing stamped after kickoff counts: a capture that landed mid-game would
    quietly improve every number on the page. This is what the schedule shows
    for a finished game - the line that was on record, not a refit after the
    fact - and what `scored` grades.
    """
    path = season_path(season)
    if not path.exists():
        return pd.DataFrame(columns=_COLS)
    archive = pd.read_parquet(path)
    if archive.empty:
        return pd.DataFrame(columns=_COLS)
    archive = archive.copy()
    archive["captured_at"] = pd.to_datetime(archive["captured"], utc=True, format="ISO8601")
    archive["kickoff"] = pd.to_datetime(archive["kickoff"], utc=True)
    before = archive[archive["captured_at"] < archive["kickoff"]]
    if before.empty:
        return pd.DataFrame(columns=_COLS)
    return (before.sort_values("captured_at")
            .drop_duplicates(subset="game_id", keep="last")
            .reset_index(drop=True))


def scored(season: int = SEASON) -> pd.DataFrame:
    """Every finished game we predicted beforehand, with the error we made."""
    latest = on_record(season)
    finals = _finals(season)
    if latest.empty or finals.empty:
        return pd.DataFrame()

    frame = latest.merge(finals, on="game_id", how="inner")
    if frame.empty:
        return frame

    frame["margin_error"] = frame["pred_margin"] - frame["actual_margin"]
    frame["total_error"] = frame["pred_total"] - frame["actual_total"]
    frame["correct"] = ((frame["pred_margin"] > 0) == (frame["actual_margin"] > 0))
    frame["market_error"] = -frame["market_spread"] - frame["actual_margin"]
    # Did the side we leaned toward cover the number the book put up?
    edge = frame["pred_margin"] - (-frame["market_spread"])
    cover = frame["actual_margin"] - (-frame["market_spread"])
    frame["beat_the_book"] = np.where(edge.abs() >= 3, (edge > 0) == (cover > 0), np.nan)
    return frame.sort_values("kickoff").reset_index(drop=True)


def summary(frame: pd.DataFrame) -> dict:
    """Headline figures for a set of scored games."""
    if frame.empty:
        return {}
    priced = frame.dropna(subset=["market_spread"])
    ats = frame["beat_the_book"].dropna()
    return {
        "games": len(frame),
        "correct": int(frame["correct"].sum()),
        "winner_accuracy": float(frame["correct"].mean()),
        "margin_mae": float(frame["margin_error"].abs().mean()),
        "margin_rmse": float(np.sqrt((frame["margin_error"] ** 2).mean())),
        "total_mae": float(frame["total_error"].abs().mean()),
        "market_margin_mae": (float(priced["market_error"].abs().mean())
                              if len(priced) else None),
        "ats_games": int(len(ats)),
        "ats_wins": int(ats.sum()) if len(ats) else 0,
    }


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--score", action="store_true", help="do not capture first")
    args = p.parse_args()

    if not args.score:
        added = capture()
        print(f"{len(added)} predictions in the archive")

    frame = scored()
    if frame.empty:
        print("nothing to score yet: no archived prediction has a finished game")
        raise SystemExit(0)
    result = summary(frame)
    print(f"\n{result['games']} games scored")
    print(f"  winners  {result['correct']}/{result['games']} "
          f"({result['winner_accuracy']:.0%})")
    print(f"  margin   MAE {result['margin_mae']:.2f}  RMSE {result['margin_rmse']:.2f}")
    if result["market_margin_mae"] is not None:
        print(f"  the book MAE {result['market_margin_mae']:.2f}")
    if result["ats_games"]:
        print(f"  against the spread where we differed by 3+: "
              f"{result['ats_wins']}/{result['ats_games']}")
