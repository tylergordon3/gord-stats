"""
Per-player point projections for an upcoming season, built without ADP.

The power rankings need a number for every drafted player, and the obvious
number — where the market drafted him — is exactly the one that would make the
rankings a restatement of the draft board. So nothing here reads ADP, auction
price, or any expert ranking. Three independent signals do the work:

  * Usage, not points.  Volume (targets, carries, air yards, target share,
    WOPR) is far more stable season to season than fantasy points are, because
    points carry touchdown luck and volume mostly does not. A ridge regression
    per position maps last season's per-game volume onto next season's per-game
    points. Trained on 2021-25 and scored on held-out 2024-25, that beats
    projecting last season's points forward: R^2 0.62 vs 0.59 for WR, 0.64 vs
    0.59 for TE, and it ties at RB. Quarterback is genuinely hard either way
    (R^2 0.13, heavily regularized), which is why the QB model shrinks hard.

  * NFL draft capital for rookies.  A rookie has no usage to read, so the prior
    comes from where the *NFL* drafted him — log(pick) against per-game points
    for every drafted skill rookie since 2021, R^2 0.38-0.45. This is a real
    signal and it is not fantasy ADP: it is 32 front offices spending picks.

  * Nothing at all for kickers and defenses.  Fitting the same model to K and
    DST gives a negative held-out R^2 — last season's kicker points do not
    predict this season's, at any amount of regularization. Rather than launder
    noise into a ranking, both positions get the positional mean, which makes a
    team's K and DST picks cancel out of its power ranking entirely. That is
    the honest answer, and it matches how these positions actually behave.

Everything is then shrunk toward replacement level by how much the player has
actually been seen, so a breakout on six games does not outrank a proven
starter on the strength of a small sample.

    python -m fantasy.projections            # build and print the top of the board
    python -m fantasy.projections --refresh  # re-pull the weekly points first

Output: one row per player with `mu` (points per game), `sd` (week-to-week
spread) and `avail` (share of weeks available), which is exactly the triple
`fantasy.league.power` samples from.
"""
import argparse

import numpy as np
import pandas as pd

from fantasy import paths
from fantasy.config import UPCOMING_YEAR
from fantasy.league import weekly_points
from fantasy.normalize import normalize_name

# Seasons of weekly points the model trains on. Five gives four year-over-year
# transitions to fit, which is the most the nflverse volume columns go back
# with a consistent definition.
TRAIN_WINDOW = 5


def train_seasons(year: int = UPCOMING_YEAR) -> list:
    return list(range(year - TRAIN_WINDOW, year))


TRAIN_SEASONS = train_seasons()

MODELLED = ["QB", "RB", "WR", "TE"]
FLAT = ["K", "DEF"]                       # no year-over-year signal; see module docstring
POSITIONS = MODELLED + FLAT

# Per-game volume columns fed to each position's model, plus last season's own
# points per game as one more feature (the model decides how much to lean on it).
FEATURES = {
    "QB": ["attempts", "passing_yards", "passing_tds", "carries", "rushing_yards",
           "rushing_tds", "ppg"],
    "RB": ["carries", "rushing_yards", "rushing_tds", "targets", "receptions",
           "receiving_yards", "receiving_tds", "target_share", "ppg"],
    "WR": ["targets", "receptions", "receiving_yards", "receiving_air_yards",
           "receiving_tds", "target_share", "air_yards_share", "wopr",
           "carries", "rushing_yards", "ppg"],
    "TE": ["targets", "receptions", "receiving_yards", "receiving_air_yards",
           "receiving_tds", "target_share", "air_yards_share", "wopr", "ppg"],
}

# Ridge penalty per position, chosen by held-out R^2 on 2024-25 (see the tuning
# note in the docstring). QB's is two orders of magnitude larger than the
# skill positions' because almost nothing about a quarterback's last season
# survives into his next one.
RIDGE_LAMBDA = {"QB": 100.0, "RB": 10.0, "WR": 1.0, "TE": 30.0}

# Games a player-season needs before it can train or be projected from.
MIN_GAMES = 6

# Roughly the last roster-worthy player at each position in a ten-team league
# (10 starters plus the bench that would realistically be started). A projection
# is shrunk toward the points per game at this positional rank, not toward zero:
# the alternative to any given player is the waiver wire, not nothing.
REPLACEMENT_RANK = {"QB": 14, "RB": 36, "WR": 44, "TE": 14, "K": 12, "DEF": 12}

# Weight on the model when a player's last season is two years old rather than
# one — someone who missed a whole year is a real projection, but a staler one.
STALE_WEIGHT = 0.65

# Weeks a healthy player can actually appear in: seventeen on the schedule,
# minus his bye. Dividing by 17 instead would charge every player for a bye the
# simulation already sits him down for separately, and cap even an iron man at
# 94% available.
GAMES_PER_SEASON = 16.0

# Pseudo-games of positional prior mixed into each player's availability rate,
# so one lost season does not brand a player permanently fragile.
AVAIL_PRIOR_GAMES = 17.0

# Rookie prior: points per game against log(NFL draft pick), fit per position.
ROOKIE_MIN_SEASON = 2021


# --------------------------------------------------------------------------- #
# Season aggregation
# --------------------------------------------------------------------------- #

_VOLUME = ["targets", "receptions", "receiving_yards", "receiving_air_yards",
           "receiving_tds", "carries", "rushing_yards", "rushing_tds",
           "attempts", "passing_yards", "passing_tds"]
_SHARES = ["target_share", "air_yards_share", "wopr"]


def season_table(weekly: pd.DataFrame) -> pd.DataFrame:
    """Collapse weekly points to one row per (season, player): rate stats + spread."""
    df = weekly.copy()
    for col in _VOLUME + _SHARES:
        df[col] = pd.to_numeric(df.get(col), errors="coerce").fillna(0.0)
    df["points"] = pd.to_numeric(df["fantasy_points_ppr"], errors="coerce").fillna(0.0)
    df = df[df["position"].isin(POSITIONS)]
    df = df[df["sleeper_id"].notna()]

    agg = df.groupby(["season", "sleeper_id", "position"], as_index=False).agg(
        games=("week", "count"),
        ppg=("points", "mean"),
        week_sd=("points", "std"),
        **{col: (col, "mean") for col in _VOLUME + _SHARES},
    )
    return agg


# --------------------------------------------------------------------------- #
# Ridge
# --------------------------------------------------------------------------- #

def _fit_ridge(X: np.ndarray, y: np.ndarray, lam: float) -> tuple:
    """Standardized ridge with an unpenalized intercept -> (center, scale, beta)."""
    center = X.mean(axis=0)
    scale = X.std(axis=0)
    scale[scale == 0] = 1.0
    Z = np.column_stack([np.ones(len(X)), (X - center) / scale])
    penalty = np.eye(Z.shape[1])
    penalty[0, 0] = 0.0                      # never penalize the intercept
    beta = np.linalg.solve(Z.T @ Z + lam * penalty, Z.T @ y)
    return center, scale, beta


def _apply_ridge(model, X: np.ndarray) -> np.ndarray:
    center, scale, beta = model
    return np.column_stack([np.ones(len(X)), (X - center) / scale]) @ beta


def _transitions(seasons: pd.DataFrame, pos: str) -> pd.DataFrame:
    """(season N features, season N+1 points per game) pairs for one position."""
    played = seasons[(seasons["position"] == pos) & (seasons["games"] >= MIN_GAMES)]
    later = played[["season", "sleeper_id", "ppg"]].copy()
    later["season"] -= 1                      # line season N+1 up against season N
    later = later.rename(columns={"ppg": "target"})
    return played.merge(later, on=["season", "sleeper_id"])


def fit_models(seasons: pd.DataFrame) -> tuple:
    """(models, residual sd) per modelled position.

    The residual sd matters as much as the fit does. A projection is a guess,
    and the simulation is only honest about a team's range of outcomes if it
    knows how wide the guess is — so the fit is scored on the last two seasons,
    held out, and the error it makes there becomes the uncertainty attached to
    every projection that position produces.
    """
    models, residual = {}, {}
    for pos in MODELLED:
        pairs = _transitions(seasons, pos).dropna(subset=FEATURES[pos] + ["target"])
        if len(pairs) < 40:
            continue                          # not enough history to fit; falls back to prior
        X = pairs[FEATURES[pos]].to_numpy(float)
        y = pairs["target"].to_numpy(float)

        holdout = pairs["season"] >= pairs["season"].max() - 1
        if holdout.sum() >= 15 and (~holdout).sum() >= 30:
            trained = _fit_ridge(X[~holdout], y[~holdout], RIDGE_LAMBDA[pos])
            errors = y[holdout] - _apply_ridge(trained, X[holdout])
            residual[pos] = float(np.sqrt((errors ** 2).mean()))
        else:
            residual[pos] = float(y.std())

        # The published model uses every pair, including the held-out ones.
        models[pos] = _fit_ridge(X, y, RIDGE_LAMBDA[pos])
    return models, residual


# --------------------------------------------------------------------------- #
# Priors: replacement level, spread, availability, rookies
# --------------------------------------------------------------------------- #

def replacement_levels(seasons: pd.DataFrame) -> dict:
    """Points per game of the last roster-worthy player at each position."""
    out = {}
    for pos, rank in REPLACEMENT_RANK.items():
        by_year = []
        for _, group in seasons[(seasons["position"] == pos)
                                & (seasons["games"] >= 8)].groupby("season"):
            ranked = group["ppg"].sort_values(ascending=False).to_numpy()
            if len(ranked):
                by_year.append(ranked[min(rank, len(ranked)) - 1])
        out[pos] = float(np.mean(by_year)) if by_year else 0.0
    return out


def _projected_replacement(board: pd.DataFrame) -> dict:
    """Points per game of the REPLACEMENT_RANK-th projected player per position."""
    out = {}
    for pos, rank in REPLACEMENT_RANK.items():
        ranked = board.loc[board["pos"] == pos, "mu"].sort_values(
            ascending=False).to_numpy()
        out[pos] = float(ranked[min(rank, len(ranked)) - 1]) if len(ranked) else 0.0
    return out


def spread_models(seasons: pd.DataFrame) -> dict:
    """Per position, weekly sd as a straight line in points per game.

    A player's own weekly sd is noisy on a short season, and every position has
    a strong mean-variance relationship (bigger scorers swing harder), so a thin
    sample is shrunk toward the line rather than trusted on its own.
    """
    out = {}
    for pos in POSITIONS:
        sample = seasons[(seasons["position"] == pos) & (seasons["games"] >= 8)]
        sample = sample.dropna(subset=["week_sd", "ppg"])
        if len(sample) < 20:
            out[pos] = (0.0, 0.6)
            continue
        slope, intercept = np.polyfit(sample["ppg"], sample["week_sd"], 1)
        out[pos] = (float(intercept), float(slope))
    return out


def _spread(pos: str, mu: float, own_sd, games, models: dict) -> float:
    intercept, slope = models.get(pos, (0.0, 0.6))
    fitted = max(1.0, intercept + slope * mu)
    if own_sd is None or not np.isfinite(own_sd) or not games:
        return fitted
    weight = min(1.0, games / 17.0)           # a full season earns full trust
    return float(weight * own_sd + (1 - weight) * fitted)


def availability(seasons: pd.DataFrame, year: int) -> pd.DataFrame:
    """Share of the season each player has been available for, recently.

    Counted over the three seasons before `year` and mixed with the positional
    base rate, so a single lost year moves a player but does not define him.
    """
    recent = seasons[seasons["season"] >= year - 3]
    played = recent.groupby(["sleeper_id", "position"], as_index=False).agg(
        games_played=("games", "sum"), seasons_seen=("season", "nunique"))
    played["rate"] = played["games_played"] / (GAMES_PER_SEASON * played["seasons_seen"])

    base = played.groupby("position")["rate"].mean().to_dict()
    prior = played["position"].map(base).fillna(0.85)
    weight = GAMES_PER_SEASON * played["seasons_seen"]
    played["avail"] = ((played["rate"] * weight + prior * AVAIL_PRIOR_GAMES)
                       / (weight + AVAIL_PRIOR_GAMES)).clip(0.4, 0.97)
    return played[["sleeper_id", "avail"]]


# Picks inside this range are the "top of the draft" bucket whose average sets
# the ceiling on the rookie prior.
ROOKIE_TOP_PICKS = 15


def rookie_curve(seasons: pd.DataFrame, draft: pd.DataFrame) -> dict:
    """Per position, (intercept, slope, ceiling, sd) of rookie ppg on log(pick).

    The ceiling is what stops the fit running away at the top. Almost every
    drafted skill player goes late, so the line is anchored by picks 100-250 and
    a straight extrapolation back to pick 3 predicts a better rookie season than
    any rookie has actually had — it had a top-three running back projected as
    the second-best back in football. Clipping at the average of the top fifteen
    picks keeps the prior inside the range of things that have happened.
    """
    debut = draft.merge(
        seasons.rename(columns={"season": "rookie_season", "position": "pos_played"}),
        left_on=["season", "sleeper_id"], right_on=["rookie_season", "sleeper_id"])
    out = {}
    for pos in MODELLED:
        sample = debut[(debut["pos_played"] == pos) & (debut["pick"] > 0)]
        if len(sample) < 25:
            continue
        picks = sample["pick"].to_numpy(float)
        ppg = sample["ppg"].to_numpy(float)
        slope, intercept = np.polyfit(np.log(picks), ppg, 1)
        top = ppg[picks <= ROOKIE_TOP_PICKS]
        ceiling = float(top.mean()) if len(top) else float(np.percentile(ppg, 95))
        residual = ppg - (intercept + slope * np.log(picks))
        out[pos] = (float(intercept), float(slope), ceiling,
                    float(residual.std()))
    return out


def draft_picks(year: int) -> pd.DataFrame:
    """NFL draft picks since ROOKIE_MIN_SEASON, joined to Sleeper ids by name.

    Matched on normalized name + position rather than gsis_id: a player drafted
    this spring who has not taken an NFL snap yet often has no gsis_id anywhere,
    and he is exactly the player the rookie prior exists for.
    """
    import nflreadpy as nfl

    picks = nfl.load_draft_picks().to_pandas()
    picks = picks[picks["season"].between(ROOKIE_MIN_SEASON, year)]
    picks = picks[picks["position"].isin(MODELLED)][
        ["season", "round", "pick", "position", "pfr_player_name"]].copy()
    picks["merge_name"] = picks["pfr_player_name"].map(normalize_name)

    sleeper = pd.read_parquet(paths.PLAYERS_DIR / "sleeper.parquet")
    sleeper = sleeper[["merge_name", "position", "sleeper_id"]].dropna()
    sleeper = sleeper.drop_duplicates(subset=["merge_name", "position"])

    merged = picks.merge(sleeper, on=["merge_name", "position"], how="left")
    return merged.dropna(subset=["sleeper_id"])


# --------------------------------------------------------------------------- #
# Assembling the board
# --------------------------------------------------------------------------- #

def _bye_weeks(year: int) -> dict:
    """{team: bye week} for a season, read off the schedule's missing weeks."""
    import nflreadpy as nfl

    sched = nfl.load_schedules([year]).to_pandas()
    sched = sched[sched["game_type"] == "REG"] if "game_type" in sched else sched
    played = pd.concat([
        sched[["week", "home_team"]].rename(columns={"home_team": "team"}),
        sched[["week", "away_team"]].rename(columns={"away_team": "team"}),
    ])
    played["team"] = played["team"].replace("LA", "LAR")
    byes = {}
    for team, group in played.groupby("team"):
        weeks = set(group["week"].astype(int))
        missing = [w for w in range(1, 15) if w not in weeks]
        byes[team] = missing[0] if missing else 0
    return byes


def _roster_frame(year: int, weekly: pd.DataFrame) -> pd.DataFrame:
    """Every player who could be drafted for `year`, on that year's rosters.

    Sleeper's player table is the live one, so it answers "who is on a team
    now" and nothing else. That is exactly right for the season being drafted
    and wrong for every past season: backtesting 2023 off it silently dropped
    a fifth of that draft class, because the players who have retired since are
    not on anybody's roster today and so had no projection to be measured by.

    So the table is the live one for the upcoming season, and last season's
    own weekly data — where a player's team is the team he actually played for
    — for any year already in the books. Either way anyone seen playing
    recently is carried over, so a name never falls off the board just because
    it has since fallen off a roster.
    """
    sleeper = pd.read_parquet(paths.PLAYERS_DIR / "sleeper.parquet")
    keep = sleeper["position"].isin(POSITIONS) & sleeper["team"].notna()
    live = sleeper[keep][["sleeper_id", "full_name", "position", "team",
                          "merge_name", "active"]].copy()
    live = live.rename(columns={"full_name": "player", "position": "pos"})
    live = live.drop_duplicates(subset=["sleeper_id"])

    # How each player was listed the last time he actually took the field.
    seen = weekly[weekly["season"] >= year - 2].dropna(subset=["sleeper_id"])
    seen = seen.sort_values(["season", "week"]).drop_duplicates(
        subset=["sleeper_id"], keep="last")
    seen = seen[["sleeper_id", "player_display_name", "position", "team"]].rename(
        columns={"player_display_name": "player", "position": "pos"})
    seen = seen[seen["pos"].isin(POSITIONS) & seen["team"].notna()].copy()
    seen["merge_name"] = seen["player"].map(normalize_name)
    seen["active"] = True

    if year >= UPCOMING_YEAR:
        # Live table wins on team and position; historical rows only fill gaps.
        extra = seen[~seen["sleeper_id"].isin(live["sleeper_id"])]
        return pd.concat([live, extra], ignore_index=True)

    # A past season: the team he played for beats the team he is on today.
    extra = live[~live["sleeper_id"].isin(seen["sleeper_id"])]
    return pd.concat([seen, extra], ignore_index=True)


def build(year: int = UPCOMING_YEAR, refresh: bool = False) -> pd.DataFrame:
    """Projected points per game, spread and availability for every player."""
    seasons_used = train_seasons(year)
    weekly = weekly_points.load(seasons_used, refresh=refresh)
    seasons = season_table(weekly)

    models, residual_sd = fit_models(seasons)
    spreads = spread_models(seasons)
    replacement = replacement_levels(seasons)
    avail = availability(seasons, year)

    picks = draft_picks(year)
    curve = rookie_curve(seasons, picks)
    rookies = picks[picks["season"] == year].drop_duplicates(subset=["sleeper_id"])

    board = _roster_frame(year, weekly)
    board = board.merge(avail, on="sleeper_id", how="left")

    # Most recent season of record for each player, and how stale it is.
    recent = seasons[seasons["games"] >= MIN_GAMES].sort_values("season")
    recent = recent.drop_duplicates(subset=["sleeper_id"], keep="last")
    board = board.merge(
        recent.rename(columns={"season": "last_season", "position": "last_pos"}),
        on="sleeper_id", how="left")

    rookie_pick = rookies.set_index("sleeper_id")["pick"].to_dict()

    mus, sds, ses, bases = [], [], [], []
    for row in board.itertuples(index=False):
        pos = row.pos
        floor = replacement.get(pos, 0.0)
        mu, basis = floor, "replacement"

        error = 0.0
        if pos in FLAT:
            # No signal exists here, so every kicker and defense is the same
            # kicker and defense. See the module docstring.
            same_pos = seasons[(seasons["position"] == pos) & (seasons["games"] >= 8)]
            mu = float(same_pos["ppg"].mean()) if len(same_pos) else floor
            basis = "positional mean"
        elif pos in models and pd.notna(row.last_season) and row.last_pos == pos:
            features = np.array([[getattr(row, col) for col in FEATURES[pos]]], float)
            if np.isfinite(features).all():
                predicted = float(_apply_ridge(models[pos], features)[0])
                # A season two years old still says something, just less.
                stale = STALE_WEIGHT if row.last_season < year - 1 else 1.0
                # And a six-game sample says less than a sixteen-game one.
                seen = min(1.0, float(row.games) / 14.0)
                weight = stale * seen
                mu = weight * predicted + (1 - weight) * floor
                error = residual_sd.get(pos, 0.0) * weight
                basis = "usage" if stale == 1.0 else "usage (stale)"

        if basis == "replacement" and row.sleeper_id in rookie_pick and pos in curve:
            intercept, slope, ceiling, spread = curve[pos]
            pick = max(1.0, float(rookie_pick[row.sleeper_id]))
            mu = float(np.clip(intercept + slope * np.log(pick), floor, ceiling))
            error = spread
            basis = "draft capital"

        mu = max(mu, 0.0)
        own_sd = row.week_sd if pd.notna(getattr(row, "week_sd", np.nan)) else None
        games = row.games if pd.notna(getattr(row, "games", np.nan)) else 0
        mus.append(mu)
        sds.append(_spread(pos, mu, own_sd, games, spreads))
        ses.append(error)
        bases.append(basis)

    board["mu"] = mus
    board["sd"] = sds
    board["mu_se"] = ses
    board["basis"] = bases
    board["avail"] = board["avail"].fillna(0.8)
    board["bye"] = board["team"].map(_bye_weeks(year)).fillna(0).astype(int)
    # Replacement level is re-read off the projections rather than off history.
    # The model deliberately compresses positions it cannot predict — most of
    # all quarterback — so measuring a projected quarterback against the points
    # a real QB14 actually scored compares two different scales and reports
    # every quarterback in the league as roughly worthless.
    board["replacement"] = board["pos"].map(_projected_replacement(board))
    # Points above the position's last roster-worthy player: the only scale on
    # which a quarterback and a tight end are comparable.
    board["vor"] = board["mu"] - board["replacement"]

    board = board.sort_values("vor", ascending=False).reset_index(drop=True)
    return board[["sleeper_id", "player", "pos", "team", "bye", "mu", "sd",
                  "mu_se", "avail", "vor", "replacement", "basis", "merge_name",
                  "active"]]


# Games of preseason projection a player carries into the season. Around five,
# so a fast start moves a player immediately but does not become his whole
# projection until most of the season has been played.
PRIOR_GAMES = 5.0


def current_form(board: pd.DataFrame, year: int = UPCOMING_YEAR,
                 refresh: bool = True) -> pd.DataFrame:
    """Blend the preseason projection with what has happened so far this season.

    Without this the power rankings would be frozen at draft night for four
    months. Once the season starts, the thing worth knowing about a player is
    mostly what he has actually done, so each week played pulls his projection
    toward his real rate and away from the preseason guess — smoothly, weighted
    by games, rather than switching over on some arbitrary week.

    A rookie who was a curve on a chart in August is a real player by October,
    and this is where the page learns that. Returns the board unchanged if the
    season has not kicked off.
    """
    try:
        weekly = weekly_points.build(year, refresh=refresh)
    except Exception as exc:
        print(f"[projections] no {year} results yet ({exc}); staying preseason")
        return board
    if weekly.empty:
        return board

    played = season_table(weekly)[["sleeper_id", "games", "ppg", "week_sd"]]
    played = played.rename(columns={"games": "played", "ppg": "actual_ppg",
                                    "week_sd": "actual_sd"})
    merged = board.merge(played, on="sleeper_id", how="left")
    weight = merged["played"].fillna(0.0)

    merged["mu"] = ((weight * merged["actual_ppg"].fillna(0.0)
                     + PRIOR_GAMES * merged["mu"])
                    / (weight + PRIOR_GAMES))
    blended_sd = merged["actual_sd"].where(merged["actual_sd"].notna(), merged["sd"])
    merged["sd"] = ((weight * blended_sd + PRIOR_GAMES * merged["sd"])
                    / (weight + PRIOR_GAMES))
    # The projection's error bar shrinks as the season answers the question.
    merged["mu_se"] = merged["mu_se"] * (PRIOR_GAMES / (weight + PRIOR_GAMES))
    merged.loc[weight > 0, "basis"] = merged.loc[weight > 0, "basis"] + " + form"

    merged["replacement"] = merged["pos"].map(_projected_replacement(merged))
    merged["vor"] = merged["mu"] - merged["replacement"]
    return merged.drop(columns=["played", "actual_ppg", "actual_sd"])


def accuracy(year: int, min_games: int = MIN_GAMES) -> pd.DataFrame:
    """How well the projection for `year` matched what players actually did.

    Rebuilds the board knowing only the seasons before `year`, then scores it
    against that year's real points per game. This is the model's own report
    card, separate from the power rankings' — a roster's season is mostly
    waivers, injuries and start/sit calls, so team-level accuracy says more
    about the league than about the projections. This says only how good the
    projections are.
    """
    from fantasy.league import weekly_points as wp

    board = build(year)
    actual = season_table(wp.load([year]))
    actual = actual[actual["games"] >= min_games][["sleeper_id", "ppg", "games"]]
    merged = board.merge(actual, on="sleeper_id")

    rows = []
    for pos in MODELLED:
        sample = merged[merged["pos"] == pos]
        if len(sample) < 15:
            continue
        rows.append({
            "season": year,
            "pos": pos,
            "players": len(sample),
            "correlation": float(np.corrcoef(sample["mu"], sample["ppg"])[0, 1]),
            "mean_error": float((sample["mu"] - sample["ppg"]).abs().mean()),
        })
    return pd.DataFrame(rows)


def path(year: int = UPCOMING_YEAR):
    return paths.PROJECTIONS_DIR / f"{year}.parquet"


def load(year: int = UPCOMING_YEAR, refresh: bool = False) -> pd.DataFrame:
    """The stored projection board, building it if missing or `refresh`."""
    out = path(year)
    if out.exists() and not refresh:
        return pd.read_parquet(out)
    board = build(year, refresh=refresh)
    paths.PROJECTIONS_DIR.mkdir(parents=True, exist_ok=True)
    board.to_parquet(out, index=False)
    print(f"[projections] {year} -> {out} ({len(board)} players)")
    return board


def main():
    p = argparse.ArgumentParser(description="Build the ADP-free projection board.")
    p.add_argument("--year", type=int, default=UPCOMING_YEAR)
    p.add_argument("--refresh", action="store_true",
                   help="Re-pull weekly points and refit before writing.")
    args = p.parse_args()

    board = load(args.year, refresh=args.refresh)
    for pos in POSITIONS:
        top = board[board["pos"] == pos].head(8)
        print(f"\n== {pos} (replacement {top['replacement'].iloc[0]:.1f} ppg) ==")
        print(top[["player", "team", "bye", "mu", "sd", "avail", "vor", "basis"]]
              .to_string(index=False, float_format=lambda v: f"{v:.2f}"))


if __name__ == "__main__":
    main()
