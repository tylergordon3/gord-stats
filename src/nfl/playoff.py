"""
The NFL playoff field, projected: the rest of the regular season played out
N_SIMS times on this site's own game model (nfl.predict), the seven seeds of
each conference worked out from the simulated standings, and the bracket
played to a Super Bowl winner.

**The format.** Seven teams a conference: the four division winners seeded
1-4 by record, then three wild cards 5-7. The 1 seed has the bye. Wild Card
weekend is 2 v 7, 3 v 6, 4 v 5 at the higher seed; the divisional round
reseeds (the 1 seed plays the lowest seed left), the higher seed hosts every
game up to the Super Bowl, which is neutral here.

**Games** are played as in cfb.playoff: the model's margin and its measured
error (nfl.predict.margin_sd), with each team's rating wandering from run to
run - an error now plus a weekly random walk, shared by all of its games,
sized against 2015-2025 (RATING_SD_NOW) - and each game's own noise shrunk so
a game next week keeps exactly the win chance /nfl/ prints. A simulated game
is never a tie; a real one counts half a win, as the NFL counts it.

**Once the regular season is over** the seeds are the real ones (every
result is in, so every run finds the same field, bar the coin standing in
for the steps not modelled), and a playoff game already played is decided.

**Tiebreaks**, the NFL's own order as far as this data reaches:
  * Division: head-to-head (the record in games among the tied clubs), then
    division record, then conference record, then a coin.
  * Seeding the division winners, and the wild cards: head-to-head (for three
    or more clubs only a sweep counts - one beat all the others, or lost to
    all of them), then conference record, then a coin. A wild-card tie
    between clubs of one division is first settled inside the division, so
    only each division's best remaining club is ever compared.
  * Whenever a step separates some of a tie but not all of it, the clubs still
    level start over at head-to-head, as the NFL's procedure does.
The NFL lists more steps between conference record and the coin - common
games, strength of victory and of schedule, points - which are not modelled;
the coin stands in for all of them. They settle a handful of seeds a season.

    python -m nfl.playoff            # print the table
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from cfb.playoff import game_noise, order, scatter, shocks, weeks_ahead

# --------------------------------------------------------------------------- #
# The format
# --------------------------------------------------------------------------- #

SEEDS = 7                     # per conference
BYES = 1
WILD_CARDS = 3
CONFERENCES = ("AFC", "NFC")

# ESPN team id -> division. The ids followed the Rams, Chargers and Raiders
# through their moves; the divisions have not changed since 2002.
DIVISIONS = {
    "2": "AFC East", "15": "AFC East", "17": "AFC East", "20": "AFC East",
    "33": "AFC North", "4": "AFC North", "5": "AFC North", "23": "AFC North",
    "34": "AFC South", "11": "AFC South", "30": "AFC South", "10": "AFC South",
    "7": "AFC West", "12": "AFC West", "13": "AFC West", "24": "AFC West",
    "6": "NFC East", "19": "NFC East", "21": "NFC East", "28": "NFC East",
    "3": "NFC North", "8": "NFC North", "9": "NFC North", "16": "NFC North",
    "1": "NFC South", "29": "NFC South", "18": "NFC South", "27": "NFC South",
    "22": "NFC West", "14": "NFC West", "25": "NFC West", "26": "NFC West",
}

# --------------------------------------------------------------------------- #
# The simulation's knobs
# --------------------------------------------------------------------------- #

N_SIMS = 10_000
CHUNK = 2_500
SEED = 20_262
# Measured as cfb.playoff's are: ratings fitted at a checkpoint of each season
# 2015-2025 and the rest played out, the spread of every team's remaining wins
# against what really happened. A coin per game gives about half of it (from
# week 5: 2.82 wins squared where the truth was 5.47); these give 5.44, and
# every checkpoint from week 2 to week 15 lands within 5% - so unlike college
# one size fits the whole season.
RATING_SD_NOW = 4.5
RATING_DRIFT = 0.75
SUPER_BOWL_NEUTRAL = True


@dataclass
class League:
    """One projection's inputs, indexed by position in `teams`. `games` is
    the regular season: integer `home`/`away`, `neutral`, `played`,
    `result` (the home side's share: 1, 0.5 for a tie, 0; NaN unplayed),
    `mean` (the model's margin) and `ahead` (weeks out)."""
    teams: list
    names: dict                     # id -> (nickname, abbreviation)
    conf: list
    div: list
    rating: np.ndarray
    home_edge: float
    margin_sd: float
    games: pd.DataFrame
    ahead: int = 1                  # weeks to the playoffs
    results: dict = field(default_factory=dict)   # (i, j) -> winner, playoff games played
    final: bool = False             # the Super Bowl has been played


def build(frame: pd.DataFrame, model, names: dict, margin_sd: float,
          anchor: pd.Timestamp) -> League:
    """A League from nfl.predict.season()'s frame."""
    teams = sorted(DIVISIONS, key=lambda t: (DIVISIONS[t], int(t)))
    index = {t: i for i, t in enumerate(teams)}
    rating = np.array([model.rating(t) for t in teams])
    probe = pd.DataFrame({"home_team": [teams[0]], "away_team": [teams[0]], "neutral": [False]})
    home_edge = float(model.predict(probe)["pred_margin"].iloc[0])

    reg = frame[(frame["seasontype"] == 2) & frame["home_team"].isin(set(index))
                & frame["away_team"].isin(set(index))]
    played = reg["played"].astype(bool).to_numpy()
    margin = reg["actual_margin"].to_numpy(float)
    games = pd.DataFrame({
        "home": reg["home_team"].map(index).to_numpy(int),
        "away": reg["away_team"].map(index).to_numpy(int),
        "neutral": reg["neutral"].astype(bool).to_numpy(),
        "played": played,
        "result": np.where(played, np.where(margin > 0, 1.0, np.where(margin < 0, 0.0, 0.5)),
                           np.nan),
        "mean": reg["pred_margin"].to_numpy(float),
        "ahead": weeks_ahead(reg["date"], anchor),
    })
    end = reg["date"].max() if len(reg) else anchor
    ahead = int(weeks_ahead(pd.Series([end]), anchor)[0])

    post = frame[(frame["seasontype"] == 3) & frame["home_team"].isin(set(index))
                 & frame["away_team"].isin(set(index)) & frame["played"].astype(bool)]
    results, final = {}, False
    for _, g in post.iterrows():
        h, a = index[str(g["home_team"])], index[str(g["away_team"])]
        results[(h, a)] = h if g["actual_margin"] > 0 else a
        if int(g["week"]) == 5:
            final = True
    return League(teams=teams, names={t: names.get(t, (t, t)) for t in teams},
                  conf=[DIVISIONS[t].split()[0] for t in teams],
                  div=[DIVISIONS[t] for t in teams], rating=rating, home_edge=home_edge,
                  margin_sd=margin_sd, games=games, ahead=ahead, results=results, final=final)


@dataclass
class Result:
    league: League
    n: int
    playoff: np.ndarray
    division: np.ndarray
    top_seed: np.ndarray
    conf_title: np.ndarray            # reached the Super Bowl
    title: np.ndarray                 # won it
    seed_count: np.ndarray            # (teams, 7): runs at each seed

    def avg_seed(self, seeds=range(SEEDS)) -> np.ndarray:
        """Average seed over the runs a team holds one of `seeds` (0-based):
        all of them by default, the division winners' 0-3, the wild cards' 4-6."""
        cols = list(seeds)
        runs = self.seed_count[:, cols].sum(axis=1)
        total = (self.seed_count[:, cols] * (np.array(cols) + 1)).sum(axis=1)
        return np.where(runs > 0, total / np.maximum(runs, 1), np.nan)


def simulate(league: League, n: int = N_SIMS, seed: int = SEED,
             sd_now: float = RATING_SD_NOW, drift: float = RATING_DRIFT) -> Result:
    rng = np.random.default_rng(seed)
    T = len(league.teams)
    acc = {k: np.zeros(T) for k in ("playoff", "division", "top_seed", "conf_title", "title")}
    acc["seed_count"] = np.zeros((T, SEEDS))
    done = 0
    while done < n:
        m = min(CHUNK, n - done)
        _chunk(league, m, rng, sd_now, drift, acc)
        done += m
    return Result(league=league, n=n, **{k: v / n for k, v in acc.items() if k != "seed_count"},
                  seed_count=acc["seed_count"])


def standings(league: League, hw: np.ndarray) -> dict:
    """Win shares overall, in the division and in the conference, and
    who beat whom, for each run - `hw` (runs, unplayed games) being the home
    side's result in each unplayed game, 1 or 0."""
    g = league.games
    T, n = len(league.teams), len(hw)
    rem, done = g[~g["played"]], g[g["played"]]
    h, a = rem["home"].to_numpy(int), rem["away"].to_numpy(int)
    ph, pa = done["home"].to_numpy(int), done["away"].to_numpy(int)
    pr = done["result"].to_numpy(float)
    div = np.array(league.div)
    conf = np.array(league.conf)
    out = {}
    for name, same in (("all", None), ("div", div), ("conf", conf)):
        keep_r = np.ones(len(rem), bool) if same is None else same[h] == same[a]
        keep_p = np.ones(len(done), bool) if same is None else same[ph] == same[pa]
        wins = scatter(T, h[keep_r], hw[:, keep_r]) + scatter(T, a[keep_r], 1 - hw[:, keep_r])
        wins += np.bincount(ph[keep_p], pr[keep_p], minlength=T) \
            + np.bincount(pa[keep_p], 1 - pr[keep_p], minlength=T)
        games = (np.bincount(h[keep_r], minlength=T) + np.bincount(a[keep_r], minlength=T)
                 + np.bincount(ph[keep_p], minlength=T) + np.bincount(pa[keep_p], minlength=T))
        out[name] = wins / np.maximum(games, 1)
    known = (np.bincount(ph * T + pa, pr, T * T)
             + np.bincount(pa * T + ph, 1 - pr, T * T)).astype(float)
    beat = (scatter(T * T, h * T + a, hw) + scatter(T * T, a * T + h, 1 - hw)
            + known[None, :]).reshape(n, T, T).astype(np.float32)
    met = np.zeros((T, T), np.float32)
    np.add.at(met, (g["home"].to_numpy(int), g["away"].to_numpy(int)), 1)
    np.add.at(met, (g["away"].to_numpy(int), g["home"].to_numpy(int)), 1)
    out["beat"], out["met"] = beat, met
    return out


def seed_conference(st: dict, members: np.ndarray, divs: list, coin: np.ndarray) -> np.ndarray:
    """(runs, 7): one conference's seeds (indices into the league), by the
    tiebreak order in the module docstring."""
    n = len(coin)
    rows = np.arange(n)
    L = members
    pct = st["all"][:, L]
    beat = st["beat"][:, L][:, :, L]
    met = st["met"][np.ix_(L, L)]
    dpct, cpct, flip = st["div"][:, L], st["conf"][:, L], coin[:, L]
    divs = np.array(divs)
    # Each division in its order, so a wild-card tie inside one division is
    # settled the division's way.
    place = np.zeros((n, len(L)), int)
    winner = np.zeros((n, len(L)), bool)
    for d in dict.fromkeys(divs):
        inside = np.tile(divs == d, (n, 1))
        ranked = order(pct, beat, met, [dpct, cpct, flip], int(inside[0].sum()), eligible=inside)
        for p in range(ranked.shape[1]):
            place[rows, ranked[:, p]] = p
        winner[rows, ranked[:, 0]] = True
    seeds = np.full((n, SEEDS), -1)
    seeds[:, :4] = order(pct, beat, met, [cpct, flip], 4, eligible=winner, sweep=True)
    left = ~winner
    for s in range(WILD_CARDS):
        best = np.zeros_like(left)
        for d in dict.fromkeys(divs):
            cols = np.flatnonzero(divs == d)
            spot = np.where(left[:, cols], place[:, cols], 99)
            top = cols[spot.argmin(axis=1)]
            ok = left[rows, top]
            best[rows[ok], top[ok]] = True
        pick = order(pct, beat, met, [cpct, flip], 1, eligible=best, sweep=True)[:, 0]
        seeds[:, 4 + s] = pick
        left[rows, pick] = False
    return L[seeds]


def _chunk(league, n, rng, sd_now, drift, acc):
    T, rows = len(league.teams), np.arange(n)
    g = league.games
    rem = g[~g["played"]]
    K = max(int(league.ahead), int(rem["ahead"].max()) if len(rem) else 1)
    S = shocks(rng, n, T, K, sd_now, drift)
    noise = game_noise(league.margin_sd, sd_now, drift)
    h, a, k = (rem[c].to_numpy(int) for c in ("home", "away", "ahead"))
    margin = (rem["mean"].to_numpy(np.float32) + S[:, h, k] - S[:, a, k]
              + noise * rng.standard_normal((n, len(rem)), dtype=np.float32))
    hw = (margin > 0).astype(np.float32)
    st = standings(league, hw)
    coin = rng.random((n, T))
    strength = league.rating[None, :].astype(np.float32) + S[:, :, K]

    forced = np.zeros((T, T), np.int8)
    for (i, j), w in league.results.items():
        forced[i, j] = 1 if w == i else -1
        forced[j, i] = -forced[i, j]

    def play(x, y, home_x):
        """Winner per run of x v y; `home_x` an array or bool."""
        mg = (strength[rows, x] - strength[rows, y] + np.where(home_x, league.home_edge, 0.0)
              + noise * rng.standard_normal(n))
        f = forced[x, y]
        return np.where(np.where(f == 0, mg > 0, f == 1), x, y)

    champs = []
    for c in CONFERENCES:
        members = np.array([i for i in range(T) if league.conf[i] == c])
        seeds = seed_conference(st, members, [league.div[i] for i in members], coin)
        for s in range(SEEDS):
            hits = np.bincount(seeds[:, s], minlength=T)
            acc["playoff"] += hits
            acc["seed_count"][:, s] += hits
            if s < 4:
                acc["division"] += hits
            if s == 0:
                acc["top_seed"] += hits
        team = [seeds[:, s] for s in range(SEEDS)]
        # Wild Card weekend: 2 v 7, 3 v 6, 4 v 5, the higher seed at home.
        alive_t = [team[0]]
        alive_s = [np.ones(n, int)]
        for hi in range(BYES, BYES + (SEEDS - BYES) // 2):
            lo = SEEDS - 1 - (hi - BYES)
            w = play(team[hi], team[lo], True)
            alive_t.append(w)
            alive_s.append(np.where(w == team[hi], hi + 1, lo + 1))
        # Divisional: reseeded - the top seed left plays the lowest.
        while len(alive_t) > 1:
            ts, ss = np.stack(alive_t, 1), np.stack(alive_s, 1)
            by = np.argsort(ss, axis=1, kind="stable")
            ts, ss = np.take_along_axis(ts, by, 1), np.take_along_axis(ss, by, 1)
            nxt_t, nxt_s = [], []
            m = ts.shape[1]
            for p in range(m // 2):
                x, y = ts[:, p], ts[:, m - 1 - p]
                w = play(x, y, True)
                nxt_t.append(w)
                nxt_s.append(np.where(w == x, ss[:, p], ss[:, m - 1 - p]))
            alive_t, alive_s = nxt_t, nxt_s
        acc["conf_title"] += np.bincount(alive_t[0], minlength=T)
        champs.append(alive_t[0])
    sb = play(champs[0], champs[1], not SUPER_BOWL_NEUTRAL)
    acc["title"] += np.bincount(sb, minlength=T)


def projected_bracket(res: Result) -> dict:
    """{conference: [team index by seed]}: each division's likeliest winner,
    seeded by its average seed when it wins the division, then the three
    likeliest of the rest by their average seed as a wild card."""
    lg = res.league
    as_winner = res.avg_seed(range(4))
    as_wild = res.avg_seed(range(4, SEEDS))
    out = {}
    for c in CONFERENCES:
        members = [i for i in range(len(lg.teams)) if lg.conf[i] == c]
        winners = []
        for d in dict.fromkeys(lg.div[i] for i in members):
            inside = [i for i in members if lg.div[i] == d]
            winners.append(max(inside, key=lambda i: (res.division[i], res.playoff[i])))
        winners.sort(key=lambda i: (np.nan_to_num(as_winner[i], nan=99), -res.division[i]))
        rest = sorted((i for i in members if i not in winners), key=lambda i: -res.playoff[i])
        wild = sorted(rest[:WILD_CARDS], key=lambda i: (np.nan_to_num(as_wild[i], nan=99),
                                                        -res.playoff[i]))
        out[c] = winners + wild
    return out


def records(league: League) -> dict:
    """{team index: (wins, losses, ties)} from the games played."""
    g = league.games[league.games["played"]]
    out = {i: [0, 0, 0] for i in range(len(league.teams))}
    for h, a, r in zip(g["home"], g["away"], g["result"]):
        if r == 0.5:
            out[h][2] += 1
            out[a][2] += 1
        else:
            out[h][0 if r == 1 else 1] += 1
            out[a][1 if r == 1 else 0] += 1
    return {i: tuple(v) for i, v in out.items()}


def anchor_time(frame: pd.DataFrame) -> pd.Timestamp:
    """Just after the last finished game: the projection is fitted there, so
    builds between results print the same numbers. Before any, today."""
    done = frame[frame["played"].astype(bool)]
    if not len(done):
        return pd.Timestamp.now(tz="UTC").floor("D")
    return done["date"].max() + pd.Timedelta(hours=6)


def project(n: int = N_SIMS, seed: int = SEED):
    """(Result or None before a game is played, League)."""
    from nfl import predict
    frame, _model, _names = predict.season()
    anchor = anchor_time(frame)
    if frame["played"].astype(bool).any():
        frame, model, names = predict.season(asof=anchor)
    else:
        model, names = _model, _names
    league = build(frame, model, names, predict.margin_sd(), anchor)
    if not league.games["played"].any():
        return None, league
    return simulate(league, n=n, seed=seed), league


if __name__ == "__main__":
    import time
    t0 = time.time()
    res, league = project()
    print(f"{time.time() - t0:.1f}s")
    if res is None:
        raise SystemExit("nothing to project yet")
    avg = res.avg_seed()
    for i in np.argsort(-res.playoff):
        nick, abbr = league.names[league.teams[i]]
        print(f"{abbr:<4} {league.div[i]:<10} in {res.playoff[i]:6.1%} div {res.division[i]:6.1%} "
              f"#1 {res.top_seed[i]:6.1%} SB {res.conf_title[i]:6.1%} win {res.title[i]:6.1%} "
              f"seed {avg[i]:4.1f}")
    for c, seeds in projected_bracket(res).items():
        print(c, [league.names[league.teams[i]][1] for i in seeds])
