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

# The smallest disagreement that counts as a call. The schedule page shows a
# recommendation only once the model and the book differ by this much - below
# it the page says the model agrees with the book and names no side - so a
# record that counted those games would be scoring picks nobody was offered.
CALL_MIN = 0.5

# The disagreement worth treating as a bet, for the gated records. Agreeing
# with the book to within a field goal is not an edge worth pricing.
BET_MIN = 3

_COLS = ["captured", "season", "week", "game_id", "kickoff", "home_id", "away_id",
         "home", "away", "neutral", "pred_margin", "pred_total",
         "home_win_prob", "market_spread", "market_total"]


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
        board = board[["home_id", "away_id", "spread", "total"]].rename(
            columns={"spread": "market_spread", "total": "market_total"})
        games = games.merge(board, on=["home_id", "away_id"], how="left")
    else:
        games["market_spread"] = np.nan
        games["market_total"] = np.nan

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
        "market_total": games["market_total"].astype(float),
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
    # Rows captured before a column existed simply have not got it. Backfilling
    # here rather than at every use keeps `scored` free of column-presence
    # checks, and NaN is the honest value: we did not record it at the time.
    for col in _COLS:
        if col not in archive.columns:
            archive[col] = np.nan
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

    return grade(latest.merge(finals, on="game_id", how="inner"))


def grade(frame: pd.DataFrame) -> pd.DataFrame:
    """Every error and call on a frame of predictions joined to finals
    (pred_margin, pred_total, market_spread, market_total, actual_margin,
    actual_total, kickoff). Shared with the NFL archive, which is the same
    record for a different sport."""
    if frame.empty:
        return frame
    frame = frame.copy()
    frame["margin_error"] = frame["pred_margin"] - frame["actual_margin"]
    frame["total_error"] = frame["pred_total"] - frame["actual_total"]
    frame["correct"] = ((frame["pred_margin"] > 0) == (frame["actual_margin"] > 0))
    frame["market_error"] = -frame["market_spread"] - frame["actual_margin"]
    # The book's own winner: its favourite. A pick'em (spread of zero) names
    # nobody and stays out, as does a game the book never priced.
    book_pick = -frame["market_spread"]
    frame["book_correct"] = np.where(book_pick.isna() | (book_pick == 0), np.nan,
                                     (book_pick > 0) == (frame["actual_margin"] > 0))
    # Did the side we leaned toward cover the number the book put up?
    edge = frame["pred_margin"] - (-frame["market_spread"])
    cover = frame["actual_margin"] - (-frame["market_spread"])
    frame["beat_the_book"] = np.where(edge.abs() >= 3, (edge > 0) == (cover > 0), np.nan)

    # Over/under, scored the same way as the spread. Our total against the
    # book's: leaning over means predicting more points than the number, and
    # the pick is right if the game went the same way. A game that lands
    # exactly on the number is a push and is scored as neither - `np.nan`
    # rather than a loss, which is what a book would do with the bet.
    ou_edge = frame["pred_total"] - frame["market_total"]
    ou_result = frame["actual_total"] - frame["market_total"]
    frame["ou_edge"] = ou_edge
    frame["ou_pick"] = np.where(frame["market_total"].isna(), None,
                                np.where(ou_edge > 0, "over", "under"))
    # Two records, and they answer different questions.
    #
    # `ou_called` is the plain one: on every game where the book put up a
    # number, did our total land on the same side of it as the game did. No
    # threshold - a lean of a tenth of a point is still a lean, and the headline
    # figure should not quietly drop the games where we barely disagreed.
    #
    # `ou_correct` keeps the three-point gate, because a record you could have
    # bet is a different claim from a record you merely called, and agreeing
    # with the book to within a field goal is not a disagreement worth pricing.
    #
    # A game landing exactly on the number is out of both: that is a push, and
    # scoring it as a loss would understate the model.
    # `pred_total` in the isna() check is not belt and braces: without it a game
    # the model never priced compares NaN, which is false, and lands in the
    # record as a loss rather than staying out of it.
    no_call = (frame["market_total"].isna() | frame["pred_total"].isna()
               | (ou_result == 0) | (ou_edge.abs() < CALL_MIN))
    frame["ou_called"] = np.where(no_call, np.nan, (ou_edge > 0) == (ou_result > 0))
    frame["ou_correct"] = np.where(
        no_call | (ou_edge.abs() < BET_MIN), np.nan, (ou_edge > 0) == (ou_result > 0))
    frame["market_total_error"] = frame["market_total"] - frame["actual_total"]
    return frame.sort_values("kickoff").reset_index(drop=True)


def summary(frame: pd.DataFrame) -> dict:
    """Headline figures for a set of scored games."""
    if frame.empty:
        return {}
    priced = frame.dropna(subset=["market_spread"])
    totals_priced = frame.dropna(subset=["market_total"])
    ats = frame["beat_the_book"].dropna()
    ou = frame["ou_correct"].dropna()
    ou_all = frame["ou_called"].dropna()
    book = frame["book_correct"].dropna()
    return {
        "games": len(frame),
        "correct": int(frame["correct"].sum()),
        "winner_accuracy": float(frame["correct"].mean()),
        # The book's favourite on the games it named one in, and our winner
        # on those same games - the like-for-like comparison.
        "book_games": int(len(book)),
        "book_correct": int(book.sum()) if len(book) else 0,
        "correct_on_book_games": int(frame.loc[book.index, "correct"].sum()) if len(book) else 0,
        "margin_mae": float(frame["margin_error"].abs().mean()),
        "margin_rmse": float(np.sqrt((frame["margin_error"] ** 2).mean())),
        "total_mae": float(frame["total_error"].abs().mean()),
        "market_margin_mae": (float(priced["market_error"].abs().mean())
                              if len(priced) else None),
        "ats_games": int(len(ats)),
        "ats_wins": int(ats.sum()) if len(ats) else 0,
        # The same three figures for the total: how often our lean beat the
        # book's number, and how the two sides compare on raw error.
        "ou_games": int(len(ou)),
        "ou_wins": int(ou.sum()) if len(ou) else 0,
        "ou_all_games": int(len(ou_all)),
        "ou_all_wins": int(ou_all.sum()) if len(ou_all) else 0,
        "market_total_mae": (float(totals_priced["market_total_error"].abs().mean())
                             if len(totals_priced) else None),
        "totals_priced": int(len(totals_priced)),
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
    print(f"  total    MAE {result['total_mae']:.2f}", end="")
    if result["market_total_mae"] is not None:
        print(f"  (the book {result['market_total_mae']:.2f}"
              f" on {result['totals_priced']})", end="")
    print()
    if result["ou_all_games"]:
        print(f"  over/under called: {result['ou_all_wins']}/{result['ou_all_games']}"
              f" ({result['ou_all_wins'] / result['ou_all_games']:.0%})")
    if result["ou_games"]:
        print(f"  over/under where we differed by 3+: "
              f"{result['ou_wins']}/{result['ou_games']}")
