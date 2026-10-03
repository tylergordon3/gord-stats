"""
Back from injury: what a player scores in his first games after one.

The season simulations hold an injured player out until ESPN's return date
(fantasy.league.injury_report) and hand his work to the men behind him while
he is gone (fantasy.league.opportunity). Then he comes back at his full line.
He does not: a team eases a player back, on a snap count, and the first game
after an injury is a part-time one. This module measures how far short of his
line he falls, game by game, and takes it off the projections.

The measurement
---------------
Every regular-season game 2019-2025 by a quarterback, back, receiver or tight
end, with 2018 lending priors (nflverse weekly stats for the points, snap
counts for who took an offensive snap, so a player who played and did nothing
counts as a zero rather than as absent). Each game gets the player's form
going into it - his points so far this season with five games of last
season's rate as the prior, projections.current_form's weighting - and only
games with a form of MIN_MU or more are kept: the players a fantasy lineup is
made of.

An absence is one or more of his team's games missed between two he played
for it in the same season (a bye is not a game missed; a player who changed
teams in between is left out). It is an injury when the official report listed
him for a missed week (Out, Doubtful, or Questionable and then inactive, or
an injury on the practice report) or he was on a reserve list (IR, PUP);
illness, personal matters and the COVID lists are not. His first, second and third games after it are the "games back".

Every other game is the control: points over form in his position, his form
band, his half of the season and how many games the form rests on. That is
what regression to the mean and the season's drift do to anyone's form, and a
returning player's points are scored against it - observed over expected, with
95% intervals from resampling players. Measured 2026-10-02 (PPR):

                       missed 1 game          missed 2 or more        all
  first game back    -8.4% (-16.5..-0.1)    -16.5% (-23.2..-9.8)    -12.9% (-18.2..-7.8)
                      n=333                  n=419                   n=752, 381 players
  second game back   -5.3% (-12.1..+2.4)    -12.3% (-18.8..-5.6)    -9.2% (-14.5..-4.5)
                      n=269                  n=338                   n=607
  third game back    +1.5% (-6.7..+10.3)    -2.8% (-9.5..+4.6)      -0.9% (-6.3..+4.8)

Half-PPR moves the same (-13.1%, -9.8%). About a point and a half for a
twelve-point player's first game back. Absences that were not injuries
(illness, personal, the COVID lists) came back -8.6% (-21.4..+6.4): not
distinguishable from nothing, and not applied.

Why it is the weeks missed and not the injury: his snap share in the first
game back is 10.5% under his usual after one game missed, 19% after two or
three, 28% after four or more (each interval about +-4 points) - teams ration
a player by how long he has been away - and by the second game the snaps are
back. By injury type the raw numbers wander (first / second game back):

    hamstring  -18.6% (-27.8..-8.9)  n=125 / -9.5%  n=100
    ankle      -11.4% (-23.3..+2.1)  n=117 / -19.2% n=98
    knee       -11.6% (-25.8..+2.9)  n=110 / -19.0% n=86
    concussion  -8.1% (-22.3..+7.0)  n=86  / +0.7%  n=69
    shoulder   -13.7% (-30.5..+4.8)  n=59  / -12.6% n=44
    foot       -19.3% (-36.1..-2.6)  n=47  / -1.1%  n=39
    groin       +4.0% (-22.7..+30.7) n=29  / +0.1%  n=24
    calf       -16.8% (-43.1..+18.1) n=22  / -6.9%  n=17
    back        +5.0%                n=9   / -3.8%  n=8
    other      -13.0% (-25.5..-1.1)  n=128 / -2.4%  n=108

but once the weeks missed are allowed for, the type says nothing more: each
type's residual on the first two games is inside +-7% (hamstring -2.9%,
-11.6..+6.0; concussion +6.2%, -7.0..+18.7; the widest, groin, +13.2% on 53
games), Cochran's Q = 4.1 on 10 df, p = 0.94. A hamstring's raw -18.6% is
the two-or-more row: hamstrings keep players out longer. Position likewise
(QB -0.2%, RB +2.4%, WR -2.2%, TE +2.7%; p = 0.81). So the table is keyed on
the weeks missed and the game back; the injury type is measured, not used.

What ships (TABLE) is the cells whose 95% interval is clear of zero: the
first game back after one game missed or more, the second after two or more.
The second game after a single missed week and every third game are left at
nothing - the measurement cannot tell them from it.

The out-of-sample check (`backtest`): fit on 2019-2022 by the same rule,
applied to 2023-2025's returning players' first and second games (571, 321
of them moved), the form-based projection's mean absolute error falls 5.94 ->
5.78 (-0.15, interval -0.27..-0.04), RMSE 7.61 -> 7.49, bias (projection
minus points) +1.09 -> +0.07. The same multipliers on control games from the
same cells buy a little absolute error (-0.06: form runs high for everyone and
points are skewed) but cost squared error (+1.3), where the returners gain
(-1.8): the gain is the injury, not shrinkage. Fit the other way round (2023-25
onto 2019-22's 793 games): 6.01 -> 5.85 (-0.23..-0.10), RMSE 7.50 -> 7.41.
On the board the season simulations use while he is held out (form blended
with Sleeper's projections from before the injury): 5.88 -> 5.72 (-0.28..-0.04)
and 5.95 -> 5.70 (-0.34..-0.17) the other way, RMSE 7.48 -> 7.37 / 7.42 -> 7.24.

Sleeper already knows some of this. Its weekly projection for a player's
first game back is 10.7% under its projections for him before the injury
(7.8% after one game missed, 21.6% after four or more), and against that
projection his first game back is only -4.2% (-9.9..+0.9). That matters for
one board: projections.with_sleeper blends backs', receivers' and tight ends'
rates halfway to Sleeper's projections for the coming week and the two before
it, so once a returning player is due back, Sleeper's discounted number is in
his rate - for every week left, which takes off more than the dip does.

Applying it
-----------
`dips(board, held, weeks_left, played, upcoming)` finds, for each projected
player who has played this season, the first games back still ahead of the
simulation: a player held out now (injury_report.held_out) comes back after
his held weeks, with the games already missed counted in; a player due back
this week, or who came back last week, is part-way through. It skips a player
whose absence is not an injury (a suspension, the not-with-team list) or who
has been out since before the season (the market priced that before the board
was built, as opportunity does), and, for the positions with_sleeper blends,
one whose Sleeper projection for a game back is already in the board.

The season simulations hold one rate per player, so the dips are spread the
way next-man-up boosts are: `season` = the sum of his dips over the games he
can play, and `apply` scales mu by it. A back held out three weeks with
eleven to play gives up (16.5% + 12.3%) / 11 = 2.6% of his rate.

`week_factors(...)` is the same thing for one week - the multiplier on a
player's projection for the week being played, for the pages that project a
single week from the form-only board (matchups' GordStats column, the Team
page): `availability.apply(..., dips=)` takes it.

    python -m fantasy.league.return_dip                 # who is coming back, and the dips
    python -m fantasy.league.return_dip --measure       # re-measure 2018-2025 (nflverse)
    python -m fantasy.league.return_dip --measure --cache DIR   # keep the inputs in DIR

Re-measuring prints a TABLE to paste here; nothing is written.
"""
import argparse
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

SEASONS = tuple(range(2018, 2026))          # 2018 lends priors only
MEASURED = tuple(range(2019, 2026))
TRAIN = tuple(range(2019, 2023))
TEST = tuple(range(2023, 2026))

SKILL = ("QB", "RB", "WR", "TE")
#: Games of last season's rate a form carries - projections.PRIOR_GAMES.
PRIOR_GAMES = 5.0
#: Form (PPR points a game) a player needs to be measured, and to be moved.
MIN_MU = 5.0
#: Games back measured; the table holds the ones that came out non-zero.
GAMES_BACK = 3

#: TABLE[bucket][game back] = change in his points, as a share of his line.
#: Bucket 1: one game missed; 2: two or more. Measured 2019-2025 (above);
#: cells whose interval took in zero are not here and count as nothing.
TABLE = {1: {1: -0.084}, 2: {1: -0.165, 2: -0.123}}

#: Holds that are not an injury: absences like them came back -8.6%
#: (-21.4..+6.4), not told from nothing, so none is applied. Sleeper tags and
#: ESPN statuses.
NOT_INJURY = {"Sus", "NA", "DNR", "COV", "Suspension", "Commissioner Exempt"}

# Cells a control is matched on: form band, half of the season, games the
# form rests on (the more of his own games, the less prior in it).
FORM_BANDS = (0, 5, 8, 11, 14, 18, np.inf)
GAME_BANDS = (-1, 2, 5, np.inf)

#: Report text -> injury type, first match wins. "not injury" is everything
#: that is not one: an absence listed only with it is not measured.
TYPES = (
    ("not injury", r"illness|not injury|personal|\brest|covid|coach|suspension|travel|"
                   r"load management|\bill\b|heat|cramp"),
    ("concussion", r"concussion|head"),
    ("hamstring", r"hamstring"),
    ("ankle", r"ankle"),
    ("knee", r"knee|acl|mcl|pcl|meniscus|patella"),
    ("shoulder", r"shoulder|collarbone|clavicle|sternoclavicular|ac joint|rotator"),
    ("foot", r"foot|feet|toe|heel|plantar|lisfranc"),
    ("groin", r"groin|adductor"),
    ("calf", r"calf"),
    ("back", r"back|spine|lumbar"),
)
#: Reserve lists that mean an injury (weekly rosters' status), and the COVID
#: reserve codes (status_description_abbr) that do not.
RESERVE = ("RES", "PUP")
COVID_CODES = ("R59", "R62")


def injury_type(text) -> str | None:
    """hamstring / ankle / knee / ... / other from a report's free text
    ("Right Hamstring", "Knee - ACL"), "not injury" for illness and the like,
    None for nothing."""
    if not isinstance(text, str) or not text.strip():
        return None
    low = text.lower()
    for name, pattern in TYPES:
        if re.search(pattern, low):
            return name
    return "other"


def bucket(missed: int) -> int:
    """1 for a single game missed, 2 for two or more."""
    return 1 if int(missed) <= 1 else 2


def dip(missed: int, game: int, table: dict = None) -> float:
    """The change (a share, negative) in a player's points in his `game`-th
    game back after missing `missed` games; 0 where nothing was measured."""
    table = TABLE if table is None else table
    if missed < 1 or game < 1:
        return 0.0
    return float(table.get(bucket(missed), {}).get(int(game), 0.0))


# --------------------------------------------------------------------------- #
# History
# --------------------------------------------------------------------------- #

def last_week(season: int) -> int:
    """The last week kept: 16-game seasons rested starters in week 17
    (opportunity.last_week)."""
    return 16 if season <= 2020 else 17


def _team(series: pd.Series) -> pd.Series:
    return series.replace({"LA": "LAR"})


def player_games(weekly: pd.DataFrame, snaps: pd.DataFrame, ids: pd.DataFrame) -> pd.DataFrame:
    """One row per skill player per regular-season game he took an offensive
    snap in (or has a stat line for): season, week, team, gsis_id, pos, ppr,
    half, snap (offensive snap share, NaN without a snap row).

    weekly  weekly_points' frame; snaps  nflverse load_snap_counts; ids  a
    pfr_id -> gsis_id map (nflverse ff_playerids)."""
    w = weekly.copy()
    w["position"] = w["position"].replace({"FB": "RB"})
    w = w[w["position"].isin(SKILL) & w["gsis_id"].notna()]
    w["half"] = (w["fantasy_points"] + w["fantasy_points_ppr"]) / 2.0
    stat = w[["season", "week", "team", "gsis_id", "position", "fantasy_points_ppr", "half"]]
    stat = stat.rename(columns={"position": "pos", "fantasy_points_ppr": "ppr"})

    s = snaps.copy()
    if "game_type" in s:
        s = s[s["game_type"] == "REG"]
    s["position"] = s["position"].replace({"FB": "RB"})
    s = s[s["position"].isin(SKILL) & (s["offense_snaps"] > 0)]
    pfr = ids[["pfr_id", "gsis_id"]].dropna().drop_duplicates("pfr_id")
    s = s.merge(pfr, left_on="pfr_player_id", right_on="pfr_id", how="inner")
    s["team"] = _team(s["team"])
    s = s[["season", "week", "team", "gsis_id", "position", "offense_pct"]].rename(
        columns={"position": "pos", "offense_pct": "snap"})

    out = stat.merge(s, on=["season", "week", "gsis_id"], how="outer", suffixes=("", "_snap"))
    out["team"] = out["team"].fillna(out["team_snap"])
    out["pos"] = out["pos"].fillna(out["pos_snap"])
    out[["ppr", "half"]] = out[["ppr", "half"]].fillna(0.0)
    out = out.dropna(subset=["team", "pos"])
    out["season"] = out["season"].astype(int)
    out["week"] = out["week"].astype(int)
    out = out[out["week"] <= out["season"].map(last_week)]
    out = out.drop_duplicates(["season", "week", "gsis_id"])
    return out[["season", "week", "team", "gsis_id", "pos", "ppr", "half", "snap"]] \
        .sort_values(["season", "gsis_id", "week"]).reset_index(drop=True)


def team_weeks(schedules: pd.DataFrame) -> dict:
    """{(season, team): [weeks it played]} - regular season, through last_week."""
    s = schedules[schedules["game_type"] == "REG"]
    out = {}
    for side in ("home_team", "away_team"):
        for season, team, week in zip(s["season"], _team(s[side]), s["week"]):
            if int(week) <= last_week(int(season)):
                out.setdefault((int(season), team), set()).add(int(week))
    return {k: sorted(v) for k, v in out.items()}


def report_rows(injuries: pd.DataFrame, rosters: pd.DataFrame = None) -> dict:
    """{(season, week, gsis_id): {status, type, roster, code}} - the week's
    final injury report (status, injury type from the game report's text,
    else the practice report's) and any reserve-type roster status."""
    out = {}
    if injuries is not None and len(injuries):
        inj = injuries[injuries["game_type"] == "REG"]
        if "date_modified" in inj:
            inj = inj.sort_values("date_modified", kind="stable")
        inj = inj.drop_duplicates(["season", "week", "gsis_id"], keep="last")
        for r in inj.itertuples(index=False):
            kind = injury_type(r.report_primary_injury) or injury_type(
                getattr(r, "practice_primary_injury", None))
            out[(int(r.season), int(r.week), r.gsis_id)] = {
                "status": r.report_status if isinstance(r.report_status, str) else None,
                "type": kind}
    if rosters is not None and len(rosters):
        ros = rosters[(rosters["game_type"] == "REG")
                      & rosters["status"].isin(RESERVE + ("INA", "NWT", "SUS", "RSN", "RSR"))]
        for r in ros.itertuples(index=False):
            row = out.setdefault((int(r.season), int(r.week), r.gsis_id),
                                 {"status": None, "type": None})
            row["roster"] = r.status
            code = getattr(r, "status_description_abbr", None)
            row["code"] = code if isinstance(code, str) else None
    return out


def _cause(rows: list, around: list) -> tuple:
    """(cause, injury type) of an absence from its weeks' report rows and, for
    the type only, the rows of the games either side of it. Any sign of an
    injury in a missed week makes it one: a game status, a reserve list, or a
    practice-report injury."""
    kinds, evidence, covid = [], False, False
    for row in rows:
        covid |= row.get("code") in COVID_CODES
        evidence |= (row.get("status") in ("Out", "Doubtful", "Questionable")
                     or row.get("roster") in RESERVE
                     or row.get("type") not in (None, "not injury"))
        if row.get("type"):
            kinds.append(row["type"])
    kind = max(sorted(set(kinds)), key=kinds.count) if kinds else next(
        (r["type"] for r in around if r.get("type")), None)
    if covid or kind == "not injury":
        return "not injury", kind
    if evidence:
        return "injury", kind or "unknown"
    return "unlisted", None


def absences(games: pd.DataFrame, weeks: dict, reports: dict,
             games_back: int = GAMES_BACK) -> pd.DataFrame:
    """One row per in-season absence: season, gsis_id, team, pos, last (his
    last game before it), back (his first after it), missed (team games),
    cause ("injury", "not injury", "unlisted"), type, and `games` - the weeks
    of his first `games_back` games after it, while he kept playing every one
    of his team's games."""
    rows = []
    for (season, pid), g in games.groupby(["season", "gsis_id"], sort=False):
        played = g["week"].to_list()
        teams = g["team"].to_list()
        mine = dict(zip(played, teams))
        for i in range(len(played) - 1):
            a, b, team = played[i], played[i + 1], teams[i]
            if teams[i + 1] != team:
                continue
            sched = weeks.get((season, team), [])
            missed = [w for w in sched if a < w < b]
            if not missed:
                continue
            cause, kind = _cause([reports.get((season, w, pid)) or {} for w in missed],
                                 [reports.get((season, w, pid)) or {} for w in (b, a)])
            back = []
            for w in [w for w in sched if w >= b][:games_back]:
                if mine.get(w) != team:
                    break
                back.append(int(w))
            rows.append({"season": int(season), "gsis_id": pid, "team": team,
                         "pos": g["pos"].iloc[-1], "last": int(a), "back": int(b),
                         "missed": len(missed), "cause": cause, "type": kind, "games": back})
    return pd.DataFrame(rows, columns=["season", "gsis_id", "team", "pos", "last", "back",
                                       "missed", "cause", "type", "games"])


def observations(games: pd.DataFrame, gone: pd.DataFrame, min_mu: float = MIN_MU,
                 prior_games: float = PRIOR_GAMES, seasons=MEASURED) -> pd.DataFrame:
    """One row per game of `seasons` with a form of `min_mu` or more: his
    points (ppr, half), snap share, form and half-PPR form going in, games the
    form rests on (n), the snap share of his four games before the previous
    one (snap_pre - a clean pre-injury share for a first game back), the
    control cell, and - for a game back - k (1st, 2nd, ...), missed, cause and
    type of the absence. Games 1..GAMES_BACK after any absence, injury or
    not, are never controls."""
    rates = games.groupby(["season", "gsis_id", "pos"]).agg(
        ppr=("ppr", "mean"), half=("half", "mean"), size=("ppr", "size")).reset_index()
    full = rates[rates["size"] >= 4]
    floor = full.groupby("pos")["ppr"].quantile(0.25).to_dict()
    ratio = (games.groupby("pos")["half"].sum() / games.groupby("pos")["ppr"].sum()).to_dict()
    prior = {(int(s) + 1, p): (a, h) for s, p, a, h in
             zip(full["season"], full["gsis_id"], full["ppr"], full["half"])}

    label = {}
    for r in gone.itertuples(index=False):
        for k, w in enumerate(r.games, 1):
            key = (r.season, r.gsis_id, int(w))
            if key not in label or label[key][0] > k:
                label[key] = (k, r.missed, r.cause, r.type)

    rows = []
    wanted = set(int(s) for s in seasons)
    for (season, pid), g in games.groupby(["season", "gsis_id"], sort=False):
        if int(season) not in wanted:
            continue
        pos = g["pos"].iloc[-1]
        base_ppr = floor.get(pos, 2.0)
        p_ppr, p_half = prior.get((int(season), pid), (base_ppr, base_ppr * ratio.get(pos, 1.0)))
        ppr = g["ppr"].to_numpy(float)
        half = g["half"].to_numpy(float)
        snap = g["snap"].to_numpy(float)
        cum = np.concatenate([[0.0], np.cumsum(ppr)])
        cum_h = np.concatenate([[0.0], np.cumsum(half)])
        for n, week in enumerate(g["week"].to_numpy()):
            form = (cum[n] + prior_games * p_ppr) / (n + prior_games)
            if form < min_mu:
                continue
            window = snap[max(0, n - 5):n - 1] if n >= 2 else snap[:0]
            window = window[~np.isnan(window)]
            k, missed, cause, kind = label.get((int(season), pid, int(week)), (0, 0, None, None))
            rows.append((int(season), pid, int(week), pos, ppr[n], half[n], snap[n], form,
                         (cum_h[n] + prior_games * p_half) / (n + prior_games), n,
                         float(window.mean()) if len(window) else np.nan,
                         int(k), int(missed), cause, kind))
    obs = pd.DataFrame(rows, columns=["season", "gsis_id", "week", "pos", "ppr", "half", "snap",
                                      "form", "form_half", "n", "snap_pre", "k", "missed",
                                      "cause", "type"])
    band = pd.cut(obs["form"], FORM_BANDS, labels=False).astype(str)
    games_band = pd.cut(obs["n"], GAME_BANDS, labels=False).astype(str)
    obs["cell"] = (obs["pos"] + ":" + band + ":" + (obs["week"] > 9).astype(int).astype(str)
                   + ":" + games_band)
    return obs


# --------------------------------------------------------------------------- #
# Effects
# --------------------------------------------------------------------------- #

def _expected(obs: pd.DataFrame, y: str = "ppr", base: str = "form") -> pd.Series:
    """What a game was expected to score: its baseline times the control
    games' (those that are no game back) points over baseline in its cell -
    NaN for a cell with none."""
    ctrl = obs[(obs["k"] == 0) & obs[y].notna() & obs[base].notna()]
    ratio = ctrl.groupby("cell")[y].sum() / ctrl.groupby("cell")[base].sum()
    return obs[base] * obs["cell"].map(ratio)


def _ratio(ids, observed, expected, draws: int, seed: int) -> dict:
    """sum(observed) / sum(expected) - 1 with a 95% interval from resampling
    players (Poisson weights per player, so his games stay together)."""
    keys, index = np.unique(np.asarray(ids), return_inverse=True)
    o = np.bincount(index, np.asarray(observed, float), minlength=len(keys))
    e = np.bincount(index, np.asarray(expected, float), minlength=len(keys))
    weights = np.random.default_rng(seed).poisson(1.0, (draws, len(keys))).astype(float)
    boots = (weights @ o) / np.maximum(weights @ e, 1e-9) - 1.0
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return {"effect": round(float(o.sum() / e.sum() - 1.0), 4), "lo": round(float(lo), 4),
            "hi": round(float(hi), 4), "n": int(len(index)), "players": int(len(keys))}


def effect(obs: pd.DataFrame, mask, y: str = "ppr", base: str = "form", draws: int = 1000,
           seed: int = 0) -> dict:
    """Observed over expected - 1 on the rows `mask` picks, against the
    control games of the same cells, with a 95% interval from resampling
    players. {effect, lo, hi, n, players}."""
    mask = np.asarray(mask, dtype=bool)
    expected = _expected(obs, y, base).to_numpy(float)
    take = mask & ~np.isnan(expected) & obs[y].notna().to_numpy()
    if not take.any():
        return {"effect": None, "lo": None, "hi": None, "n": 0, "players": 0}
    return _ratio(obs["gsis_id"].to_numpy()[take], obs[y].to_numpy(float)[take],
                  expected[take], draws, seed)


def _hurt(obs: pd.DataFrame) -> np.ndarray:
    return (obs["cause"] == "injury").to_numpy()


def fit_table(obs: pd.DataFrame, draws: int = 1000) -> tuple:
    """(table, cells): the dips by bucket and game back, keeping only the
    cells whose 95% interval is clear of zero, and every cell measured."""
    hurt = _hurt(obs)
    table, cells = {}, {}
    for b in (1, 2):
        in_bucket = (obs["missed"].map(lambda m: bucket(m) if m else 0) == b).to_numpy()
        for k in range(1, GAMES_BACK + 1):
            got = effect(obs, hurt & in_bucket & (obs["k"] == k).to_numpy(), draws=draws)
            cells[(b, k)] = got
            if got["n"] and (got["hi"] < 0 or got["lo"] > 0):
                table.setdefault(b, {})[k] = round(got["effect"], 3)
    return table, cells


def heterogeneity(obs: pd.DataFrame, column: str, games=(1, 2), draws: int = 1000) -> tuple:
    """Does `column` (type, pos) say anything beyond the weeks missed? Each
    group's points over what the bucket-by-game effect expects (the measured
    effect, not the shipped table: zeroed cells would leak into it), with
    Cochran's Q across the groups. (rows, Q, df, p)."""
    from scipy.stats import chi2

    expected = _expected(obs)
    rows = obs[_hurt(obs) & obs["k"].isin(games).to_numpy() & expected.notna().to_numpy()]
    rows = rows.assign(_exp=expected[rows.index], _b=rows["missed"].map(bucket))
    pooled = rows.groupby(["k", "_b"]).apply(
        lambda g: g["ppr"].sum() / g["_exp"].sum(), include_groups=False)
    rows["_exp"] = rows["_exp"] * [pooled[(k, b)] for k, b in zip(rows["k"], rows["_b"])]
    out = []
    for value, g in rows.dropna(subset=[column]).groupby(column):
        out.append({column: value, **_ratio(g["gsis_id"], g["ppr"], g["_exp"], draws, 0)})
    est = np.array([r["effect"] for r in out])
    se = np.array([max((r["hi"] - r["lo"]) / 3.92, 1e-6) for r in out])
    w = 1.0 / se ** 2
    q = float((w * (est - (w * est).sum() / w.sum()) ** 2).sum())
    df = len(out) - 1
    return out, round(q, 2), df, (round(float(1 - chi2.cdf(q, df)), 3) if df > 0 else None)


def backtest(obs: pd.DataFrame, train=TRAIN, test=TEST, games=(1, 2), draws: int = 1000,
             seed: int = 0, placebo_draws: int = 20) -> dict:
    """Fit the table on `train` (the shipping rule: cells clear of zero only),
    then project `test`'s returning players' games back from their form, with
    and without it: mean absolute error, RMSE and bias, with 95% intervals on
    the changes (players resampled).

    The placebo puts the same multipliers on control games drawn from the
    same cells. Form runs high for everyone (its bias is positive on control
    games too) and points are skewed, so shading any projection buys a little
    absolute error for nothing; the placebo is that little, and the squared
    error - which shrinkage cannot game - should get worse on it."""
    tr = obs[obs["season"].isin(list(train))]
    te = obs[obs["season"].isin(list(test))]
    table, _ = fit_table(tr, draws=draws)
    back = te[(te["cause"] == "injury") & te["k"].isin(games)]
    mult = np.array([1.0 + dip(m, k, table) for m, k in zip(back["missed"], back["k"])])
    y = back["ppr"].to_numpy(float)
    p0 = back["form"].to_numpy(float)
    p1 = p0 * mult
    keys, index = np.unique(back["gsis_id"].to_numpy(), return_inverse=True)
    rng = np.random.default_rng(seed)
    weights = rng.poisson(1.0, (draws, len(keys))).astype(float)
    count = weights @ np.bincount(index, minlength=len(keys)).astype(float)

    def interval(change):
        boots = (weights @ np.bincount(index, change, minlength=len(keys))) / np.maximum(count, 1e-9)
        return [round(float(v), 3) for v in np.percentile(boots, [2.5, 97.5])]

    controls = {c: g for c, g in te[te["k"] == 0].groupby("cell")}
    mae_p, mse_p = [], []
    for cell, m in zip(back["cell"], mult):
        pool = controls.get(cell)
        if pool is None or pool.empty or m == 1.0:
            continue
        pick = pool.iloc[rng.integers(0, len(pool), placebo_draws)]
        yy, pp = pick["ppr"].to_numpy(float), pick["form"].to_numpy(float)
        mae_p.append(float(np.mean(np.abs(yy - pp * m) - np.abs(yy - pp))))
        mse_p.append(float(np.mean((yy - pp * m) ** 2 - (yy - pp) ** 2)))
    moved = mult != 1.0

    def r3(v):
        return round(float(v), 3)

    return {"train": [min(train), max(train)], "test": [min(test), max(test)],
            "table": table, "n": int(len(back)), "moved": int(moved.sum()),
            "mae": [r3(np.abs(y - p0).mean()), r3(np.abs(y - p1).mean())],
            "mae_change_95": interval(np.abs(y - p1) - np.abs(y - p0)),
            "rmse": [r3(np.sqrt(np.mean((y - p0) ** 2))), r3(np.sqrt(np.mean((y - p1) ** 2)))],
            "mse_change_95": interval((y - p1) ** 2 - (y - p0) ** 2),
            "bias": [r3(np.mean(p0 - y)), r3(np.mean(p1 - y))],
            "placebo": {"mae_change": r3(np.sum(mae_p) / max(len(back), 1)),
                        "mse_change": r3(np.sum(mse_p) / max(len(back), 1)),
                        "returners_mae_change": r3(np.mean(np.abs(y - p1) - np.abs(y - p0))),
                        "returners_mse_change": r3(np.mean((y - p1) ** 2 - (y - p0) ** 2))}}


# --------------------------------------------------------------------------- #
# Re-measuring
# --------------------------------------------------------------------------- #

def history(seasons=SEASONS, cache: Path = None) -> tuple:
    """(weekly, snaps, ids, injuries, rosters, schedules) for `seasons`: the
    weekly points cache and nflverse (network), or parquet copies in `cache`
    (written there on the first run - keep it outside the repo)."""
    from fantasy.league import weekly_points

    seasons = [int(s) for s in seasons]
    weekly = weekly_points.load(seasons)
    frames = {}
    loaders = {
        "snaps": lambda nfl: nfl.load_snap_counts(seasons),
        "ids": lambda nfl: nfl.load_ff_playerids(),
        "injuries": lambda nfl: nfl.load_injuries(seasons),
        "rosters": lambda nfl: nfl.load_rosters_weekly(seasons),
        "schedules": lambda nfl: nfl.load_schedules(seasons),
    }
    for name, load in loaders.items():
        path = Path(cache) / f"{name}.parquet" if cache else None
        if path is not None and path.exists():
            frames[name] = pd.read_parquet(path)
            continue
        import nflreadpy as nfl
        frames[name] = load(nfl).to_pandas()
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            frames[name].to_parquet(path, index=False)
    return (weekly, frames["snaps"], frames["ids"], frames["injuries"], frames["rosters"],
            frames["schedules"])


def measure(seasons=SEASONS, cache: Path = None, draws: int = 1000) -> dict:
    """The whole measurement: the table, every cell, the injury-type and
    position checks, snap shares in the first game back, and the backtest
    both ways round."""
    weekly, snaps, ids, injuries, rosters, schedules = history(seasons, cache)
    games = player_games(weekly, snaps, ids)
    gone = absences(games, team_weeks(schedules), report_rows(injuries, rosters))
    measured = [s for s in seasons if s - 1 in seasons]
    obs = observations(games, gone, seasons=measured)
    table, cells = fit_table(obs, draws=draws)
    hurt = _hurt(obs)
    overall = {k: effect(obs, hurt & (obs["k"] == k).to_numpy(), draws=draws)
               for k in range(1, GAMES_BACK + 1)}
    half = {k: effect(obs, hurt & (obs["k"] == k).to_numpy(), y="half", base="form_half",
                      draws=draws) for k in (1, 2)}
    snaps_first = {}
    for lo, hi in ((1, 1), (2, 3), (4, 99)):
        mask = hurt & (obs["k"] == 1).to_numpy() & obs["missed"].between(lo, hi).to_numpy()
        snaps_first[f"{lo}-{hi}" if hi < 99 else f"{lo}+"] = effect(
            obs, mask, y="snap", base="snap_pre", draws=draws)
    first, last = min(measured), max(measured)
    early = tuple(s for s in measured if s in TRAIN) or tuple(measured[:len(measured) // 2])
    late = tuple(s for s in measured if s not in early)
    return {"seasons": [first, last], "table": table, "cells": cells, "overall": overall,
            "half_ppr": half, "snaps_first_game": snaps_first,
            "by_type": heterogeneity(obs, "type", draws=draws),
            "by_position": heterogeneity(obs, "pos", draws=draws),
            "backtest": backtest(obs, early, late, draws=draws),
            "backtest_reversed": backtest(obs, late, early, draws=draws)}


# --------------------------------------------------------------------------- #
# Today
# --------------------------------------------------------------------------- #

def _team_weeks_played(played: pd.DataFrame) -> dict:
    """{team: sorted weeks it has a row in} - the weeks a team has played as
    far as the data goes: a bye, or a week not in yet, has no rows."""
    return {team: sorted(set(int(w) for w in g)) for team, g in
            played.groupby("team")["week"]}


def _state(mine: dict, team_weeks: list, upcoming: int, listed=None) -> tuple | None:
    """Where a player stands against his most recent absence, from {week:
    team} he played and his team's played weeks before `upcoming`: (games
    missed, games played since, the missed weeks) - (n, 0, ...) while he is
    still out - or None when no absence is within GAMES_BACK games.

    Only weeks since his first game for his current team count, so a trade
    is not an absence, and one out since before the season has none: nothing
    before his first game is ever a gap. `listed(week)` -> was he on the
    injury report that week; an absence with no listed week is not an injury
    (None)."""
    if not mine:
        return None
    team = mine[max(mine)]
    played = {w for w, t in mine.items() if t == team}
    weeks = [w for w in team_weeks if min(played) <= w < upcoming]
    since = 0
    while weeks and weeks[-1] in played:
        weeks.pop()
        since += 1
        if since > GAMES_BACK:
            return None
    gap = []
    while weeks and weeks[-1] not in played:
        gap.append(weeks.pop())
    if not gap or (listed is not None and not any(listed(w) for w in gap)):
        return None
    return len(gap), since, sorted(gap)


def dips(board: pd.DataFrame, held: dict, weeks_left: int, played: pd.DataFrame,
         upcoming: int, reports: dict = None, sleeper_weeks: dict = None, skip=(),
         table: dict = None, min_mu: float = MIN_MU) -> dict:
    """{sleeper id: {missed, games, season, week}} for every player whose
    first games back are still ahead of a simulation drawing from week
    `upcoming` for `weeks_left` weeks.

    board          sleeper_id, pos, mu (+ bye): the season board.
    held           {sleeper id: weeks out from `upcoming`} (injury_report.held_out).
    played         this season's games before `upcoming`: week, sleeper_id,
                   team (season_played) - only players in it are considered;
                   one out since before the season is not.
    reports        {week: {sleeper id: {status, ...}}} (availability
                   .official_reports): the evidence that a player who is not
                   held now missed his games hurt. Without it only held
                   players are moved.
    sleeper_weeks  {week: {sleeper id: projected pts}} for the weeks
                   projections.with_sleeper blended. A back, receiver or tight
                   end Sleeper projected for a game back is skipped: its
                   discounted projection is already in his rate.
    skip           ids held for something other than an injury (NOT_INJURY).

    missed   games of the absence (so far + held ahead)
    games    [[game back, weeks from `upcoming` (0 = that week), dip]] ahead
    season   the dips summed over the weeks he can play - the per-game change
             for a simulation that holds one mu per player
    week     the multiplier on `upcoming` itself (1.0 if it is no game back)
    """
    from fantasy import projections

    table = TABLE if table is None else table
    if board is None or board.empty or played is None or played.empty:
        return {}
    held = {str(k): int(v) for k, v in (held or {}).items() if v}
    skip = {str(p) for p in skip or ()}
    sleeper_weeks = sleeper_weeks or {}
    frame = played.dropna(subset=["sleeper_id"]).copy()
    frame["sleeper_id"] = frame["sleeper_id"].astype(str)
    frame = frame[frame["week"] < upcoming]
    by_team = _team_weeks_played(frame)
    mine_of = {pid: dict(zip(g["week"].astype(int), g["team"]))
               for pid, g in frame.groupby("sleeper_id")}

    def listed_for(pid):
        if reports is None:
            return None
        return lambda w: (reports.get(int(w)) or {}).get(pid) is not None

    out = {}
    rows = board.drop_duplicates("sleeper_id")
    byes = rows["bye"] if "bye" in rows else pd.Series(0, index=rows.index)
    for pid, pos, mu, bye in zip(rows["sleeper_id"].astype(str), rows["pos"], rows["mu"], byes):
        if pos not in SKILL or pd.isna(mu) or float(mu) < min_mu or pid in skip:
            continue
        mine = mine_of.get(pid)
        if not mine:
            continue
        bye = int(bye) if pd.notna(bye) else 0
        team = mine[max(mine)]
        hold = held.get(pid, 0)
        if hold:
            # Held now: the hold is the evidence. The games still to miss
            # are the held weeks less his bye, if it falls among them.
            state = _state(mine, by_team.get(team, []), upcoming)
            so_far = state[0] if state and not state[1] else 0
            missed = so_far + hold - (1 if upcoming <= bye < upcoming + hold else 0)
            first, at, returned = 1, hold, None
        else:
            if reports is None:
                continue
            state = _state(mine, by_team.get(team, []), upcoming, listed_for(pid))
            if state is None:
                continue
            missed, since, gap = state
            first, at, returned = since + 1, 0, max(gap) + 1
        if missed < 1:
            continue
        games = []
        for k in range(first, GAMES_BACK + 1):
            while bye and upcoming + at == bye:
                at += 1                         # his bye comes first
            d = dip(missed, k, table)
            if d and at < weeks_left:
                games.append([k, at, d])
            at += 1
        if not games:
            continue
        if returned is not None and pos in projections.SLEEPER_POSITIONS and any(
                ((sleeper_weeks.get(w) or {}).get(pid) or 0) > 0
                for w in sleeper_weeks if w >= returned):
            continue                            # Sleeper's discount is in his rate already
        playable = max(int(weeks_left) - hold, 1)
        out[pid] = {"missed": int(missed),
                    "games": [[int(k), int(a), round(float(d), 3)] for k, a, d in games],
                    "season": round(sum(d for _, _, d in games) / playable, 4),
                    "week": round(1.0 + sum(d for _, a, d in games if a == 0), 3)}
    return out


def apply(board: pd.DataFrame, result: dict) -> pd.DataFrame:
    """`board` with each returning player's mu scaled by his `season` dip -
    for a simulation that holds one mu per player."""
    if not result:
        return board
    board = board.copy()
    change = board["sleeper_id"].astype(str).map(
        lambda pid: result[pid]["season"] if pid in result else 0.0)
    board["mu"] = (board["mu"] * (1.0 + change)).clip(lower=0.0)
    return board


def season_played(year: int, through_week: int) -> pd.DataFrame:
    """This season's games through `through_week` (week, sleeper_id, team):
    nflverse's weekly points and Sleeper's usage (a row with an offensive
    snap), whichever has him - read from their caches, never fetched."""
    from fantasy.league import usage
    from fantasy.league.opportunity import season_games

    frames = [season_games(year, through_week)]
    try:
        u = usage.load(year)
        if len(u):
            u = u[(u["week"] <= through_week) & (u["off_snp"] > 0)]
            frames.append(u[["week", "sleeper_id", "team"]])
    except Exception as exc:                                # noqa: BLE001
        print(f"  ! usage unavailable for the return dip ({exc})")
    frame = pd.concat(frames, ignore_index=True)
    if frame.empty:
        return pd.DataFrame(columns=["week", "sleeper_id", "team"])
    frame["sleeper_id"] = frame["sleeper_id"].astype(str)
    frame["week"] = frame["week"].astype(int)
    return frame.drop_duplicates(["week", "sleeper_id"])


def _sleeper_weeks(year: int, through_week: int) -> dict:
    """{week: {id: pts}} for the window projections.with_sleeper blends after
    `through_week` (its own cached fetch, so nothing is fetched twice)."""
    from fantasy import projections

    if not through_week:
        return {}
    upcoming = min(int(through_week) + 1, 18)
    out = {}
    for week in range(max(1, upcoming - projections.SLEEPER_WEEKS + 1), upcoming + 1):
        try:
            out[week] = projections._sleeper_week(int(year), week)
        except Exception as exc:                            # noqa: BLE001
            print(f"  ! Sleeper week {week} unavailable for the return dip ({exc})")
    return out


def not_injured(tags: dict = None, report: dict = None) -> set:
    """Ids held for something other than an injury, from Sleeper's tags and
    ESPN's report (fantasy.league.injury_report.report())."""
    out = {str(p) for p, t in (tags or {}).items() if t in NOT_INJURY}
    out |= {str(p) for p, e in (report or {}).items() if (e or {}).get("status") in NOT_INJURY}
    return out


def _reports(year: int) -> dict | None:
    from fantasy.league import availability
    got = availability.official_reports(year)
    return got or None


def for_board(board: pd.DataFrame, held: dict, year: int, through_week: int,
              weeks_left: int, tags: dict = None, sleeper_through: int = None) -> dict:
    """`dips` with this season's games, the official reports, Sleeper's window
    and the non-injury holds filled in - what a builder holding the board
    (current_form + with_sleeper) and injury_report.held_out(..., from_week=
    `through_week`) calls, beside opportunity.for_board. `sleeper_through` is
    the week with_sleeper was given, where it is not `through_week`."""
    try:
        from fantasy.league import injury_report
        report = injury_report.report()
    except Exception:                                       # noqa: BLE001
        report = {}
    window = through_week if sleeper_through is None else sleeper_through
    return dips(board, held, weeks_left, played=season_played(year, through_week),
                upcoming=int(through_week) + 1, reports=_reports(year),
                sleeper_weeks=_sleeper_weeks(year, window),
                skip=not_injured(tags, report))


def week_factors(board: pd.DataFrame, year: int, week: int, played: pd.DataFrame = None,
                 reports: dict = None, tags: dict = None) -> dict:
    """{sleeper id: multiplier} on the projection for `week` of every player
    for whom it is a game back - for the pages that project one week from the
    form-only board (matchups' GordStats column, the Team page); pass it to
    availability.apply(..., dips=). Nobody Sleeper's window has to be skipped
    for: those pages do not blend Sleeper's projections."""
    played = season_played(year, int(week) - 1) if played is None else played
    reports = _reports(year) if reports is None else reports
    got = dips(board, {}, 1, played=played, upcoming=int(week), reports=reports,
               skip=not_injured(tags))
    return {pid: v["week"] for pid, v in got.items() if v["week"] != 1.0}


def _today(top: int = 30) -> None:
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
    try:
        tags = json.loads(season_board.INJURY_CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        tags = {}
    held = injury_report.held_out(tags, from_week=weeks, weeks=NFL_WEEKS, year=year)
    result = for_board(board, held, year, weeks, season_board.SEASON_WEEKS - weeks, tags=tags)
    names = dict(zip(board["sleeper_id"].astype(str), board["player"]))
    print(f"{len(result)} players with games back ahead of week {weeks + 1}")
    for pid, r in sorted(result.items(), key=lambda kv: kv[1]["season"])[:top]:
        games = ", ".join(f"game {k} in {at} wk {d:+.0%}" for k, at, d in r["games"])
        print(f"  {names.get(pid, pid):<24} missed {r['missed']:>2}  {games:<44} "
              f"season {r['season']:+.2%}")


def _print_measure(report: dict) -> None:
    pct = lambda v: "   n/a" if v is None else f"{100 * v:+6.1f}%"      # noqa: E731

    def line(label, e):
        print(f"  {label:<26} {pct(e['effect'])} ({pct(e['lo'])} .. {pct(e['hi'])})  "
              f"n={e['n']}, {e['players']} players")

    print(f"Measured {report['seasons'][0]}-{report['seasons'][1]}")
    for k, e in report["overall"].items():
        line(f"game {k} back, all", e)
    for (b, k), e in sorted(report["cells"].items()):
        line(f"game {k} back, missed {'1' if b == 1 else '2+'}", e)
    for k, e in report["half_ppr"].items():
        line(f"game {k} back, half-PPR", e)
    for band, e in report["snaps_first_game"].items():
        line(f"snap share g1, missed {band}", e)
    for name in ("by_type", "by_position"):
        rows, q, df, p = report[name]
        print(f"\n{name}: Q={q} df={df} p={p}")
        for r in rows:
            key = r.get("type") or r.get("pos")
            line(str(key), r)
    for name in ("backtest", "backtest_reversed"):
        b = report[name]
        print(f"\n{name}: fit {b['train']} test {b['test']}, {b['n']} games back "
              f"({b['moved']} moved), table {b['table']}")
        print(f"  MAE {b['mae'][0]} -> {b['mae'][1]} (change 95% {b['mae_change_95']}); RMSE "
              f"{b['rmse'][0]} -> {b['rmse'][1]} (MSE change 95% {b['mse_change_95']}); bias "
              f"{b['bias'][0]} -> {b['bias'][1]}")
        print(f"  placebo on matched control games: {b['placebo']}")
    print(f"\nTABLE = {report['table']}")


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("--measure", action="store_true", help="Re-measure 2018-2025 and print it.")
    p.add_argument("--cache", type=Path, help="Keep nflverse's inputs here (outside the repo).")
    p.add_argument("--draws", type=int, default=1000)
    args = p.parse_args()
    if args.measure:
        _print_measure(measure(cache=args.cache, draws=args.draws))
    else:
        _today()


if __name__ == "__main__":
    main()
