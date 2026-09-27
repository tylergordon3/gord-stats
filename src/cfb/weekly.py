"""
What a rostered player is worth *this week*, in this league's points.

The draft board (cfb.projections) prices a season; a matchup is one week, and
a week is one game - or none, on a bye. So a weekly projection here is the
season projection spread over the games the school actually plays, tilted by
what the site's own model expects of this particular game:

  * A skill player's per-game share of his season projection, scaled by how
    the model's predicted score for his offence this week compares with what
    it predicts for that offence on average. The opponent, the venue and the
    week are all already in that predicted score, which is why nothing else is
    added on top.
  * A defense priced straight off the game, the way the season board prices
    it: the model's predicted opponent score integrated over Yahoo's
    points-allowed brackets, plus the big-play line.
  * Zero on a bye - the one thing a season projection cannot say and the
    thing a lineup is most often wrong about.

The tilt is stronger than the season board's ENV_WEIGHT, deliberately: the
board's tilt corrects a ranking that already knows which offences are good,
while a single week's number has to carry the opponent by itself.

    python -m cfb.weekly            # this week's top projections
"""
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from cfb import in_season, predict, projections, schools as schools_mod, yahoo
from cfb.config import LEAGUE_TZ

# The exponent on (this game's predicted score / the offence's season average)
# and the band the result is held inside. At 0.6 a game the model prices 25%
# above the offence's norm lifts its players about 14%.
#
# The band is lopsided on purpose. Downward, a hard opponent really does cost
# a starter his share, so the tilt runs to -30%. Upward it stops at +10%: the
# games the model prices far above an offence's norm are the mismatches, and
# in those the starters sit for the second half. Week 1 of 2026 was the
# evidence - 30% of the league's starters hit the old +30% cap and the
# lineups projected 214 against 191 scored, while the untilted number was
# within a point. A margin-based benching haircut was tried and did no better
# than simply not tilting up.
GAME_WEIGHT = 0.6
GAME_CAP_DOWN = 0.30
GAME_CAP_UP = 0.10

# Yahoo's injury designations and what a week is worth under each: out, on a
# reserve list, suspended or not with the team is nothing; doubtful about a
# game in four; questionable and probable play, and the projection stands.
STATUS_FACTOR = {"O": 0.0, "IR": 0.0, "IR-R": 0.0, "PUP": 0.0, "SUSP": 0.0, "NA": 0.0,
                 "NFI": 0.0, "D": 0.25}


def _window(start: str, end: str) -> tuple:
    """A Yahoo week's [start, end] dates as UTC bounds covering whole local days."""
    lo = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=LEAGUE_TZ)
    hi = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=LEAGUE_TZ) + timedelta(days=1)
    return pd.Timestamp(lo).tz_convert("UTC"), pd.Timestamp(hi).tz_convert("UTC")


def games_between(frame: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    """The model's frame restricted to games kicking off inside a Yahoo week.

    By date, not by ESPN week number: ESPN folds the Week 0 slate into week 1,
    Yahoo's week 1 starts the following Thursday, and a player's Week 0 game
    does not score in it.
    """
    lo, hi = _window(start, end)
    return frame[(frame["date"] >= lo) & (frame["date"] < hi)]


def team_games(games: pd.DataFrame) -> dict:
    """{espn team id: [game dict, ...]} for every side of every game in `games`."""
    out = {}
    for _, g in games.iterrows():
        for side, other in (("home", "away"), ("away", "home")):
            entry = {
                "game_id": str(g.get("game_id", "")),
                "date": g["date"],
                "home": side == "home",
                "opp": g[other],
                "opp_abbr": g.get(f"{other}_abbr", ""),
                "opp_id": str(g[f"{other}_id"]),
                "opp_rank": g.get(f"{other}_rank"),
                "pred_for": float(g[f"pred_{side}"]),
                "pred_against": float(g[f"pred_{other}"]),
                "state": g.get("state", "pre"),
                "detail": g.get("detail", ""),
                "score_for": g.get(f"{side}_score"),
                "score_against": g.get(f"{other}_score"),
                "tv": g.get("tv", ""),
            }
            out.setdefault(str(g[f"{side}_id"]), []).append(entry)
    return out


def _skill_points(row: pd.Series, game: dict) -> float:
    per_game = float(row["proj"]) / max(float(row.get("games") or 0), 1.0)
    avg = float(row.get("team_scored") or 0)
    if not avg:
        return per_game
    tilt = (game["pred_for"] / avg) ** GAME_WEIGHT
    return per_game * float(np.clip(tilt, 1 - GAME_CAP_DOWN, 1 + GAME_CAP_UP))


def week_projections(start: str, end: str, board: pd.DataFrame = None,
                     league: dict = None, frame: pd.DataFrame = None,
                     injuries: dict = None) -> pd.DataFrame:
    """Every board player's projection for the Yahoo week [start, end].

    Indexed by yahoo_id. Columns: proj_week (0 on a bye), n_games, and the
    game itself - opp, opp_abbr, home, kickoff (UTC), state, score_for,
    score_against, pred_for, pred_against - for the first game of the week
    (a school plays at most one in nearly every week).

    `injuries` is {yahoo_id: Yahoo status} from the week's rosters; a player
    ruled out projects nothing (STATUS_FACTOR). Without it the page priced a
    player Yahoo had already marked O at his full week.
    """
    injuries = injuries or {}
    league = yahoo.league() if league is None else league
    if frame is None:
        frame, _model, _names = predict.season()
    # Frozen at the draft and blended with the season (cfb.in_season), not
    # Yahoo's in-season order, which swung a projection week to week.
    board = in_season.board(frame=frame) if board is None else board
    board = board.drop_duplicates("yahoo_id").set_index("yahoo_id")

    by_team = team_games(games_between(frame, start, end))
    espn = schools_mod.espn_ids()
    mods = projections._def_modifiers(league)
    intercept, slope = projections.big_play_model(league)

    rows = {}
    for pid, row in board.iterrows():
        school = row.get("school")
        team_id = espn.get(school) if isinstance(school, str) else None
        games = by_team.get(str(team_id), []) if team_id else []
        total = 0.0
        for g in games:
            if row["pos"] == "DEF":
                allowed = np.array([g["pred_against"]])
                total += float(projections._points_allowed_value(allowed, mods)[0]
                               + intercept + slope * g["pred_against"])
            else:
                total += _skill_points(row, g)
        first = games[0] if games else {}
        total *= STATUS_FACTOR.get(injuries.get(str(pid), ""), 1.0)
        rows[pid] = {
            "proj_week": total if (games or team_id) else np.nan,
            "n_games": len(games),
            "game_id": first.get("game_id"),
            "opp": first.get("opp"), "opp_abbr": first.get("opp_abbr"),
            "opp_id": first.get("opp_id"),
            "opp_rank": first.get("opp_rank"),
            "home": first.get("home"), "kickoff": first.get("date"),
            "state": first.get("state"), "detail": first.get("detail"),
            "score_for": first.get("score_for"), "score_against": first.get("score_against"),
            "pred_for": first.get("pred_for"), "pred_against": first.get("pred_against"),
            "tv": first.get("tv"),
        }
    out = pd.DataFrame.from_dict(rows, orient="index")
    out.index.name = "yahoo_id"
    return out


if __name__ == "__main__":
    sb = yahoo.scoreboard()
    mu = sb["matchups"][0]
    board = in_season.board()
    wk = week_projections(mu["week_start"], mu["week_end"], board=board)
    show = board.drop_duplicates("yahoo_id").set_index("yahoo_id")[["player", "pos", "team"]]
    show = show.join(wk[["proj_week", "opp", "home", "state"]])
    print(f"Week {int(sb['week'])}: {mu['week_start']} to {mu['week_end']}")
    print(show.sort_values("proj_week", ascending=False).head(25).round(1).to_string())
