"""
What a college fantasy player is worth, in this league's points.

Yahoo ranks the college pool but publishes no projections for it, so a draft
board built on Yahoo alone can only ever say "the next name down". This turns
that ranking into points, and points into the two numbers a draft is actually
decided by: value over replacement, and what the roster in front of you needs.

Four inputs, each doing the one job it is good at:

  * Yahoo's board rank (cfb.yahoo) is the ordering. It is the market's opinion
    with depth charts, transfers and camp reports already in it, and nothing
    here tries to beat it at that.
  * Real seasons (cfb.players) are the scale. Sort last season's players at a
    position by what they actually scored under this league's modifiers and you
    get the points curve - what a WR12 or a QB8 is worth - which is what turns
    a rank into a number.
  * Uncertainty is what stops the curve from lying. The player ranked RB4 does
    not finish RB4; he finishes somewhere, and the spread of "somewhere" is
    wide. So a projection here is the *expected* value of the curve over a
    distribution of finishes, not the curve read off at his rank. This matters
    most at the top, where a player can only fall, and it is the difference
    between a model that overrates the first round and one that does not.
  * This site's own game model (cfb.predict) is the tilt. It already predicts
    every score of the season, so it knows which offences are about to be good
    and which schedules are soft in the fantasy playoffs - a signal a fantasy
    ranking mostly is not made of, applied gently because Yahoo's rank is not
    ignorant of it either.

Replacement level comes from the league's own roster settings, which is where
the college game stops resembling the NFL one: two starting quarterbacks in a
ten-team league means QB20 is the replacement, not QB10, and 6-point passing
touchdowns mean the position outscores everything else on the board.

    python -m cfb.projections           # the top of the board, valued
"""
import json

import numpy as np
import pandas as pd
from scipy.stats import norm

from cfb import players, schools as schools_mod, yahoo
from cfb.config import DATA_DIR, LEAGUE_TEAMS, SEASON

# Positions this league can actually roster. Yahoo's board also ranks team
# offence units ("OFF"), which most college leagues start and this one does
# not - leaving them in would inflate every board rank below them.
POSITIONS = ["QB", "RB", "WR", "TE", "DEF"]
FLEX_POSITIONS = ["RB", "WR", "TE"]
FLEX_SLOT = "W/R/T"

# Seasons the points curve is built from. Two is enough for a stable shape and
# recent enough that the sport's scoring environment is the current one.
CURVE_SEASONS = [SEASON - 1, SEASON - 2]

# How far a player's finishing rank scatters from his board rank, as the
# standard deviation of log(finish rank / board rank). 0.85 puts the middle
# half of RB6 outcomes between roughly RB3 and RB11, which is about what a
# preseason college ranking is worth: the sport turns over half its rosters
# every year and the board is guessing at depth charts as much as talent.
RANK_SD = 0.85

# Quadrature points for that integral. Odd, so the median finish is one of them.
_NODES = 61

# How hard the site's own game model is allowed to move a projection, as the
# exponent on (this offence's expected points / the average board offence's),
# and the band the result is held inside. Deliberately small: Yahoo's rank is
# not ignorant of which offences are good, so most of this signal is already in
# the ranking and applying it at full strength would count it twice. At 0.30
# the best offence on the board is worth about a tenth of a projection over the
# worst, which reorders players Yahoo has close together and leaves the rest of
# the board where the market put it.
ENV_WEIGHT = 0.30
ENV_CAP = 0.12

# The fantasy playoffs, from the league settings, and how much of the season a
# playoff-week schedule is allowed to be worth. Reported, and a tiebreaker.
PLAYOFF_WEIGHT = 0.10


# --------------------------------------------------------------------------- #
# The points curve
# --------------------------------------------------------------------------- #

def _board_schools(board: pd.DataFrame) -> set:
    """The CFBD school names Yahoo's college game covers (Power 4 plus Notre
    Dame - 68 of them). The curve has to be built over the same universe the
    board ranks, or a rank and a finish would not be measured on the same axis.
    """
    to_school = schools_mod.yahoo_school()
    return {s for s in (to_school.get(n) for n in board["team_full"].dropna().unique())
            if s}


def _smooth(values: np.ndarray, window: int = 5) -> np.ndarray:
    """A monotone points curve: rolling mean, then a running minimum.

    One season's ranked scores are already sorted, so the shape is right and
    only the wobble needs removing; enforcing the sort again afterwards keeps
    the average of two seasons from crossing itself.
    """
    if len(values) < window:
        return values
    smoothed = (pd.Series(values).rolling(window, center=True, min_periods=1)
                .mean().to_numpy())
    return np.minimum.accumulate(smoothed)


def points_curve(board: pd.DataFrame = None, seasons: list = None,
                 league: dict = None) -> dict:
    """{position: array of season points by positional rank, 1 first}.

    Averaged across seasons at each rank, over the schools the board covers.
    """
    board = yahoo.board() if board is None else board
    seasons = CURVE_SEASONS if seasons is None else seasons
    league = yahoo.league() if league is None else league
    universe = _board_schools(board)

    out = {}
    for pos in ["QB", "RB", "WR", "TE"]:
        ranked = []
        for season in seasons:
            df = players.scored(season, league)
            df = df[(df["pos"] == pos) & (df["school"].isin(universe))]
            ranked.append(np.sort(df["points"].to_numpy())[::-1])
        if not ranked:
            continue
        depth = min(len(r) for r in ranked)
        stacked = np.vstack([r[:depth] for r in ranked])
        out[pos] = _smooth(stacked.mean(axis=0))
    return out


def _lookup(curve: np.ndarray, ranks: np.ndarray) -> np.ndarray:
    """Points at (possibly fractional) positional ranks, off the end included.

    Past the curve's depth the tail is extended by its own final slope rather
    than clamped, so a deep-bench flier is worth less than the last real player
    instead of exactly as much. It never goes below zero.
    """
    n = len(curve)
    inside = np.interp(np.clip(ranks, 1, n), np.arange(1, n + 1), curve)
    if n >= 2:
        slope = curve[-1] - curve[-2]                 # negative
        beyond = curve[-1] + slope * (ranks - n)
        inside = np.where(ranks > n, beyond, inside)
    return np.maximum(inside, 0.0)


def _finish_nodes(sd: float = RANK_SD) -> np.ndarray:
    """Multipliers on a board rank, one per equal-probability slice of the
    finish distribution. exp(sd * z) - a rank scatters multiplicatively, so
    RB2 finishing RB6 and RB20 finishing RB60 are the same sized miss."""
    quantiles = (np.arange(_NODES) + 0.5) / _NODES
    return np.exp(sd * norm.ppf(quantiles))


def expected_points(curve: np.ndarray, ranks, sd: float = RANK_SD) -> pd.DataFrame:
    """Expected, floor and ceiling points for players at these board ranks.

    The projection is the mean of the points curve over where the player might
    actually finish - not the curve read off at his rank. Floor and ceiling are
    the 20th and 80th percentiles of the same distribution, which is what makes
    "safe" and "swing for it" a thing the board can say rather than a vibe.
    """
    ranks = np.asarray(ranks, dtype=float)
    grid = np.maximum(np.outer(ranks, _finish_nodes(sd)), 1.0)
    points = _lookup(curve, grid)
    points.sort(axis=1)                     # ascending, for the percentiles
    lo = int(0.20 * _NODES)
    hi = int(0.80 * _NODES)
    return pd.DataFrame({"proj": points.mean(axis=1),
                         "floor": points[:, lo],
                         "ceiling": points[:, hi]})


# --------------------------------------------------------------------------- #
# Team environment, from this site's own model
# --------------------------------------------------------------------------- #

def team_environment(league: dict = None) -> pd.DataFrame:
    """Per school: expected points scored and allowed per game, over the fantasy
    season and over the fantasy playoff weeks, from cfb.predict.

    Indexed by CFBD school name so the board can join to it. Weeks are the
    league's own (settings say 1-13, playoffs from 11); a team's bye is simply a
    week it has no game in, so the mean over its games is the right average.
    """
    from cfb import predict

    league = yahoo.league() if league is None else league
    start = int(league.get("start_week") or 1)
    end = int(league.get("end_week") or 13)
    playoff = int(league.get("playoff_start_week") or end)

    frame, _model, _names = predict.season()
    frame = frame[(frame["week"] >= start) & (frame["week"] <= end)]

    # One row per team-game: what we expect them to score, and to allow.
    home = frame[["week", "home_team", "pred_home", "pred_away"]].rename(
        columns={"home_team": "team", "pred_home": "scored", "pred_away": "allowed"})
    away = frame[["week", "away_team", "pred_away", "pred_home"]].rename(
        columns={"away_team": "team", "pred_away": "scored", "pred_home": "allowed"})
    long = pd.concat([home, away], ignore_index=True)
    long["team"] = long["team"].astype(str)

    season_avg = long.groupby("team")[["scored", "allowed"]].mean()
    playoff_avg = (long[long["week"] >= playoff].groupby("team")[["scored", "allowed"]]
                   .mean().rename(columns={"scored": "playoff_scored",
                                           "allowed": "playoff_allowed"}))
    games = long.groupby("team").size().rename("games")
    playoff_games = (long[long["week"] >= playoff].groupby("team").size()
                     .rename("playoff_games"))

    env = season_avg.join(playoff_avg).join(games).join(playoff_games)
    env["playoff_games"] = env["playoff_games"].fillna(0).astype(int)

    # ESPN team id -> CFBD school, which is the key everything else here uses.
    by_espn = {v: k for k, v in schools_mod.espn_ids().items()}
    env["school"] = [by_espn.get(str(i)) for i in env.index]
    return env.dropna(subset=["school"]).set_index("school")


# --------------------------------------------------------------------------- #
# Replacement level
# --------------------------------------------------------------------------- #

def starter_demand(league: dict = None, teams: int = LEAGUE_TEAMS) -> dict:
    """{position: dedicated starting slots across the league} plus flex count."""
    league = yahoo.league() if league is None else league
    demand = {p: 0 for p in POSITIONS}
    flex = 0
    for slot in league["roster"]:
        name, count = slot["position"], int(slot["count"])
        if name in demand:
            demand[name] += count * teams
        elif name == FLEX_SLOT:
            flex += count * teams
    return {"dedicated": demand, "flex": flex}


def replacement_levels(frame: pd.DataFrame, league: dict = None,
                       teams: int = LEAGUE_TEAMS) -> dict:
    """{position: the projection of the first player nobody has to start}.

    Dedicated slots are filled first, then the flex slots go to whichever of
    RB/WR/TE has the best player left, one at a time - which is what actually
    happens in a draft and is why the flex raises replacement level unevenly
    rather than by a third each.
    """
    demand = starter_demand(league, teams)
    pools = {p: frame.loc[frame["pos"] == p, "proj"].sort_values(ascending=False)
             .to_numpy() for p in POSITIONS}
    used = {p: min(demand["dedicated"][p], len(pools[p])) for p in POSITIONS}

    for _ in range(demand["flex"]):
        best, best_pts = None, -np.inf
        for p in FLEX_POSITIONS:
            i = used[p]
            if i < len(pools[p]) and pools[p][i] > best_pts:
                best, best_pts = p, pools[p][i]
        if best is None:
            break
        used[best] += 1

    levels = {}
    for p in POSITIONS:
        pool, i = pools[p], used[p]
        if len(pool) == 0:
            levels[p] = 0.0
        elif i < len(pool):
            levels[p] = float(pool[i])
        else:
            levels[p] = float(pool[-1])
    return levels


if __name__ == "__main__":
    board = yahoo.board()
    league = yahoo.league()
    curves = points_curve(board, league=league)
    for pos, c in curves.items():
        idx = [1, 5, 10, 20, 30, 50]
        print(f"{pos:>3} curve:", " ".join(f"{i}:{c[i-1]:.0f}" for i in idx if len(c) >= i))
    env = team_environment(league)
    print(f"\nenvironment: {len(env)} schools, "
          f"scored {env['scored'].mean():.1f} +/- {env['scored'].std():.1f} per game")
    print(env.sort_values("scored", ascending=False).head(5).round(1).to_string())


# --------------------------------------------------------------------------- #
# Team defenses
# --------------------------------------------------------------------------- #
# A team defense is the one position on this board that does not need a points
# curve at all: this site already predicts every score of the season, and most
# of what a fantasy defense scores is decided by what its opponent scores. So
# the points-allowed half is computed straight off the model, and only the
# big-play half - sacks, takeaways, defensive scores - is estimated from
# history.

# How far a real score lands from the model's prediction for it, in points. The
# margin model's own error is measured (cfb.predict.margin_sd, ~16 across the
# two teams); a single team's score is the looser half of that.
_SCORE_SD = 11.0

# Yahoo's points-allowed brackets, as (upper bound, points). The last bracket is
# open-ended. 21-27 pays nothing and so is not listed in the league modifiers;
# it is the gap between 20 and 28 here.
_PA_BRACKETS = [(0, "Pts Allow 0"), (6, "Pts Allow 1-6"), (13, "Pts Allow 7-13"),
                (20, "Pts Allow 14-20"), (27, None), (34, "Pts Allow 28-34"),
                (None, "Pts Allow 35+")]

# CFBD team season stats -> the league modifier each one scores under.
_DEF_STATS = {"sacks": "Sack", "passesIntercepted": "Int", "fumblesRecovered": "Fum Rec",
              "interceptionTDs": "TD", "kickReturnTDs": "Ret TD", "puntReturnTDs": "Ret TD"}


def _def_modifiers(league: dict) -> dict:
    """Defensive modifier values by Yahoo's name for them.

    Yahoo uses "Int" and "TD" for both an offensive and a defensive stat; the
    defensive ones come second in the list, so here the *last* occurrence wins -
    the mirror of the offensive lookup in cfb.players.modifiers.
    """
    out = {}
    for m in league["modifiers"]:
        if m["name"]:
            out[m["name"]] = float(m["value"])
    return out


def _points_allowed_value(mean_allowed: np.ndarray, mods: dict,
                          sd: float = _SCORE_SD) -> np.ndarray:
    """Expected points-allowed score per game, integrating the model's
    predicted opponent score over Yahoo's brackets.

    A defense projected to allow 20 does not score the 14-20 bracket; it scores
    a probability-weighted blend of every bracket, which is both more accurate
    and the reason two defenses with the same season average can be worth
    different amounts.
    """
    mean_allowed = np.asarray(mean_allowed, dtype=float)
    total = np.zeros_like(mean_allowed)
    lower = -0.5                       # scores are integers; 0 owns (-inf, 0.5)
    for bound, name in _PA_BRACKETS:
        upper = np.inf if bound is None else bound + 0.5
        share = norm.cdf(upper, mean_allowed, sd) - norm.cdf(lower, mean_allowed, sd)
        total += share * (mods.get(name, 0.0) if name else 0.0)
        lower = upper
    return total


# Where the fitted big-play line is kept, and what to use if it is missing and
# cannot be refitted. The fallback is roughly the fit's own average defense; it
# shifts every team's projection by the same amount, so the board still ranks
# defenses correctly, it just prices them all a little flat.
BIG_PLAY_CACHE = DATA_DIR / "def_big_play.json"
BIG_PLAY_FALLBACK = (8.6, -0.153)


def big_play_model(league: dict, season: int = SEASON - 1, refresh: bool = False):
    """(intercept, slope) of big-play defensive points per game on points allowed.

    Two numbers off a finished season, so they are cached on disk and committed:
    refitting them needs a CFBD key, and the machine that publishes this site
    does not have one - a page that has to hold a credential to render is a page
    that stops rendering the day the credential is somewhere else.
    """
    if not refresh and BIG_PLAY_CACHE.exists():
        try:
            saved = json.loads(BIG_PLAY_CACHE.read_text())
            if saved.get("season") == season:
                return float(saved["intercept"]), float(saved["slope"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            pass
    try:
        fit = _fit_big_play(league, season)
    except Exception:
        return BIG_PLAY_FALLBACK
    BIG_PLAY_CACHE.parent.mkdir(parents=True, exist_ok=True)
    BIG_PLAY_CACHE.write_text(json.dumps(
        {"season": season, "intercept": fit[0], "slope": fit[1]}, indent=1))
    return fit


def _fit_big_play(league: dict, season: int):
    """Fit that line from CFBD's team season stats. Needs a key; called once.

    Sacks, takeaways and defensive scores are not in the game model, so they are
    estimated the only way available: from what defenses actually did last year,
    against the one thing that does predict them - how good the defense is. It
    is a line rather than a constant because good defenses genuinely take the
    ball away more, by about the amount this measures.
    """
    import requests

    from cfb.lines import _key

    mods = _def_modifiers(league)
    r = requests.get("https://api.collegefootballdata.com/stats/season", timeout=60,
                     headers={"Authorization": f"Bearer {_key()}"}, params={"year": season})
    r.raise_for_status()
    per_team = {}
    for row in r.json():
        per_team.setdefault(row["team"], {})[row["statName"]] = row["statValue"]

    points, allowed = [], []
    for team, stats in per_team.items():
        games = float(stats.get("games") or 0)
        if games < 6:
            continue
        big = sum(float(stats.get(stat) or 0) * mods.get(name, 0.0)
                  for stat, name in _DEF_STATS.items())
        # Points allowed per game is not in this feed; the opponent's scoring
        # plays are, and they add up to it closely enough to fit a line against.
        opp = (float(stats.get("passingTDsOpponent") or 0)
               + float(stats.get("rushingTDsOpponent") or 0)) * 7.0
        points.append(big / games)
        allowed.append(opp / games)
    if len(points) < 20:
        raise RuntimeError(f"only {len(points)} teams with a full season of stats")
    slope, intercept = np.polyfit(allowed, points, 1)
    return float(intercept), float(slope)


def defense_projections(env: pd.DataFrame, league: dict) -> pd.DataFrame:
    """Projected season points for every school's defense, from the game model."""
    mods = _def_modifiers(league)
    intercept, slope = big_play_model(league)
    per_game = (_points_allowed_value(env["allowed"].to_numpy(), mods)
                + intercept + slope * env["allowed"].to_numpy())
    playoff = (_points_allowed_value(env["playoff_allowed"].fillna(env["allowed"]).to_numpy(), mods)
               + intercept + slope * env["playoff_allowed"].fillna(env["allowed"]).to_numpy())
    return pd.DataFrame({"def_per_game": per_game,
                         "def_playoff_per_game": playoff,
                         "def_proj": per_game * env["games"].to_numpy()},
                        index=env.index)


# --------------------------------------------------------------------------- #
# The valued board
# --------------------------------------------------------------------------- #

# A new tier starts where the drop to the next player is this many times the
# typical drop at that position. Tiers are the thing a draft board is actually
# read for - "six left before it falls off a cliff" is a decision, "he is ranked
# 14th" is not.
TIER_GAP = 2.2
TIER_MAX = 12

# Spread of where a player actually goes, around Yahoo's average pick, as a
# fraction of that pick number with a floor. Early picks are nearly determined
# and late ones are nearly random, which is what the proportional term says; the
# floor keeps the first round from being treated as certain.
ADP_SD_FRACTION = 0.32
ADP_SD_FLOOR = 4.0


def adp_sigma(adp: pd.Series) -> pd.Series:
    """How far from his average pick a player is actually taken."""
    return np.maximum(ADP_SD_FLOOR, ADP_SD_FRACTION * adp.astype(float))


def _tiers(points: pd.Series) -> pd.Series:
    """Tier number within a position, 1 best, from the gaps in the curve."""
    values = points.sort_values(ascending=False)
    gaps = -values.diff().fillna(0.0)
    typical = gaps[gaps > 0].median() if (gaps > 0).any() else 0.0
    tier, size, out = 1, 0, {}
    for name, gap in gaps.items():
        if size and (gap > TIER_GAP * typical or size >= TIER_MAX):
            tier += 1
            size = 0
        out[name] = tier
        size += 1
    return pd.Series(out)


def value_board(refresh: bool = False) -> pd.DataFrame:
    """Yahoo's board, priced: projection, floor, ceiling, VORP, tier, schedule.

    One row per rosterable player, in Yahoo's own rank order with the team
    offence units removed and the ranks closed up behind them - this league has
    no slot for one, so leaving them in would have every player below them
    looking a round cheaper than he is.
    """
    league = yahoo.league(refresh=refresh)
    board = yahoo.board(refresh=refresh)
    board = board[board["pos"].isin(POSITIONS)].copy()
    board["rank"] = range(1, len(board) + 1)
    board["pos_rank"] = board.groupby("pos").cumcount() + 1
    board["school"] = board["team_full"].map(schools_mod.yahoo_school())

    env = team_environment(league)
    curves = points_curve(board, league=league)

    board["proj"] = np.nan
    board["floor"] = np.nan
    board["ceiling"] = np.nan
    for pos, curve in curves.items():
        mask = board["pos"] == pos
        est = expected_points(curve, board.loc[mask, "pos_rank"])
        for col in ("proj", "floor", "ceiling"):
            board.loc[mask, col] = est[col].to_numpy()

    # The site's own model, as a tilt on the skill positions and as the whole
    # projection for a defense.
    on_board = env.loc[env.index.intersection(board["school"].dropna().unique())]
    league_scored = on_board["scored"].mean()
    scored = board["school"].map(env["scored"])
    tilt = ((scored / league_scored) ** ENV_WEIGHT).clip(1 - ENV_CAP, 1 + ENV_CAP)
    skill = board["pos"] != "DEF"
    board["env_tilt"] = tilt
    board.loc[skill, ["proj", "floor", "ceiling"]] = (
        board.loc[skill, ["proj", "floor", "ceiling"]].mul(tilt[skill], axis=0))

    defense = defense_projections(env, league)
    is_def = board["pos"] == "DEF"
    def_proj = board.loc[is_def, "school"].map(defense["def_proj"])
    board.loc[is_def, "proj"] = def_proj
    # A defense's spread comes from its schedule, not from a rank distribution.
    board.loc[is_def, "floor"] = def_proj * 0.72
    board.loc[is_def, "ceiling"] = def_proj * 1.30

    # Playoff-week schedule: what the model expects this team to do in weeks the
    # league plays for the title, against what it expects of them all season.
    playoff_scored = board["school"].map(env["playoff_scored"])
    playoff_allowed = board["school"].map(env["playoff_allowed"])
    ratio = np.where(is_def,
                     board["school"].map(env["allowed"]) / playoff_allowed,
                     playoff_scored / scored)
    board["playoff_ratio"] = pd.Series(ratio, index=board.index)
    board["playoff_games"] = board["school"].map(env["playoff_games"])
    board["opp_allowed"] = board["school"].map(env["allowed"])
    board["team_scored"] = scored

    board = board.dropna(subset=["proj"])
    board["proj_playoff"] = board["proj"] * board["playoff_ratio"].fillna(1.0)

    levels = replacement_levels(board, league)
    board["replacement"] = board["pos"].map(levels)
    board["vorp"] = board["proj"] - board["replacement"]
    board["vorp_floor"] = board["floor"] - board["replacement"]
    board["vorp_ceiling"] = board["ceiling"] - board["replacement"]

    board["tier"] = pd.concat([_tiers(g["proj"]) for _, g in board.groupby("pos")])
    board["adp_sd"] = adp_sigma(board["adp"])
    board["value_rank"] = board["vorp"].rank(ascending=False, method="first").astype(int)
    board["reach"] = board["adp"] - board["value_rank"]

    return board.sort_values("vorp", ascending=False, ignore_index=True)
