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

from cfb import predict, projections, schools as schools_mod, yahoo
from cfb.config import LEAGUE_TZ

# The exponent on (this game's predicted score / the offence's season average)
# and the band the result is held inside. At 0.6 a game the model prices 25%
# above the offence's norm lifts its players about 14%; the cap keeps a
# mismatch against an FCS opponent from doubling anyone.
GAME_WEIGHT = 0.6
GAME_CAP = 0.30


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
    return per_game * float(np.clip(tilt, 1 - GAME_CAP, 1 + GAME_CAP))


def week_projections(start: str, end: str, board: pd.DataFrame = None,
                     league: dict = None, frame: pd.DataFrame = None) -> pd.DataFrame:
    """Every board player's projection for the Yahoo week [start, end].

    Indexed by yahoo_id. Columns: proj_week (0 on a bye), n_games, and the
    game itself - opp, opp_abbr, home, kickoff (UTC), state, score_for,
    score_against, pred_for, pred_against - for the first game of the week
    (a school plays at most one in nearly every week).
    """
    league = yahoo.league() if league is None else league
    if frame is None:
        frame, _model, _names = predict.season()
    board = projections.value_board(frame=frame) if board is None else board
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
        rows[pid] = {
            "proj_week": total if (games or team_id) else np.nan,
            "n_games": len(games),
            "opp": first.get("opp"), "opp_abbr": first.get("opp_abbr"),
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
    board = projections.value_board()
    wk = week_projections(mu["week_start"], mu["week_end"], board=board)
    show = board.drop_duplicates("yahoo_id").set_index("yahoo_id")[["player", "pos", "team"]]
    show = show.join(wk[["proj_week", "opp", "home", "state"]])
    print(f"Week {int(sb['week'])}: {mu['week_start']} to {mu['week_end']}")
    print(show.sort_values("proj_week", ascending=False).head(25).round(1).to_string())
