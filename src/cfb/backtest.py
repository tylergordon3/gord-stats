"""
Walk-forward evaluation — the only honest way to score a ratings model.

For every week of every season: fit on games that had finished before that
week's first kickoff, predict the week, keep the predictions, move on. Never a
random train/test split. Team ratings carry the whole season inside them, so a
random split lets a team's November form set its September rating and reports
an accuracy the model could never have had on the day.

What counts as good is worth knowing before reading any number below:

    always pick the home team      ~19-20 points of margin RMSE
    plain team ratings             ~15-16
    a genuinely good model         ~13.5-14
    the closing spread             ~13.0-13.5

The spread is the practical ceiling and beating it is essentially not a thing.
The target is to get near it without using it.

    python -m cfb.backtest --tune
    python -m cfb.backtest
"""
import json

import numpy as np
import pandas as pd

from cfb import efficiency, fcs
from cfb import games as games_mod
from cfb import ratings as ratings_mod

MIN_TRAIN_GAMES = 400


def walk_forward(games: pd.DataFrame, first: int, last: int,
                 alpha: float = None, half_life: float = None,
                 total_alpha: float = None, total_half_life: float = None,
                 fcs_rows: pd.DataFrame = None) -> pd.DataFrame:
    """Predict every week of `first`..`last` from what was known beforehand.

    The margin and total models are tuned apart, because they want different
    things: strength is a recent, lightly-shrunk quantity, while how many
    points a team plays to is steadier and wants a longer memory.

    With `fcs_rows` (cfb.fcs.load()) the FCS's own games join every fit and
    teams are pulled toward their conferences - the model cfb.predict uses -
    with each season's FBS and FCS membership as that season had it.
    """
    alpha = ratings_mod.DEFAULT_ALPHA if alpha is None else alpha
    half_life = ratings_mod.DEFAULT_HALF_LIFE if half_life is None else half_life
    total_alpha = ratings_mod.DEFAULT_TOTAL_ALPHA if total_alpha is None else total_alpha
    total_half_life = (ratings_mod.DEFAULT_TOTAL_HALF_LIFE
                       if total_half_life is None else total_half_life)

    structured = fcs_rows is not None and not fcs_rows.empty
    history = fcs.conference_history(games, fcs_rows) if structured else {}

    out = []
    for season in range(first, last + 1):
        target_season = games[games["season"] == season]
        fbs_conf = fcs.fbs_conferences(games, season, history) if structured else {}
        for week in sorted(target_season["week"].unique()):
            target = target_season[target_season["week"] == week]
            asof = target["date"].min()
            train = games[games["date"] < asof]
            if len(train) < MIN_TRAIN_GAMES:
                continue
            knobs = {"alpha": alpha, "half_life": half_life, "total_alpha": total_alpha,
                     "total_half_life": total_half_life}
            prepared = (fcs.prepare(train, asof, fbs_conf, season, rows=fcs_rows)
                        if structured else None)
            if prepared is None:
                model = ratings_mod.fit(train, asof=asof, **knobs)
            else:
                fit_on, levels, divisions = prepared
                model = ratings_mod.fit(fit_on, asof=asof, levels=levels,
                                        divisions=divisions, **knobs)
            preds = model.predict(target)
            out.append(target[["season", "week", "date", "home_team", "away_team",
                               "home", "away", "neutral", "margin", "total"]]
                       .join(preds))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def fbs_only(preds: pd.DataFrame) -> pd.DataFrame:
    """Drop games against the pooled FCS side.

    They stay in training, where a 49-point win over an FCS team is real
    evidence about schedule strength. They come out of scoring, because their
    margins are wild in a way nobody is trying to predict and leaving them in
    flatters or punishes a model for the wrong reason.
    """
    return preds[(preds["home_team"] != games_mod.FCS)
                 & (preds["away_team"] != games_mod.FCS)]


def score(preds: pd.DataFrame) -> dict:
    """Headline accuracy, plus the baselines that say whether it is any good."""
    err = preds["pred_margin"] - preds["margin"]
    decided = preds[preds["margin"] != 0]
    right = ((decided["pred_margin"] > 0) == (decided["margin"] > 0)).mean()

    # Baseline: home field only, no idea who is playing.
    flat = preds.loc[~preds["neutral"], "margin"]
    flat_err = flat.mean() - flat

    return {
        "games": len(preds),
        "margin_mae": float(err.abs().mean()),
        "margin_rmse": float(np.sqrt((err ** 2).mean())),
        "margin_sd": float(err.std()),
        "total_mae": float((preds["pred_total"] - preds["total"]).abs().mean()),
        "total_rmse": float(np.sqrt(((preds["pred_total"] - preds["total"]) ** 2).mean())),
        "winner_accuracy": float(right),
        "baseline_home_rmse": float(np.sqrt((flat_err ** 2).mean())),
    }


def tune(games: pd.DataFrame, first: int, last: int,
         alphas=(0.25, 0.5, 1, 2, 4), half_lives=(60, 90, 130, 180, 260)) -> pd.DataFrame:
    """Grid search on a development span, scored the same walk-forward way."""
    rows = []
    for alpha in alphas:
        for half_life in half_lives:
            preds = walk_forward(games, first, last, alpha=alpha, half_life=half_life)
            if preds.empty:
                continue
            result = score(fbs_only(preds))
            rows.append({"alpha": alpha, "half_life": half_life,
                         "margin_rmse": result["margin_rmse"],
                         "margin_mae": result["margin_mae"],
                         "total_rmse": result["total_rmse"],
                         "winner_accuracy": result["winner_accuracy"]})
            print(f"  alpha={alpha:>4} half_life={half_life:>5} -> "
                  f"margin RMSE {result['margin_rmse']:.3f}  "
                  f"total RMSE {result['total_rmse']:.3f}  "
                  f"winner {result['winner_accuracy']:.1%}", flush=True)
    return pd.DataFrame(rows).sort_values("margin_rmse").reset_index(drop=True)


def report(games: pd.DataFrame, dev=(2015, 2019), test=(2020, 2025)) -> dict:
    """Score the held-out span and write the record the site can quote.

    Kept as a committed file rather than recomputed on a page build, for the
    same reason the fantasy model's is: it is derived only from seasons that
    have finished, it takes minutes rather than milliseconds, and a number a
    page uses to describe its own accuracy should not quietly change.
    """
    # The ratings from the first season the correction can learn on, so every
    # test season has seasons behind it to fit the correction; each is then
    # corrected by a stack fitted only on the seasons before it.
    rows_fcs = fcs.load()
    base = walk_forward(games, efficiency.STACK_FIRST, test[1], fcs_rows=rows_fcs)
    rows = efficiency.walk_forward_features(games, base)
    alone = fbs_only(base[base["season"].between(*test)])
    fbs = fbs_only(efficiency.validate(rows, test))[base.columns]
    overall = score(fbs)
    market = _versus_market(games, fbs)
    ratings_alone = score(alone)

    seasons = []
    for season, block in fbs.groupby("season"):
        row = score(block)
        seasons.append({"season": int(season), "games": row["games"],
                        "margin_rmse": round(row["margin_rmse"], 3),
                        "margin_mae": round(row["margin_mae"], 3),
                        "total_rmse": round(row["total_rmse"], 3),
                        "winner_accuracy": round(row["winner_accuracy"], 4)})

    record = {
        "model": ("ridge team ratings, margin and total fitted separately; margins "
                  "corrected by opponent-adjusted efficiency (cfb.efficiency)"
                  + ("; the FCS's own games in the fit, each team pulled toward its "
                     "conference (cfb.fcs)" if not rows_fcs.empty else "")),
        "tuned_on": f"{dev[0]}-{dev[1]}",
        "scored_on": f"{test[0]}-{test[1]}",
        "scored_games": "FBS vs FBS only; FCS opponents train the ratings but are not scored",
        "fcs_games": bool(not rows_fcs.empty),
        "hyperparameters": {
            "alpha": ratings_mod.DEFAULT_ALPHA,
            "half_life_days": ratings_mod.DEFAULT_HALF_LIFE,
            "total_alpha": ratings_mod.DEFAULT_TOTAL_ALPHA,
            "total_half_life_days": ratings_mod.DEFAULT_TOTAL_HALF_LIFE,
        },
        "overall": {k: (round(v, 4) if isinstance(v, float) else v)
                    for k, v in overall.items()},
        "ratings_alone": {k: (round(v, 4) if isinstance(v, float) else v)
                          for k, v in ratings_alone.items()},
        "efficiency": {"half_life_days": efficiency.HALF_LIFE, "alpha": efficiency.ALPHA,
                       "stack": "refitted each season on every season before it, "
                                f"from {efficiency.STACK_FIRST}"},
        "by_season": seasons,
        "versus_market": market,
    }
    path = games_mod.DATA_DIR / "model_validation.json"
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    # The correction the site uses: every finished season, the same fit.
    efficiency.write_stack(rows, test[1], {
        "scored_on": record["scored_on"], "games": overall["games"],
        "margin_rmse": round(overall["margin_rmse"], 4),
        "ratings_alone_rmse": round(ratings_alone["margin_rmse"], 4),
        "winner_accuracy": round(overall["winner_accuracy"], 4)})
    return record


def _versus_market(games: pd.DataFrame, preds: pd.DataFrame) -> dict:
    """Score the same games against the closing line, where one exists.

    The market is the ceiling, not a rival: it prices every game with injury
    news, weather and the sharpest money available, and no ratings model built
    from final scores is going to systematically beat it. What this measures is
    how much of that the model recovers on its own -- and, in `ats_when_we_
    disagree`, whether the games where the two part company are ones the model
    knows something about or ones it has simply got wrong.
    """
    from cfb import lines as lines_mod
    board = lines_mod.load()
    if board.empty or "game_id" not in games.columns:
        return {}

    keyed = games[["season", "date", "home_team", "away_team", "game_id"]]
    joined = (preds.merge(keyed, on=["season", "date", "home_team", "away_team"], how="left")
              .merge(board[["game_id", "market_margin", "market_total",
                            "home_class", "away_class"]], on="game_id", how="left"))
    both = joined[joined["market_margin"].notna()
                  & (joined["home_class"] == "fbs") & (joined["away_class"] == "fbs")]
    if both.empty:
        return {}

    def rmse(a, b):
        return float(np.sqrt(((a - b) ** 2).mean()))

    edge = both["pred_margin"] - both["market_margin"]
    cover = both["margin"] - both["market_margin"]
    picked = both[edge.abs() >= 3]
    ats = ((picked["pred_margin"] - picked["market_margin"] > 0)
           == (picked["margin"] - picked["market_margin"] > 0)).mean()

    return {
        "games": len(both),
        "our_margin_rmse": round(rmse(both["pred_margin"], both["margin"]), 3),
        "market_margin_rmse": round(rmse(both["market_margin"], both["margin"]), 3),
        "our_total_rmse": round(rmse(both["pred_total"], both["total"]), 3),
        "gap_rmse": round(rmse(both["pred_margin"], both["margin"])
                          - rmse(both["market_margin"], both["margin"]), 3),
        "ats_when_we_disagree_by_3": round(float(ats), 4),
        "ats_sample": int(len(picked)),
        "break_even_at_minus_110": 0.5238,
        "verdict": ("Within a point of the closing line without using it, but the "
                    "disagreements are noise: below break-even against the spread, "
                    "and our error grows with the size of the disagreement while the "
                    "market's does not. No betting edge."),
    }


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--tune", action="store_true")
    p.add_argument("--report", action="store_true")
    p.add_argument("--dev-first", type=int, default=2015)
    p.add_argument("--dev-last", type=int, default=2019)
    p.add_argument("--test-first", type=int, default=2020)
    p.add_argument("--test-last", type=int, default=2025)
    args = p.parse_args()

    games = games_mod.load()
    if args.tune:
        print(f"tuning on {args.dev_first}-{args.dev_last} (development seasons)")
        grid = tune(games, args.dev_first, args.dev_last)
        print("\nbest by margin RMSE:")
        print(grid.head(8).to_string(index=False))
    elif args.report:
        record = report(games)
        print(json.dumps(record["overall"], indent=2))
        print("\nby season:")
        for row in record["by_season"]:
            print(f"  {row['season']}  n={row['games']:>4}  margin RMSE "
                  f"{row['margin_rmse']:>6.2f}  winner {row['winner_accuracy']:.1%}")
    else:
        preds = walk_forward(games, args.test_first, args.test_last, fcs_rows=fcs.load())
        for label, subset in (("all games", preds), ("FBS vs FBS", fbs_only(preds))):
            print(f"\n--- {label} ---")
            for k, v in score(subset).items():
                print(f"{k:>22}: {v:.4f}" if isinstance(v, float) else f"{k:>22}: {v}")
