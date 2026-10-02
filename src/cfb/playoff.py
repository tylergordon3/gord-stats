"""
The College Football Playoff, projected: the rest of the season played out
N_SIMS times on this site's own game model (cfb.predict), the conference title
games decided from the simulated standings, the field picked by a stand-in for
the selection committee, and the bracket played to a champion.

**The format (2026-27, checked 2026-09-30).** Twelve teams. The champions of
the ACC, Big 12, Big Ten and SEC are in whatever their ranking; so is the
highest-ranked team from the American, CUSA, MAC, Mountain West, Pac-12 and
Sun Belt - since 2026 that team need not have won its conference - and Notre
Dame when it finishes in the top 12. The rest are at-large. Seeding has been
straight by the final ranking since 2025: the top four get the byes whether or
not they won a conference, 5-12 play on the higher seed's campus, and the
bracket is fixed (1 v 8/9, 4 v 5/12 on one side, 2 v 7/10, 3 v 6/11 on the
other; no reseeding). Sources: collegefootballplayoff.com (2026-01-23, the
12-team format extended through 2026-27) and NCAA.com's "How the College
Football Playoff works" (2026-08-11). The format has changed every year of
the 12-team era, so each piece of it is a named constant below.

**Every game left** is played on the model's own margin and its measured error
(cfb.predict.margin_sd). A team's rating also wanders from run to run: an
error now (rating_sd_now) plus a random walk of RATING_DRIFT a week, shared by
all of its games. Each game's own noise is shrunk to match, so a game next
week keeps exactly the win chance the predictions page prints - what the
wander adds is that a team better than we think wins its games *together*,
which a coin per game cannot say, and that a game in November is less certain
than one on Saturday.

The size of the wander is measured, not assumed. Fitting the ratings at a
checkpoint of each season 2015-2025 (2020 out) and playing the rest out, a
coin per game gives each team's remaining wins about half the spread they
really had: from week 5, a squared error of 1.40 wins where the truth was
2.61. An error now of 7.5 points brings it to 2.6 - and the error shrinks as
results come in, 8 points with week 3 next and 5.75 with week 11 next
(SD_NOW_BY_WEEK, every checkpoint within a few percent). The drift a week
barely matters in that check and is left at a point.

**Conference title games** are the two best conference records (the Sun Belt:
East winner v West winner), from conference games before the title week.
Ties, a simplified version of what the conferences publish: record in games
among the tied teams, then our rating as it stands in that run - the stand-in
for the computer composite the ACC, Big 12 and SEC fall back on. A step that
separates some but not all of a tie starts again from head-to-head with the
teams still tied, as the conferences' own procedures do. Common opponents and
the rest of the long lists are not modelled. A title game ESPN has already
filled is played between the teams it names; a finished one counts as played.
Title games are neutral here (most are; a few G6 games are at the higher
seed).

**Selection.** The committee has no formula, so this is a proxy, and it says
so on the page: strength of record - wins above what an average top-25 team
(our ratings) would expect against the same schedule, home and away included -
plus our own rating, RATING_PER_WIN points of it counting as one win. Record
first because the committee's protocol is results first; the rating because
it also ranks how good teams are, and two teams with one loss are not equal.
Straight-seeded off the same order.

**Once the field is real** (ESPN has the CFP games with teams in them), the
simulation stops guessing it: those twelve, seeded in the order of the ranks
ESPN prints beside them, and any CFP game already played is decided.

    python -m cfb.playoff            # print the table
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.stats import norm

# --------------------------------------------------------------------------- #
# The format - one edit when it changes
# --------------------------------------------------------------------------- #

FIELD_SIZE = 12
BYES = 4
POWER_CONFERENCES = ("ACC", "Big 12", "Big Ten", "SEC")
GROUP_OF_SIX = ("American", "CUSA", "MAC", "Mountain West", "Pac-12", "Sun Belt")
G6_BIDS = 1
# 2024-2025: the bid went to the best *champion*. 2026: the best G6 team.
G6_BID_NEEDS_TITLE = False
NOTRE_DAME = "87"                   # ESPN id
# Independents with a bid of their own: (team id, ranked this high or better).
INDEPENDENT_BIDS = ((NOTRE_DAME, 12),)
# 2024's rule - the byes to the four best champions. Straight seeding since 2025.
CHAMPION_BYES = False
FIRST_ROUND_AT_HIGHER_SEED = True
INDEPENDENT = "Independent"

# --------------------------------------------------------------------------- #
# The simulation's own knobs
# --------------------------------------------------------------------------- #

N_SIMS = 10_000
CHUNK = 2_000                       # runs at a time: keeps the Pi's memory flat
SEED = 20_261                       # fixed: a rebuild without new results is the same page
# How far a rating can be off, by the first week still to play: fitted so the
# spread of every team's remaining wins matches 2015-2025's (see the module
# docstring). Linear between the points, flat beyond them.
SD_NOW_BY_WEEK = ((3, 8.0), (5, 7.5), (7, 7.0), (9, 6.25), (11, 5.75))
RATING_DRIFT = 1.0                  # a week, on top: injuries, a quarterback change
RATING_PER_WIN = 10.0               # selection: ten points of rating = one win of resume
REFERENCE_TOP = 25                  # strength of record against an average top-25 team


def rating_sd_now(next_week: int) -> float:
    weeks, sds = zip(*SD_NOW_BY_WEEK)
    return float(np.interp(next_week, weeks, sds))


@dataclass(frozen=True)
class Format:
    field: int = FIELD_SIZE
    byes: int = BYES
    power: tuple = POWER_CONFERENCES
    group_of_six: tuple = GROUP_OF_SIX
    g6_bids: int = G6_BIDS
    g6_needs_title: bool = G6_BID_NEEDS_TITLE
    independents: tuple = INDEPENDENT_BIDS
    champion_byes: bool = CHAMPION_BYES
    home_first_round: bool = FIRST_ROUND_AT_HIGHER_SEED


FORMAT = Format()


# --------------------------------------------------------------------------- #
# Shared machinery (nfl.playoff uses these too)
# --------------------------------------------------------------------------- #

def shocks(rng, n: int, teams: int, ahead: int, sd_now: float, drift: float) -> np.ndarray:
    """(n, teams, ahead + 1): each team's rating error 0..ahead weeks out - a
    draw for now, then a random walk. Index k is the error k weeks ahead."""
    out = np.empty((n, teams, ahead + 1), np.float32)
    out[:, :, 0] = rng.standard_normal((n, teams), dtype=np.float32) * sd_now
    if ahead:
        steps = rng.standard_normal((n, teams, ahead), dtype=np.float32) * drift
        out[:, :, 1:] = out[:, :, :1] + np.cumsum(steps, axis=2)
    return out


def game_noise(margin_sd: float, sd_now: float, drift: float) -> float:
    """A game's own noise once the two ratings' wander is drawn separately,
    sized so a game one week out has exactly the model's measured error."""
    return float(np.sqrt(max(margin_sd ** 2 - 2 * (sd_now ** 2 + drift ** 2), 1.0)))


def weeks_ahead(dates: pd.Series, anchor: pd.Timestamp) -> np.ndarray:
    """Whole weeks from the anchor to each date, at least one."""
    days = (dates - anchor).dt.total_seconds().to_numpy() / 86400.0
    return np.maximum(1, np.ceil(np.nan_to_num(days, nan=7.0) / 7.0)).astype(int)


def scatter(size: int, cols: np.ndarray, vals: np.ndarray) -> np.ndarray:
    """(runs, size): each run's `vals` (runs, k) summed into the positions
    `cols` (k,) - np.add.at's answer at bincount's speed."""
    n = len(vals)
    idx = (np.arange(n)[:, None] * size + np.asarray(cols)[None, :]).ravel()
    # astype: with nothing to add, bincount answers in integers.
    return np.bincount(idx, weights=np.asarray(vals, float).ravel(),
                       minlength=n * size).astype(float).reshape(n, size)


def keep_best(tied: np.ndarray, score: np.ndarray) -> np.ndarray:
    """`tied` narrowed to the teams with the best `score` among it."""
    s = np.where(tied, np.round(score, 6), -np.inf)
    return tied & (s == s.max(axis=1, keepdims=True))


def head_to_head(tied: np.ndarray, wins: np.ndarray, games: np.ndarray,
                 sweep: bool = False) -> np.ndarray:
    """`tied` narrowed by head-to-head among the tied teams.

    `wins[n, i, j]` is i's wins over j (a tie half each), `games[i, j]` the
    games they played. The default is the mini-league: each team's record in
    games among the tied teams, 0.5 for a team that played none of them. With
    `sweep` (the NFL's wild-card rule) two tied clubs still go by head-to-head,
    but three or more only when one beat each of the others (it goes through)
    or lost to each of them (it drops out)."""
    tw = tied.astype(np.float32)
    won = np.einsum("nij,nj->ni", wins, tw)
    played = tw @ games.T if games.ndim == 2 else np.einsum("nij,nj->ni", games, tw)
    score = np.where(played > 0, won / np.maximum(played, 1e-9), 0.5)
    if sweep:
        size = tied.sum(axis=1)[:, None]
        back = np.swapaxes(wins, 1, 2)
        beat = ((wins > 0) & (back == 0) & tied[:, None, :]).sum(axis=2)
        lost = ((back > 0) & (wins == 0) & tied[:, None, :]).sum(axis=2)
        swept = np.where(beat == size - 1, 1.0, np.where(lost == size - 1, 0.0, 0.5))
        score = np.where(size == 2, score, swept)
    return keep_best(tied, score)


def pick_best(tied: np.ndarray, wins: np.ndarray, games: np.ndarray, keys: list,
              sweep: bool = False) -> np.ndarray:
    """Index per run of the team a tiebreak procedure puts first among `tied`.

    The steps are head-to-head and then each of `keys` in turn (arrays, higher
    is better). Whenever a step separates some of a tie but not all of it, the
    teams still tied start again from head-to-head - how both the conferences
    and the NFL run a tie of three or more. The last key should be something
    that cannot tie (a rating, a coin)."""
    steps = [lambda t: head_to_head(t, wins, games, sweep)] + \
        [lambda t, k=k: keep_best(t, k) for k in keys]
    for _ in range(4 * tied.shape[1]):
        size = tied.sum(axis=1)
        if (size <= 1).all():
            break
        new, done = tied.copy(), np.zeros(len(tied), bool)
        for step in steps:
            cand = step(tied)
            hit = ~done & (cand.sum(axis=1) < size)
            new[hit] = cand[hit]
            done |= hit
        if not done.any():
            break
        tied = new
    return tied.argmax(axis=1)


def order(pct: np.ndarray, wins: np.ndarray, games: np.ndarray, keys: list, k: int,
          eligible: np.ndarray = None, sweep: bool = False) -> np.ndarray:
    """(n, k): the first k teams per run, one at a time - best winning share,
    then the tiebreaks (pick_best) among the teams level on it. -1 where a run
    has fewer than k eligible teams."""
    n, m = pct.shape
    left = np.ones((n, m), bool) if eligible is None else eligible.copy()
    out = np.full((n, k), -1)
    rows = np.arange(n)
    for r in range(k):
        has = left.any(axis=1)
        if not has.any():
            break
        pick = pick_best(keep_best(left, pct), wins, games, keys, sweep)
        out[:, r] = np.where(has, pick, -1)
        left[rows[has], pick[has]] = False
    return out


def bracket_order(slots: int) -> list:
    """Seed order down a fixed bracket: 1, 8, 4, 5, 2, 7, 3, 6 for eight."""
    out = [1]
    while len(out) < slots:
        size = 2 * len(out)
        out = [s for x in out for s in (x, size + 1 - x)]
    return out


def first_round(field_size: int, byes: int) -> list:
    """[(higher seed, lower seed)] of the opening games: 5 v 12, 6 v 11 ..."""
    return [(byes + 1 + k, field_size - k) for k in range((field_size - byes) // 2)]


# --------------------------------------------------------------------------- #
# The league as the simulation sees it
# --------------------------------------------------------------------------- #

@dataclass
class League:
    """Everything one projection needs, indexed by position in `teams`.

    `games` is the regular season up to the title week: integer `home` and
    `away` (len(teams) = the FCS pool), `neutral`, `conf_game`, `played`,
    `home_won` (1/0, NaN unplayed), `mean` (the model's margin, home
    advantage in it) and `ahead` (weeks out, unplayed games)."""
    teams: list
    names: dict
    conf: list
    division: list
    rating: np.ndarray               # len(teams) + 1: the FCS pool last
    home_edge: float
    margin_sd: float
    games: pd.DataFrame
    title: dict = field(default_factory=dict)      # conf -> {"pair": (i, j) | None, "winner": i | None}
    ahead: int = 1                   # weeks to the title games
    next_week: int = 1               # the first regular-season week still to play
    cfp_seeds: list = None           # the real field, seed order, once it is out
    cfp_results: dict = field(default_factory=dict)  # (i, j) -> winner, CFP games played
    final: bool = False              # the title game has been played
    record: dict = field(default_factory=dict)     # i -> (wins, losses), every game played


def _is_placeholder(team_id) -> bool:
    return team_id is None or str(team_id).strip() in ("", "nan", "None") \
        or str(team_id).startswith("-")


def title_week(schedule: pd.DataFrame) -> int:
    """The week of the conference title games, from ESPN's notes; one past
    the regular season when it has none."""
    note = schedule.get("note", pd.Series("", index=schedule.index)).fillna("")
    title = schedule[note.str.contains("Championship", case=False)
                     & ~note.str.contains("College Football Playoff", case=False)]
    from cfb.espn import POSTSEASON_WEEK
    title = title[title["week"] != POSTSEASON_WEEK]
    if len(title):
        return int(title["week"].min())
    regular = schedule[schedule["week"] != POSTSEASON_WEEK]
    return int(regular["week"].max()) + 1 if len(regular) else 1


def conference_map(fpi_payload: dict) -> tuple:
    """({id: conference}, {id: division}) from ESPN's FPI pull: the FBS, and
    the Sun Belt's East and West ("Sun Belt - East")."""
    conf, div = {}, {}
    for entry in (fpi_payload or {}).get("teams", []):
        team = entry.get("team") or {}
        name = (team.get("group") or {}).get("shortName")
        if not name or team.get("id") is None:
            continue
        tid = str(team["id"])
        if " - " in name:
            name, half = name.split(" - ", 1)
            div[tid] = half.strip()
        conf[tid] = INDEPENDENT if name == "FBS Indep." else name.strip()
    return conf, div


def build(frame: pd.DataFrame, model, names: dict, conf: dict, division: dict,
          schedule: pd.DataFrame, margin_sd: float, anchor: pd.Timestamp,
          fcs: str = "FCS") -> League:
    """A League from cfb.predict.season()'s frame, the raw ESPN schedule (for
    the title week and the CFP rows, which the frame drops while a side is
    TBD) and the conference map."""
    from cfb.espn import POSTSEASON_WEEK
    teams = sorted(t for t in conf if t in set(model.teams))
    index = {t: i for i, t in enumerate(teams)}
    pool = len(teams)
    rating = np.array([model.rating(t) for t in teams] + [model.rating(fcs)])
    probe = pd.DataFrame({"home_team": [teams[0]], "away_team": [teams[0]], "neutral": [False]})
    home_edge = float(model.predict(probe)["pred_margin"].iloc[0]) if teams else 0.0

    week_cut = title_week(schedule)
    reg = frame[(frame["week"] < week_cut) & (frame["week"] != POSTSEASON_WEEK)]
    known = set(index)
    reg = reg[reg["home_team"].isin(known) | reg["away_team"].isin(known)]
    played = reg["played"].astype(bool).to_numpy()
    margin = reg["actual_margin"].to_numpy(float)
    games = pd.DataFrame({
        "home": reg["home_team"].map(index).fillna(pool).astype(int).to_numpy(),
        "away": reg["away_team"].map(index).fillna(pool).astype(int).to_numpy(),
        "neutral": reg["neutral"].astype(bool).to_numpy(),
        "conf_game": (reg["conference_game"].astype(bool)
                      & (reg["home_team"].map(conf) == reg["away_team"].map(conf))).to_numpy(),
        "played": played,
        "home_won": np.where(played, (margin > 0).astype(float), np.nan),
        "mean": reg["pred_margin"].to_numpy(float),
        "ahead": weeks_ahead(reg["date"], anchor),
    })

    note = frame["note"].fillna("") if "note" in frame else pd.Series("", index=frame.index)
    when = pd.to_datetime(schedule["date_utc"], format="ISO8601", utc=True) \
        if "date_utc" in schedule else pd.Series(dtype="datetime64[ns, UTC]")
    title_dates = when[(schedule["week"] == week_cut)] if len(schedule) else when
    ahead = int(weeks_ahead(pd.Series([title_dates.max() if len(title_dates)
                                       else anchor + pd.Timedelta(days=7)]), anchor)[0])
    ahead = max(ahead, int(games["ahead"].where(~games["played"], 0).max() or 1))

    # A title game ESPN has filled: both teams known, perhaps the result too.
    title = {}
    rows = frame[(frame["week"] >= week_cut) & (frame["week"] != POSTSEASON_WEEK)
                 & note.str.contains("Championship", case=False)
                 & ~note.str.contains("College Football Playoff", case=False)]
    for _, g in rows.iterrows():
        h, a = str(g["home_team"]), str(g["away_team"])
        if h in index and a in index and conf.get(h) == conf.get(a):
            winner = None
            if bool(g["played"]) and pd.notna(g["actual_margin"]):
                winner = index[h] if g["actual_margin"] > 0 else index[a]
            title[conf[h]] = {"pair": (index[h], index[a]), "winner": winner}

    cfp_seeds, cfp_results, final = _real_field(schedule, index)
    open_weeks = reg.loc[~reg["played"].astype(bool), "week"]
    next_week = int(open_weeks.min()) if len(open_weeks) else int(week_cut)
    return League(teams=teams, names={t: names.get(t, t) for t in teams},
                  conf=[conf.get(t, "") for t in teams],
                  division=[division.get(t, "") for t in teams],
                  rating=rating, home_edge=home_edge, margin_sd=margin_sd, games=games,
                  title=title, ahead=ahead, next_week=next_week, cfp_seeds=cfp_seeds,
                  cfp_results=cfp_results, final=final, record=_record(frame, index))


def _record(frame: pd.DataFrame, index: dict) -> dict:
    """{team index: (wins, losses)} over every game played, whatever its week:
    the regular season, the title games, Army-Navy the Saturday after them,
    the bowls and the CFP - the record a team page prints. `games` stops at
    the title week, and a 12-0 champion read 12-0 from it all December."""
    w, l = np.zeros(len(index), int), np.zeros(len(index), int)
    done = frame[frame["played"].astype(bool) & frame["actual_margin"].notna()]
    for side, sign in (("home", 1), ("away", -1)):
        i = done[f"{side}_team"].astype(str).map(index)
        mine = i.notna()
        at = i[mine].astype(int).to_numpy()
        won = (done.loc[mine, "actual_margin"].to_numpy(float) * sign) > 0
        np.add.at(w, at, won.astype(int))
        np.add.at(l, at, (~won).astype(int))
    return {k: (int(w[k]), int(l[k])) for k in range(len(index))}


def _real_field(schedule: pd.DataFrame, index: dict) -> tuple:
    """(seeds, results, final) from ESPN's CFP rows once the field is out:
    the teams in them in the order of the ranks ESPN prints (straight
    seeding), the games played, and whether the title game is one of them."""
    from cfb.espn import POSTSEASON_WEEK
    if schedule is None or not len(schedule) or "note" not in schedule:
        return None, {}, False
    cfp = schedule[(schedule["week"] == POSTSEASON_WEEK)
                   & schedule["note"].fillna("").str.contains("College Football Playoff")]
    rank, results, final = {}, {}, False
    for _, g in cfp.iterrows():
        for side in ("home", "away"):
            tid = str(g[f"{side}_id"])
            if not _is_placeholder(tid) and tid in index:
                r = g.get(f"{side}_rank")
                rank.setdefault(index[tid], float(r) if pd.notna(r) else 99.0)
        h, a = str(g["home_id"]), str(g["away_id"])
        done = (g.get("state") == "post" and pd.notna(g.get("home_score"))
                and pd.notna(g.get("away_score")) and (g["home_score"] + g["away_score"]) > 0)
        if done and h in index and a in index:
            winner = index[h] if g["home_score"] > g["away_score"] else index[a]
            results[(index[h], index[a])] = winner
            if "National Championship" in str(g.get("note")):
                final = True
    if len(rank) < FORMAT.field:
        return None, results, final
    seeds = sorted(rank, key=lambda i: rank[i])[:FORMAT.field]
    return seeds, results, final


# --------------------------------------------------------------------------- #
# The simulation
# --------------------------------------------------------------------------- #

@dataclass
class Result:
    league: League
    n: int
    playoff: np.ndarray              # share of runs, per team
    bye: np.ndarray
    conf_title: np.ndarray
    title: np.ndarray
    seed_sum: np.ndarray             # seeds summed over the runs a team is in
    seed_count: np.ndarray           # (teams, field): runs at each seed

    def avg_seed(self) -> np.ndarray:
        runs = self.playoff * self.n
        return np.where(runs > 0, self.seed_sum / np.maximum(runs, 1), np.nan)


def _incidence(idx: np.ndarray, width: int) -> np.ndarray:
    out = np.zeros((len(idx), width), np.float32)
    out[np.arange(len(idx)), idx] = 1.0
    return out


def simulate(league: League, fmt: Format = FORMAT, n: int = N_SIMS, seed: int = SEED,
             sd_now: float = None, drift: float = RATING_DRIFT) -> Result:
    rng = np.random.default_rng(seed)
    sd_now = rating_sd_now(league.next_week) if sd_now is None else sd_now
    T = len(league.teams)
    acc = {k: np.zeros(T) for k in ("playoff", "bye", "conf_title", "title", "seed_sum")}
    seed_count = np.zeros((T, fmt.field))
    done = 0
    while done < n:
        m = min(CHUNK, n - done)
        _chunk(league, fmt, m, rng, sd_now, drift, acc, seed_count)
        done += m
    return Result(league=league, n=n, playoff=acc["playoff"] / n, bye=acc["bye"] / n,
                  conf_title=acc["conf_title"] / n, title=acc["title"] / n,
                  seed_sum=acc["seed_sum"], seed_count=seed_count)


def _conferences(league: League) -> list:
    """Conferences that play a title game: every one but the independents."""
    out = []
    for c in dict.fromkeys(league.conf):
        if c and c != INDEPENDENT and sum(1 for x in league.conf if x == c) >= 2:
            out.append(c)
    return out


def _chunk(league, fmt, n, rng, sd_now, drift, acc, seed_count):
    T, rows = len(league.teams), np.arange(n)
    g = league.games
    rem = g[~g["played"]]
    K = max(int(league.ahead), int(rem["ahead"].max()) if len(rem) else 1)
    S = shocks(rng, n, T + 1, K, sd_now, drift)
    noise = game_noise(league.margin_sd, sd_now, drift)
    r = league.rating.astype(np.float32)

    # ---- the regular season ------------------------------------------------
    h, a, k = (rem[c].to_numpy(int) for c in ("home", "away", "ahead"))
    margin = (rem["mean"].to_numpy(np.float32) + S[:, h, k] - S[:, a, k]
              + noise * rng.standard_normal((n, len(rem)), dtype=np.float32))
    hw = (margin > 0).astype(np.float32)                         # (n, remaining)

    played = g[g["played"]]
    base = np.zeros(T + 1)
    np.add.at(base, played["home"].to_numpy(int), played["home_won"].to_numpy(float))
    np.add.at(base, played["away"].to_numpy(int), 1 - played["home_won"].to_numpy(float))
    H, A = _incidence(h, T + 1), _incidence(a, T + 1)
    wins = base + hw @ H + (1 - hw) @ A                          # (n, T+1)

    # Conference records, and who beat whom inside each conference.
    cg = g["conf_game"].to_numpy(bool)
    rem_conf = cg[~g["played"].to_numpy(bool)]
    cbase, cgames = np.zeros(T + 1), np.zeros(T + 1)
    pc = played[played["conf_game"]]
    np.add.at(cbase, pc["home"].to_numpy(int), pc["home_won"].to_numpy(float))
    np.add.at(cbase, pc["away"].to_numpy(int), 1 - pc["home_won"].to_numpy(float))
    allc = g[g["conf_game"]]
    np.add.at(cgames, allc["home"].to_numpy(int), 1)
    np.add.at(cgames, allc["away"].to_numpy(int), 1)
    cwins = cbase + hw[:, rem_conf] @ H[rem_conf] + (1 - hw[:, rem_conf]) @ A[rem_conf]
    cpct = cwins / np.maximum(cgames, 1)

    strength = r[None, :] + S[:, :, K]                          # (n, T+1) at title time

    # ---- conference title games ---------------------------------------------
    champ = {}
    title_adj = np.zeros((n, T + 1))
    pref = _reference_win(league)                                # vs each team, neutral
    rem_index = {gid: j for j, gid in enumerate(rem.index)}
    for c in _conferences(league):
        members = np.array([i for i, x in enumerate(league.conf) if x == c])
        known = league.title.get(c)
        if known and known.get("pair"):
            ta = np.full(n, known["pair"][0])
            tb = np.full(n, known["pair"][1])
        else:
            ta, tb = _title_pair(league, members, c, cpct, allc, rem_index, hw, strength, n)
        if known and known.get("winner") is not None:
            winner = np.full(n, known["winner"])
        else:
            mg = strength[rows, ta] - strength[rows, tb] + noise * rng.standard_normal(n)
            winner = np.where(mg > 0, ta, tb)
        champ[c] = winner
        acc["conf_title"] += np.bincount(winner, minlength=T + 1)[:T]
        title_adj[rows, ta] += (winner == ta) - pref[tb]
        title_adj[rows, tb] += (winner == tb) - pref[ta]

    # ---- selection -------------------------------------------------------------
    score = (wins - _reference_wins(league) + title_adj + strength / RATING_PER_WIN)[:, :T]
    if league.cfp_seeds:
        seeds = np.tile(np.array(league.cfp_seeds[:fmt.field]), (n, 1))
    else:
        seeds = select(score, champ, league, fmt)

    for s in range(fmt.field):
        hits = np.bincount(seeds[:, s], minlength=T)
        acc["playoff"] += hits
        acc["seed_sum"] += hits * (s + 1)
        seed_count[:, s] += hits
        if s < fmt.byes:
            acc["bye"] += hits

    # ---- the bracket -------------------------------------------------------------
    champion = play_bracket(seeds, strength, league, fmt, noise, rng)
    acc["title"] += np.bincount(champion, minlength=T)[:T]


def _title_pair(league, members, c, cpct, allc, rem_index, hw, strength, n):
    """The two teams in conference c's title game, per run (global indices)."""
    m = len(members)
    local = {int(t): i for i, t in enumerate(members)}
    W = np.zeros((n, m, m), np.float32)
    P = np.zeros((m, m), np.float32)
    games = allc[allc["home"].isin(local) & allc["away"].isin(local)]
    i, j = games["home"].map(local).to_numpy(int), games["away"].map(local).to_numpy(int)
    np.add.at(P, (i, j), 1)
    np.add.at(P, (j, i), 1)
    done = games["played"].to_numpy(bool)
    won = np.empty((n, len(games)), np.float32)
    won[:, done] = games["home_won"].to_numpy(float)[done]
    if (~done).any():
        won[:, ~done] = hw[:, [rem_index[x] for x in games.index[~done]]]
    W += (scatter(m * m, i * m + j, won) + scatter(m * m, j * m + i, 1 - won)).reshape(n, m, m)
    pct = cpct[:, members]
    keys = [strength[:, members]]
    divs = [league.division[t] for t in members]
    halves = [d for d in dict.fromkeys(divs) if d]
    if len(halves) == 2:
        picks = [order(pct, W, P, keys, 1, eligible=np.tile(np.array(divs) == d, (n, 1)))[:, 0]
                 for d in halves]
    else:
        two = order(pct, W, P, keys, 2)
        picks = [two[:, 0], two[:, 1]]
    return members[picks[0]], members[picks[1]]


def _reference_rating(league: League) -> float:
    top = np.sort(league.rating[:-1])[::-1][:REFERENCE_TOP]
    return float(top.mean()) if len(top) else 0.0


def _reference_win(league: League) -> np.ndarray:
    """An average top-25 team's chance against each team on a neutral field."""
    return norm.cdf((_reference_rating(league) - league.rating) / league.margin_sd)


def _reference_wins(league: League) -> np.ndarray:
    """The wins an average top-25 team would expect against each team's
    regular season, venue by venue - the bar strength of record measures
    from."""
    ref, g = _reference_rating(league), league.games
    out = np.zeros(len(league.rating))
    edge = np.where(g["neutral"].to_numpy(bool), 0.0, league.home_edge)
    h, a = g["home"].to_numpy(int), g["away"].to_numpy(int)
    sd = league.margin_sd
    # In the home side's place the reference team is at home; in the away side's, away.
    np.add.at(out, h, norm.cdf((ref - league.rating[a] + edge) / sd))
    np.add.at(out, a, norm.cdf((ref - league.rating[h] - edge) / sd))
    return out


def select(score: np.ndarray, champ: dict, league: League, fmt: Format = FORMAT) -> np.ndarray:
    """(n, field): the field per run in seed order.

    The automatic bids (the power conferences' champions, the best Group of
    Six team or champion, an independent ranked high enough) go in first, and
    the best of the rest fill it; then everyone is seeded by the ranking."""
    n, T = score.shape
    rows = np.arange(n)
    auto = np.zeros((n, T), bool)
    for c in fmt.power:
        if c in champ:
            auto[rows, champ[c]] = True
    g6 = np.array([c in fmt.group_of_six for c in league.conf])
    if fmt.g6_bids and g6.any():
        pool = np.tile(g6, (n, 1))
        if fmt.g6_needs_title:
            pool = np.zeros((n, T), bool)
            for c in fmt.group_of_six:
                if c in champ:
                    pool[rows, champ[c]] = True
        masked = np.where(pool, score, -np.inf)
        best = np.argsort(-masked, axis=1)[:, :fmt.g6_bids]
        for j in range(best.shape[1]):
            ok = np.isfinite(masked[rows, best[:, j]])
            auto[rows[ok], best[ok, j]] = True
    for tid, cutoff in fmt.independents:
        if tid in league.teams:
            i = league.teams.index(tid)
            rank = 1 + (score > score[:, [i]]).sum(axis=1)
            auto[rows, i] |= rank <= cutoff
    key = score + auto * 1e6
    field_ = np.argsort(-key, axis=1, kind="stable")[:, :fmt.field]
    seeded = np.take_along_axis(field_, np.argsort(-np.take_along_axis(score, field_, 1),
                                                   axis=1, kind="stable"), 1)
    if fmt.champion_byes:
        champs = np.zeros((n, T), bool)
        for c, w in champ.items():
            champs[rows, w] = True
        is_c = np.take_along_axis(champs, seeded, 1)
        rank_c = np.cumsum(is_c, axis=1)
        top = is_c & (rank_c <= fmt.byes)
        order_ = np.argsort(~top, axis=1, kind="stable")
        seeded = np.take_along_axis(seeded, order_, 1)
    return seeded


def play_bracket(seeds: np.ndarray, strength: np.ndarray, league: League, fmt: Format,
                 noise: float, rng) -> np.ndarray:
    """The champion per run: the opening round on the higher seed's field,
    then a fixed bracket on neutral fields. A game already played is
    decided as it was."""
    n = len(seeds)
    rows = np.arange(n)
    T = len(league.teams)
    forced = np.zeros((T + 1, T + 1), np.int8)
    for (i, j), w in league.cfp_results.items():
        forced[i, j] = 1 if w == i else -1
        forced[j, i] = -forced[i, j]

    def play(x, y, home_x):
        mg = (strength[rows, x] - strength[rows, y] + (league.home_edge if home_x else 0.0)
              + noise * rng.standard_normal(n))
        f = forced[x, y]
        win = np.where(f == 1, True, np.where(f == -1, False, mg > 0))
        return np.where(win, x, y)

    slot = {s: seeds[:, s - 1] for s in range(1, fmt.byes + 1)}
    for hi, lo in first_round(fmt.field, fmt.byes):
        slot[hi] = play(seeds[:, hi - 1], seeds[:, lo - 1], fmt.home_first_round)
    alive = [slot[s] for s in bracket_order(len(slot))]
    while len(alive) > 1:
        alive = [play(alive[i], alive[i + 1], False) for i in range(0, len(alive), 2)]
    return alive[0]


# --------------------------------------------------------------------------- #
# The projected bracket
# --------------------------------------------------------------------------- #

def projected_field(res: Result, fmt: Format = FORMAT) -> list:
    """The bracket in seed order (team indices): the likeliest champion of
    each power conference, the likeliest Group of Six team(s), then the
    likeliest of the rest by playoff chance; seeded by average seed."""
    lg = res.league
    if lg.cfp_seeds:
        return list(lg.cfp_seeds[:fmt.field])
    T = len(lg.teams)
    chosen = []
    for c in fmt.power:
        members = [i for i in range(T) if lg.conf[i] == c]
        if members:
            best = max(members, key=lambda i: (res.conf_title[i], res.playoff[i]))
            if res.playoff[best] > 0:
                chosen.append(best)
    g6 = sorted((i for i in range(T) if lg.conf[i] in fmt.group_of_six),
                key=lambda i: -res.playoff[i])
    chosen += [i for i in g6[:fmt.g6_bids] if i not in chosen and res.playoff[i] > 0]
    for i in np.argsort(-res.playoff, kind="stable"):
        if len(chosen) >= fmt.field:
            break
        if int(i) not in chosen and res.playoff[i] > 0:
            chosen.append(int(i))
    avg = res.avg_seed()
    return sorted(chosen, key=lambda i: (avg[i], -res.playoff[i]))


def records(league: League) -> dict:
    """{team index: (wins, losses)} from the games played: the schedule's
    whole record where build() read one (League.record), else - a League put
    together by hand - the regular season's games, the title games and the
    CFP's."""
    if league.record:
        return dict(league.record)
    g = league.games[league.games["played"]]
    w = np.zeros(len(league.teams) + 1)
    l = np.zeros(len(league.teams) + 1)
    np.add.at(w, g["home"].to_numpy(int), g["home_won"].to_numpy(float))
    np.add.at(l, g["home"].to_numpy(int), 1 - g["home_won"].to_numpy(float))
    np.add.at(w, g["away"].to_numpy(int), 1 - g["home_won"].to_numpy(float))
    np.add.at(l, g["away"].to_numpy(int), g["home_won"].to_numpy(float))
    played = [(t["pair"], t["winner"]) for t in league.title.values()
              if t.get("pair") and t.get("winner") is not None]
    for pair, winner in played + list(league.cfp_results.items()):
        loser = pair[0] if winner == pair[1] else pair[1]
        w[winner], l[loser] = w[winner] + 1, l[loser] + 1
    return {i: (int(w[i]), int(l[i])) for i in range(len(league.teams))}


def anchor_time(schedule: pd.DataFrame) -> pd.Timestamp:
    """The moment the projection is fitted at: just after the last finished
    regular-season game, so builds between results use the same ratings and
    print the same numbers. Before any result, today."""
    from cfb.espn import POSTSEASON_WEEK
    if schedule is None or not len(schedule):
        return pd.Timestamp.now(tz="UTC").floor("D")
    done = schedule[(schedule["state"] == "post") & (schedule["week"] != POSTSEASON_WEEK)
                    & (schedule["home_score"].fillna(0) + schedule["away_score"].fillna(0) > 0)]
    if not len(done):
        return pd.Timestamp.now(tz="UTC").floor("D")
    return pd.to_datetime(done["date_utc"], format="ISO8601", utc=True).max() + pd.Timedelta(hours=6)


def project(n: int = N_SIMS, seed: int = SEED):
    """(Result, League, fpi payload) for this season, or (None, league, fpi)
    before a game is played. Reads the caches cfb.site.power and the build's
    schedule pull keep fresh."""
    from cfb import espn, predict
    from cfb.site import power
    try:
        payload = power.fpi()
    except Exception as exc:                            # noqa: BLE001 - the page says so
        print(f"  ! playoff: no FPI pull ({exc})")
        payload = {}
    conf, division = conference_map(payload)
    schedule = espn.schedule()
    anchor = anchor_time(schedule)
    frame, model, names = predict.season(asof=anchor)
    if not conf:
        return None, None, payload
    league = build(frame, model, names, conf, division, schedule, predict.margin_sd(), anchor)
    if not league.games["played"].any():
        return None, league, payload
    return simulate(league, n=n, seed=seed), league, payload


if __name__ == "__main__":
    import time
    t0 = time.time()
    res, league, _ = project()
    print(f"{time.time() - t0:.1f}s")
    if res is None:
        raise SystemExit("nothing to project yet")
    order_ = np.argsort(-res.playoff)
    avg = res.avg_seed()
    for i in order_[:30]:
        print(f"{league.names[league.teams[i]]:<22} {league.conf[i]:<14} "
              f"in {res.playoff[i]:6.1%}  bye {res.bye[i]:6.1%}  conf {res.conf_title[i]:6.1%}  "
              f"title {res.title[i]:6.1%}  seed {avg[i]:4.1f}")
    print([league.names[league.teams[i]] for i in projected_field(res)])
