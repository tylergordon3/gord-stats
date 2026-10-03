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

Since 2026-10 the college model is fitted with the FCS's own games too
(cfb.fcs), every Division I team rated as itself, and the ridge pulls each
team toward its own conference's average rather than toward zero - an
unpenalised level per conference (`_fit_levels`). Called without divisions,
as the NFL calls it, the fit is exactly the plain one above.

Tried and not kept, 2026-10-03, walk-forward on 2016-2025 and 2026: a
half-life of 120, 150 or 240 days, a penalty of 0.125, 0.5 or 1.0, and an
extra discount on last season's games (x0.7, x0.85). The basin is flat - no
setting moved margin RMSE by more than 0.03 anywhere, and none was better on
every span by more than that (0.5 came closest, 0.01-0.03), so the frozen
knobs stay. The early-season gap to the book was the FCS, not the memory.
"""
import numpy as np
import pandas as pd
import scipy.sparse as sp

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

# The division an unlabelled team is in, and the near-zero penalty on the
# conference levels of the hierarchical fit (_fit_levels): enough to pin
# where zero is, nowhere near enough to shrink a level.
FBS = "fbs"
LEVEL_PENALTY = 1e-4


def _weights(dates: pd.Series, asof: pd.Timestamp, half_life: float) -> np.ndarray:
    age = (asof - dates).dt.total_seconds().to_numpy() / 86400.0
    return np.power(0.5, np.clip(age, 0.0, None) / half_life)


def _solve(X: np.ndarray, y: np.ndarray, w: np.ndarray, penalty: np.ndarray):
    """Weighted ridge, with a per-column penalty so some columns go unpenalised."""
    Xw = X * w[:, None]
    return np.linalg.solve(X.T @ Xw + np.diag(penalty), Xw.T @ y)


class Ratings:
    """Fitted margin and total models, and the scores they imply.

    Fitted with divisions (`fit(..., divisions=)`, cfb.fcs), the model also
    rates every FCS team as itself. Those ratings price the games they play
    in - `predict` reads an FCS side's ESPN id (`home_id`/`away_id`) where the
    frame names it only as FCS - but they are not in `teams`, which stays the
    FBS and one generic FCS opponent (the FCS teams' average), so a ranking or
    a simulation built on `teams` sees the same shape as ever. `sides` says
    which team the model will use for each row.
    """

    def __init__(self, teams, margin_coef, hfa, total_coef, total_base,
                 asof, n_games, divisions: dict = None):
        keys = list(teams)
        self._index = {t: i for i, t in enumerate(keys)}
        self.margin_coef = margin_coef
        self.hfa = float(hfa)
        self.total_coef = total_coef
        self.total_base = float(total_base)
        self.asof = asof
        self.n_games = int(n_games)
        # {key: "fbs" / "fcs" / "nond1"}; empty for a model fitted without.
        self.divisions = dict(divisions or {})
        self.teams = [t for t in keys
                      if t == FCS or self.divisions.get(t, FBS) == FBS]

    def rating(self, team: str) -> float:
        """Points better than an average team. Unknown teams rate as FCS."""
        i = self._index.get(team, self._index.get(FCS))
        return 0.0 if i is None else float(self.margin_coef[i])

    def pace(self, team: str) -> float:
        i = self._index.get(team, self._index.get(FCS))
        return 0.0 if i is None else float(self.total_coef[i])

    def table(self) -> pd.DataFrame:
        return (pd.DataFrame({"team": self.teams,
                              "rating": [self.rating(t) for t in self.teams],
                              "pace": [self.pace(t) for t in self.teams]})
                .sort_values("rating", ascending=False).reset_index(drop=True))

    def sides(self, frame: pd.DataFrame, side: str) -> pd.Series:
        """Who plays on one side, as the model knows them: the frame's team,
        or - where that is the generic FCS opponent - the FCS team itself,
        by its ESPN id, when it has a rating of its own."""
        teams = frame[f"{side}_team"]
        column = f"{side}_id"
        if not self.divisions or column not in frame.columns:
            return teams
        ids = frame[column].astype(str)
        own = (teams == FCS) & ids.isin(self._index)
        return teams.where(~own, ids)

    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Predicted margin, total and both scores for each row given."""
        home_side, away_side = self.sides(frame, "home"), self.sides(frame, "away")
        home = home_side.map(self.rating).to_numpy(float)
        away = away_side.map(self.rating).to_numpy(float)
        edge = np.where(frame["neutral"].to_numpy(bool), 0.0, self.hfa)
        margin = home - away + edge

        total = (self.total_base
                 + home_side.map(self.pace).to_numpy(float)
                 + away_side.map(self.pace).to_numpy(float))
        return pd.DataFrame({
            "pred_margin": margin,
            "pred_total": total,
            "pred_home": (total + margin) / 2.0,
            "pred_away": (total - margin) / 2.0,
        }, index=frame.index)


def fit(games: pd.DataFrame, asof: pd.Timestamp = None,
        alpha: float = DEFAULT_ALPHA, half_life: float = DEFAULT_HALF_LIFE,
        total_alpha: float = DEFAULT_TOTAL_ALPHA,
        total_half_life: float = DEFAULT_TOTAL_HALF_LIFE,
        levels: dict = None, divisions: dict = None) -> Ratings:
    """Fit both models on every game in `games`, weighted by age at `asof`.

    With `divisions` ({team: "fbs" / "fcs" / "nond1"}) and `levels` ({team:
    its conference}), the hierarchical fit `_fit_levels` (cfb.fcs prepares
    both); without, the plain one every other caller - the NFL included -
    has always had.
    """
    if games.empty:
        raise ValueError("no games to fit on")
    asof = asof if asof is not None else games["date"].max()
    if divisions:
        return _fit_levels(games, asof, alpha, half_life, total_alpha, total_half_life,
                           levels or {}, divisions)

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


def _sparse_solve(X, y: np.ndarray, w: np.ndarray, penalty: np.ndarray) -> np.ndarray:
    """`_solve` for a sparse design: a few nonzeros a row over a few hundred
    columns, where the dense matrix would be tens of megabytes a fit."""
    Xw = sp.csr_matrix(X.multiply(w[:, None]))
    lhs = (X.T @ Xw).toarray() + np.diag(penalty)
    return np.linalg.solve(lhs, np.asarray(Xw.T @ y).ravel())


def _fit_levels(games: pd.DataFrame, asof: pd.Timestamp, alpha: float, half_life: float,
                total_alpha: float, total_half_life: float, levels: dict,
                divisions: dict) -> Ratings:
    """Every team's rating as its conference's level plus its own shrunk
    difference from it.

    The levels go unpenalised (LEVEL_PENALTY only pins where zero is), so
    the ridge pulls a team toward its own conference rather than toward the
    whole field. With 130 FCS teams in the fit that is the difference between
    the FCS sitting ~30 points below the FBS and the penalty dragging the
    whole division up toward the middle by six or seven - one collective
    shift, paid for by every FCS team at once, on the strength of only the
    hundred-odd games a season the two divisions play each other. Measured
    on 2016-2025 (cfb.fcs), conferences rather than divisions alone were
    better in every one of the ten seasons.

    Ratings are re-centred so the average FBS team is zero, and a generic
    FCS opponent (FCS) - the FCS teams' average - is added for any caller
    that prices "an FCS team" without saying which.
    """
    teams = sorted(set(games["home_team"]) | set(games["away_team"]))
    index = {t: i for i, t in enumerate(teams)}
    division = {t: divisions.get(t, FBS) for t in teams}
    level = {t: levels.get(t, division[t]) for t in teams}
    level_names = sorted(set(level.values()))
    level_index = {name: i for i, name in enumerate(level_names)}
    n, k, q = len(games), len(teams), len(level_names)
    rows = np.arange(n)

    home = games["home_team"].to_numpy()
    away = games["away_team"].to_numpy()
    home_i = np.array([index[t] for t in home])
    away_i = np.array([index[t] for t in away])
    home_l = np.array([level_index[level[t]] for t in home])
    away_l = np.array([level_index[level[t]] for t in away])
    home_d = np.array([division[t] for t in home])
    away_d = np.array([division[t] for t in away])

    def design(entries, width):
        r, c, v = (np.concatenate(x) for x in zip(*entries))
        return sp.csr_matrix((v, (r, c)), shape=(n, width))

    ones = np.ones(n)
    # margin: team +1/-1, level +1/-1, home field
    Xm = design([(rows, home_i, ones), (rows, away_i, -ones),
                 (rows, k + home_l, ones), (rows, k + away_l, -ones),
                 (rows, np.full(n, k + q),
                  np.where(games["neutral"].to_numpy(bool), 0.0, 1.0))], k + q + 1)
    pen_m = np.concatenate([np.full(k, alpha), np.full(q, LEVEL_PENALTY), [0.0]])

    bm = _sparse_solve(Xm, games["margin"].to_numpy(float),
                       _weights(games["date"], asof, half_life), pen_m)
    rating = np.array([bm[i] + bm[k + level_index[level[t]]] for i, t in enumerate(teams)])
    fbs = np.array([division[t] == FBS for t in teams])
    if fbs.any():
        rating = rating - rating[fbs].mean()

    # total: as the plain fit has it - games with an FBS side, everyone else
    # one pooled opponent. How many points two FCS teams score against each
    # other says little about an FBS game; tried with every team's own pace
    # (and a term for mismatches), it was no better on 2016-2025 and worse on
    # 2026.
    pool = [t if division[t] == FBS else FCS for t in teams]
    keep = (home_d == FBS) | (away_d == FBS)
    tkeys = sorted(set(np.array(pool)[[index[t] for t in np.concatenate(
        [home[keep], away[keep]])]]) | {FCS})
    tindex = {t: i for i, t in enumerate(tkeys)}
    kt = len(tkeys)
    sub = games[keep]
    m = len(sub)
    trows = np.arange(m)
    th = np.array([tindex[pool[index[t]]] for t in sub["home_team"]])
    ta = np.array([tindex[pool[index[t]]] for t in sub["away_team"]])
    tones = np.ones(m)
    Xt = sp.csr_matrix((np.concatenate([tones, tones, tones]),
                        (np.concatenate([trows, trows, trows]),
                         np.concatenate([th, ta, np.full(m, kt)]))), shape=(m, kt + 1))
    pen_t = np.append(np.full(kt, total_alpha), 0.0)
    bt = _sparse_solve(Xt, sub["total"].to_numpy(float),
                       _weights(sub["date"], asof, total_half_life), pen_t)
    pace = np.array([bt[tindex[pool[i]]] if pool[i] in tindex else bt[tindex[FCS]]
                     for i in range(k)])

    divs = dict(division)
    if FCS not in index:
        fcs = np.array([division[t] == "fcs" for t in teams])
        teams = teams + [FCS]
        rating = np.append(rating, rating[fcs].mean() if fcs.any() else rating.min())
        pace = np.append(pace, bt[tindex[FCS]])
    divs[FCS] = "fcs"
    return Ratings(teams, rating, bm[k + q], pace, bt[kt], asof, n, divisions=divs)
