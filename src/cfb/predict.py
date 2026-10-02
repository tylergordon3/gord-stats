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

The ratings' margins are then corrected by opponent-adjusted efficiency - EPA,
success rate and the rest from CFBD's box scores (cfb.efficiency) - worth a
tenth of a point of margin error on 2020-2025. A team's rating is on that
corrected scale.

    python -m cfb.predict                # this week
    python -m cfb.predict --week 3
"""
import json

import numpy as np
import pandas as pd
from scipy.stats import norm

from cfb import efficiency, espn, games as games_mod, ratings as ratings_mod
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


def floor_scores(out: pd.DataFrame) -> pd.DataFrame:
    """No team scores below zero; the arithmetic does not know that.

    Margin and total are modelled separately, and in a fifty-point mismatch
    (total + margin) / 2 and its mirror hand the underdog a negative score --
    which reached a team page as "49 to -2" before this existed. The margin is
    the modelled quantity and is kept; the total gives way, which amounts to
    saying that if the underdog cannot score below zero then the total must be
    at least the margin.

    Deliberately not inside `ratings.Ratings.predict`: the backtest scores the
    model's own `pred_total`, and flooring it there would quietly change the
    accuracy the site publishes.
    """
    out = out.copy()
    for low, high in (("pred_away", "pred_home"), ("pred_home", "pred_away")):
        under = out[low] < 0
        if under.any():
            out.loc[under, high] = out.loc[under, "pred_margin"].abs()
            out.loc[under, low] = 0.0
    out["pred_total"] = out["pred_home"] + out["pred_away"]
    return out


def _current_season_games() -> pd.DataFrame:
    """This season's finished games, shaped like the historical archive."""
    schedule = espn.schedule()
    if schedule.empty or "home_id" not in schedule.columns:
        return pd.DataFrame()
    # Regular season only, as the archive it extends: bowls and the CFP are a
    # different game to model (layoffs, opt-outs) - see cfb.games. And no 0-0
    # "finals": ESPN files a cancelled game that way, and one would have
    # trained as a scoreless tie.
    played = schedule[(schedule["state"] == "post")
                      & schedule["home_score"].notna()
                      & schedule["away_score"].notna()
                      & ~cancelled(schedule)
                      & (schedule["week"] != espn.POSTSEASON_WEEK)].copy()
    if played.empty:
        return pd.DataFrame()
    played["season"] = SEASON
    return played


def cancelled(schedule: pd.DataFrame) -> pd.Series:
    """Games ESPN has closed without playing them.

    A cancelled or postponed game is filed as state=post with a 0-0 score
    (CFB has had no ties since 1996) or a status that says so, and a
    rescheduled meeting is a separate event - so one of these left in the
    schedule is a game simulated, projected and priced that nobody will play,
    and the replay counted a second time. The same test as
    cfb.site.schedule._abandoned and cfb.site.previews._played.
    """
    post = schedule["state"] == "post"
    scoreless = schedule["home_score"].fillna(0) + schedule["away_score"].fillna(0) <= 0
    detail = (schedule["detail"] if "detail" in schedule
              else pd.Series("", index=schedule.index))
    said = detail.fillna("").astype(str).str.contains("Cancel|Postpon")
    return post & (scoreless | said)


def _placeholder(ids: pd.Series) -> pd.Series:
    """ESPN's stand-in ids for a side not yet decided (-1, -2, ...)."""
    return ids.astype(str).str.startswith("-")


def history() -> tuple:
    """(games to fit on, this season's schedule, id -> name).

    Loaded without the archive's per-season pooling, because this decides
    membership on its own terms a few lines down and paying for a
    classification only to overwrite every row of it is wasted work.
    """
    past = games_mod.load(classify=False)
    current = _current_season_games()

    frame = pd.concat([past, current], ignore_index=True) if not current.empty else past
    frame = frame.copy()
    if "date" not in frame.columns or frame["date"].isna().any():
        frame["date"] = pd.to_datetime(frame["date_utc"], format="ISO8601", utc=True)
    frame["margin"] = frame["home_score"] - frame["away_score"]
    frame["total"] = frame["home_score"] + frame["away_score"]

    schedule = espn.schedule().copy()
    schedule["date"] = pd.to_datetime(schedule["date_utc"], format="ISO8601", utc=True)
    # A game whose teams are not decided yet - every bowl until the pairings,
    # each conference title game until its last Saturday - is filed with
    # placeholder ids (-1, -2, named TBD). There is nothing to predict, and
    # counted here TBD would even pass for an FBS team with forty games.
    schedule = schedule[~(_placeholder(schedule["home_id"])
                          | _placeholder(schedule["away_id"]))]

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

    # A game called off is not a game still to play: out of everything built
    # on this schedule (the playoff simulation, team pages' projected records,
    # the fantasy weeks), after it has counted towards membership above - a
    # school's schedule says it is FBS whether or not a storm cancelled one
    # Saturday of it.
    schedule = schedule[~cancelled(schedule)]
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
    # The margins corrected by how each side has been playing, not only what
    # it has scored (cfb.efficiency) - as of the same moment.
    model = efficiency.corrected(model, frame, upcoming["date"].min())
    preds = model.predict(upcoming)

    # Carry the ESPN team ids: names are for reading, ids are what joins to the
    # betting board without arguing about how a school spells itself.
    carry = ["week", "game_id", "date", "time_valid", "home", "away", "neutral",
             "home_id", "away_id", "home_rank", "away_rank", "tv", "venue", "place", "note"]
    out = upcoming[[c for c in carry if c in upcoming.columns]].join(preds)
    out["home_rating"] = upcoming["home_team"].map(model.rating)
    out["away_rating"] = upcoming["away_team"].map(model.rating)
    out = floor_scores(out)
    out["home_win_prob"] = norm.cdf(out["pred_margin"] / margin_sd())
    # Sportsbook convention: a favourite is quoted negative.
    out["spread"] = -out["pred_margin"]
    return out.sort_values("date").reset_index(drop=True)


def season(asof: pd.Timestamp = None) -> pd.DataFrame:
    """Every game of the season: played ones with their result, the rest predicted.

    One fit and one pass, rather than a fit per week, because a team page wants
    the whole schedule and there is no reason for the rating behind week three
    to differ from the rating behind week ten when both are being shown today.
    A cancelled or postponed game is in neither half: `history` has dropped it.
    """
    frame, schedule, names = history()
    asof = asof if asof is not None else pd.Timestamp.now(tz="UTC")

    played = schedule["state"] == "post"
    real = played & (schedule["home_score"].fillna(0) + schedule["away_score"].fillna(0) > 0)

    train = frame[frame["date"] < asof]
    model = efficiency.corrected(ratings_mod.fit(train, asof=asof), frame, asof)
    preds = model.predict(schedule)

    out = floor_scores(schedule.copy().join(preds))
    out["played"] = real
    out["home_rating"] = schedule["home_team"].map(model.rating)
    out["away_rating"] = schedule["away_team"].map(model.rating)
    out["home_win_prob"] = norm.cdf(out["pred_margin"] / margin_sd())
    out["actual_margin"] = np.where(real, out["home_score"] - out["away_score"], np.nan)
    return out.sort_values("date").reset_index(drop=True), model, names


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
