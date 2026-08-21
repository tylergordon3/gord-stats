"""
The projection model's report card, scored once and stored.

The power rankings page publishes how well its own model has done, which means
rebuilding that model for every past season and re-running the simulation
against what actually happened. That is six model fits and nine thousand
simulated seasons, and the answer only changes when a season ends — so
recomputing it every six hours on a Raspberry Pi, forever, to print the same
numbers, is work nobody needs done.

So it is computed once and written to data/fantasy/model_validation.json, which
is committed. Rebuild it when a season finishes:

    python -m fantasy.league.validation --refresh
"""
import argparse
import json
from datetime import date

import pandas as pd

from fantasy import paths, projections
from fantasy.config import LEAGUE_IDS, SEASON_YEAR


def compute() -> dict:
    """Score the model against every completed season the league has played."""
    from fantasy.league import power

    accuracy, backtest, spearman = [], {}, {}
    for season_str in LEAGUE_IDS:
        year = SEASON_YEAR[season_str]
        try:
            accuracy.extend(projections.accuracy(year).to_dict("records"))
        except Exception as exc:
            print(f"[validation] accuracy {season_str} skipped: {exc}")
        try:
            result = power.backtest(season_str, year)
        except Exception as exc:
            print(f"[validation] backtest {season_str} skipped: {exc}")
            continue
        spearman[season_str] = float(
            result["proj_points"].corr(result["PF"], method="spearman"))
        backtest[season_str] = result[
            ["manager", "proj_rank", "proj_points", "actual_rank", "PF", "total_wins"]
        ].to_dict("records")

    return {"built": date.today().isoformat(), "accuracy": accuracy,
            "backtest": backtest, "spearman": spearman}


def load(refresh: bool = False) -> dict:
    """The stored report card, computing it if missing or `refresh`."""
    if paths.VALIDATION_PATH.exists() and not refresh:
        return json.loads(paths.VALIDATION_PATH.read_text(encoding="utf-8"))

    scored = compute()
    paths.VALIDATION_PATH.parent.mkdir(parents=True, exist_ok=True)
    paths.VALIDATION_PATH.write_text(json.dumps(scored, indent=1), encoding="utf-8")
    print(f"[validation] -> {paths.VALIDATION_PATH}")
    return scored


def accuracy_frame(scored: dict) -> pd.DataFrame:
    return pd.DataFrame(scored.get("accuracy", []))


def backtest_frame(scored: dict, season_str: str) -> pd.DataFrame:
    return pd.DataFrame(scored.get("backtest", {}).get(season_str, []))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Score the projection model.")
    p.add_argument("--refresh", action="store_true", help="Recompute, don't read the cache.")
    scored = load(refresh=p.parse_args().refresh)
    print(json.dumps(scored["spearman"], indent=1))
