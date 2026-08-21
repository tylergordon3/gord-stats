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
  5. Fourteen weeks, then six playoff teams, then a bracket.

What comes out is a distribution — projected wins, points, playoff odds, title
odds — and none of it has looked at where anybody was drafted.

    python -m fantasy.league.power
"""
import numpy as np
import pandas as pd
import requests

from fantasy import projections
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

PLAYOFF_TEAMS = 6
PLAYOFF_WEEKS = 3            # quarters (with two byes), semis, final

DEFAULT_SIMS = 10_000
SIM_CHUNK = 500              # sims per vectorized batch, to cap peak memory


# --------------------------------------------------------------------------- #
# Rosters
# --------------------------------------------------------------------------- #

def _get(url: str):
    response = requests.get(url, timeout=_TIMEOUT)
    response.raise_for_status()
    return response.json()


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


def schedule(league_id: str = UPCOMING_LEAGUE_ID, weeks: int = FANTASY_REG_WEEKS):
    """{week: {roster_id: opponent_roster_id}}, or None before Sleeper posts it.

    Returning None is not a failure: with no schedule the simulation deals a
    fresh random round-robin each season, which averages out schedule luck
    rather than baking one draw of it into the ranking.
    """
    found = {}
    for week in range(1, weeks + 1):
        matchups = _get(f"{SLEEPER_API}/league/{league_id}/matchups/{week}") or []
        pairs = {}
        by_matchup = {}
        for entry in matchups:
            if entry.get("matchup_id") is None:
                continue
            by_matchup.setdefault(entry["matchup_id"], []).append(int(entry["roster_id"]))
        for sides in by_matchup.values():
            if len(sides) == 2:
                pairs[sides[0]], pairs[sides[1]] = sides[1], sides[0]
        if not pairs:
            return None
        found[week] = pairs
    return found or None


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
        self.by_position = {
            pos: np.flatnonzero((frame["pos"] == pos).to_numpy())
            for pos in set(STARTERS) | set(FLEX_POSITIONS)
        }


def _rank_desc(scores: np.ndarray, columns: np.ndarray) -> np.ndarray:
    """Scores for `columns`, sorted high to low along the player axis."""
    if len(columns) == 0:
        return np.zeros(scores.shape[:-1] + (0,))
    return -np.sort(-scores[..., columns], axis=-1)


def _take(sorted_scores: np.ndarray, count: int) -> tuple:
    """(sum of the best `count`, whatever is left over) — zero-padded if short."""
    have = sorted_scores.shape[-1]
    if have >= count:
        return sorted_scores[..., :count].sum(axis=-1), sorted_scores[..., count:]
    padding = np.zeros(sorted_scores.shape[:-1] + (count - have,))
    return (np.concatenate([sorted_scores, padding], axis=-1).sum(axis=-1),
            sorted_scores[..., :0])


def _lineup_points(scores: np.ndarray, roster: Roster) -> np.ndarray:
    """Best legal lineup for one team: (sims, weeks) of starting points.

    Filling the fixed slots first and handing the flex whatever ranks highest
    among the leftovers is optimal here, because the flex accepts every position
    that could have been left over.
    """
    total = np.zeros(scores.shape[:2])
    leftovers = []
    for pos, count in STARTERS.items():
        best, rest = _take(_rank_desc(scores, roster.by_position[pos]), count)
        total += best
        if pos in FLEX_POSITIONS:
            leftovers.append(rest)

    if leftovers:
        pool = np.concatenate(leftovers, axis=-1)
        pool = -np.sort(-pool, axis=-1)
        flex, _ = _take(pool, FLEX_SLOTS)
        total += flex
    return total


def _weekly_scores(players: pd.DataFrame, weeks: int, sims: int,
                   rng: np.random.Generator) -> np.ndarray:
    """(sims, weeks, players) of points, after byes and availability."""
    mu = players["mu"].to_numpy(float)
    sd = players["sd"].to_numpy(float)
    mu_se = players["mu_se"].to_numpy(float)
    avail = players["avail"].to_numpy(float)
    bye = players["bye"].to_numpy(int)

    # One true rate per player per season: the projection's own uncertainty.
    true_mu = np.clip(mu[None, :] + rng.normal(0.0, 1.0, (sims, len(mu))) * mu_se[None, :],
                      0.0, None)

    scores = rng.normal(true_mu[:, None, :], sd[None, None, :],
                        size=(sims, weeks, len(mu)))
    np.clip(scores, 0.0, None, out=scores)          # nobody scores negative in practice

    playing = rng.random((sims, weeks, len(mu))) < avail[None, None, :]
    week_index = np.arange(1, weeks + 1)[None, :, None]
    on_bye = week_index == bye[None, None, :]
    return np.where(playing & ~on_bye, scores, 0.0)


def _round_robin(rng: np.random.Generator, teams: int, weeks: int) -> np.ndarray:
    """(weeks, teams) opponent indices from a randomly rotated circle schedule."""
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


def _bracket(points: np.ndarray, seeds: np.ndarray) -> np.ndarray:
    """Title winner per sim, from playoff-week points and the six seeds.

    Seeds 1 and 2 sit out the first round; 3 plays 6 and 4 plays 5; the two
    winners meet the byes; the survivors play for it. Higher points wins, which
    is how the league's bracket already works.
    """
    sims = seeds.shape[0]
    rows = np.arange(sims)

    def better(week, left, right):
        return np.where(points[rows, week, left] >= points[rows, week, right],
                        left, right)

    quarter_a = better(0, seeds[:, 2], seeds[:, 5])
    quarter_b = better(0, seeds[:, 3], seeds[:, 4])
    semi_a = better(1, seeds[:, 0], quarter_b)
    semi_b = better(1, seeds[:, 1], quarter_a)
    return better(2, semi_a, semi_b)


def simulate(board: pd.DataFrame, roster_frame: pd.DataFrame,
             weeks: int = FANTASY_REG_WEEKS, sims: int = DEFAULT_SIMS,
             fixed_schedule=None, seed: int = 20260821) -> pd.DataFrame:
    """Run the season `sims` times and summarize each team's outcomes."""
    players = roster_frame.merge(board, on="sleeper_id", how="left")
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
    done = 0

    while done < sims:
        batch = min(SIM_CHUNK, sims - done)
        total_weeks = weeks + PLAYOFF_WEEKS
        scores = _weekly_scores(players, total_weeks, batch, rng)

        team_points = np.stack(
            [_lineup_points(scores[:, :, team.slice], team) for team in teams], axis=-1)
        regular = team_points[:, :weeks, :]

        # Top half of the league takes a win, same as the league's median rule.
        ranks = (-regular).argsort(axis=-1).argsort(axis=-1)
        median_wins = (ranks < n_teams // 2).sum(axis=1).astype(float)

        if fixed_schedule is not None:
            opponents = fixed_schedule
            opponent_points = regular[:, np.arange(weeks)[:, None], opponents]
            h2h = (regular > opponent_points).sum(axis=1).astype(float)
        else:
            h2h = np.zeros((batch, n_teams))
            for sim in range(batch):
                table = _round_robin(rng, n_teams, weeks)
                opponent_points = regular[sim][np.arange(weeks)[:, None], table]
                h2h[sim] = (regular[sim] > opponent_points).sum(axis=0)

        batch_wins = h2h + median_wins
        batch_points = regular.sum(axis=1)

        # Seed on wins, then points for — the league's tiebreaker.
        order = np.lexsort((-batch_points, -batch_wins), axis=-1)
        seeds = order[:, :PLAYOFF_TEAMS]
        made_playoffs += np.bincount(seeds.ravel(), minlength=n_teams)
        for position in range(n_teams):
            seed_counts[:, position] += np.bincount(order[:, position], minlength=n_teams)

        champion = _bracket(team_points[:, weeks:, :], seeds)
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


def rankings(year: int = UPCOMING_YEAR, sims: int = DEFAULT_SIMS,
             refresh: bool = False) -> tuple:
    """(rankings, projection board, rosters) for the upcoming season."""
    board = projections.load(year, refresh=refresh)
    # Once the season is under way the rankings follow it: see
    # projections.current_form. Before kickoff this is a no-op.
    board = projections.current_form(board, year)
    roster_frame = rosters()
    if roster_frame.empty:
        raise RuntimeError(
            "No rosters yet — the draft has not happened, or Sleeper has not "
            "published its picks. Nothing to rank.")

    table = schedule()
    fixed = None
    if table:
        order = sorted({rid for week in table.values() for rid in week})
        index = {rid: i for i, rid in enumerate(order)}
        fixed = np.array([[index[table[w][rid]] for rid in order]
                          for w in sorted(table)])
    return simulate(board, roster_frame, sims=sims, fixed_schedule=fixed), board, roster_frame


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
    table = simulate(board, draft_day_rosters(season_str), sims=sims)

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
