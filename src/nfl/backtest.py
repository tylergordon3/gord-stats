"""
Does the NFL model know anything? Walk-forward, the way cfb.backtest judges
the college one: every week of a season predicted from the games before it,
tuned on 2015-2019, scored once on 2020-2025, written to
data/nfl/model_validation.json for the page to quote.

Playoff rounds are numbered past the regular season (week 19 onward) so a
wild-card game is never grouped with September's week 1.

    python -m nfl.backtest             # score, write the record
    python -m nfl.backtest --tune      # grid search on the development span
"""
import json

import numpy as np
import pandas as pd

from cfb import backtest as _college
from nfl import games as games_mod
from nfl import ratings as ratings_mod

MIN_TRAIN_GAMES = 200


def frame() -> pd.DataFrame:
    games = games_mod.load()
    games = games.copy()
    games["week"] = games["week"] + np.where(games["seasontype"] == 3, games_mod.REGULAR_WEEKS, 0)
    return games


def walk_forward(games: pd.DataFrame, first: int, last: int, **knobs) -> pd.DataFrame:
    knobs = {"alpha": ratings_mod.DEFAULT_ALPHA, "half_life": ratings_mod.DEFAULT_HALF_LIFE,
             "total_alpha": ratings_mod.DEFAULT_TOTAL_ALPHA,
             "total_half_life": ratings_mod.DEFAULT_TOTAL_HALF_LIFE, **knobs}
    _college.MIN_TRAIN_GAMES = MIN_TRAIN_GAMES
    return _college.walk_forward(games, first, last, **knobs)


score = _college.score


def tune(games: pd.DataFrame, first: int = 2015, last: int = 2019) -> pd.DataFrame:
    rows = []
    for alpha in (0.5, 1, 2, 4, 8):
        for half_life in (90, 130, 180, 260, 365):
            preds = walk_forward(games, first, last, alpha=alpha, half_life=half_life)
            got = score(preds)
            rows.append({"alpha": alpha, "half_life": half_life, **got})
            print(f"  alpha={alpha:>4} half_life={half_life:>4} -> margin RMSE "
                  f"{got['margin_rmse']:.3f}  winner {got['winner_accuracy']:.1%}", flush=True)
    print("total model:")
    for alpha in (2, 4, 8, 16):
        for half_life in (130, 180, 260, 365):
            preds = walk_forward(games, first, last, total_alpha=alpha, total_half_life=half_life)
            got = score(preds)
            rows.append({"total_alpha": alpha, "total_half_life": half_life, **got})
            print(f"  total_alpha={alpha:>4} half_life={half_life:>4} -> total RMSE "
                  f"{got['total_rmse']:.3f}", flush=True)
    return pd.DataFrame(rows)


def report(games: pd.DataFrame, dev=(2015, 2019), test=(2020, 2025)) -> dict:
    preds = walk_forward(games, test[0], test[1])
    overall = score(preds)
    seasons = []
    for season, block in preds.groupby("season"):
        row = score(block)
        seasons.append({"season": int(season), "games": row["games"],
                        "margin_rmse": round(row["margin_rmse"], 3),
                        "margin_mae": round(row["margin_mae"], 3),
                        "total_rmse": round(row["total_rmse"], 3),
                        "winner_accuracy": round(row["winner_accuracy"], 4)})
    record = {
        "model": "ridge team ratings, margin and total fitted separately (cfb.ratings)",
        "tuned_on": f"{dev[0]}-{dev[1]}",
        "scored_on": f"{test[0]}-{test[1]}",
        "scored_games": "every regular-season and playoff game",
        "hyperparameters": {
            "alpha": ratings_mod.DEFAULT_ALPHA,
            "half_life_days": ratings_mod.DEFAULT_HALF_LIFE,
            "total_alpha": ratings_mod.DEFAULT_TOTAL_ALPHA,
            "total_half_life_days": ratings_mod.DEFAULT_TOTAL_HALF_LIFE,
        },
        "overall": {k: (round(v, 4) if isinstance(v, float) else v)
                    for k, v in overall.items()},
        "by_season": seasons,
    }
    path = games_mod.DATA_DIR / "model_validation.json"
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--tune", action="store_true")
    args = p.parse_args()
    games = frame()
    if args.tune:
        print(tune(games).to_string(index=False))
    else:
        got = report(games)
        print(json.dumps(got["overall"], indent=2))
        print(pd.DataFrame(got["by_season"]).to_string(index=False))
