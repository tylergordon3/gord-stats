"""
The board every in-season CFB page prices players from.

Frozen at the draft (projections.value_board(frozen=True)) - after it, Yahoo's
rank order is season-to-date form rather than a pre-season ranking - with each
projection then pulled toward what the player has actually scored:

    per-game rate = (pre-season rate x PRIOR_GAMES + points) / (PRIOR_GAMES + games)

League power, the weekly projections and the waiver page all read this one
board, so they agree with each other. They used to read Yahoo's drifting order
directly, which swung a projection with every week (Arch Manning 33 -> 16) and,
on the league power page, counted the season twice.

Points come from ESPN's box scores, which see every player's every game.
Yahoo's weekly archive only sees the weeks a player spent on a league roster -
and a waiver candidate is by definition someone who has not been - so it is
the fallback, for the rows box scores cannot name (defences, mostly).

A player Yahoo ranks now who was not on the draft board at all - a freshman who
took the job in week 3 - joins at Yahoo's current price, which already holds
his form, and is not blended a second time. Without him the waiver page could
never suggest the pickup everyone else is making.
"""
import pandas as pd

from cfb import boxscores, players, projections, schools as schools_mod, yahoo
from cfb.config import SEASON

# How many games of the pre-season projection the prior is worth. Its true
# spread around the pre-season per-game projection is sd 3.8 and a week's noise
# much larger, so noise_var / prior_var ~ 4.7: after five games the season so
# far counts as much as the draft-day projection.
PRIOR_GAMES = 5.0


def yahoo_season(before_week: int = None) -> pd.DataFrame:
    """yahoo_id -> points and games played, from the weekly matchup archive.

    A week counts as a game only when Yahoo has any stat for the player -
    byes, injuries and games not yet kicked off come back empty, so an
    in-progress week counts just the games already played. Only weeks a player
    spent on a league roster are seen; free-agent weeks are not."""
    seen = {}
    for w in yahoo.archived_weeks():
        if before_week is not None and w >= before_week:
            continue                    # as it stood before that week (league_backfill)
        for roster in yahoo.week_matchups(w)["rosters"].values():
            for p in roster:
                if p.get("stats"):
                    seen[(w, str(p["yahoo_id"]))] = float(p["points"] or 0.0)
    if not seen:
        return pd.DataFrame(columns=["points", "played"])
    pts = pd.Series(seen)
    return pts.groupby(level=1).agg(points="sum", played="count")


def box_score_season(board: pd.DataFrame, league: dict = None,
                     season: int = SEASON, before_week: int = None) -> pd.DataFrame:
    """board index -> points and games played, from ESPN box scores, matched
    to the board's rows by name and school (the ownership page's matcher)."""
    from cfb.ownership import Index                     # late: it imports usage

    box = boxscores.load(season)
    if before_week is not None and "week" in box:
        box = box[box["week"] < before_week]
    if box.empty:
        return pd.DataFrame(columns=["points", "played"])
    league = yahoo.league() if league is None else league
    school_of = {str(v): k for k, v in schools_mod.espn_ids().items()}
    box = box.assign(points=players.fantasy_points(box, league),
                     school=box["team_id"].astype(str).map(school_of))
    per = (box.dropna(subset=["school"])
           .groupby(["player", "school"], as_index=False)
           .agg(points=("points", "sum"), played=("game_id", "nunique")))
    index = Index(per)
    rows = {}
    for i, name, school in zip(board.index, board["player"], board["school"]):
        hit = index.find(name, school) if isinstance(school, str) else None
        if hit is not None:
            rows[i] = (float(hit["points"]), float(hit["played"]))
    return pd.DataFrame.from_dict(rows, orient="index", columns=["points", "played"])


def blend(board: pd.DataFrame, league: dict = None, before_week: int = None) -> pd.DataFrame:
    """`board` (value_board rows, any index) with proj/floor/ceiling pulled
    toward the season so far, `vorp` recomputed and `played` added -
    or toward the weeks before `before_week`, for a past week's view."""
    board = board.copy()
    # Floats throughout: an empty source (week 1, or no box scores yet) comes
    # back as object columns, which pandas will not write into float ones.
    so_far = box_score_season(board, league, before_week=before_week).reindex(
        board.index).astype(float)
    ids = board["yahoo_id"].astype(str) if "yahoo_id" in board else pd.Series(
        board.index.astype(str), index=board.index)
    fallback = yahoo_season(before_week).reindex(ids.to_numpy()).astype(float)
    fallback.index = board.index
    missing = so_far["played"].isna()
    so_far.loc[missing] = fallback.loc[missing]
    played = so_far["played"].fillna(0.0)
    board["played"] = played
    if not played.any():
        return board
    prior = board["proj"] / board["games"]
    rate = (prior * PRIOR_GAMES + so_far["points"].fillna(0.0)) / (PRIOR_GAMES + played)
    scale = (rate / prior).where(prior > 0, 1.0).fillna(1.0)
    for col in ("proj", "floor", "ceiling"):
        board[col] = board[col] * scale
    board["vorp"] = board["proj"] - board["replacement"]
    return board


def board(frame: pd.DataFrame = None, refresh: bool = False,
          before_week: int = None) -> pd.DataFrame:
    """The in-season board: frozen and blended, plus the late arrivals at
    Yahoo's current price. Same columns as projections.value_board.
    `before_week` blends only the weeks before it (cfb.league_backfill)."""
    frozen = projections.value_board(refresh=refresh, frame=frame, frozen=True)
    current = projections.value_board(refresh=refresh, frame=frame)
    late = current[~current["yahoo_id"].isin(frozen["yahoo_id"])].assign(played=0.0)
    return pd.concat([blend(frozen, before_week=before_week), late], ignore_index=True)
