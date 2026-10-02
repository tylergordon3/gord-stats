"""
Post-draft power rankings, by simulating the season the league actually plays.

A drafted roster is not a number, it is ten starting slots filled from fifteen
players across fourteen weeks, and the things that separate good rosters from
top-heavy ones — bench depth, bye-week pileups, whether the second running back
is startable when the first one is out — only show up when you make the roster
play. So the ranking is not a sum of player values. It is ten thousand seasons.

Each simulated season:

  1. Every player is dealt a true rate for the year, drawn from his projection
     and that projection's error bar (`fantasy.projections` measures both). A
     ranking that treated projections as facts would report 95% playoff odds it
     has no business reporting.
  2. Each week he is available or he is not, at his own historical rate, and he
     is out on his bye.
  3. Whoever is available scores, and the best legal lineup is filled:
     QB / RB / RB / WR / WR / TE / FLEX / FLEX / K / DEF.
  4. Team scores decide the week: one win against the head-to-head opponent,
     one more for finishing in the top half, which is how this league scores it.
  5. Fourteen weeks, then six playoff teams, then a bracket - reseeded each
     round, as the league plays it (the rules come from Sleeper: league_rules).

What comes out is a distribution — projected wins, points, playoff odds,
title odds. Player values anchor on the consensus ADP board with the usage
model as minority partner (fantasy.projections tells that story, including
why the anchor won the argument); what this module adds is everything a list
of player values cannot say — byes, injuries, depth, and a legal lineup every
week against the real schedule.

Once the season starts the simulation stops guessing at weeks that have
happened: played weeks carry each team's actual score, and only the weeks
still to come are drawn. So "projected wins" is always actual wins so far plus
the expected rest, and the page gains the record, an all-play-based luck
figure, and movement against a week ago and against draft night — every
build's table is archived under data/fantasy/power/{year}/ for that.

    python -m fantasy.league.power
"""
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests

from fantasy import paths, projections
from fantasy.league import consensus, external
from fantasy.league import matchups as matchups_mod
from fantasy import sleeper_retry
from fantasy.config import (
    FANTASY_REG_WEEKS, ROSTER_NAMES, UPCOMING_DRAFT_ID,
    UPCOMING_LEAGUE_ID, UPCOMING_YEAR,
)

SLEEPER_API = "https://api.sleeper.app/v1"
_TIMEOUT = 20

# The starting lineup, as the league defines it. FLEX takes RB/WR/TE.
STARTERS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "K": 1, "DEF": 1}
FLEX_SLOTS = 2
FLEX_POSITIONS = ("RB", "WR", "TE")

# The league's own rules, used where Sleeper's settings will not say
# (league_rules reads them): six teams, three weeks - quarters with two byes,
# semis, final - and a reseeded bracket, Sleeper's playoff_seed_type 1, which
# the league has played every season (2023-24 on). Reseeded, the top seed left
# meets the lowest seed left each round: in 2024-25 the 6 seed's upset sent it
# to the 1 seed in the semis, where the fixed bracket would have had it play 2.
PLAYOFF_TEAMS = 6
PLAYOFF_WEEKS = 3            # quarters (with two byes), semis, final
RESEED = True

# How long a player is out once he is out. Three weeks is the middle of the
# distribution of real absences: most are one or two, a few end the season.
MEAN_ABSENCE_WEEKS = 3.0
MIN_MU = 0.05                # a gamma needs a positive mean
MIN_SD = 0.5                 # and a positive variance

DEFAULT_SIMS = 10_000
SIM_CHUNK = 500              # sims per vectorized batch, to cap peak memory


# --------------------------------------------------------------------------- #
# Rosters
# --------------------------------------------------------------------------- #

def _get(url: str):
    """GET JSON, retrying a dropped handshake - see fantasy.sleeper_retry.

    This one was missed twice: once when the retry was added to the library,
    and again when it was added to the direct callers, because the URL here is
    a variable rather than a literal and the test was matching on the argument.
    """
    return sleeper_retry.get_json(url, timeout=_TIMEOUT)


def rosters(league_id: str = UPCOMING_LEAGUE_ID,
            draft_id: str = UPCOMING_DRAFT_ID) -> pd.DataFrame:
    """(roster_id, sleeper_id) for every rostered player.

    Reads the league's rosters, and falls back to the draft's picks when the
    league has not populated them yet — Sleeper fills `players` some minutes
    after a draft ends, and the whole point of this page is to be readable the
    moment the last pick is in.
    """
    rows = []
    for roster in _get(f"{SLEEPER_API}/league/{league_id}/rosters") or []:
        for player in roster.get("players") or []:
            rows.append({"roster_id": int(roster["roster_id"]),
                         "sleeper_id": str(player)})
    if rows:
        return pd.DataFrame(rows)

    for pick in _get(f"{SLEEPER_API}/draft/{draft_id}/picks") or []:
        if pick.get("roster_id") and pick.get("player_id"):
            rows.append({"roster_id": int(pick["roster_id"]),
                         "sleeper_id": str(pick["player_id"])})
    return pd.DataFrame(rows, columns=["roster_id", "sleeper_id"])


def matchups(league_id: str = UPCOMING_LEAGUE_ID, weeks: int = FANTASY_REG_WEEKS) -> dict:
    """{week: Sleeper matchup rows} for every week the league has posted.

    Stops at the first week with no matchup ids: before the season Sleeper
    returns an empty list for every week, and it builds the schedule out in
    order once it exists.
    """
    found = {}
    for week in range(1, weeks + 1):
        rows = [r for r in (_get(f"{SLEEPER_API}/league/{league_id}/matchups/{week}") or [])
                if r.get("matchup_id") is not None]
        if not rows:
            break
        found[week] = rows
    return found


def league_rules(league_id: str = UPCOMING_LEAGUE_ID) -> dict:
    """{weeks, playoff_teams, reseed} from Sleeper's league settings: the
    regular season is every week before `playoff_week_start`, the field is
    `playoff_teams`, and `playoff_seed_type` 1 reseeds the bracket each round.
    This league's long-standing values (FANTASY_REG_WEEKS, PLAYOFF_TEAMS,
    RESEED) stand in for anything Sleeper does not answer."""
    rules = {"weeks": FANTASY_REG_WEEKS, "playoff_teams": PLAYOFF_TEAMS, "reseed": RESEED}
    try:
        settings = (_get(f"{SLEEPER_API}/league/{league_id}") or {}).get("settings") or {}
    except Exception as exc:                                # noqa: BLE001
        print(f"  ! league settings unavailable ({exc}); the league's usual rules")
        return rules
    start = settings.get("playoff_week_start")
    if isinstance(start, (int, float)) and start > 1:
        rules["weeks"] = int(start) - 1
    if isinstance(settings.get("playoff_teams"), (int, float)) and settings["playoff_teams"] >= 2:
        rules["playoff_teams"] = int(settings["playoff_teams"])
    if settings.get("playoff_seed_type") is not None:
        rules["reseed"] = int(settings["playoff_seed_type"]) == 1
    return rules


def bracket_rounds(field: int) -> int:
    """Weeks a bracket of `field` teams takes: byes fill it to a power of two."""
    return max(int(field) - 1, 0).bit_length()


def bracket_losers(order: list, league_id: str = UPCOMING_LEAGUE_ID, rows=None):
    """[[team index, ...] per round]: who Sleeper's winners bracket says lost
    each round already decided, teams indexed by `order` - or None before any.

    Only elimination games count. Sleeper files placement games in the same
    bracket (third place, fifth place, rounds of their own once reseeded), and
    a game between two teams already beaten is one of those: so a team is out
    from the round after its first loss, and a game with an out team in it is
    not read. The simulation's seeds can disagree with Sleeper's on a tie
    break; with these the bracket still sends the teams Sleeper did through.
    """
    rows = _get(f"{SLEEPER_API}/league/{league_id}/winners_bracket") if rows is None else rows
    index = {int(rid): i for i, rid in enumerate(order)}
    out, losers = set(), []
    for rnd in sorted({int(m["r"]) for m in rows or [] if m.get("r") is not None}):
        lost = []
        for m in rows:
            if m.get("r") is None or int(m["r"]) != rnd:
                continue
            t1, t2, loser = m.get("t1"), m.get("t2"), m.get("l")
            if (not isinstance(t1, int) or not isinstance(t2, int) or t1 in out or t2 in out
                    or m.get("w") is None or loser is None):
                continue
            lost.append(int(loser))
        out |= set(lost)
        losers.append([index[rid] for rid in lost if rid in index])
    return losers if any(losers) else None


def playoff_points(order: list, over: int | None, league_id: str = UPCOMING_LEAGUE_ID,
                   first: int = FANTASY_REG_WEEKS + 1, rounds: int = PLAYOFF_WEEKS):
    """(played playoff weeks, teams) real scores, teams in `order` - for the
    playoff weeks Sleeper's clock has moved past - or None before any.

    The simulation drew the bracket from scratch every time, so after week 14
    a team knocked out in week 15 kept its title odds into January. Played
    playoff weeks are now taken as they happened, the way played regular-
    season weeks already were, and "higher score advances" does the rest. A
    team with no score that week (eliminated, or on a bye) counts 0; the
    bracket never reads it.
    """
    weeks = [w for w in range(first, first + rounds) if over is not None and w <= over]
    if not weeks:
        return None
    index = {int(rid): i for i, rid in enumerate(order)}
    out = []
    for week in weeks:
        scores = np.zeros(len(order))
        for r in _get(f"{SLEEPER_API}/league/{league_id}/matchups/{week}") or []:
            i = index.get(int(r.get("roster_id") or -1))
            if i is not None:
                scores[i] = float(r.get("points") or 0.0)
        out.append(scores)
    return np.array(out)


def schedule(league_id: str = UPCOMING_LEAGUE_ID, weeks: int = FANTASY_REG_WEEKS,
             posted: dict = None):
    """{week: {roster_id: opponent_roster_id}}, or None before Sleeper posts it.

    Returning None is not a failure: with no schedule the simulation deals a
    fresh random round-robin each season, which averages out schedule luck
    rather than baking one draw of it into the ranking.
    """
    posted = matchups(league_id, weeks) if posted is None else posted
    found = {}
    for week, rows in posted.items():
        by_matchup = {}
        for entry in rows:
            by_matchup.setdefault(entry["matchup_id"], []).append(int(entry["roster_id"]))
        pairs = {}
        for sides in by_matchup.values():
            if len(sides) == 2:
                pairs[sides[0]], pairs[sides[1]] = sides[1], sides[0]
        if pairs:
            found[week] = pairs
    return found or None


def scored_weeks(posted: dict, over: int | None = None) -> int:
    """How many regular-season weeks Sleeper has fully scored, counting from 1.

    A week counts once every team has points on it AND it is one of the `over`
    weeks Sleeper's clock has moved past (matchups.weeks_over). Points alone
    are true from Sunday lunchtime: Sleeper shows Thursday night's score on a
    week otherwise still to be played, and everyone has points long before
    Monday night is done. `over=None` (Sleeper would not say) leaves the
    points to decide, as they always did.
    """
    week = 0
    while (week + 1) in posted and (over is None or week + 1 <= over):
        rows = posted[week + 1]
        if not all(float(r.get("points") or 0) > 0 for r in rows):
            break
        week += 1
    return week


def actual_results(league_id: str = UPCOMING_LEAGUE_ID, through_week: int = 0,
                   posted: dict = None):
    """What has actually happened, for the weeks that are over.

    Returns None before any week is complete. Otherwise a dict with the team
    order (roster ids, ascending), a (weeks, teams) array of real scores, and
    per-team head-to-head wins, median wins, points for, and all-play record.
    A week only counts once every team has a score on it: nflverse says a
    week is published, but Sleeper can show a Thursday night's points on a
    week that is otherwise still to be played.

    A tie is half a win and half a loss, as Sleeper's W-L-T counts it in a
    standings race (`ties` says how many): a level head-to-head game used to
    be a loss for both sides, and a score level with the median a win or a
    loss on the order an argsort happened to leave the two in. The median
    game is won by scoring above the week's median, strictly.
    """
    if through_week <= 0:
        return None
    posted = matchups(league_id) if posted is None else posted
    weeks = [w for w in sorted(posted) if w <= through_week]
    if not weeks:
        return None

    order = sorted({int(r["roster_id"]) for r in posted[weeks[0]]})
    index = {rid: i for i, rid in enumerate(order)}
    n = len(order)
    points, h2h, median, allplay = [], np.zeros(n), np.zeros(n), np.zeros(n)
    ties = np.zeros(n)

    for week in weeks:
        rows = posted[week]
        scores = np.zeros(n)
        for r in rows:
            scores[index[int(r["roster_id"])]] = float(r.get("points") or 0.0)
        if scores.min() <= 0:
            break                                   # not a finished week
        by_matchup = {}
        for r in rows:
            by_matchup.setdefault(r["matchup_id"], []).append(index[int(r["roster_id"])])
        for sides in by_matchup.values():
            if len(sides) == 2:
                a, b = sides
                if scores[a] > scores[b]:
                    h2h[a] += 1
                elif scores[b] > scores[a]:
                    h2h[b] += 1
                else:
                    h2h[[a, b]] += 0.5
                    ties[[a, b]] += 1
        mid = np.median(scores)
        median += (scores > mid) + 0.5 * (scores == mid)
        ties += scores == mid
        # All-play: a win over every team scored under, half over every level.
        allplay += ((scores[:, None] > scores[None, :]).sum(axis=1)
                    + 0.5 * ((scores[:, None] == scores[None, :]).sum(axis=1) - 1))
        points.append(scores)

    if not points:
        return None
    played = len(points)
    points = np.array(points)
    allplay_pct = allplay / (played * (n - 1))
    return {
        "order": order, "points": points, "weeks": played,
        "h2h_wins": h2h, "median_wins": median, "wins": h2h + median, "ties": ties,
        "losses": 2 * played - (h2h + median),
        "points_for": points.sum(axis=0), "allplay_pct": allplay_pct,
        # What the all-play record says the team should have: win two a week
        # at its all-play rate. Luck is how far the real record sits from it.
        "luck": (h2h + median) - allplay_pct * 2 * played,
    }


# --------------------------------------------------------------------------- #
# The simulation
# --------------------------------------------------------------------------- #

class Roster:
    """One team's players, grouped by position and indexed into the score array."""

    def __init__(self, roster_id: int, frame: pd.DataFrame, offset: int):
        self.roster_id = roster_id
        self.name = ROSTER_NAMES.get(roster_id, f"Roster {roster_id}")
        self.frame = frame.reset_index(drop=True)
        self.slice = slice(offset, offset + len(frame))
        self.mu = self.frame["mu"].to_numpy(float)
        self.by_position = {
            pos: np.flatnonzero((frame["pos"] == pos).to_numpy())
            for pos in set(STARTERS) | set(FLEX_POSITIONS)
        }


def _fill(values: np.ndarray, keys: np.ndarray, count: int) -> tuple:
    """Take the best `count` by key, and hand back what is left over."""
    have = values.shape[-1]
    if have >= count:
        return values[..., :count].sum(-1), values[..., count:], keys[..., count:]
    padding = np.zeros(values.shape[:-1] + (count - have,))
    return (np.concatenate([values, padding], -1).sum(-1),
            values[..., :0], keys[..., :0])


def _lineup_points(scores: np.ndarray, available: np.ndarray,
                   roster: Roster) -> np.ndarray:
    """Points from the lineup a manager could actually have set: (sims, weeks).

    Starters are chosen on projection among whoever is available, never on the
    scores that are about to happen. Choosing with hindsight flattered every
    roster by about 7.5 points a week, and — because the benefit goes to
    whoever owns the most volatile bench — flattered some rosters four points a
    week more than others, which is large next to the gaps this page reports.

    A player who is out sorts below everyone and contributes nothing, so a team
    short of bodies at a position simply starts an empty slot, which is what
    actually happens.
    """
    key = np.where(available, roster.mu[None, None, :], -1.0)
    total = np.zeros(scores.shape[:2])
    leftovers = []
    for pos, count in STARTERS.items():
        columns = roster.by_position[pos]
        if len(columns) == 0:
            continue
        order = np.argsort(-key[..., columns], axis=-1)
        picked = np.take_along_axis(scores[..., columns], order, axis=-1)
        picked_keys = np.take_along_axis(key[..., columns], order, axis=-1)
        best, rest, rest_keys = _fill(picked, picked_keys, count)
        total += best
        if pos in FLEX_POSITIONS:
            leftovers.append((rest, rest_keys))

    if leftovers:
        pool = np.concatenate([v for v, _ in leftovers], axis=-1)
        pool_keys = np.concatenate([k for _, k in leftovers], axis=-1)
        order = np.argsort(-pool_keys, axis=-1)
        pool = np.take_along_axis(pool, order, axis=-1)
        pool_keys = np.take_along_axis(pool_keys, order, axis=-1)
        flex, _, _ = _fill(pool, pool_keys, FLEX_SLOTS)
        total += flex
    return total


# Sleeper's injury designations and the weeks a player is held out for, from
# the week the simulation is standing in. A reserve list (IR, PUP) is four
# games by rule; NA (not with the team) and a suspension are treated the same,
# an Out or Doubtful tag is this week. After the held-out weeks the chain
# takes over from the out state, so a player on IR comes back at the usual
# rate rather than on the dot.
FORCED_OUT = {"IR": 4, "PUP": 4, "NA": 4, "Sus": 4, "DNR": 4, "Out": 1, "Doubtful": 1, "COV": 1}
# Return dates are counted against the NFL's regular season; a date after it
# is the rest of the year.
NFL_WEEKS = 18


def injury_designations(year: int = UPCOMING_YEAR) -> dict:
    """{sleeper_id: Sleeper injury status} for rostered players, from the
    newest week the matchups archive holds - the current week refetches every
    few hours, so this is as fresh as the site gets. Empty if nothing is
    archived yet."""
    import json
    from fantasy.league import matchups as data_mod
    files = sorted((data_mod.MATCHUPS_DIR / str(year)).glob("week_*.json"))
    if not files:
        return {}
    data = json.loads(files[-1].read_text())
    return {pid: v["injury"] for pid, v in (data.get("projections") or {}).items()
            if v.get("injury")}


def seen_playing(year: int, week: int) -> set:
    """Rostered players the week's matchups archive already has in a game -
    a stat line with a game played, or points (availability.playing) - from
    the file alone; empty when the week is not archived."""
    import json
    from fantasy.league import availability
    path = matchups_mod._path(week, year)
    if week < 1 or not path.exists():
        return set()
    data = json.loads(path.read_text())
    pts = {}
    for m in data.get("matchups") or []:
        for side in m.get("sides") or []:
            pts.update(side.get("players_points") or {})
    stats = data.get("stats") or {}
    return {str(pid) for pid in set(stats) | set(pts)
            if availability.playing(stats.get(pid), pts.get(pid))}


def _availability(players: pd.DataFrame, weeks: int, sims: int,
                  rng: np.random.Generator, from_week: int = 0) -> np.ndarray:
    """(sims, weeks, players) of who is playing, byes included.

    Injuries persist. A weekly coin flip at each player's own rate gives the
    right number of missed games but spreads them evenly over every roster and
    every season, which is the one thing injuries never do — the risk that
    decides a fantasy season is a starter gone for a month, not everyone
    missing a scattered game apiece. So availability is a two-state chain:
    `avail` fixes the long-run share of weeks played and MEAN_ABSENCE_WEEKS
    how long a spell lasts once it starts, and the season opens in the
    stationary state rather than assuming everyone is healthy in week one.

    Except where we know better: `out_weeks` (from FORCED_OUT, when the frame
    carries it) holds a player out from `from_week` - the week being played
    next - for that many weeks, and the chain resumes from the out state.
    `out_from`, where the frame carries it, starts that many weeks later: a
    player already seen playing in the week the model has yet to count was
    hurt after it, and his absence begins the week after.
    """
    avail = players["avail"].to_numpy(float)
    bye = players["bye"].to_numpy(int)
    n = len(avail)
    out_weeks = (players["out_weeks"].fillna(0).to_numpy(int) if "out_weeks" in players
                 else np.zeros(n, dtype=int))
    start = from_week + (players["out_from"].fillna(0).to_numpy(int) if "out_from" in players
                         else np.zeros(n, dtype=int))

    back = 1.0 / MEAN_ABSENCE_WEEKS                    # out -> available
    out = np.clip(back * (1.0 - avail) / np.maximum(avail, 1e-9), 0.0, 1.0)

    playing = rng.random((sims, n)) < avail[None, :]
    states = np.empty((sims, weeks, n), dtype=bool)
    for week in range(weeks):
        draw = rng.random((sims, n))
        playing = np.where(playing, draw >= out[None, :], draw < back)
        held = (week >= start) & (week < start + out_weeks)
        if held.any():
            playing = playing & ~held[None, :]
        states[:, week, :] = playing

    week_index = np.arange(1, weeks + 1)[None, :, None]
    return states & ~(week_index == bye[None, None, :])


def _weekly_scores(players: pd.DataFrame, weeks: int, sims: int,
                   rng: np.random.Generator, from_week: int = 0) -> tuple:
    """((sims, weeks, players) of points, the same shape of availability)."""
    mu = players["mu"].to_numpy(float)
    sd = np.maximum(players["sd"].to_numpy(float), MIN_SD)
    mu_se = players["mu_se"].to_numpy(float)

    # One true rate per player per season: the projection's own uncertainty.
    true_mu = np.clip(mu[None, :] + rng.normal(0.0, 1.0, (sims, len(mu))) * mu_se[None, :],
                      MIN_MU, None)

    # A gamma matched on mean and variance, not a normal clipped at zero.
    # Weekly scores are non-negative and right-skewed, and clipping a normal
    # does not just reshape it, it adds points that were never projected —
    # worth +0.2 a week per player on this board, and up to +0.9 for the
    # volatile ones. That is a thumb on the scale for precisely the boom-or-bust
    # rosters this page exists to judge. A gamma keeps the mean it was handed.
    shape = (true_mu / sd[None, :]) ** 2
    scale = sd[None, :] ** 2 / true_mu
    scores = rng.gamma(shape[:, None, :], scale[:, None, :], size=(sims, weeks, len(mu)))

    available = _availability(players, weeks, sims, rng, from_week)
    return np.where(available, scores, 0.0), available


def _round_robin(rng: np.random.Generator, teams: int, weeks: int) -> np.ndarray:
    """(weeks, teams) opponent indices from a randomly rotated circle schedule.

    Even-sized leagues only, which this one has always been. With an odd number
    of teams one sits out each week and its row here stays zero, which reads as
    a fixture against whoever holds index 0 rather than as the bye it is. The
    browser's port of this (gordstats.my_power) fills with -1 and skips it,
    because a reader's league can be any size; fix it the same way here if this
    is ever pointed at one.
    """
    order = rng.permutation(teams)
    fixed, rotating = order[0], list(order[1:])
    table = np.zeros((weeks, teams), dtype=int)
    for week in range(weeks):
        pairs = [(fixed, rotating[0])]
        for i in range(1, teams // 2):
            pairs.append((rotating[i], rotating[-i]))
        for a, b in pairs:
            table[week, a], table[week, b] = b, a
        rotating = rotating[1:] + rotating[:1]
    return table


def bracket_order(size: int) -> list:
    """Seed numbers in bracket order, so adjacent pairs are the standard
    meeting: [1, 4, 2, 3] for four, [1, 8, 4, 5, 2, 7, 3, 6] for eight. Seeds
    past the field are byes, which is how six teams give the top two a week
    off. gordstats.my_power's bracketOrder, for the browser's twin."""
    order = [1]
    while len(order) < size:
        n = len(order) * 2
        order = [s for seed in order for s in (seed, n + 1 - seed)]
    return order


def _bracket(points: np.ndarray, seeds: np.ndarray, reseed: bool = False,
             decided: list = None) -> np.ndarray:
    """Title winner per sim, from playoff-week points and the seeds.

    `seeds` is (sims, field) team indices, best first; `points` (sims, rounds,
    teams). The top seeds sit out round one until the field is a power of two
    (six teams: 1 and 2 rest, 3 plays 6, 4 plays 5). After that the bracket is
    either fixed - the 1 seed meets the 4/5 winner - or, `reseed`, redrawn each
    round so the best seed left meets the worst left, which is how this league
    plays it (Sleeper's playoff_seed_type 1). Higher points wins, the better
    seed on a tie.

    `decided` is bracket_losers: whoever lost a round Sleeper has decided
    loses it here too, and every round after - the real result over anything
    the seeding or the points would say.

    gordstats.my_power's runBracket is the same bracket in the browser; the
    two are held to each other in tests.
    """
    sims, field = seeds.shape
    size = 1 << bracket_rounds(field)
    rows = np.arange(sims)[:, None]
    # Bracket positions as seed numbers (0 is the top seed), -1 a bye.
    pos = np.tile([s - 1 if s <= field else -1 for s in bracket_order(size)], (sims, 1))
    out = np.zeros(points.shape[2], dtype=bool)
    rnd = 0
    while pos.shape[1] > 1:
        if decided is not None and rnd < len(decided) and len(decided[rnd]):
            out[np.asarray(decided[rnd], dtype=int)] = True
        a, b = pos[:, 0::2], pos[:, 1::2]
        ta = np.take_along_axis(seeds, np.maximum(a, 0), axis=1)
        tb = np.take_along_axis(seeds, np.maximum(b, 0), axis=1)
        week = points[:, min(rnd, points.shape[1] - 1), :]
        pa = np.where(out[ta], -np.inf, week[rows, ta])
        pb = np.where(out[tb], -np.inf, week[rows, tb])
        pos = np.where(b < 0, a, np.where(a < 0, b, np.where(pa >= pb, a, b)))
        if reseed and pos.shape[1] > 2:
            # Best left against worst left: sorted, then paired from the ends.
            pos = np.sort(pos, axis=1)
            k = pos.shape[1]
            ends = np.column_stack([np.arange(k // 2), np.arange(k - 1, k // 2 - 1, -1)])
            pos = pos[:, ends.ravel()]
        rnd += 1
    return np.take_along_axis(seeds, pos, axis=1)[:, 0]


def simulate(board: pd.DataFrame, roster_frame: pd.DataFrame,
             weeks: int = FANTASY_REG_WEEKS, sims: int = DEFAULT_SIMS,
             fixed_schedule=None, actual_points=None, seed: int = 20260821,
             injuries: dict = None, playoff_points=None, held: dict = None,
             held_from: dict = None, playoff_teams: int = PLAYOFF_TEAMS,
             reseed: bool = False, decided: list = None) -> pd.DataFrame:
    """Run the season `sims` times and summarize each team's outcomes.

    `actual_points` is a (played weeks, teams) array of real scores, in
    ascending roster_id order; those weeks are taken as they happened in every
    simulation and only the rest of the season is drawn. `playoff_points` is
    the same for the playoff weeks already played (see playoff_points). `injuries` is
    {sleeper_id: Sleeper injury status} today; a player on a reserve list is
    held out of the next weeks (FORCED_OUT) instead of opening healthy. `held`,
    {sleeper_id: weeks}, says how many where it is known - ESPN's expected
    return dates (fantasy.league.injury_report.held_out) - and replaces the
    tag's flat count; `held_from`, {sleeper_id: weeks}, starts that hold later
    (a player hurt in a game of the week the model has yet to count).

    The bracket takes `playoff_teams` (byes for the top seeds) and is fixed
    unless `reseed` - rankings passes the league's own rules (league_rules);
    `decided` is bracket_losers, the rounds Sleeper has already settled.

    With a fixed schedule and a regular-season week still to play, each team's
    playoff odds are also split on the next week's head-to-head game - the
    same runs, counted by whether it won that game - into `playoff_if_win` and
    `playoff_if_loss`, with `win_prob`, `opponent` and `stakes_week` (1-based).
    The gap between the two is what the game is worth: the matchups page's
    game of the week and the power page's stakes table read it.
    """
    players = roster_frame.merge(board, on="sleeper_id", how="left")
    if held is not None:
        players["out_weeks"] = players["sleeper_id"].astype(str).map(
            lambda pid: int(held.get(pid, 0)))
    else:
        players["out_weeks"] = (players["sleeper_id"].astype(str)
                                .map(lambda pid: FORCED_OUT.get((injuries or {}).get(pid, ""), 0)))
    if held_from:
        players["out_from"] = players["sleeper_id"].astype(str).map(
            lambda pid: int(held_from.get(pid, 0)))
    played = min(len(actual_points), weeks) if actual_points is not None and len(actual_points) else 0
    missing = players["mu"].isna()
    if missing.any():
        # Anyone the projection board has never heard of is a deep-bench flier;
        # treating him as a zero would quietly punish whoever drafted him.
        players.loc[missing, ["mu", "sd", "mu_se", "avail", "bye"]] = [3.0, 3.0, 3.0, 0.6, 0]
        players.loc[missing, "pos"] = players.loc[missing, "pos"].fillna("WR")

    players = players.sort_values(["roster_id"]).reset_index(drop=True)
    teams, offset = [], 0
    for roster_id, group in players.groupby("roster_id", sort=True):
        teams.append(Roster(int(roster_id), group, offset))
        offset += len(group)
    players = players.reset_index(drop=True)

    rng = np.random.default_rng(seed)
    n_teams = len(teams)
    wins = np.zeros((0, n_teams))
    points_for = np.zeros((0, n_teams))
    made_playoffs = np.zeros(n_teams)
    titles = np.zeros(n_teams)
    seed_counts = np.zeros((n_teams, n_teams))
    # The next regular-season week's game: [made & won, won, made & lost, lost].
    stakes_week = played if (fixed_schedule is not None and played < min(weeks, len(fixed_schedule))) else None
    stakes = np.zeros((4, n_teams))
    done = 0

    field = min(int(playoff_teams), n_teams)
    rounds = bracket_rounds(field)
    while done < sims:
        batch = min(SIM_CHUNK, sims - done)
        total_weeks = weeks + rounds
        scores, available = _weekly_scores(players, total_weeks, batch, rng, from_week=played)

        team_points = np.stack(
            [_lineup_points(scores[:, :, team.slice], available[:, :, team.slice], team)
             for team in teams], axis=-1)
        if playoff_points is not None and len(playoff_points):
            k = min(len(playoff_points), rounds)
            team_points[:, weeks:weeks + k, :] = playoff_points[None, :k, :]
        regular = team_points[:, :weeks, :]
        if actual_points is not None and len(actual_points):
            played = min(len(actual_points), weeks)
            regular[:, :played, :] = actual_points[None, :played, :]

        # Above the week's median takes a win, the league's median rule; a
        # score level with it (and a level head-to-head game) is half of one,
        # as actual_results counts the weeks already played.
        mid = np.median(regular, axis=-1, keepdims=True)
        median_wins = ((regular > mid) + 0.5 * (regular == mid)).sum(axis=1)

        if fixed_schedule is not None:
            opponents = fixed_schedule
            opponent_points = regular[:, np.arange(weeks)[:, None], opponents]
            h2h = ((regular > opponent_points) + 0.5 * (regular == opponent_points)).sum(axis=1)
        else:
            h2h = np.zeros((batch, n_teams))
            for sim in range(batch):
                table = _round_robin(rng, n_teams, weeks)
                opponent_points = regular[sim][np.arange(weeks)[:, None], table]
                h2h[sim] = ((regular[sim] > opponent_points)
                            + 0.5 * (regular[sim] == opponent_points)).sum(axis=0)

        batch_wins = h2h + median_wins
        batch_points = regular.sum(axis=1)

        # Seed on wins, then points for — the league's tiebreaker.
        order = np.lexsort((-batch_points, -batch_wins), axis=-1)
        seeds = order[:, :field]
        made_playoffs += np.bincount(seeds.ravel(), minlength=n_teams)
        if stakes_week is not None:
            made = np.zeros((batch, n_teams), dtype=bool)
            made[np.arange(batch)[:, None], seeds] = True
            won = regular[:, stakes_week, :] > regular[:, stakes_week, fixed_schedule[stakes_week]]
            stakes += [(made & won).sum(axis=0), won.sum(axis=0),
                       (made & ~won).sum(axis=0), (~won).sum(axis=0)]
        for position in range(n_teams):
            seed_counts[:, position] += np.bincount(order[:, position], minlength=n_teams)

        champion = _bracket(team_points[:, weeks:, :], seeds, reseed=reseed, decided=decided)
        titles += np.bincount(champion, minlength=n_teams)

        wins = np.vstack([wins, batch_wins])
        points_for = np.vstack([points_for, batch_points])
        done += batch

    summary = pd.DataFrame({
        "roster_id": [team.roster_id for team in teams],
        "manager": [team.name for team in teams],
        "proj_wins": wins.mean(axis=0),
        "wins_p10": np.percentile(wins, 10, axis=0),
        "wins_p90": np.percentile(wins, 90, axis=0),
        "proj_points": points_for.mean(axis=0),
        "points_sd": points_for.std(axis=0),
        "playoff_odds": made_playoffs / sims,
        "title_odds": titles / sims,
        "first_seed_odds": seed_counts[:, 0] / sims,
        "last_odds": seed_counts[:, -1] / sims,
    })

    if stakes_week is not None:
        summary["stakes_week"] = stakes_week + 1
        summary["opponent"] = [teams[j].roster_id for j in fixed_schedule[stakes_week]]
        summary["win_prob"] = stakes[1] / sims
        summary["playoff_if_win"] = np.where(stakes[1] > 0, stakes[0] / np.maximum(stakes[1], 1), np.nan)
        summary["playoff_if_loss"] = np.where(stakes[3] > 0, stakes[2] / np.maximum(stakes[3], 1), np.nan)

    # One readable number, on the scale everyone already reads: points per week
    # relative to the league. Ranking on it and ranking on projected wins agree,
    # but this one does not round ten teams into four distinct values.
    per_week = summary["proj_points"] / weeks
    summary["power"] = 100.0 * per_week / per_week.mean()
    return summary.sort_values("power", ascending=False).reset_index(drop=True)


def starting_lineup(board: pd.DataFrame, roster_frame: pd.DataFrame) -> pd.DataFrame:
    """Each team's projected starters, for showing the roster behind the number."""
    players = roster_frame.merge(board, on="sleeper_id", how="left").dropna(subset=["mu"])
    rows = []
    for roster_id, group in players.groupby("roster_id"):
        group = group.sort_values("mu", ascending=False)
        used = set()
        for pos, count in STARTERS.items():
            picked = group[group["pos"] == pos].head(count)
            for _, player in picked.iterrows():
                used.add(player["sleeper_id"])
                rows.append({"roster_id": int(roster_id), "slot": pos, **player})
        flex = group[group["pos"].isin(FLEX_POSITIONS)
                     & ~group["sleeper_id"].isin(used)].head(FLEX_SLOTS)
        for _, player in flex.iterrows():
            rows.append({"roster_id": int(roster_id), "slot": "FLEX", **player})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Snapshot history
# --------------------------------------------------------------------------- #
# Every build's table is archived under data/fantasy/power/{year}/ — committed,
# unlike the projection cache, because it is the only record of what the page
# said before the season answered it. Two things read it: the Move column
# (rank against the newest snapshot at least a week old) and the preseason
# rank, which is the last table built before any week was played.

HISTORY_DIR = paths.DATA_DIR / "power"
SNAPSHOT_GAP_HOURS = 6       # four builds a day; one snapshot a day is plenty
MOVE_WINDOW = timedelta(days=7)
_SNAP_FMT = "%Y%m%d-%H%M%S"
_SNAP_COLS = ["roster_id", "manager", "power", "combined", "proj_wins", "proj_points",
              "playoff_odds", "title_odds", "week"]


def _history_dir(year):
    return HISTORY_DIR / str(year)


def _snapshots(year) -> list:
    """[(taken_at, path)] for every archived table, oldest first."""
    out = []
    for path in _history_dir(year).glob("*.parquet"):
        try:
            out.append((datetime.strptime(path.stem, _SNAP_FMT), path))
        except ValueError:
            continue                                  # preseason.parquet
    return sorted(out)


def write_snapshot(table: pd.DataFrame, year: int, week: int, when=None):
    """Archive a table, unless one was taken in the last few hours.

    Before kickoff the same table is also kept as preseason.parquet, replaced
    on every preseason build so the copy that survives is the last word
    before week 1 — draft night, as amended by every waiver move up to then.
    """
    when = when or datetime.now()
    out = _history_dir(year)
    out.mkdir(parents=True, exist_ok=True)
    keep = table[[c for c in _SNAP_COLS if c in table.columns]].assign(week=week)
    keep.attrs = {}          # with_movement leaves a datetime here; parquet can't take it
    if week == 0:
        keep.to_parquet(out / "preseason.parquet", index=False)
    snaps = _snapshots(year)
    if snaps and when - snaps[-1][0] < timedelta(hours=SNAPSHOT_GAP_HOURS):
        return
    keep.to_parquet(out / f"{when:{_SNAP_FMT}}.parquet", index=False)


def preseason(year: int):
    path = _history_dir(year) / "preseason.parquet"
    return pd.read_parquet(path) if path.exists() else None


def history(year: int) -> pd.DataFrame:
    """Every snapshot stacked, with `taken` — for the trend chart."""
    frames = []
    for taken, path in _snapshots(year):
        frames.append(pd.read_parquet(path).assign(taken=taken))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _rank_by_rating(frame: pd.DataFrame) -> pd.Series:
    """Rank on the published rating, so Move and Pre track the printed order.

    That is `combined` once an outside source is in the mix, and our own power
    when it is not — a snapshot taken while the source was unreachable still
    compares against later ones on the only basis both of them have.
    """
    column = "combined" if "combined" in frame.columns else "power"
    return frame.set_index("roster_id")[column].rank(ascending=False, method="min").astype(int)


def with_movement(table: pd.DataFrame, year: int, now=None) -> pd.DataFrame:
    """Add rank, the rank a week ago (`prev_rank`, `move`), and `pre_rank`.

    The week-ago baseline is the newest snapshot at or before the cutoff,
    falling back to the oldest on hand so a three-day-old archive still
    reports something; `prev_taken` says how far back it really goes.
    """
    now = now or datetime.now()
    table = table.copy()
    table["rank"] = _rank_by_rating(table).reindex(table["roster_id"]).to_numpy()

    snaps = _snapshots(year)
    older = [sp for sp in snaps if sp[0] <= now - MOVE_WINDOW]
    base = older[-1] if older else (snaps[0] if snaps else None)
    if base is not None:
        prev = _rank_by_rating(pd.read_parquet(base[1]))
        table["prev_rank"] = table["roster_id"].map(prev)
        table["move"] = table["prev_rank"] - table["rank"]
        table.attrs["prev_taken"] = base[0]
    else:
        table["prev_rank"] = pd.NA
        table["move"] = pd.NA

    pre = preseason(year)
    table["pre_rank"] = table["roster_id"].map(_rank_by_rating(pre)) if pre is not None else pd.NA
    return table


# --------------------------------------------------------------------------- #
# The whole thing
# --------------------------------------------------------------------------- #

class NoRosters(RuntimeError):
    """Nothing to rank: the draft has not happened, or Sleeper has not posted
    it. The one failure the power page answers with its pre-draft text."""


def rankings(year: int = UPCOMING_YEAR, sims: int = DEFAULT_SIMS,
             refresh: bool = False) -> tuple:
    """(rankings, projection board, rosters) for the upcoming season.

    The table carries actual results once there are any (record, points,
    all-play, luck), plus rank movement against the snapshot archive — and is
    itself archived before returning.
    """
    board = projections.load(year, refresh=refresh)
    roster_frame = rosters()
    if roster_frame.empty:
        raise NoRosters(
            "No rosters yet — the draft has not happened, or Sleeper has not "
            "published its picks. Nothing to rank.")

    # The season's length, the field and the bracket's rules, as Sleeper has
    # them this year (the league's long-standing ones if it will not say).
    rules = league_rules()
    weeks = rules["weeks"]
    posted = matchups(weeks=weeks)
    # A week is "played" only when Sleeper has scored all of it AND nflverse
    # has published it; each source gets ahead of the other in its own way.
    over = matchups_mod.weeks_over(year)
    scored = scored_weeks(posted, over=over)
    # Once the season is under way the rankings follow it: see
    # projections.current_form. Before kickoff this is a no-op.
    board = projections.current_form(board, year, through_week=scored)
    board = projections.with_sleeper(board, year, through_week=scored)
    table = schedule(posted=posted)
    fixed = None
    if table:
        order = sorted({rid for week in table.values() for rid in week})
        index = {rid: i for i, rid in enumerate(order)}
        fixed = np.array([[index[table[w][rid]] for rid in order]
                          for w in sorted(table)])

    through = min(scored, projections.completed_weeks(year))
    actual = actual_results(through_week=through, posted=posted)
    points = actual["points"] if actual else None
    # With the regular season in, the bracket's played weeks are taken as
    # they happened too - a team knocked out stops holding title odds - and
    # so are the rounds Sleeper has settled: who went through, whatever the
    # simulation's seeding or the points would say.
    playoff = decided = None
    if actual and actual["weeks"] >= weeks:
        rounds = bracket_rounds(rules["playoff_teams"])
        playoff = playoff_points(actual["order"], over, first=weeks + 1, rounds=rounds)
        try:
            decided = bracket_losers(actual["order"])
        except Exception as exc:                            # noqa: BLE001
            print(f"  ! winners bracket unavailable ({exc}); the points alone")
    # How long each injured player is out: ESPN's expected return date where
    # its report has one, the Sleeper tag's flat count where it does not.
    # The model counts a week a day or two after it ends (nflverse), so the
    # week it plays next can be one some players have played already: one
    # seen in it was hurt after his game, and his absence starts the week
    # after - not in a game he played (held_from).
    tags = injury_designations(year)
    from_week = actual["weeks"] if actual else 0
    held_from = None
    try:
        from fantasy.league import injury_report
        seen = seen_playing(year, from_week + 1)
        held = injury_report.held_out(tags, from_week=from_week, weeks=NFL_WEEKS, year=year,
                                      seen=seen)
        held_from = {pid: 1 for pid in held if pid in seen} or None
    except Exception as exc:                                # noqa: BLE001
        print(f"  ! injury return dates unavailable ({exc}); Sleeper's tags alone")
        held = None
    # And the other half of an injury: his work goes to the teammates behind
    # him for as long as he is out (fantasy.league.opportunity).
    if held:
        try:
            from fantasy.league import opportunity
            from fantasy.site.season_board import SEASON_WEEKS, depth_charts
            played_weeks = actual["weeks"] if actual else 0
            board = opportunity.apply(board, opportunity.for_board(
                board, held, year, scored, weeks_left=max(SEASON_WEEKS - played_weeks, 1),
                depth=depth_charts()))
        except Exception as exc:                            # noqa: BLE001
            print(f"  ! next-man-up boosts not applied ({exc})")
    summary = simulate(board, roster_frame, weeks=weeks, sims=sims, fixed_schedule=fixed,
                       actual_points=points, injuries=tags, held=held, held_from=held_from,
                       playoff_points=playoff, playoff_teams=rules["playoff_teams"],
                       reseed=rules["reseed"], decided=decided)

    week = actual["weeks"] if actual else 0
    summary["week"] = week
    if actual:
        facts = pd.DataFrame({
            "roster_id": actual["order"], "wins": actual["wins"], "losses": actual["losses"],
            "ties": actual["ties"],
            "points_for": actual["points_for"], "allplay_pct": actual["allplay_pct"],
            "luck": actual["luck"],
        })
        summary = summary.merge(facts, on="roster_id", how="left")

    # The published ranking is our simulation blended with an outside source;
    # see fantasy.league.consensus for why they are averaged on a common scale
    # rather than by rank, and what happens when the source is unreachable.
    summary = consensus.combined(summary, external.load(year))
    summary = summary.sort_values("combined", ascending=False).reset_index(drop=True)

    summary = with_movement(summary, year)
    write_snapshot(summary, year, week)
    # The rules it was played under, for the page's games left and its field.
    summary.attrs["rules"] = rules
    return summary, board, roster_frame


def draft_day_rosters(season_str: str) -> pd.DataFrame:
    """(roster_id, sleeper_id) as a past season's draft left them."""
    from fantasy.config import DRAFT_IDS

    picks = _get(f"{SLEEPER_API}/draft/{DRAFT_IDS[season_str]}/picks") or []
    return pd.DataFrame([{"roster_id": int(p["roster_id"]),
                          "sleeper_id": str(p["player_id"])}
                         for p in picks if p.get("roster_id") and p.get("player_id")])


def backtest(season_str: str, season_year: int, sims: int = 3000) -> pd.DataFrame:
    """Rank a past season's draft-day rosters, beside what actually happened.

    The projection is rebuilt from the five seasons before `season_year`, so it
    knows nothing about the year it is being scored on. What it cannot correct
    for is the rest of the season: waivers, trades, and who each manager
    actually chose to start. So this compares a draft-day roster to a
    fourteen-week result, and the gap between them is the league, not the model.
    """
    from fantasy import paths

    board = projections.build(season_year)
    table = simulate(board, draft_day_rosters(season_str), sims=sims, reseed=RESEED)

    actual = pd.read_json(paths.SEASON_DIR / f"{season_str}.json")
    actual = actual[actual["week"] == FANTASY_REG_WEEKS][
        ["roster_id", "PF", "total_wins"]]
    merged = table.merge(actual, on="roster_id")
    merged["proj_rank"] = merged["proj_points"].rank(ascending=False).astype(int)
    merged["actual_rank"] = merged["PF"].rank(ascending=False).astype(int)
    return merged


if __name__ == "__main__":
    table, _, _ = rankings()
    print(table.to_string(index=False, float_format=lambda v: f"{v:.2f}"))
