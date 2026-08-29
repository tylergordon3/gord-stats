"""
Team ratings by ridge regression — the baseline every later model must beat.

One number per team, chosen so that the difference between two teams' numbers,
plus home-field, best explains the margins actually played. That is adjusted
margin: beating a good team by three says more than beating a bad one by
thirty, and solving every team at once is what separates the two.

Two models, not one, because the two questions are almost unrelated — margin
and total correlate 0.09 over these twelve seasons:

  * `margin` = rating(home) - rating(away) + home field. Each team gets one
    column, +1 when home and -1 when away, so a rating is a single strength.
  * `total`  = pace(home) + pace(away) + a constant. Both columns are +1: a
    team contributes the same to the shootout whichever sideline it is on.

Scores come back out as home = (total + margin) / 2, away = (total - margin) / 2.
Predicting the two scores directly instead would fight the data: raw scores are
skewed, bounded below, and correlated with each other, while these two are
close to normal and close to independent.

Three deliberate choices:

  * **Ridge, not least squares.** With 130-odd teams and a schedule where
    nobody plays most of the league, plain regression happily hands an
    undefeated team from a weak conference an enormous rating. The penalty
    pulls every rating toward the league average, and the less evidence there
    is the harder it pulls.
  * **Home field is not penalised.** It is a real constant to be measured, not
    a team effect to be shrunk. Shrinking it would bleed home advantage into
    the ratings of whoever happened to play at home more.
  * **Games decay with age.** A half-life in days does the work a "preseason
    prior" would otherwise need: in week one nearly all the evidence is last
    season's, by November it is mostly this season's, and nothing has to
    switch over on a particular date.
"""
import numpy as np
import pandas as pd

from cfb.games import FCS

# Grid-searched walk-forward on 2015-2019 only, then frozen before 2020-2025 was
# ever scored (cfb.backtest --tune). Both optima are interior and both basins are
# flat — margin moves 0.2 RMSE across the whole neighbourhood, the total 0.03 —
# so these are a sensible middle rather than a knife edge.
DEFAULT_ALPHA = 0.25           # ridge penalty on team ratings
DEFAULT_HALF_LIFE = 180.0      # days: about half a season
# The total wants more shrinkage than the margin. How good a team is separates
# them sharply; how many points they play to barely separates them at all, so
# the evidence for a pace of its own has to be strong before it is believed.
DEFAULT_TOTAL_ALPHA = 4.0
DEFAULT_TOTAL_HALF_LIFE = 180.0


def _weights(dates: pd.Series, asof: pd.Timestamp, half_life: float) -> np.ndarray:
    age = (asof - dates).dt.total_seconds().to_numpy() / 86400.0
    return np.power(0.5, np.clip(age, 0.0, None) / half_life)


def _solve(X: np.ndarray, y: np.ndarray, w: np.ndarray, penalty: np.ndarray):
    """Weighted ridge, with a per-column penalty so some columns go unpenalised."""
    Xw = X * w[:, None]
    return np.linalg.solve(X.T @ Xw + np.diag(penalty), Xw.T @ y)


class Ratings:
    """Fitted margin and total models, and the scores they imply."""

    def __init__(self, teams, margin_coef, hfa, total_coef, total_base,
                 asof, n_games):
        self.teams = list(teams)
        self._index = {t: i for i, t in enumerate(self.teams)}
        self.margin_coef = margin_coef
        self.hfa = float(hfa)
        self.total_coef = total_coef
        self.total_base = float(total_base)
        self.asof = asof
        self.n_games = int(n_games)

    def rating(self, team: str) -> float:
        """Points better than an average team. Unknown teams rate as FCS."""
        i = self._index.get(team, self._index.get(FCS))
        return 0.0 if i is None else float(self.margin_coef[i])

    def pace(self, team: str) -> float:
        i = self._index.get(team, self._index.get(FCS))
        return 0.0 if i is None else float(self.total_coef[i])

    def table(self) -> pd.DataFrame:
        return (pd.DataFrame({"team": self.teams, "rating": self.margin_coef,
                              "pace": self.total_coef})
                .sort_values("rating", ascending=False).reset_index(drop=True))

    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Predicted margin, total and both scores for each row given."""
        home = frame["home_team"].map(self.rating).to_numpy(float)
        away = frame["away_team"].map(self.rating).to_numpy(float)
        edge = np.where(frame["neutral"].to_numpy(bool), 0.0, self.hfa)
        margin = home - away + edge

        total = (self.total_base
                 + frame["home_team"].map(self.pace).to_numpy(float)
                 + frame["away_team"].map(self.pace).to_numpy(float))
        return pd.DataFrame({
            "pred_margin": margin,
            "pred_total": total,
            "pred_home": (total + margin) / 2.0,
            "pred_away": (total - margin) / 2.0,
        }, index=frame.index)


def fit(games: pd.DataFrame, asof: pd.Timestamp = None,
        alpha: float = DEFAULT_ALPHA, half_life: float = DEFAULT_HALF_LIFE,
        total_alpha: float = DEFAULT_TOTAL_ALPHA,
        total_half_life: float = DEFAULT_TOTAL_HALF_LIFE) -> Ratings:
    """Fit both models on every game in `games`, weighted by age at `asof`."""
    if games.empty:
        raise ValueError("no games to fit on")
    asof = asof if asof is not None else games["date"].max()

    teams = sorted(set(games["home_team"]) | set(games["away_team"]))
    index = {t: i for i, t in enumerate(teams)}
    n, k = len(games), len(teams)

    home_i = games["home_team"].map(index).to_numpy()
    away_i = games["away_team"].map(index).to_numpy()
    rows = np.arange(n)

    # margin: +1 home, -1 away, plus an unpenalised home-field column
    Xm = np.zeros((n, k + 1))
    Xm[rows, home_i] += 1.0
    Xm[rows, away_i] -= 1.0
    Xm[:, k] = np.where(games["neutral"].to_numpy(bool), 0.0, 1.0)
    pen_m = np.append(np.full(k, alpha), 0.0)

    # total: +1 for both teams, plus an unpenalised constant
    Xt = np.zeros((n, k + 1))
    Xt[rows, home_i] += 1.0
    Xt[rows, away_i] += 1.0
    Xt[:, k] = 1.0
    pen_t = np.append(np.full(k, total_alpha), 0.0)

    wm = _weights(games["date"], asof, half_life)
    wt = _weights(games["date"], asof, total_half_life)

    bm = _solve(Xm, games["margin"].to_numpy(float), wm, pen_m)
    bt = _solve(Xt, games["total"].to_numpy(float), wt, pen_t)
    return Ratings(teams, bm[:k], bm[k], bt[:k], bt[k], asof, n)
