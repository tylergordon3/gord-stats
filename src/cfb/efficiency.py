"""
Opponent-adjusted efficiency: what the box score adds to a rating built from
final scores.

`cfb.ratings` knows who won and by how much. CFBD's per-game advanced stats
(/stats/game/advanced, one call a season) know how: EPA per play, success
rate, explosiveness, line yards, stuff rate, split by down and by run or pass.
Each is opponent-adjusted the way the ratings are - a weighted ridge over every
team-game before the date in question, offence and defence apart, older games
counting for less - and the difference between the two sides becomes a
correction to the ratings' margin:

    margin = a + b * ratings_margin + sum_m c_m * [(O_h - D_h) - (O_a - D_a)]_m

Measured walk-forward on the 4,238 FBS-vs-FBS games of 2020-2025, the
correction refitted each season on every season before it, exactly as it is
used:

    ratings alone        margin RMSE 16.18   winners 71.5%
    with this            margin RMSE 16.07   winners 72.0%, better in all six seasons
    the closing line     margin RMSE 15.38

Against the spread it still covers under half the games where it parts from
the line by 3+ (49.5%, break-even 52.4%): more accurate, not an edge. Totals
barely move (16.28 -> 16.26) and are left to the ratings.

Tried on 2015-2019 and not kept: garbage time excluded (worse, 16.38 against
16.34), a 120- or 180-day half-life (worse), and CFBD's Elo and recruiting
talent as further inputs (-0.05 on 2020-2025 with a 95% interval spanning
zero). The adjusted numbers track CFBD's own weekly training file closely -
this season through week 4, r = 0.88 for EPA per play and 0.90 for success
rate - with CFBD working from plays and this from game totals.

    data/cfb/advanced/<season>.parquet   one row per FBS team per game
    data/cfb/efficiency_stack.json       a, b, c_m and how they scored

    python -m cfb.efficiency --fetch     backfill and refresh the archive
"""
import json
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import scipy.sparse as sp
from sklearn.linear_model import Ridge, RidgeCV

from cfb.config import DATA_DIR, SEASON

ARCHIVE = DATA_DIR / "advanced"
TEAMS_PATH = DATA_DIR / "cfbd" / "teams.json"
STACK_PATH = DATA_DIR / "efficiency_stack.json"

FIRST_SEASON = 2014
STACK_FIRST = 2015             # the first season with a year of history behind it
CURRENT_AGE_HOURS = 6          # this season's file refetched at most this often

METRICS = ["ppa", "successRate", "explosiveness", "rushingPlays_ppa", "passingPlays_ppa",
           "standardDowns_successRate", "passingDowns_successRate", "lineYards",
           "secondLevelYards", "openFieldYards", "stuffRate", "powerSuccess", "plays"]
HALF_LIFE = 60.0               # days; chosen on 2015-2019 from 60 / 120 / 180 / 365
ALPHA = 1.0                    # ridge on the team terms, chosen with it
WINDOW_DAYS = 730
POOLED = "FCS"
_PAUSE = 0.6                   # CFBD answers 429 to a burst


# --------------------------------------------------------------------------- #
# The archive
# --------------------------------------------------------------------------- #

def _flat(rec: dict) -> dict:
    row = {"game_id": str(rec["gameId"]), "season": rec["season"], "week": rec["week"],
           "season_type": rec["seasonType"], "team": rec["team"], "opponent": rec["opponent"]}
    for side in ("offense", "defense"):
        block = rec.get(side) or {}
        for m in METRICS:
            head, _, tail = m.partition("_")
            v = (block.get(head) or {}).get(tail) if tail else block.get(head)
            row[f"{side}_{m}"] = v
    return row


def _get(path: str, **params):
    from cfb import cfbd
    for attempt in range(5):
        time.sleep(_PAUSE)
        try:
            return cfbd.get(path, **params)
        except Exception as exc:                        # noqa: BLE001
            if "429" not in str(exc) or attempt == 4:
                raise
            time.sleep(5 * (attempt + 1))


def archive(season: int, refresh: bool = False) -> pd.DataFrame:
    """One season's team-games. A finished season is fetched once; this one
    is refetched when its file is older than CURRENT_AGE_HOURS, and a failed
    fetch keeps the last copy."""
    path = ARCHIVE / f"{season}.parquet"
    stale = (not path.exists() or refresh
             or (season >= SEASON
                 and time.time() - path.stat().st_mtime > CURRENT_AGE_HOURS * 3600))
    if stale:
        try:
            rows = [_flat(r) for st in ("regular", "postseason")
                    for r in _get("stats/game/advanced", year=season, seasonType=st)]
            if rows:
                path.parent.mkdir(parents=True, exist_ok=True)
                pd.DataFrame(rows).to_parquet(path, index=False)
        except Exception as exc:                        # noqa: BLE001
            print(f"  ! CFBD advanced stats {season} not refreshed ({exc})")
    return pd.read_parquet(path) if path.exists() else pd.DataFrame()


def teams() -> tuple:
    """({CFBD school name: ESPN id}, {FBS ids}). CFBD's team ids are ESPN's."""
    if not TEAMS_PATH.exists() or time.time() - TEAMS_PATH.stat().st_mtime > 30 * 86400:
        try:
            got = _get("teams")
            TEAMS_PATH.parent.mkdir(parents=True, exist_ok=True)
            TEAMS_PATH.write_text(json.dumps(
                [{"id": t["id"], "school": t["school"], "classification": t.get("classification")}
                 for t in got]), encoding="utf-8")
        except Exception as exc:                        # noqa: BLE001
            print(f"  ! CFBD teams not refreshed ({exc})")
    if not TEAMS_PATH.exists():
        return {}, set()
    rows = json.loads(TEAMS_PATH.read_text(encoding="utf-8"))
    return ({t["school"]: str(t["id"]) for t in rows},
            {str(t["id"]) for t in rows if t.get("classification") == "fbs"})


def load(last: int = SEASON) -> pd.DataFrame:
    frames = [archive(s) for s in range(FIRST_SEASON, last + 1)]
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# --------------------------------------------------------------------------- #
# Adjusting
# --------------------------------------------------------------------------- #

def observations(games: pd.DataFrame, adv: pd.DataFrame = None) -> pd.DataFrame:
    """One row per offence facing a defence in a game: `off`, `dfn` (ESPN
    ids), `date`, `home` (+1, -1, 0 neutral) and a column per metric.

    `games` supplies the dates and the home side (game_id, date, home_id,
    neutral). A team with its own row gives its offence; an opponent without
    one - an FCS side - gets its offence from the FBS team's defence block."""
    adv = load() if adv is None else adv
    to_id, _fbs = teams()
    if adv.empty or not to_id:
        return pd.DataFrame()
    g = games.drop_duplicates("game_id").set_index(games.drop_duplicates("game_id")["game_id"].astype(str))
    adv = adv[adv["game_id"].astype(str).isin(g.index)].copy()
    adv["team_id"] = adv["team"].map(to_id)
    adv["opp_id"] = adv["opponent"].map(to_id)
    have = set(zip(adv["game_id"], adv["team_id"]))
    parts = []
    for prefix, off, dfn, rows in (
            ("offense_", "team_id", "opp_id", adv),
            ("defense_", "opp_id", "team_id",
             adv[[(gid, o) not in have for gid, o in zip(adv["game_id"], adv["opp_id"])]])):
        cols = {f"{prefix}{m}": m for m in METRICS}
        parts.append(rows[["game_id", off, dfn] + list(cols)]
                     .rename(columns={off: "off", dfn: "dfn", **cols}))
    obs = pd.concat(parts, ignore_index=True)
    obs["date"] = obs["game_id"].map(g["date"])
    home_id = obs["game_id"].map(g["home_id"]).astype(str)
    neutral = obs["game_id"].map(g["neutral"]).fillna(False).astype(bool)
    obs["home"] = np.where(neutral, 0.0, np.where(obs["off"].astype(str) == home_id, 1.0, -1.0))
    return obs.dropna(subset=["date"])


def fit(obs: pd.DataFrame, asof, fbs: set = None) -> dict:
    """{metric: (league mean, {team: offence}, {team: defence})} from
    team-games before `asof`, each weighted 0.5 ** (age / HALF_LIFE).
    Offence is what the team produces above the mean, defence what it allows.
    Non-FBS sides are pooled."""
    if obs.empty:
        return {}
    fbs = teams()[1] if fbs is None else fbs
    w = obs[(obs["date"] < asof) & (obs["date"] >= asof - pd.Timedelta(days=WINDOW_DAYS))]
    if len(w) < 200:
        return {}
    off = w["off"].astype(str).where(w["off"].astype(str).isin(fbs), POOLED)
    dfn = w["dfn"].astype(str).where(w["dfn"].astype(str).isin(fbs), POOLED)
    names = sorted(set(off) | set(dfn))
    idx = {t: i for i, t in enumerate(names)}
    n, k = len(w), len(names)
    r = np.arange(n)
    X = sp.hstack([sp.csr_matrix((np.ones(n), (r, off.map(idx).to_numpy())), shape=(n, k)),
                   sp.csr_matrix((np.ones(n), (r, dfn.map(idx).to_numpy())), shape=(n, k)),
                   sp.csr_matrix(w["home"].to_numpy(float).reshape(-1, 1))]).tocsr()
    age = (asof - w["date"]).dt.total_seconds().to_numpy() / 86400
    weight = 0.5 ** (age / HALF_LIFE)
    out = {}
    for m in METRICS:
        y = pd.to_numeric(w[m], errors="coerce").to_numpy(float)
        ok = ~np.isnan(y)
        if ok.sum() < 200:
            continue
        model = Ridge(alpha=ALPHA).fit(X[ok], y[ok], sample_weight=weight[ok])
        out[m] = (float(model.intercept_), dict(zip(names, model.coef_[:k])),
                  dict(zip(names, model.coef_[k:2 * k])))
    return out


def edges(fitted: dict, ids) -> pd.DataFrame:
    """Per team and metric, offence less defence allowed - the separable part
    of a matchup: a game's feature is home's edge less away's."""
    rows = []
    for t in ids:
        t = str(t)
        row = {}
        for m, (_mu, O, D) in fitted.items():
            o = O.get(t, O.get(POOLED, 0.0))
            d = D.get(t, D.get(POOLED, 0.0))
            row[f"d_{m}"] = o - d
        rows.append(row)
    return pd.DataFrame(rows, columns=[f"d_{m}" for m in METRICS])


def differences(fitted: dict, home_ids, away_ids) -> pd.DataFrame:
    """Each game's (O_h + D_a) - (O_a + D_h) per metric: how much more of it
    the home offence should produce against this defence than the away one."""
    return edges(fitted, home_ids) - edges(fitted, away_ids)


# --------------------------------------------------------------------------- #
# The correction
# --------------------------------------------------------------------------- #

FEATURES = ["pred_margin"] + [f"d_{m}" for m in METRICS]


def load_stack() -> dict:
    try:
        return json.loads(STACK_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def apply(stack: dict, frame: pd.DataFrame) -> np.ndarray:
    coef = stack["coef"]
    return stack["intercept"] + sum(coef[c] * frame[c].to_numpy(float) for c in FEATURES)


def team_values(history: pd.DataFrame, asof, ids, stack: dict = None) -> dict:
    """{team: its share of the correction} - sum_m c_m * (O - D)_m, fitted on
    `history` (game_id, date, home_id, neutral) before `asof`. A game's
    correction is the home side's value less the away side's."""
    stack = load_stack() if stack is None else stack
    if not stack:
        return {}
    fitted = fit(observations(history), asof)
    if len(fitted) < len(METRICS):
        raise ValueError(f"{len(fitted)} of {len(METRICS)} metrics fitted")
    ids = [str(i) for i in ids]
    e = edges(fitted, ids)
    coef = stack["coef"]
    vals = sum(coef[f"d_{m}"] * e[f"d_{m}"].to_numpy(float) for m in METRICS)
    return dict(zip(ids, (float(v) for v in vals)))


class Corrected:
    """A fitted `cfb.ratings.Ratings` with the correction folded in.

    `rating` is the team's strength on the corrected margins' scale - b times
    its rating plus its efficiency value - so a ranking sorts the way the
    predictions lean; `predict` returns the corrected margins with the
    ratings' totals, and the scores split from the two. Everything else is
    the ratings model's own."""

    def __init__(self, base, intercept: float, b: float, values: dict):
        self.base, self.intercept, self.b, self.values = base, intercept, b, values
        self.teams = base.teams

    def __getattr__(self, name):
        return getattr(self.base, name)

    def value(self, team) -> float:
        return self.values.get(str(team), self.values.get(POOLED, 0.0))

    def rating(self, team) -> float:
        return self.b * self.base.rating(team) + self.value(team)

    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        out = self.base.predict(frame)
        edge = (frame["home_team"].map(self.value).to_numpy(float)
                - frame["away_team"].map(self.value).to_numpy(float))
        out["pred_margin"] = self.intercept + self.b * out["pred_margin"].to_numpy(float) + edge
        out["pred_home"] = (out["pred_total"] + out["pred_margin"]) / 2.0
        out["pred_away"] = (out["pred_total"] - out["pred_margin"]) / 2.0
        return out


def corrected(model, history: pd.DataFrame, asof, stack: dict = None):
    """`model` with the correction as it stood at `asof`, or `model` itself -
    said so - when the stack or the archive cannot be read: the ratings stand
    on their own."""
    stack = load_stack() if stack is None else stack
    if not stack:
        return model
    try:
        values = team_values(history, asof, model.teams, stack)
    except Exception as exc:                            # noqa: BLE001
        print(f"  ! efficiency correction skipped ({exc}); ratings alone")
        return model
    return Corrected(model, stack["intercept"], stack["coef"]["pred_margin"], values)


# --------------------------------------------------------------------------- #
# Fitting and scoring the correction (cfb.backtest --report)
# --------------------------------------------------------------------------- #

def walk_forward_features(games: pd.DataFrame, base: pd.DataFrame) -> pd.DataFrame:
    """`base` (backtest.walk_forward rows) with each game's efficiency
    differences as they stood before its week's first kickoff - the same
    moment the ratings were fitted."""
    obs = observations(games)
    _to_id, fbs = teams()
    keyed = games[["season", "date", "home_team", "away_team", "game_id", "home_id", "away_id"]]
    rows = base.merge(keyed, on=["season", "date", "home_team", "away_team"], how="left")
    parts = []
    for (_season, _week), block in rows.groupby(["season", "week"], sort=True):
        asof = block["date"].min()
        fitted = fit(obs, asof, fbs)
        if len(fitted) < len(METRICS):
            continue
        feats = differences(fitted, block["home_id"], block["away_id"])
        feats.index = block.index
        parts.append(block.join(feats))
    return pd.concat(parts) if parts else pd.DataFrame()


def fit_stack(rows: pd.DataFrame) -> dict:
    model = RidgeCV(alphas=np.logspace(-2, 4, 25)).fit(rows[FEATURES], rows["margin"])
    return {"intercept": float(model.intercept_),
            "coef": dict(zip(FEATURES, (float(c) for c in model.coef_))),
            "alpha": float(model.alpha_)}


def validate(rows: pd.DataFrame, test: tuple) -> pd.DataFrame:
    """Each test season predicted by a stack fitted on every season before
    it, from STACK_FIRST - how it is used, one season behind. FBS vs FBS."""
    scored = rows[(rows["home_team"] != POOLED) & (rows["away_team"] != POOLED)]
    out = []
    for season in range(test[0], test[1] + 1):
        train = scored[scored["season"].between(STACK_FIRST, season - 1)]
        target = scored[scored["season"] == season]
        if train.empty or target.empty:
            continue
        stack = fit_stack(train)
        out.append(target.assign(pred_margin=apply(stack, target)))
    return pd.concat(out) if out else pd.DataFrame()


def write_stack(rows: pd.DataFrame, through: int, validation: dict) -> dict:
    scored = rows[(rows["home_team"] != POOLED) & (rows["away_team"] != POOLED)
                  & rows["season"].between(STACK_FIRST, through)]
    stack = fit_stack(scored)
    stack.update({"fitted_on": f"{STACK_FIRST}-{through}", "games": int(len(scored)),
                  "half_life_days": HALF_LIFE, "alpha_team": ALPHA,
                  "written": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                  "validation": validation})
    STACK_PATH.write_text(json.dumps(stack, indent=2) + "\n", encoding="utf-8")
    return stack


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--fetch", action="store_true", help="backfill and refresh the archive")
    args = p.parse_args()
    if args.fetch:
        teams()
        for s in range(FIRST_SEASON, SEASON + 1):
            print(s, len(archive(s)))
