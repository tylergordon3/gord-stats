"""
Best Ball calculations (src/): what each team's score would have been with its
optimal lineup each week, plus season standings.

Uses Sleeper's authoritative per-player points (league scoring); fantasy.stats is
only used to resolve each player's name/position.

Library only - the Best Ball pages were retired from the site, so nothing here
writes HTML. `compute()` is the entry point; it refreshes data/bestball.json and
returns the per-week outcomes plus the standings frame.

    from fantasy.site.bestball import compute
    outcomes, standings = compute("2526")
"""
import json
from io import StringIO

import pandas as pd
from sleeper_wrapper import League

from fantasy import stats, util
from fantasy.config import DATA_DIR, LEAGUE_IDS, SEASON_YEAR
from fantasy.league import rosters as rosters_mod

BESTBALL_JSON = DATA_DIR / "bestball.json"
LINEUP = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 2, "DEF": 1, "K": 1}


def _create_df(raw: pd.DataFrame, db: pd.DataFrame) -> pd.DataFrame:
    raw = raw.copy()
    raw["obj"] = raw["id"].apply(lambda x: stats.from_id(x, db))
    raw["name"] = raw["obj"].apply(lambda y: y.cleaned_name.item() if not y.cleaned_name.empty else "err")
    raw["position"] = raw["obj"].apply(lambda y: y.position.item() if not y.position.empty else "err")
    valid = raw[(raw["name"] != "err")]
    return valid.drop(columns=["obj"])


def _best_lineup(df: pd.DataFrame) -> pd.DataFrame:
    best = pd.DataFrame()
    for pos, amt in LINEUP.items():
        if pos == "FLEX":
            pool = df[df["position"].isin(["RB", "TE", "WR"])].copy()
            pool["position"] = "FLEX"
        else:
            pool = df[df["position"] == pos]
        pool = pool.sort_values("points", ascending=False)
        best = pd.concat([best, pool.iloc[0:amt]])
        df = df.drop(pool.iloc[0:amt].index)
    return best


def _weekly(week: int, league: League, db: pd.DataFrame) -> pd.DataFrame:
    matchups = pd.DataFrame.from_dict(league.get_matchups(week))
    combined = pd.DataFrame()
    for _, team in matchups.iterrows():
        raw = pd.DataFrame(team["players_points"].items(), columns=["id", "points"])
        best = _best_lineup(_create_df(raw, db))
        best["roster_id"] = team["roster_id"]
        best["week"] = week
        combined = pd.concat([combined, best])
    return combined


def _matchup_pairs(matchups: pd.DataFrame):
    n = int(matchups["matchup_id"].max())
    return [list(matchups[matchups["matchup_id"] == i + 1]["roster_id"]) for i in range(n)]


# --------------------------------------------------------------------------- #
# Season outcomes + standings
# --------------------------------------------------------------------------- #

def _team_totals(week_df, roster_id, matchups):
    team = week_df[week_df["roster_id"] == roster_id]
    new_total = round(float(team["points"].sum()), 2)
    original = matchups[matchups["roster_id"] == roster_id]["points"].iloc[0]
    return new_total, original


def _results(season_df, matchups_by_week, league):
    def win(a, b):
        return 1 if a > b else 0

    outcomes = pd.DataFrame()
    for week in range(1, int(season_df["week"].max()) + 1):
        matchups = pd.DataFrame.from_dict(league.get_matchups(week))
        wk = season_df[season_df["week"] == week]
        for a, b in matchups_by_week[week]:
            a_bb, a_og = _team_totals(wk, a, matchups)
            b_bb, b_og = _team_totals(wk, b, matchups)
            outcomes = pd.concat([outcomes, pd.DataFrame({
                "week": week, "roster_id": [a, b],
                "score": [a_og, b_og], "bb_score": [a_bb, b_bb],
                "opp_score": [b_og, a_og], "bb_opp_score": [b_bb, a_bb],
                "winner": [win(a_og, b_og), win(b_og, a_og)],
                "bb_winner": [win(a_bb, b_bb), win(b_bb, a_bb)],
            })])
    outcomes = outcomes.reset_index(drop=True)

    def med(group):
        return (group > group.median()).astype(int)

    outcomes["median"] = outcomes.groupby("week")["score"].transform(med)
    outcomes["bb_median"] = outcomes.groupby("week")["bb_score"].transform(med)
    return outcomes


def bestball_season(season_str: str, league: League) -> pd.DataFrame:
    """Compute every week's best lineups, cache the outcomes, and return them."""
    end_week = min(14, util.get_week()) if season_str == util.year_str() else 14
    full_db = stats.get(0, SEASON_YEAR[season_str])   # full-season points, computed once
    season_combined, matchups_by_week = pd.DataFrame(), {}
    for week in range(1, end_week + 1):
        db = full_db[full_db["week"] == week]
        season_combined = pd.concat([season_combined, _weekly(week, league, db)])
        matchups_by_week[week] = _matchup_pairs(pd.DataFrame.from_dict(league.get_matchups(week)))

    outcomes = _results(season_combined, matchups_by_week, league)
    with open(BESTBALL_JSON, "w", encoding="utf-8") as f:
        json.dump(outcomes.to_json(), f, indent=4)
    return outcomes


def standings(league: League) -> pd.DataFrame:
    """Best-ball vs actual standings, read from the cached data/bestball.json."""
    with open(BESTBALL_JSON, "r", encoding="utf-8") as f:
        df = pd.read_json(StringIO(json.load(f)))
    last_wk = df["week"].max()

    r = rosters_mod.get(league)[["roster_id", "wins", "team_name", "PF", "PA"]].set_index("roster_id")
    r = r.rename(columns={"wins": "Wins", "team_name": "Team"})
    r["BestBall Wins"] = df.groupby("roster_id")["bb_median"].sum() + df.groupby("roster_id")["bb_winner"].sum()
    r["Losses"] = last_wk * 2 - r["Wins"]
    r["BestBall Losses"] = last_wk * 2 - r["BestBall Wins"]
    r["Record"] = r["Wins"].astype(int).astype(str) + "-" + r["Losses"].astype(int).astype(str)
    r["BB Record"] = r["BestBall Wins"].astype(int).astype(str) + "-" + r["BestBall Losses"].astype(int).astype(str)
    r["BB PF"] = df.groupby("roster_id")["bb_score"].sum()
    r["BB PA"] = df.groupby("roster_id")["bb_opp_score"].sum()
    r["Change"] = r["BestBall Wins"] - r["Wins"]
    r = r.sort_values("BestBall Wins", ascending=False)
    return r[["Team", "Change", "BB Record", "BB PF", "BB PA", "Record", "PF", "PA"]]


def compute(season_str: str):
    """Refresh a season's best-ball cache. Returns (outcomes, standings)."""
    league = League(LEAGUE_IDS[season_str])
    outcomes = bestball_season(season_str, league)
    return outcomes, standings(league)
