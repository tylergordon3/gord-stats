"""
What each defence gives up, by position - and how hard a schedule is because
of it (data/cfb/def_vs_pos_{season}.json).

Points allowed to a position is mostly a statement about who a defence has
played: hold three FCS offences and Group of Five visitors and you look
excellent. So every game is priced against what the offence facing you would
be expected to produce - our own model already has that number (cfb.predict
gives a predicted score for every game) - and a defence's rating is the ratio
of what it actually allowed to what the schedule said it should.

    1.00  exactly what the opposing offences should have scored at that spot
    1.25  a quarter more than that - a defence fantasy teams want to face
    0.80  a fifth less - the ones to avoid

Scoring is this league's own (cfb.players.modifiers off the Yahoo settings),
so the numbers are in the points the league actually plays for.

    python -m cfb.defense
"""
import json

import numpy as np
import pandas as pd

from cfb import boxscores, players, predict
from cfb.config import DATA_DIR, SEASON

POSITIONS = ("QB", "RB", "WR", "TE")
# Games behind a rating before it is worth printing on its own. Under this the
# rating is shrunk toward 1.00 rather than hidden: two games is a real signal,
# it is just a weak one.
FULL_WEIGHT_GAMES = 5


def _positions(frame: pd.DataFrame) -> pd.DataFrame:
    """Box-score rows reduced to the four positions the league starts."""
    out = frame.copy()
    out["pos"] = out["pos"].str.upper().replace({"FB": "RB", "HB": "RB", "TB": "RB",
                                                 "WR/RB": "WR", "ATH": "WR"})
    return out[out["pos"].isin(POSITIONS)]


def allowed(season: int = SEASON, league: dict = None) -> pd.DataFrame:
    """One row per (defence, position, game): the fantasy points that position
    scored against it, and what the model expected that offence to score."""
    box = boxscores.load(season)
    if box.empty:
        return pd.DataFrame()
    if league is None:
        from cfb import yahoo
        league = yahoo.league()
    # Every (game, offence) the box scores cover, before the position filter:
    # a position that did nothing has no rows, and a defence that held tight
    # ends to zero used to lose that game from its average and its game count
    # alike - 132 of 228 defences had one, and stingy read as generous.
    sides = (box[["game_id", "opp_id", "team_id"]].drop_duplicates()
             .rename(columns={"opp_id": "defense", "team_id": "offense"}))
    box = _positions(box)
    box["points"] = players.fantasy_points(box, league)

    scored = (box.groupby(["game_id", "opp_id", "team_id", "pos"], as_index=False)
              ["points"].sum()
              .rename(columns={"opp_id": "defense", "team_id": "offense"}))
    grid = sides.merge(pd.DataFrame({"pos": POSITIONS}), how="cross")
    per_game = grid.merge(scored, on=["game_id", "defense", "offense", "pos"], how="left")
    per_game["points"] = per_game["points"].fillna(0.0)

    # What the model said that offence would score in that game. The ratio of
    # actual fantasy points to it is the schedule adjustment: a defence that
    # held an offence expected to score 40 to nothing did something; one that
    # held an offence expected to score 10 did not.
    frame, _model, _names = predict.season()
    expected = {}
    for _, g in frame.iterrows():
        expected[(str(g["game_id"]), str(g["home_id"]))] = float(g["pred_home"])
        expected[(str(g["game_id"]), str(g["away_id"]))] = float(g["pred_away"])
    per_game["expected_pts"] = [
        expected.get((str(r["game_id"]), str(r["offense"]))) for _, r in per_game.iterrows()]
    per_game = per_game.dropna(subset=["expected_pts"])
    # A predicted score of zero is a game the model could not price (an FCS
    # side it has never rated). Dividing by it made every share infinite, which
    # ran through the league averages and came out as a table where every
    # defence had the same rating.
    return per_game[per_game["expected_pts"] > 1.0]


def ratings(season: int = SEASON, league: dict = None) -> pd.DataFrame:
    """One row per (defence, position): games, points allowed per game, and the
    schedule-adjusted rating - 1.00 is what the schedule said, above 1 is
    generous, below 1 is stingy."""
    per_game = allowed(season, league)
    if per_game.empty:
        return per_game

    # A position's points scale with how much scoring the game had in it, so
    # the league-average share of a team's points that goes to each position is
    # the yardstick; a defence is then judged against its own opponents' shares.
    per_game["share"] = per_game["points"] / per_game["expected_pts"]
    league_share = per_game.groupby("pos")["share"].mean()

    rows = []
    for (defense, pos), group in per_game.groupby(["defense", "pos"]):
        games = len(group)
        got = group["points"].mean()
        par = league_share[pos] * group["expected_pts"].mean()
        raw = got / par if par else np.nan
        # Shrink toward par on a short sample: three weeks in, one shootout
        # should not brand a defence for the season.
        weight = min(games / FULL_WEIGHT_GAMES, 1.0)
        rows.append({"defense": str(defense), "pos": pos, "games": games,
                     "allowed": round(got, 2), "par": round(par, 2),
                     "rating": round(1 + (raw - 1) * weight, 3) if par else None})
    out = pd.DataFrame(rows).dropna(subset=["rating"])
    # FBS defences only. A fantasy roster never faces an FCS defence except in
    # the cupcake weeks, and those rows are priced off one game against an
    # offence the model rates in a single pooled bucket.
    from cfb import espn
    out = out[out["defense"].isin(set(espn.conferences()))]
    return out.sort_values(["pos", "rating"], ascending=[True, False]).reset_index(drop=True)


def table(season: int = SEASON, league: dict = None) -> pd.DataFrame:
    """Ratings as a defence-by-position grid, plus each defence's average."""
    frame = ratings(season, league)
    if frame.empty:
        return frame
    grid = frame.pivot(index="defense", columns="pos", values="rating")
    grid["all"] = grid.mean(axis=1)
    return grid.sort_values("all", ascending=False)


def save(season: int = SEASON) -> dict:
    """Write the grid where the pages can read it without a refit."""
    grid = table(season)
    out = DATA_DIR / f"def_vs_pos_{season}.json"
    payload = {"season": season,
               "defense": {str(k): {p: (None if pd.isna(v) else round(float(v), 3))
                                    for p, v in row.items()}
                           for k, row in grid.iterrows()}} if len(grid) else {"season": season,
                                                                              "defense": {}}
    out.write_text(json.dumps(payload), encoding="utf-8")
    return payload


if __name__ == "__main__":
    grid = table()
    if grid.empty:
        print("no box scores archived yet - run python -m cfb.boxscores")
    else:
        from cfb import espn
        names = {}
        sched = espn.schedule()
        for _, g in sched.iterrows():
            names[str(g["home_id"])] = g["home"]
            names[str(g["away_id"])] = g["away"]
        show = grid.copy()
        show.index = [names.get(i, i) for i in show.index]
        print("most generous:"); print(show.head(8).round(2).to_string())
        print("stingiest:"); print(show.tail(8).round(2).to_string())
