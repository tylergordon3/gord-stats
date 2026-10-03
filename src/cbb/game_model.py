"""
College basketball game predictions: each side's expected points and the home
side's chance, from Bart Torvik's adjusted efficiencies and tempo.

The standard possession model, the one T-Rank and KenPom both publish in some
form: a game's pace is the product of the two teams' adjusted tempos over the
average; each side scores its adjusted offence times the other's adjusted
defence over the average efficiency, per hundred possessions; home court adds
a fixed edge. Three constants per league are fitted on a finished season,
walked forward - each game predicted from the last ratings published before it
(see `backtest`):

    home_edge   points the home side is worth (none at a neutral site)
    scale       how much the raw margin under-calls results (they run wider)
    sd          the spread of results around the predicted margin, which
                turns a margin into a win chance

On 2025-26: men 5,315 D-1 games from Nov 12, 70.2% of winners, results
11.6 points either side of the call; women 3,827 from Dec 17, 75.3%, 12.0.
theScore marks no neutral sites, so a tournament game logged as "home"
counts as one: the fitted home edge (2.5 / 2.7) is a shade under the usual
3-3.5 for that reason.

    python -m cbb.game_model --backtest          # refit on last season

The live scoreboard (cbb.live_scraper) and the home page's My teams card show
it; the betting lines kept since 2026-27 (cbb.lines) are what it will be graded
against.
"""
import argparse
import json
import math
from datetime import date
from pathlib import Path

from cbb import constants, paths, teams, utils

# Fitted by `backtest` on 2025-26 (see the module docstring); refit yearly.
FIT = {"M": {"home_edge": 2.53, "scale": 1.071, "sd": 11.59},
       "W": {"home_edge": 2.67, "scale": 1.117, "sd": 11.97}}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def ratings(snapshot: dict) -> dict:
    """{site team name: (adj_o, adj_d, tempo)} from one Torvik table
    ({headers, rows}, as cbb.scrape.torvik saves them)."""
    h = snapshot["headers"]
    i_team, i_o, i_d, i_t = h.index("Team"), h.index("AdjOE"), h.index("AdjDE"), h.index("Adj T.")
    out = {}
    for r in snapshot["rows"]:
        name = teams.cleanTorvikNames(r[i_team]).strip()
        name = constants.TORVIK_RENAMES.get(name, name)
        o, d, t = _num(r[i_o]), _num(r[i_d]), _num(r[i_t])
        if None not in (o, d, t):
            out[name] = (o, d, t)
    return out


def _averages(table: dict) -> tuple:
    vals = list(table.values())
    eff = sum(v[0] for v in vals) / len(vals)
    tempo = sum(v[2] for v in vals) / len(vals)
    return eff, tempo


def raw(home: str, away: str, table: dict, avgs: tuple = None) -> tuple | None:
    """(home points, away points) on a neutral floor, or None if either side
    is not in the table (a non-D1 opponent)."""
    if home not in table or away not in table:
        return None
    eff, pace = avgs or _averages(table)
    ho, hd, ht = table[home]
    ao, ad, at = table[away]
    poss = ht * at / pace
    return ho * ad / eff * poss / 100, ao * hd / eff * poss / 100


def predict(home: str, away: str, table: dict, neutral: bool = False,
            gender: str = "M", avgs: tuple = None) -> dict | None:
    """{pred_home, pred_away, home_win_prob} for one game, or None when either
    side is not rated (a non-D1 opponent)."""
    pts = raw(home, away, table, avgs)
    if pts is None:
        return None
    fit = FIT[gender]
    margin = fit["scale"] * (pts[0] - pts[1]) + (0.0 if neutral else fit["home_edge"])
    total = pts[0] + pts[1]
    prob = 0.5 * (1 + math.erf(margin / (fit["sd"] * math.sqrt(2))))
    return {"pred_home": round((total + margin) / 2, 1), "pred_away": round((total - margin) / 2, 1),
            "home_win_prob": round(prob, 3)}


def today_table(gender: str = "M", day: date = None) -> dict:
    """This season's newest Torvik table as ratings(), or {} - never last
    season's (utils.latest_this_season). Both leagues fall back on T-Rank's
    own table until the daily snapshots begin (its preseason projections,
    then its current ratings): the daily snapshot needs Torvik's four-factor
    file, which he posts only once games are played."""
    folder = paths.M_TOR_DIR if gender == "M" else paths.W_TOR_DIR
    path = utils.latest_this_season(folder, day)
    if path:
        return ratings(json.loads(path.read_text(encoding="utf-8")))
    return trank_table(day) if gender == "M" else trank_table(day, "W")


def trank_table(day: date = None, gender: str = "M") -> dict:
    """ratings() from T-Rank's team results - the CBB power page's cache
    (the women's beside it, render_power.trank_women), refreshed twice a day
    all year - if it is this season's."""
    import pandas as pd
    from cbb.render import render_power

    path = render_power._cache_path() if gender == "M" else render_power._cache_path_w()
    if render_power.TRANK_YEAR != utils.season_year(day or date.today()) or not path.exists():
        return {}
    df = pd.read_csv(path, usecols=["team", "adjoe", "adjde", "adjt"])
    out = {}
    for r in df.itertuples(index=False):
        name = constants.TORVIK_RENAMES.get(str(r.team).strip(), str(r.team).strip())
        if not any(pd.isna(v) for v in (r.adjoe, r.adjde, r.adjt)):
            out[name] = (float(r.adjoe), float(r.adjde), float(r.adjt))
    return out


def trank_ranks(gender: str = "M", day: date = None) -> dict:
    """{site team name: T-Rank's rank} from the same cache as trank_table, if
    it is this season's, else {}. The scoreboard carries it beside GordStats'
    own rank, which needs the bracketology models' inputs (KenPom's season and
    Torvik's four factors) and so is blank for the first week or more of a
    season: the watch guide ranks games on T-Rank's until it is there."""
    from cbb.render import render_power

    if render_power.TRANK_YEAR != utils.season_year(day or date.today()):
        return {}
    df = render_power.cached(gender)
    if df is None or "rank" not in df or "team" not in df:
        return {}
    out = {}
    for team, rank in zip(df["team"], df["rank"]):
        try:
            rank = int(rank)
        except (TypeError, ValueError):
            continue
        name = str(team).strip()
        out[constants.TORVIK_RENAMES.get(name, name)] = rank
    return out


# --------------------------------------------------------------------------- #
# Fitting
# --------------------------------------------------------------------------- #

def _games(schedule_path: Path) -> list:
    """[(date, home, away, home_score, away_score)] once each, from the
    per-team season file - each game appears in both teams' logs."""
    sched = json.loads(schedule_path.read_text(encoding="utf-8"))
    seen, out = set(), []
    for team, log in sched.items():
        for day, g in log.items():
            if g.get("location") != "home" or g.get("score") is None:
                continue
            key = (day, team, g["opponent"])
            if key in seen:
                continue
            seen.add(key)
            out.append((day, team, g["opponent"], float(g["score"]), float(g["opponent_score"])))
    return sorted(out)


def backtest(snap_dir: Path = paths.M_TOR_DIR, schedule: Path = paths.M_SCHEDULE) -> dict:
    """Walk last season forward: every game between two D-1 teams predicted
    from the last Torvik table published before its day. Fits the home edge and a
    scale on the raw margin by least squares, then the sd from what is left,
    and reports how the fitted model does (RMSE, winners called)."""
    snaps = sorted(snap_dir.glob("*.json"))
    tables = [(p.stem, ratings(json.loads(p.read_text(encoding="utf-8")))) for p in snaps]
    rows = []
    j = -1
    for day, home, away, hs, as_ in _games(schedule):
        while j + 1 < len(tables) and tables[j + 1][0] < day:
            j += 1
        if j < 0:
            continue                    # before the first table of the season
        table = tables[j][1]
        pts = raw(home, away, table)
        if pts is not None:
            rows.append((pts[0] - pts[1], hs - as_))
    n = len(rows)
    sx = sum(x for x, _ in rows); sy = sum(y for _, y in rows)
    sxx = sum(x * x for x, _ in rows); sxy = sum(x * y for x, y in rows)
    scale = (n * sxy - sx * sy) / (n * sxx - sx * sx)
    edge = (sy - scale * sx) / n
    resid = [y - (scale * x + edge) for x, y in rows]
    sd = math.sqrt(sum(r * r for r in resid) / (n - 2))
    unscaled = math.sqrt(sum((y - (x + edge)) ** 2 for x, y in rows) / n)
    right = sum(1 for x, y in rows if (scale * x + edge > 0) == (y > 0) and y != 0)
    return {"games": n, "home_edge": round(edge, 2), "scale": round(scale, 3),
            "margin_sd": round(sd, 2), "rmse_scale_1": round(unscaled, 2),
            "winners": round(right / n, 4), "from": tables[0][0] if tables else None}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="CBB game predictions.")
    ap.add_argument("--backtest", action="store_true")
    ap.add_argument("--women", action="store_true")
    args = ap.parse_args()
    if args.backtest:
        if args.women:
            print(backtest(paths.W_TOR_DIR, paths.W_SCHEDULE))
        else:
            print(backtest())
