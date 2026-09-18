"""
NFL team ratings: the college ridge model (cfb.ratings) with its own knobs.

The model is the same one - a strength per team fitted to margins with an
unpenalised home field, a pace per team fitted to totals, games decaying by
age - because nothing about it is college-specific. What differs is the
data: thirty-two teams who all play each other's schedules, far more parity,
and a roster that turns over every March. So the shrinkage and the memory
are tuned here on 2015-2019 and frozen (nfl.backtest --tune), rather than
inherited from the college numbers.
"""
from cfb import ratings as _college

# Tuned walk-forward on 2015-2019, then frozen before 2020-2025 was scored.
# The margin basin is flat (13.07-13.16 RMSE across alpha 2-8, half-life
# 130-260), so these are its middle. Sixteen times the college shrinkage: with
# 32 teams who all play one another, the evidence for any one team's strength
# is a third of a college team's and the noise per game is the same. An extra
# per-season discount for roster turnover was tried and moved nothing (0.01).
DEFAULT_ALPHA = 4.0             # ridge penalty on team ratings
DEFAULT_HALF_LIFE = 180.0       # days
DEFAULT_TOTAL_ALPHA = 8.0
DEFAULT_TOTAL_HALF_LIFE = 180.0


def fit(games, asof=None, alpha=None, half_life=None, total_alpha=None,
        total_half_life=None) -> _college.Ratings:
    return _college.fit(
        games, asof=asof,
        alpha=DEFAULT_ALPHA if alpha is None else alpha,
        half_life=DEFAULT_HALF_LIFE if half_life is None else half_life,
        total_alpha=DEFAULT_TOTAL_ALPHA if total_alpha is None else total_alpha,
        total_half_life=DEFAULT_TOTAL_HALF_LIFE if total_half_life is None else total_half_life)
