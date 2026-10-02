"""
Next man up: what an injury does to his teammates' fantasy value.

The season simulations hold an injured player out for the weeks ESPN says he
will miss (fantasy.league.injury_report). That is half of an injury. The other
half is that his work does not vanish: when a team's lead back is out for the
year, the back behind him gets the carries, and his projection should rise for
as long as the starter is gone. This module measures that on history and
applies it to today's board.

The measurement
---------------
Every regular-season NFL game 2019-2025, with 2018 lending priors (nflverse
weekly stats for the points, snap counts for who actually took the field, so
a backup who played and did nothing counts as a zero rather than as absent).
Each player who played gets a real-time form going into the week - his points
so far this season, with five games of last season's rate as the prior, the
same weighting as projections.current_form - and his teammates at his
position are ranked on it. The prior leaves out last season's games that had
an injured teammate's work on offer, or a backup's fill-in weeks would pass
for his "with the starter" line and every later promotion would look smaller.

A teammate is "out" in a week when he had played for the team earlier that
season, did not play this week, did not turn up on another team, carried a
form of at least MIN_MU points, and was on the injury report as Out or
Doubtful or on a reserve list. That last filter is what keeps benchings,
releases and healthy scratches - a different event, where the replacement
often took the job on merit - out of the effect. Those absences still go into
the fit, as their own columns, so they do not leak into anything else.

For every player who played, his points minus his form are regressed on the
absences around him, with an intercept for each position and depth rank (the
form's own bias, measured mostly on the weeks nobody was out):

  * same position: each healthy teammate below the absent player in the depth
    order gains a share of the absent player's form - one share for the next
    man, another for the one after him, and so on (DEPTH_CAP deep);
  * a starting quarterback out: each back and receiver loses a share of his
    *own* form (a worse passer moves everyone's numbers by a proportion, not
    by a fixed amount); a tight end's share came out at zero;
  * each discounted by how much of the absence the form already contains: a
    back who has spent three of his eight form games behind an empty starting
    spot already carries three eighths of his promotion. Fitting with that
    discount beat fitting without it out of sample, so it is real.

What it found, 2019-2025 (share of the injured player's points a game):

    RB out   next back .32, the one after .15, third .11   (~58% recovered)
    WR out   next .15, then .11, .08, .07                   (~41%)
    TE out   next .27, then .14                             (~41%)
    QB out   receivers -11% of their own points, backs -8%, tight ends 0

So a 16-point back's injury is worth about +5 a game to the man behind him.
Fit on 2019-2022 and scored on 2023-2025, the rule beats "no change" on the
teammates it moves by a point or more (RMSE 6.69 -> 6.33, the gain's 95%
interval clear of zero) and on every player-week with an injured teammate
out (5.94 -> 5.87); the numbers are stored with the coefficients.

Cross-position effects (a receiver out and the tight end catching more) were
measured too. They are small - a tight end gains about 3% of a missing
receiver's points - and including them made the out-of-sample fit worse, so
they are left out. So is the backup quarterback's own line: the board already
prices a quarterback per game he plays, and a backup's board number is not
the "with the starter" baseline the rule is built on.

Fitted coefficients live in data/fantasy/opportunity.json, about 2 KB, with
the out-of-sample check that justified them. `refit()` rebuilds it from
nflverse.

Applying it
-----------
`boosts(board, held, weeks_left, depth=...)` turns the injury report into
per-teammate additions: {teammate: {add, full, weeks, because, season,
parts}}. `full` is the measured effect - what he scores a game with the
injured player gone, over what he scores with him playing. `add` is what is
missing from the board: the board's form already holds the games he has played
without the injured player, and its Sleeper half (projections.with_sleeper)
already holds the weeks Sleeper projected with the injured player ruled out.
`season` is `add` spread over the simulation's remaining weeks, which is what
a simulation holding one mu per player wants.

Depth comes from Sleeper's player table (`depth_charts`), whose
depth_chart_order is the team's own order - except that an injured player is
moved to the bottom of it, so where he *was* is read off the board's mu
instead: he slots in above every healthy teammate with a lower one.

    python -m fantasy.league.opportunity            # today's biggest boosts
    python -m fantasy.league.opportunity --refit    # re-measure 2018-2025
"""
import argparse
import json
from bisect import bisect_left
from collections import defaultdict
from datetime import date

import numpy as np
import pandas as pd

from fantasy import paths

PATH = paths.DATA_DIR / "opportunity.json"

SEASONS = tuple(range(2018, 2026))
TRAIN = tuple(range(2019, 2023))
TEST = tuple(range(2023, 2026))

SKILL = ("QB", "RB", "WR", "TE")
CATCHERS = ("RB", "WR", "TE")

#: Games of prior a player's history form carries - projections.PRIOR_GAMES,
#: so the history is measured against the same kind of number the board holds.
PRIOR_GAMES = 5.0
#: Form (PPR points a game) an absent player needs before his absence counts.
MIN_MU = 5.0
#: Smallest change (points a game) worth reporting: a tight end's share of a
#: missing quarterback is +0.01 +- 0.04 of his points, which is a line of
#: noise per tight end, not a finding.
MIN_EFFECT = 0.1
#: How far down the depth chart a missing player's work is spread. Deeper than
#: this the measured shares are a few percent and mostly noise.
DEPTH_CAP = {"RB": 3, "WR": 4, "TE": 2}
#: Depth ranks the form's bias is measured separately for (the last is "and below").
RANK_CAP = {"QB": 1, "RB": 3, "WR": 4, "TE": 2}

#: What makes an absence an injury: the week's report, or a reserve list.
HURT_REPORT = ("Out", "Doubtful")
HURT_ROSTER = ("RES", "INA", "PUP", "RSR", "RSN", "NWT", "SUS")



def last_week(season: int) -> int:
    """The last regular-season week kept: 16-game seasons ended in week 17
    with starters resting, which is not football anyone drafts for, and
    weekly_points stops at 17 anyway."""
    return 16 if season <= 2020 else 17


# --------------------------------------------------------------------------- #
# History
# --------------------------------------------------------------------------- #

def games_frame(weekly: pd.DataFrame, snaps: pd.DataFrame, ids: pd.DataFrame) -> pd.DataFrame:
    """One row per skill player per regular-season game he played:
    season, week, team, gsis_id, pos, pts.

    `weekly` is weekly_points' frame (stat rows), `snaps` nflverse's snap
    counts, `ids` a pfr_id -> gsis_id map (nflverse ff_playerids). A player
    with offensive snaps and no stat row played and scored nothing; one with a
    stat row and no snap row (an id the map misses) still played.
    """
    weekly = weekly.copy()
    weekly["position"] = weekly["position"].replace({"FB": "RB"})
    weekly = weekly[weekly["position"].isin(SKILL) & weekly["gsis_id"].notna()]
    stat = weekly[["season", "week", "team", "gsis_id", "position", "fantasy_points_ppr"]]
    stat = stat.rename(columns={"position": "pos", "fantasy_points_ppr": "pts"})

    snaps = snaps.copy()
    if "game_type" in snaps:
        snaps = snaps[snaps["game_type"] == "REG"]
    snaps["position"] = snaps["position"].replace({"FB": "RB"})
    snaps = snaps[snaps["position"].isin(SKILL) & (snaps["offense_snaps"] > 0)]
    pfr = ids[["pfr_id", "gsis_id"]].dropna().drop_duplicates("pfr_id")
    snaps = snaps.merge(pfr, left_on="pfr_player_id", right_on="pfr_id", how="inner")
    snaps["team"] = snaps["team"].replace({"LA": "LAR"})
    snaps = snaps[["season", "week", "team", "gsis_id", "position"]].rename(
        columns={"position": "pos"})

    out = stat.merge(snaps, on=["season", "week", "gsis_id"], how="outer",
                     suffixes=("", "_snap"))
    out["team"] = out["team"].fillna(out["team_snap"])
    out["pos"] = out["pos"].fillna(out["pos_snap"])
    out["pts"] = out["pts"].fillna(0.0)
    out = out.dropna(subset=["team", "pos"])
    out["season"] = out["season"].astype(int)
    out["week"] = out["week"].astype(int)
    out = out[out["week"] <= out["season"].map(last_week)]
    out = out.drop_duplicates(["season", "week", "gsis_id"])
    return out[["season", "week", "team", "gsis_id", "pos", "pts"]].reset_index(drop=True)


def hurt_keys(injuries: pd.DataFrame = None, rosters: pd.DataFrame = None) -> set:
    """{(season, week, gsis_id)} of player-weeks with an injury reason to miss:
    Out/Doubtful on nflverse's weekly injury report, or a reserve-type status
    on its weekly rosters."""
    keys = set()
    if injuries is not None and len(injuries):
        frame = injuries[injuries["report_status"].isin(HURT_REPORT)].dropna(
            subset=["season", "week", "gsis_id"])
        keys |= set(zip(frame["season"].astype(int), frame["week"].astype(int),
                        frame["gsis_id"]))
    if rosters is not None and len(rosters):
        frame = rosters[rosters["status"].isin(HURT_ROSTER)].dropna(
            subset=["season", "week", "gsis_id"])
        keys |= set(zip(frame["season"].astype(int), frame["week"].astype(int),
                        frame["gsis_id"]))
    return keys


def _defaults(games: pd.DataFrame) -> dict:
    """A position's prior for a player with no last season: the 25th
    percentile season rate among players with four games or more."""
    rates = games.groupby(["season", "gsis_id", "pos"])["pts"].agg(["mean", "size"])
    rates = rates[rates["size"] >= 4].reset_index()
    out = rates.groupby("pos")["mean"].quantile(0.25).to_dict()
    return {pos: float(out.get(pos, 2.0)) for pos in SKILL}


def observations(games: pd.DataFrame, hurt: set, min_mu: float = MIN_MU,
                 prior_games: float = PRIOR_GAMES) -> pd.DataFrame:
    """One row per player per game played: his points, his form going in, his
    depth rank that week, and every meaningful teammate missing that week.

    `absent` holds (pos, mu, c, d, kind) per missing teammate: his form, the
    share `c` of this player's form already played without him, `d` how many
    depth steps below him this player stands (negative: above), and `kind`
    "inj" or "other".

    A player's prior is last season's rate in the games no injured teammate's
    work was on offer to him (all his games if fewer than four were clean). A
    backup who started half of last season otherwise carries his fill-in
    numbers into this one as his "with the starter" line, and every later
    promotion looks smaller than it is. The first season in `games` has no
    priors at all and only lends them: no rows of its own.
    """
    defaults = _defaults(games)
    prior = {}

    rows = []
    for season, sg in games.groupby("season"):
        touched = set()
        sg = sg.sort_values("week")
        weeks, cums, team_at, pos_of = {}, {}, {}, {}
        for pid, grp in sg.groupby("gsis_id"):
            weeks[pid] = grp["week"].to_list()
            cums[pid] = np.concatenate([[0.0], np.cumsum(grp["pts"].to_numpy(float))])
            team_at[pid] = dict(zip(grp["week"], grp["team"]))
            pos_of[pid] = grp["pos"].iloc[-1]
        pts_at = {(w, pid): p for w, pid, p in zip(sg["week"], sg["gsis_id"], sg["pts"])}

        def form(pid, week):
            n = bisect_left(weeks[pid], week)
            base = prior.get((season, pid), defaults[pos_of[pid]])
            return (cums[pid][n] + prior_games * base) / (n + prior_games), n

        for team, tg in sg.groupby("team"):
            members = set(tg["gsis_id"])
            by_week = tg.groupby("week")["gsis_id"].apply(list).to_dict()
            for week in sorted(by_week):
                present = by_week[week]
                here = set(present)
                bases = {pid: form(pid, week) for pid in present}

                missing = []
                for x in members - here:
                    at = team_at[x]
                    before = [w for w, t in at.items() if w < week and t == team]
                    if not before or week in at:
                        continue
                    # Left for another team since his last game here: a trade
                    # or a release, not an absence.
                    if any(t != team and max(before) < w <= week for w, t in at.items()):
                        continue
                    mu, _ = form(x, week)
                    if mu < min_mu:
                        continue
                    kind = "inj" if (season, week, x) in hurt else "other"
                    missing.append((x, pos_of[x], mu, min(before), kind))

                for pos in SKILL:
                    ranked = sorted((p for p in present if pos_of[p] == pos),
                                    key=lambda p: -bases[p][0])
                    for rank, pid in enumerate(ranked, 1):
                        base, n = bases[pid]
                        mine = [w for w, t in team_at[pid].items() if w < week and t == team]
                        absent = []
                        for x, px, mu, first, kind in missing:
                            without = sum(1 for w in mine if w > first and w not in team_at[x])
                            c = without / (n + prior_games)
                            d = None
                            if px == pos:
                                slot = 1 + sum(1 for p in ranked if bases[p][0] > mu)
                                d = (rank if rank < slot else rank + 1) - slot
                            absent.append((px, mu, c, d, kind))
                            if kind == "inj" and (px == pos or px == "QB"):
                                touched.add((pid, week))
                        rows.append({"season": int(season), "week": int(week), "team": team,
                                     "gsis_id": pid, "pos": pos, "rank": rank,
                                     "actual": float(pts_at[(week, pid)]), "base": float(base),
                                     "games": int(n), "absent": absent})

        for pid, played in weeks.items():
            every = [pts_at[(w, pid)] for w in played]
            clean = [pts_at[(w, pid)] for w in played if (pid, w) not in touched]
            sample = clean if len(clean) >= 4 else every
            if len(sample) >= 4:
                prior[(int(season) + 1, pid)] = float(np.mean(sample))

    # A season with no season before it in `games` has nobody's prior - every
    # starter's form opens at the positional floor - so it only lends priors.
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    seasons = set(int(s) for s in games["season"].unique())
    return frame[(frame["season"] - 1).isin(seasons)].reset_index(drop=True)


def _design(obs: pd.DataFrame) -> tuple:
    """(X, columns) for the regression of points over form on the absences.

    Columns: an intercept per position and depth rank; injury effects - same
    position by depth steps below (`same:RB:1` ..), a starting QB out on each
    catcher's own form (`qb:WR`); and nuisance columns for what is measured
    but never applied (`deep`, `above`, the backup QB's own line, and every
    non-injury absence)."""
    cols, index, entries = [], {}, []

    def col(key):
        if key not in index:
            index[key] = len(cols)
            cols.append(key)
        return index[key]

    for pos in SKILL:
        for r in range(1, RANK_CAP[pos] + 1):
            col(f"icpt:{pos}:{r}")
    for i, (pos, rank, base, absent) in enumerate(zip(obs["pos"], obs["rank"], obs["base"],
                                                       obs["absent"])):
        r = min(int(rank), RANK_CAP[pos])
        entries.append((i, col(f"icpt:{pos}:{r}"), 1.0))
        for px, mu, c, d, kind in absent:
            keep = 1.0 - c
            if kind != "inj":
                if px == pos or px == "QB":
                    entries.append((i, col(f"other:{px}:{pos}:{r}"), mu * keep))
                continue
            if px == pos == "QB":
                entries.append((i, col("backup:QB"), mu * keep))
            elif px == pos:
                if d < 0:
                    key = f"above:{pos}"
                elif d > DEPTH_CAP[pos]:
                    key = f"deep:{pos}"
                else:
                    key = f"same:{pos}:{d}"
                entries.append((i, col(key), mu * keep))
            elif px == "QB":
                entries.append((i, col(f"qb:{pos}"), base * keep))
    X = np.zeros((len(obs), len(cols)))
    for i, j, v in entries:
        X[i, j] += v
    return X, cols


def _solve(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    return beta


def _coefficients(beta: np.ndarray, cols: list) -> dict:
    """The applied part of a fit, as stored."""
    value = dict(zip(cols, beta))
    same = {pos: [round(float(value.get(f"same:{pos}:{d}", 0.0)), 4)
                  for d in range(1, DEPTH_CAP[pos] + 1)] for pos in DEPTH_CAP}
    qb = {pos: round(float(value.get(f"qb:{pos}", 0.0)), 4) for pos in CATCHERS}
    return {"same": same, "qb_out": qb,
            "backup_qb": round(float(value.get("backup:QB", 0.0)), 4)}


def _applied(cols: list) -> np.ndarray:
    return np.array([c.startswith("same:") or c.startswith("qb:") for c in cols])


def fit(obs: pd.DataFrame) -> dict:
    """Coefficients from an observations frame (see `observations`)."""
    X, cols = _design(obs)
    return _coefficients(_solve(X, (obs["actual"] - obs["base"]).to_numpy(float)), cols)


def validate(obs: pd.DataFrame, train=TRAIN, test=TEST, draws: int = 1000,
             seed: int = 0) -> dict:
    """Fit on `train` seasons, score on `test`: does the rule predict
    teammates' points in the weeks a player was out better than no change?

    "No change" is the same regression without the injury columns - form plus
    its measured bias - so the comparison isolates the rule. Reported on every
    player-week with an injured teammate out, and on those where the rule
    moves the prediction by a point or more (with a 95% interval on the gain,
    resampling whole team-seasons)."""
    X, cols = _design(obs)
    y = (obs["actual"] - obs["base"]).to_numpy(float)
    tr = obs["season"].isin(train).to_numpy()
    te = obs["season"].isin(test).to_numpy()
    rule = _applied(cols)
    injury = np.array([any(a[4] == "inj" for a in absent) for absent in obs["absent"]])

    full = _solve(X[tr], y[tr])
    plain = _solve(X[tr][:, ~rule], y[tr])
    effect = X[te][:, rule] @ full[rule]
    err_rule = y[te] - X[te] @ full
    err_none = y[te] - X[te][:, ~rule] @ plain
    sel = injury[te]

    def rmse(e):
        return round(float(np.sqrt(np.mean(e ** 2))), 4) if len(e) else None

    big = sel & (np.abs(effect) >= 1.0)
    keys = (obs["season"].astype(str) + obs["team"]).to_numpy()[te][big]
    gain = err_none[big] ** 2 - err_rule[big] ** 2
    interval = [None, None]
    if len(gain):
        rng = np.random.default_rng(seed)
        groups = [np.flatnonzero(keys == k) for k in np.unique(keys)]
        boots = [np.mean(gain[np.concatenate([groups[g] for g in
                                              rng.integers(0, len(groups), len(groups))])])
                 for _ in range(draws)]
        interval = [round(float(v), 3) for v in np.percentile(boots, [2.5, 97.5])]

    bins = []
    for lo, hi in [(-99, -1), (-1, -0.25), (0.25, 1), (1, 2), (2, 99)]:
        m = sel & (effect >= lo) & (effect < hi)
        if m.any():
            bins.append({"from": lo, "to": hi, "n": int(m.sum()),
                         "predicted": round(float(effect[m].mean()), 2),
                         "observed": round(float(err_none[m].mean()), 2),
                         "rmse_none": rmse(err_none[m]), "rmse_rule": rmse(err_rule[m])})
    return {"train": [int(s) for s in train], "test": [int(s) for s in test],
            "injury_weeks": {"n": int(sel.sum()), "rmse_none": rmse(err_none[sel]),
                             "rmse_rule": rmse(err_rule[sel])},
            "moved_a_point": {"n": int(big.sum()), "rmse_none": rmse(err_none[big]),
                              "rmse_rule": rmse(err_rule[big]),
                              "mse_gain": round(float(gain.mean()), 3) if len(gain) else None,
                              "mse_gain_95": interval},
            "by_effect": bins,
            "coefficients": _coefficients(full, cols)}


def history(seasons=SEASONS) -> tuple:
    """(games, hurt) for `seasons`, from the weekly points cache and nflverse."""
    import nflreadpy as nfl

    from fantasy.league import weekly_points

    seasons = [int(s) for s in seasons]
    weekly = weekly_points.load(seasons)
    snaps = nfl.load_snap_counts(seasons).to_pandas()
    ids = nfl.load_ff_playerids().to_pandas()
    injuries = nfl.load_injuries(seasons).to_pandas()
    rosters = nfl.load_rosters_weekly(seasons).to_pandas()
    return games_frame(weekly, snaps, ids), hurt_keys(injuries, rosters)


def refit(seasons=SEASONS, train=TRAIN, test=TEST, write: bool = True) -> dict:
    """Re-measure the coefficients on `seasons` and (by default) store them."""
    games, hurt = history(seasons)
    obs = observations(games, hurt)
    payload = {
        "about": "Next-man-up shares (fantasy.league.opportunity). same[pos][d-1]: share "
                 "of an injured player's PPR points a game that the healthy teammate d "
                 "depth steps below him gains; qb_out[pos]: share of each catcher's own "
                 "points that a starting QB's absence moves. backup_qb is measured, not "
                 "applied.",
        "fitted": date.today().isoformat(),
        "seasons": [int(s) for s in seasons],
        "min_mu": MIN_MU,
        "prior_games": PRIOR_GAMES,
        **fit(obs),
        "validation": validate(obs, train, test),
    }
    if write:
        PATH.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
        print(f"[opportunity] {len(obs)} player-games -> {PATH}")
    return payload


def load() -> dict:
    """The stored coefficients ({} if the file is missing or unreadable)."""
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# --------------------------------------------------------------------------- #
# Today
# --------------------------------------------------------------------------- #

def depth_charts(players: dict) -> dict:
    """{team: {pos: [sleeper id, ...]}} in Sleeper's depth_chart_order, from
    its whole player table ({id: player}, sleeper_wrapper's get_all_players).
    An injured player is usually already at the bottom; that is handled when
    the order is used."""
    out = defaultdict(lambda: defaultdict(list))
    for pid, p in (players or {}).items():
        team, pos, order = p.get("team"), p.get("position"), p.get("depth_chart_order")
        if team and pos in SKILL and order is not None:
            out[team][pos].append((int(order), str(pid)))
    return {team: {pos: [pid for _, pid in sorted(rows)] for pos, rows in by_pos.items()}
            for team, by_pos in out.items()}


def _evidence(board: pd.DataFrame) -> pd.Series:
    """Whether a board row is a real projection rather than the replacement
    floor every unknown player is given (mu_se 0, no form behind it)."""
    seen = pd.Series(True, index=board.index)
    if "mu_se" in board:
        seen = board["mu_se"].fillna(0) > 0
        if "basis" in board:
            seen |= board["basis"].fillna("").str.contains("form|Sleeper")
    return seen


def _absorbed(pid: str, x: str, team: str, pos: str, games: dict, sleeper_weeks: list,
              prior_games: float, sleeper_weight: float, sleeper_positions) -> float:
    """Share of the effect of `x` being out that `pid`'s board mu already
    holds: his form games played for x's team without x, and (for the
    positions projections.with_sleeper blends) Sleeper's weeks that projected
    him with x ruled out."""
    mine = games.get(pid, {})
    theirs = games.get(x, {})
    without = sum(1 for week, where in mine.items() if where == team and week not in theirs)
    form = without / (len(mine) + prior_games)
    if sleeper_weeks and pos in sleeper_positions:
        counted = [wk for wk in sleeper_weeks if (wk.get(pid) or 0) > 0]
        if counted:
            ruled_out = sum(1 for wk in counted if (wk.get(x) or 0) <= 0)
            return (1 - sleeper_weight) * form + sleeper_weight * ruled_out / len(counted)
    return form


def boosts(board: pd.DataFrame, held: dict, weeks_left: int, depth: dict = None,
           played: pd.DataFrame = None, sleeper_weeks: list = None,
           coeffs: dict = None) -> dict:
    """{teammate sleeper id: {add, full, weeks, because, season, parts}}.

    board          sleeper_id, pos, mu (+ team, mu_se, basis if there): the
                   season board after current_form / with_sleeper.
    held           {sleeper id: weeks out from the next week}, as
                   injury_report.held_out gives it.
    weeks_left     weeks the simulation still draws (`season` spreads over these).
    depth          depth_charts(...) - Sleeper's order; without it the board's
                   own order (real projections first, then mu) is used.
    played         this season's games so far: rows of week, sleeper_id, team
                   (weekly_points' file through the board's last week). With
                   it, what the form already holds is taken off, and a player
                   out since before the season is skipped - the market priced
                   him before the board was built.
    sleeper_weeks  [{sleeper id: projected pts}] for the weeks with_sleeper
                   averaged; takes off what Sleeper's half already holds.

    add      points a game to add to the board while he is out (the measured
             effect less what the board already holds); negative for a
             catcher whose starting quarterback is out.
    full     the measured effect: points a game over his line with the
             injured player playing. The number to show a reader.
    weeks    weeks it lasts (the injured player's weeks out, less any of the
             teammate's own); because: the injured player's id. With more than
             one injury feeding a player, add/full are summed, weeks/because
             are the biggest one's and `parts` lists each [id, add, full, weeks].
    season   sum(add x weeks) / the weeks he can play - the per-game change
             for a simulation that holds one mu per player.
    """
    coeffs = load() if coeffs is None else coeffs
    if not coeffs or not held or board is None or board.empty:
        return {}
    from fantasy import projections

    same = coeffs.get("same") or {}
    qb_out = coeffs.get("qb_out") or {}
    min_mu = float(coeffs.get("min_mu", MIN_MU))

    frame = board.copy()
    frame["sleeper_id"] = frame["sleeper_id"].astype(str)
    frame = frame.drop_duplicates("sleeper_id")
    frame["_seen"] = _evidence(frame)
    mu = dict(zip(frame["sleeper_id"], frame["mu"].astype(float)))
    seen = dict(zip(frame["sleeper_id"], frame["_seen"]))
    pos_of = dict(zip(frame["sleeper_id"], frame["pos"]))
    team_of = dict(zip(frame["sleeper_id"], frame["team"])) if "team" in frame else {}
    team_of = {k: v for k, v in team_of.items() if isinstance(v, str) and v}

    order = defaultdict(list)
    if depth:
        for team, by_pos in depth.items():
            for pos, ids in by_pos.items():
                order[(team, pos)] = [str(p) for p in ids]
                for p in ids:
                    team_of[str(p)] = team
                    pos_of.setdefault(str(p), pos)
    ranked = frame[frame["pos"].isin(SKILL)].sort_values(["_seen", "mu"], ascending=False)
    for pid, pos in zip(ranked["sleeper_id"], ranked["pos"]):
        team = team_of.get(pid)
        if team and not (depth and team in depth and pos in depth[team]):
            order[(team, pos)].append(pid)

    games = {}
    if played is not None and len(played):
        for week, pid, team in zip(played["week"], played["sleeper_id"].astype(str),
                                   played["team"]):
            games.setdefault(pid, {})[int(week)] = team

    held = {str(k): int(v) for k, v in held.items() if v}
    parts = defaultdict(list)
    for x, out in held.items():
        pos, team = pos_of.get(x), team_of.get(x)
        if pos not in SKILL or not team or mu.get(x, 0.0) < min_mu:
            continue
        out = min(out, int(weeks_left))
        if out <= 0 or (games and x not in games):
            continue
        healthy = [p for p in order.get((team, pos), [])
                   if p != x and held.get(p, 0) < out]
        # Where he stood before he was hurt: Sleeper has usually moved him to
        # the bottom already, so it is read off the board - below every
        # healthy teammate with a higher real projection, above the rest,
        # who keep the depth chart's order among themselves.
        below = [p for p in healthy if not (seen.get(p) and mu.get(p, 0.0) > mu[x])]
        if pos == "QB":
            if len(below) < len(healthy):
                continue                    # a backup: nobody's line moves
            effects = [(p, qb_out.get(cpos, 0.0) * mu.get(p, 0.0), cpos)
                       for cpos in CATCHERS if qb_out.get(cpos)
                       for p in order.get((team, cpos), []) if held.get(p, 0) < out]
        else:
            shares = same.get(pos) or []
            effects = [(p, share * mu[x], pos) for p, share in zip(below, shares)]
        for p, full, ppos in effects:
            if abs(full) < MIN_EFFECT:
                continue
            kept = 1.0 - _absorbed(p, x, team, ppos, games, sleeper_weeks,
                                   projections.PRIOR_GAMES, projections.SLEEPER_WEIGHT,
                                   projections.SLEEPER_POSITIONS)
            parts[p].append((x, full * kept, full, out - held.get(p, 0)))

    result = {}
    for p, items in parts.items():
        main = max(items, key=lambda item: abs(item[1]) * item[3])
        playable = max(int(weeks_left) - held.get(p, 0), 1)
        result[p] = {
            "add": round(sum(i[1] for i in items), 2),
            "full": round(sum(i[2] for i in items), 2),
            "weeks": int(main[3]),
            "because": main[0],
            "season": round(sum(i[1] * i[3] for i in items) / playable, 3),
            "parts": [[i[0], round(i[1], 2), round(i[2], 2), int(i[3])] for i in items],
        }
    return result


def apply(board: pd.DataFrame, result: dict) -> pd.DataFrame:
    """`board` with each boosted player's mu moved by his `season` add (never
    below zero) - for a simulation that holds one mu per player."""
    if not result:
        return board
    board = board.copy()
    add = board["sleeper_id"].astype(str).map(
        lambda pid: result[pid]["season"] if pid in result else 0.0)
    board["mu"] = (board["mu"] + add).clip(lower=0.0)
    return board


def season_games(year: int, through_week: int) -> pd.DataFrame:
    """This season's games through `through_week` (week, sleeper_id, team),
    from the weekly points cache - read, never fetched."""
    from fantasy.league import weekly_points

    path = weekly_points.path(year)
    if not through_week or not path.exists():
        return pd.DataFrame(columns=["week", "sleeper_id", "team"])
    frame = pd.read_parquet(path, columns=["week", "sleeper_id", "team"])
    frame = frame.dropna(subset=["sleeper_id"])
    return frame[frame["week"] <= through_week]


def sleeper_window(year: int, through_week: int) -> list:
    """Sleeper's projections for the weeks projections.with_sleeper averages
    after `through_week` ([] before kickoff or with Sleeper down)."""
    from fantasy import projections

    if not through_week:
        return []
    upcoming = min(int(through_week) + 1, 18)
    out = []
    for week in range(max(1, upcoming - projections.SLEEPER_WEEKS + 1), upcoming + 1):
        try:
            out.append(projections._sleeper_week(int(year), week))
        except Exception as exc:                            # noqa: BLE001
            print(f"  ! Sleeper week {week} unavailable for next-man-up ({exc})")
    return out


def for_board(board: pd.DataFrame, held: dict, year: int, through_week: int,
              weeks_left: int, depth: dict = None) -> dict:
    """`boosts` with the season's games and Sleeper's window filled in - what
    a builder holding the board (current_form + with_sleeper through
    `through_week`) and injury_report.held_out(...) calls."""
    return boosts(board, held, weeks_left, depth=depth,
                  played=season_games(year, through_week),
                  sleeper_weeks=sleeper_window(year, through_week))


def _today(top: int = 25) -> None:
    from fantasy import projections
    from fantasy.config import UPCOMING_YEAR
    from fantasy.league import injury_report
    from fantasy.league.power import NFL_WEEKS
    from fantasy.site import season_board

    year = UPCOMING_YEAR
    weeks = season_board.absorbed_weeks(year)
    board = projections.load(year)
    board = projections.current_form(board, year, refresh=False, through_week=weeks)
    board = projections.with_sleeper(board, year, through_week=weeks)
    from sleeper_wrapper import Players
    raw = Players().get_all_players(sport="nfl") or {}
    tags = {str(k): p.get("injury_status") for k, p in raw.items() if p.get("injury_status")}
    held = injury_report.held_out(tags, from_week=weeks, weeks=NFL_WEEKS, year=year)
    result = for_board(board, held, year, weeks, NFL_WEEKS - weeks, depth=depth_charts(raw))
    name = {str(k): p.get("full_name") or k for k, p in raw.items()}
    team = {str(k): p.get("team") or "" for k, p in raw.items()}
    pos = {str(k): p.get("position") or "" for k, p in raw.items()}
    rows = sorted(result.items(), key=lambda kv: -abs(kv[1]["add"]) * kv[1]["weeks"])
    print(f"{len(result)} teammates moved by {len(held)} players held out after week {weeks}")
    for pid, b in rows[:top]:
        x = b["because"]
        print(f"  {name.get(x, x):<22} out {held.get(x)} wk -> {pos.get(pid):<2} "
              f"{name.get(pid, pid):<22} {team.get(pid):<3} full {b['full']:+5.2f} "
              f"add {b['add']:+5.2f} for {b['weeks']} wk (season {b['season']:+.2f})")


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("--refit", action="store_true", help="Re-measure on 2018-2025 and store.")
    args = p.parse_args()
    if args.refit:
        payload = refit()
        print(json.dumps({k: payload[k] for k in ("same", "qb_out", "backup_qb")}, indent=1))
        print(json.dumps(payload["validation"], indent=1))
    else:
        _today()


if __name__ == "__main__":
    main()
