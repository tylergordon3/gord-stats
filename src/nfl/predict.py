"""
Predicted scores for NFL games not yet played - nfl.ratings fitted as of now
on every game since 2014, this season's included.

The win probability is the margin prediction under the error spread the
backtest measured (data/nfl/model_validation.json), read rather than typed
so it cannot drift from the record that justifies it. Early in a season the
fit leans on last year; at a 180-day half-life a January playoff game still
carries most of its weight in September.

    python -m nfl.predict                # this week
    python -m nfl.predict --week 5
"""
import json

import numpy as np
import pandas as pd
from scipy.stats import norm

from nfl import games as games_mod
from nfl import ratings as ratings_mod
from nfl.config import DATA_DIR, SEASON

_FALLBACK_SD = 13.12


def margin_sd() -> float:
    path = DATA_DIR / "model_validation.json"
    try:
        return float(json.loads(path.read_text())["overall"]["margin_sd"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return _FALLBACK_SD


def history() -> tuple:
    """(every played game to fit on, this season's schedule, id -> (name, abbr))."""
    past = games_mod.load(last=SEASON - 1)
    schedule = games_mod._derive(games_mod.schedule())
    current = games_mod.played(schedule)
    frame = pd.concat([past, current], ignore_index=True).sort_values("date")
    names = games_mod.team_names(pd.concat([past, schedule], ignore_index=True))
    return frame.reset_index(drop=True), schedule.reset_index(drop=True), names


def current_week(schedule: pd.DataFrame, asof: pd.Timestamp = None) -> tuple:
    """(week, seasontype) of the first regular-season or playoff game that has
    not finished; the last one played once the season is over."""
    asof = asof if asof is not None else pd.Timestamp.now(tz="UTC")
    open_games = schedule[~schedule["completed"].astype(bool)]
    if open_games.empty:
        last = schedule.sort_values("date").iloc[-1]
        return int(last["week"]), int(last["seasontype"])
    first = open_games.sort_values("date").iloc[0]
    return int(first["week"]), int(first["seasontype"])


def season(asof: pd.Timestamp = None) -> tuple:
    """Every game of the season, played ones with their result, the rest
    predicted from one fit as of `asof`. Returns (frame, model, names)."""
    frame, schedule, names = history()
    asof = asof if asof is not None else pd.Timestamp.now(tz="UTC")
    train = frame[frame["date"] < asof]
    model = ratings_mod.fit(train, asof=asof)
    out = schedule.join(model.predict(schedule))
    out["played"] = out.index.isin(games_mod.played(schedule).index)
    out["home_rating"] = out["home_team"].map(model.rating)
    out["away_rating"] = out["away_team"].map(model.rating)
    out["home_win_prob"] = norm.cdf(out["pred_margin"] / margin_sd())
    out["pred_spread"] = -out["pred_margin"]           # book convention: favourite negative
    out["actual_margin"] = np.where(out["played"], out["margin"], np.nan)
    return out.sort_values("date").reset_index(drop=True), model, names


def week(number: int = None, seasontype: int = 2) -> pd.DataFrame:
    """One week's games with the prediction on each."""
    out, _model, _names = season()
    if number is None:
        number, seasontype = current_week(out)
    return out[(out["week"] == number) & (out["seasontype"] == seasontype)].reset_index(drop=True)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--week", type=int, default=None)
    args = p.parse_args()
    games = week(args.week)
    if games.empty:
        raise SystemExit("no games found")
    show = pd.DataFrame({
        "kick": games["date"].dt.strftime("%a %H:%MZ"),
        "matchup": games["away_abbr"] + " at " + games["home_abbr"],
        "score": (games["pred_away"].round(0).astype(int).astype(str) + "-"
                  + games["pred_home"].round(0).astype(int).astype(str)),
        "spread": games["pred_spread"].round(1), "book": games["book_spread"],
        "total": games["pred_total"].round(1), "book_total": games["book_total"],
        "home win": (games["home_win_prob"] * 100).round(0).astype(int).astype(str) + "%",
    })
    print(f"Week {int(games['week'].iloc[0])}, {len(games)} games\n")
    print(show.to_string(index=False))
