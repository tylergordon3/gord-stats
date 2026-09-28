"""
The rest of the college fantasy season, played out: wins, playoffs, titles.

League power used to be one number per roster - its best lineup in projected
season points - which counted games already played, knew nothing of the
schedule, and could not say who was actually going to make the playoffs. This
plays the season that is left, many times over:

  * every remaining week, each roster starts its best lineup on that week's
    projections (cfb.weekly: the in-season board, byes, the opponent through
    the game model's predicted score, injuries for the week at hand);
  * the week being played uses the lineup Yahoo has set, each starter's points
    so far plus the unplayed share of his projection by his game's clock;
  * a player's week scatters around its projection with sd SD_SHARE of it
    (floor SD_FLOOR) - measured on weeks 1-4 of 2026, where it reproduces the
    34-point spread of real lineup totals against their projection;
  * a week is won head to head and, in this league, again against the median;
    the wins land on top of Yahoo's standings, and the bracket - its size,
    byes and reseeding from Yahoo's settings - is played out from the seeds.

    python -m cfb.league_sim
"""
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from cfb import in_season, predict, weekly, yahoo
from cfb.config import LEAGUE_KEY

SIMS = 20000
SD_SHARE = 0.55
SD_FLOOR = 2.0
SEED = 20260928


def _sd(proj) -> np.ndarray:
    return np.maximum(SD_FLOOR, SD_SHARE * np.asarray(proj, float))


def schedule(lg: dict) -> dict:
    """{week: {"start", "end", "pairs": [(key, key), ...]}} for every week left,
    regular season and playoffs. Yahoo sets the regular season's pairings in
    advance; playoff weeks have none until they arrive, and their windows run
    on a week at a time from the last one it has given."""
    out = {}
    last = None
    playoff_start = int(lg["playoff_start_week"] or lg["end_week"] + 1)
    for week in range(int(lg["current_week"]), int(lg["end_week"]) + 1):
        pairs, start, end = [], None, None
        try:
            data = (yahoo.week_matchups(week) if week in yahoo.archived_weeks()
                    else yahoo._parse_scoreboard(yahoo._get(
                        f"league/{LEAGUE_KEY}/scoreboard;week={week}")))
        except Exception:                               # noqa: BLE001
            data = {"matchups": []}
        first = data["matchups"][0] if data.get("matchups") else {}
        start = data.get("week_start") or first.get("week_start")
        end = data.get("week_end") or first.get("week_end")
        # Head-to-head pairings count only in the regular season; the bracket
        # makes its own from the seeds.
        if week < playoff_start:
            for m in data.get("matchups") or []:
                keys = [t["team_key"] for t in m["teams"]]
                if len(keys) == 2:
                    pairs.append(tuple(keys))
        if not start and last:
            s = datetime.strptime(last[0], "%Y-%m-%d") + timedelta(days=7)
            e = datetime.strptime(last[1], "%Y-%m-%d") + timedelta(days=7)
            start, end = s.strftime("%Y-%m-%d"), e.strftime("%Y-%m-%d")
        if start:
            last = (start, end)
            out[week] = {"start": start, "end": end, "pairs": pairs}
    return out


def _best(players: pd.DataFrame, lg: dict) -> list:
    """The best lineup by this week's projection (cfb.site.league_power's fill)."""
    from cfb.site.league_power import best_lineup
    frame = players.assign(proj=players["proj_week"].fillna(0.0), vorp=0.0, playoff_ratio=1.0)
    return best_lineup(frame, lg)["starters"]


def _live_week(week: int, wk: pd.DataFrame, frame: pd.DataFrame) -> dict:
    """{team_key: (mean, variance)} for the week being played: the starters
    Yahoo has set, each at his points so far plus the unplayed share of his
    projection. Empty until the week has anything on the board."""
    from cfb.site.matchups import _elapsed
    data = yahoo.week_matchups(week)
    if data.get("status") == "preevent":
        return {}
    games = frame.set_index(frame["game_id"].astype(str))
    out = {}
    for key, roster in data["rosters"].items():
        mean = var = 0.0
        for p in roster:
            if p["slot"] in ("BN", "IL", "IR"):
                continue
            pid = str(p["yahoo_id"])
            proj = float(wk["proj_week"].get(pid, 0.0) or 0.0) if pid in wk.index else 0.0
            gid = str(wk["game_id"].get(pid)) if pid in wk.index else None
            g = games.loc[gid] if gid in games.index else None
            left = 1.0 - (_elapsed(g) if g is not None else 0.0)
            mean += float(p.get("points") or 0.0) + proj * left
            var += float(_sd(proj)) ** 2 * left
        out[key] = (mean, var)
    return out


def weekly_means(lg: dict, sched: dict, rosters: dict, board: pd.DataFrame = None,
                 frame: pd.DataFrame = None) -> tuple:
    """(keys, weeks, mean[w, t], sd[w, t], {key: {pos: points per regular week}})."""
    if frame is None:
        frame, _m, _n = predict.season()
    board = in_season.board(frame=frame) if board is None else board
    board = board.drop_duplicates("yahoo_id")
    injuries = {str(p["yahoo_id"]): p.get("status") or ""
                for r in yahoo.week_matchups(int(lg["current_week"]))["rosters"].values()
                for p in r} if int(lg["current_week"]) in yahoo.archived_weeks() else {}
    keys = sorted(rosters)
    weeks = sorted(sched)
    mean = np.zeros((len(weeks), len(keys)))
    var = np.zeros((len(weeks), len(keys)))
    playoff_start = int(lg["playoff_start_week"] or lg["end_week"] + 1)
    by_pos, counted = {k: {} for k in keys}, {k: 0 for k in keys}
    regular = [w for w in weeks if w < playoff_start] or weeks
    for i, week in enumerate(weeks):
        span = sched[week]
        # Yahoo's designations describe today, so they price the week at hand.
        wk = weekly.week_projections(span["start"], span["end"], board=board, league=lg,
                                     frame=frame, injuries=injuries if i == 0 else None)
        live = _live_week(week, wk, frame) if i == 0 else {}
        for j, key in enumerate(keys):
            if key in live:
                mean[i, j], var[i, j] = live[key]
                continue
            ids = [str(x) for x in dict.fromkeys(rosters[key]) if str(x) in wk.index]
            players = board.set_index(board["yahoo_id"].astype(str)).reindex(ids)[["pos"]]
            players["proj_week"] = wk["proj_week"].reindex(ids).to_numpy(float)
            players = players.dropna(subset=["pos"])
            start = _best(players, lg)
            p = players.loc[start, "proj_week"].fillna(0.0).to_numpy(float)
            mean[i, j] = p.sum()
            var[i, j] = (_sd(p) ** 2).sum()
            if week in regular:
                counted[key] += 1
                for pos, pts in zip(players.loc[start, "pos"], p):
                    by_pos[key][pos] = by_pos[key].get(pos, 0.0) + pts
    by_pos = {k: {pos: v / max(counted[k], 1) for pos, v in d.items()} for k, d in by_pos.items()}
    return keys, weeks, mean, np.sqrt(var), by_pos


def _bracket(order: np.ndarray, scores: np.ndarray, reseed: bool) -> np.ndarray:
    """The champion of each simulated bracket.

    `order` is (sims, n) team indices by seed; `scores` (sims, rounds, teams).
    The top seeds sit out round one until the field is a power of two; each
    round the best remaining seed meets the worst (reseeded) or the bracket's
    fixed opponent."""
    sims, n = order.shape
    alive = order.copy()                            # seeds still in, best first
    size = 1 << int(np.ceil(np.log2(n)))
    byes = size - n
    rnd = 0
    rows = np.arange(sims)[:, None]
    seed_of = np.full((sims, scores.shape[2]), n)
    seed_of[rows, order] = np.arange(n)
    while alive.shape[1] > 1:
        if byes:
            sit, play = alive[:, :byes], alive[:, byes:]
            byes = 0
        else:
            sit, play = alive[:, :0], alive
        k = play.shape[1] // 2
        hi, lo = play[:, :k], play[:, ::-1][:, :k]
        s = scores[:, min(rnd, scores.shape[1] - 1), :]
        win = np.where(s[rows, hi] >= s[rows, lo], hi, lo)
        alive = np.concatenate([sit, win], axis=1)
        if reseed:
            alive = np.take_along_axis(
                alive, np.argsort(seed_of[rows, alive], axis=1), axis=1)
        rnd += 1
    return alive[:, 0]


def simulate(lg: dict, sched: dict, keys: list, weeks: list, mean: np.ndarray,
             sd: np.ndarray, sims: int = SIMS, seed: int = SEED,
             played_playoffs: dict = None) -> pd.DataFrame:
    """`played_playoffs` is {week: {team_key: points}} for bracket rounds
    already final: they are taken as they happened, and only the rounds left
    are drawn."""
    rng = np.random.default_rng(seed)
    n = len(keys)
    idx = {k: i for i, k in enumerate(keys)}
    standing = {t["team_key"]: t for t in lg["teams"]}
    wins = np.array([float(standing.get(k, {}).get("wins") or 0)
                     + 0.5 * float(standing.get(k, {}).get("ties") or 0) for k in keys])
    pf = np.array([float(standing.get(k, {}).get("points_for") or 0) for k in keys])
    playoff_start = int(lg["playoff_start_week"] or lg["end_week"] + 1)
    regular = [i for i, w in enumerate(weeks) if w < playoff_start]

    scores = rng.normal(mean[None], sd[None], size=(sims, len(weeks), n))
    total_w = np.tile(wins, (sims, 1))
    total_pf = np.tile(pf, (sims, 1)) + scores[:, regular, :].sum(axis=1)
    for i in regular:
        s = scores[:, i, :]
        for a, b in sched[weeks[i]]["pairs"]:
            ia, ib = idx.get(a), idx.get(b)
            if ia is None or ib is None:
                continue
            total_w[:, ia] += (s[:, ia] > s[:, ib]) + 0.5 * (s[:, ia] == s[:, ib])
            total_w[:, ib] += (s[:, ib] > s[:, ia]) + 0.5 * (s[:, ia] == s[:, ib])
        if lg.get("uses_median_score"):
            rank = (-s).argsort(axis=1).argsort(axis=1)
            total_w += rank < n // 2
    # Seeds: wins, then points for.
    order = np.lexsort((-total_pf, -total_w), axis=1)
    field = int(lg.get("num_playoff_teams") or 0)
    # Every bracket round in week order: a played one as it happened, the one
    # being played and those to come drawn like any other week.
    played_playoffs = played_playoffs or {}
    rounds = []
    for week in range(playoff_start, int(lg["end_week"]) + 1):
        if week in played_playoffs:
            got = played_playoffs[week]
            rounds.append(np.tile([float(got.get(k, 0.0)) for k in keys], (sims, 1)))
        elif week in weeks:
            rounds.append(scores[:, weeks.index(week), :])
    out = pd.DataFrame({"team_key": keys,
                        "wins": total_w.mean(axis=0),
                        "per_week": mean[regular].mean(axis=0) if regular else mean.mean(axis=0)})
    games = len(regular) * (2 if lg.get("uses_median_score") else 1)
    out["losses"] = [float(standing.get(k, {}).get("losses") or 0) for k in keys]
    out["losses"] += games - (out["wins"] - wins)
    if field:
        seeds = order[:, :field]
        made = np.zeros(n)
        np.add.at(made, seeds.ravel(), 1)
        size = 1 << int(np.ceil(np.log2(field)))
        byes = np.zeros(n)
        np.add.at(byes, seeds[:, :size - field].ravel(), 1)
        champ = (_bracket(seeds, np.stack(rounds, axis=1) if rounds else scores[:, -1:, :],
                          bool(lg.get("uses_playoff_reseeding")))
                 if field > 1 else seeds[:, 0])
        titles = np.bincount(champ, minlength=n)
        out["playoffs"] = made / sims
        out["bye"] = byes / sims
        out["title"] = titles / sims
    return out


def _week_points(week: int) -> dict:
    """{team_key: points} for one archived week."""
    return {t["team_key"]: float(t.get("points") or 0.0)
            for m in yahoo.week_matchups(week)["matchups"] for t in m["teams"]}


def regular_season(lg: dict) -> dict:
    """{team_key: (wins, points for)} over the regular season, from the week
    archive - head to head, and against the median where the league plays it.
    What seeds the bracket once it is being played: Yahoo's standings then
    describe the playoffs as well, and the seeds must not move with them."""
    playoff_start = int(lg["playoff_start_week"])
    wins, pf = {}, {}
    for week in range(int(lg["start_week"] or 1), playoff_start):
        if week not in yahoo.archived_weeks():
            continue
        data = yahoo.week_matchups(week)
        pts = _week_points(week)
        for m in data["matchups"]:
            if len(m["teams"]) != 2:
                continue
            a, b = (t["team_key"] for t in m["teams"])
            wins[a] = wins.get(a, 0.0) + (pts[a] > pts[b]) + 0.5 * (pts[a] == pts[b])
            wins[b] = wins.get(b, 0.0) + (pts[b] > pts[a]) + 0.5 * (pts[a] == pts[b])
        if lg.get("uses_median_score") and pts:
            median = float(np.median(list(pts.values())))
            for k, v in pts.items():
                wins[k] = wins.get(k, 0.0) + (v > median)
        for k, v in pts.items():
            pf[k] = pf.get(k, 0.0) + v
    return {k: (wins.get(k, 0.0), pf.get(k, 0.0)) for k in pf}


def run(lg: dict = None, rosters: dict = None, sims: int = SIMS) -> pd.DataFrame:
    lg = yahoo.league() if lg is None else lg
    if rosters is None:
        from cfb.site.league_power import team_rosters
        rosters = team_rosters()
    sched = schedule(lg)
    if not sched:
        return pd.DataFrame()
    keys, weeks, mean, sd, by_pos = weekly_means(lg, sched, rosters)
    playoff_start = int(lg["playoff_start_week"] or lg["end_week"] + 1)
    played = {}
    if int(lg["current_week"]) >= playoff_start:
        # The bracket is under way: seeds from the regular season as it
        # finished, and the rounds already final as they happened.
        final = regular_season(lg)
        lg = {**lg, "teams": [{**t, "wins": final.get(t["team_key"], (0, 0))[0], "ties": 0,
                               "losses": 0, "points_for": final.get(t["team_key"], (0, 0))[1]}
                              for t in lg["teams"]]}
        played = {w: _week_points(w) for w in range(playoff_start, int(lg["current_week"]))
                  if w in yahoo.archived_weeks() and yahoo.week_final(yahoo.week_matchups(w))}
    out = simulate(lg, sched, keys, weeks, mean, sd, sims=sims, played_playoffs=played)
    out["by_pos"] = out["team_key"].map(by_pos)
    return out


if __name__ == "__main__":
    lg = yahoo.league()
    names = {t["team_key"]: t["name"] for t in lg["teams"]}
    res = run(lg).assign(team=lambda d: d["team_key"].map(names))
    print(res.sort_values("title", ascending=False).round(3).to_string(index=False))
