"""
Predicted scores for games that have not been played.

`cfb.ratings` fits; `cfb.backtest` judges; this is the part that answers the
question anyone actually asks. It stitches the finished seasons on disk to
whatever the current one has produced so far, fits as of the moment it is
called, and reports a score, a win probability and a spread for every upcoming
game.

The win probability is not a second model. Walk-forward residuals on six
held-out seasons are close to normal with a standard deviation the backtest
measures, so the margin prediction plus that spread is a distribution, and the
probability is the part of it above zero. A single number with no error bar
would be the one thing on this site that claims more than it knows.

Early in the season this leans almost entirely on last year: at a 180-day
half-life a game from last November still carries about a third of the weight
of a game from last week, and nothing switches over on a particular date. It
is at its weakest in week one and gets better every Saturday.

    python -m cfb.predict                # this week
    python -m cfb.predict --week 3
"""
import json

import numpy as np
import pandas as pd
from scipy.stats import norm

from cfb import espn, games as games_mod, ratings as ratings_mod
from cfb.config import SEASON

WINDOW_DAYS = 7

_FALLBACK_SD = 16.17          # only if the validation record is missing


def margin_sd() -> float:
    """The spread of the model's own errors, read from its validation record.

    Measured walk-forward on held-out seasons, not assumed, and read rather
    than copied so the win probabilities cannot drift away from the backtest
    that justifies them.
    """
    path = games_mod.DATA_DIR / "model_validation.json"
    if not path.exists():
        return _FALLBACK_SD
    try:
        return float(json.loads(path.read_text())["overall"]["margin_sd"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return _FALLBACK_SD


def _current_season_games() -> pd.DataFrame:
    """This season's finished games, shaped like the historical archive."""
    schedule = espn.schedule()
    if schedule.empty or "home_id" not in schedule.columns:
        return pd.DataFrame()
    played = schedule[(schedule["state"] == "post")
                      & schedule["home_score"].notna()
                      & schedule["away_score"].notna()].copy()
    if played.empty:
        return pd.DataFrame()
    played["season"] = SEASON
    return played


def history(asof: pd.Timestamp = None) -> tuple:
    """(games to fit on, this season's schedule, id -> name)."""
    past = games_mod.load()
    current = _current_season_games()

    frame = pd.concat([past, current], ignore_index=True) if not current.empty else past
    frame = frame.copy()
    if "date" not in frame.columns or frame["date"].isna().any():
        frame["date"] = pd.to_datetime(frame["date_utc"], format="ISO8601", utc=True)
    frame["margin"] = frame["home_score"] - frame["away_score"]
    frame["total"] = frame["home_score"] + frame["away_score"]

    schedule = espn.schedule().copy()
    schedule["date"] = pd.to_datetime(schedule["date_utc"], format="ISO8601", utc=True)

    # Membership is this season's, applied to the whole archive -- deliberately
    # not the per-season identity `games.load` uses for the backtest.
    #
    # A team promoted this year has no FBS record, and the choice is between
    # rating it from the FCS football it did play and giving it the generic
    # pool. Measured against the book on this week's 42 games, its own record
    # wins: 7.03 points of mean error against 7.64, and it is the difference
    # between pricing North Dakota State -- a promoted FCS champion -- within
    # three points of the market and missing it by twenty-six.
    #
    # The cost is that the record was earned against opposition this archive
    # pools together, so a promoted team is rated optimistically. The backtest
    # is unaffected: it scores FBS against FBS, where nobody is in this state.
    counts = pd.concat([schedule["home_id"], schedule["away_id"]]).value_counts()
    this_year = set(counts[counts >= 8].index)

    for side in ("home", "away"):
        frame[f"{side}_team"] = frame[f"{side}_id"].where(
            frame[f"{side}_id"].isin(this_year), games_mod.FCS)
        schedule[f"{side}_team"] = schedule[f"{side}_id"].where(
            schedule[f"{side}_id"].isin(this_year), games_mod.FCS)

    names = games_mod.team_names(past)
    names.update(dict(zip(schedule["home_id"], schedule["home"])))
    names.update(dict(zip(schedule["away_id"], schedule["away"])))
    return frame.sort_values("date").reset_index(drop=True), schedule, names


def week(number: int = None, asof: pd.Timestamp = None) -> pd.DataFrame:
    """Predicted score, spread and win probability for one week's games."""
    frame, schedule, names = history()
    asof = asof if asof is not None else pd.Timestamp.now(tz="UTC")

    if number is not None:
        upcoming = schedule[schedule["week"] == number]
    else:
        # Not ESPN's week number. It folds the season-opening Week 0 slate into
        # week 1, so "week 1" spans ten days and a dozen teams appear in it
        # twice — fine as a label, useless as "the games coming up". A rolling
        # window is what anyone means by that.
        ahead = schedule[schedule["date"] >= asof]
        upcoming = ahead[ahead["date"] < asof + pd.Timedelta(days=WINDOW_DAYS)]
    if upcoming.empty:
        return pd.DataFrame()

    train = frame[frame["date"] < upcoming["date"].min()]
    model = ratings_mod.fit(train, asof=upcoming["date"].min())
    preds = model.predict(upcoming)

    # Carry the ESPN team ids: names are for reading, ids are what joins to the
    # betting board without arguing about how a school spells itself.
    carry = ["week", "date", "home", "away", "neutral", "home_id", "away_id",
             "home_rank", "away_rank", "tv", "venue", "place"]
    out = upcoming[[c for c in carry if c in upcoming.columns]].join(preds)
    out["home_rating"] = upcoming["home_team"].map(model.rating)
    out["away_rating"] = upcoming["away_team"].map(model.rating)
    # A team cannot score below zero. The margin and total models do not know
    # that, and in a 45-point mismatch the arithmetic hands the underdog four
    # points or fewer. Clipping keeps the margin, which is the modelled
    # quantity, and moves the total instead.
    floor = out["pred_away"] < 0
    out.loc[floor, "pred_home"] = out.loc[floor, "pred_margin"]
    out.loc[floor, "pred_away"] = 0.0
    out["pred_total"] = out["pred_home"] + out["pred_away"]

    out["home_win_prob"] = norm.cdf(out["pred_margin"] / margin_sd())
    # Sportsbook convention: a favourite is quoted negative.
    out["spread"] = -out["pred_margin"]
    return out.sort_values("date").reset_index(drop=True)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--week", type=int, default=None)
    args = p.parse_args()

    games = week(args.week)
    if games.empty:
        raise SystemExit("no upcoming games found")
    show = pd.DataFrame({
        "kick": games["date"].dt.strftime("%a %H:%MZ"),
        "matchup": games["away"] + " at " + games["home"],
        "score": (games["pred_away"].round(0).astype(int).astype(str) + "-"
                  + games["pred_home"].round(0).astype(int).astype(str)),
        "spread": games["spread"].round(1),
        "total": games["pred_total"].round(1),
        "home win": (games["home_win_prob"] * 100).round(0).astype(int).astype(str) + "%",
    })
    print(f"Week {int(games['week'].iloc[0])}, {len(games)} games\n")
    print(show.to_string(index=False))
