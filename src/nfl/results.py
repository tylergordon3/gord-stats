"""
The NFL model's record: every prediction archived before kickoff, graded
against the final - data/nfl/predictions/{season}.parquet, the college
archive's shape (cfb.results) with ESPN's book line beside each one.

    python -m nfl.results              # capture this week's board, then score
    python -m nfl.results --score
"""
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from cfb import results as _college
from nfl import games as games_mod, predict
from nfl.config import DATA_DIR, SEASON

PRED_DIR = DATA_DIR / "predictions"
_COLS = _college._COLS + ["seasontype"]


def season_path(season: int = SEASON):
    return PRED_DIR / f"{season}.parquet"


def capture(season: int = SEASON) -> pd.DataFrame:
    """Append every unplayed game's prediction to the archive."""
    board, _model, _names = predict.season()
    games = board[~board["played"]]
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
    PRED_DIR.mkdir(parents=True, exist_ok=True)
    path = season_path(season)
    if path.exists():
        fresh = pd.concat([pd.read_parquet(path), fresh], ignore_index=True)
    fresh["day"] = fresh["captured"].str[:10]
    fresh = fresh.drop_duplicates(subset=["game_id", "day"], keep="last")
    fresh.drop(columns="day").to_parquet(path, index=False)
    return fresh


def on_record(season: int = SEASON) -> pd.DataFrame:
    """The last prediction archived before each game's kickoff."""
    path = season_path(season)
    if not path.exists():
        return pd.DataFrame(columns=_COLS)
    archive = pd.read_parquet(path)
    for col in _COLS:
        if col not in archive.columns:
            archive[col] = np.nan
    archive["captured_at"] = pd.to_datetime(archive["captured"], utc=True, format="ISO8601")
    archive["kickoff"] = pd.to_datetime(archive["kickoff"], utc=True)
    before = archive[archive["captured_at"] < archive["kickoff"]]
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
