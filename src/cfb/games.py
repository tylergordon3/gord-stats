"""
Every FBS game since 2014, from ESPN's scoreboard — the training set.

`cfb.espn` fetches the current season's schedule for the site. This fetches the
past, once, and keeps it: one parquet per season under data/cfb/games/, which
together are what any prediction model is fitted and judged on. ESPN answers
for old seasons exactly as it does for this one, no key and no scraping, at one
request per week of one season.

Two facts about the data shape everything built on it:

  * `groups=80` returns games *involving* an FBS team, so roughly one game a
    week has an opponent from outside it. Those opponents are collapsed to a
    single pseudo-team, FCS — an individual FCS side plays too rarely to earn a
    rating, but dropping the games entirely would throw away the schedule
    softness that is genuinely part of a team's record.
  * Only the regular season is here (seasontype 2). Bowls and playoff games are
    a different sport for modelling purposes — month-long layoffs, opt-outs,
    and rosters that no longer resemble the ones that earned the rating.

    python -m cfb.games --backfill
    python -m cfb.games                 # summarise what is on disk
"""
import time

import pandas as pd

from cfb import espn
from cfb.config import DATA_DIR

GAMES_DIR = DATA_DIR / "games"
FIRST_SEASON = 2014
MAX_WEEK = 17                  # ESPN numbers conference title games week 15-16
FCS = "FCS"                    # every non-FBS opponent, pooled
_PAUSE = 0.3                   # ESPN is generous; do not lean on it


def season_path(season: int):
    return GAMES_DIR / f"{season}.parquet"


def fetch_season(season: int) -> pd.DataFrame:
    """One request per week of `season`, flattened to a row per game."""
    rows, skipped = [], []
    for week in range(1, MAX_WEEK + 1):
        data = espn._get({"groups": espn._FBS, "week": week, "dates": season,
                          "seasontype": 2, "limit": 500})
        events = data.get("events", [])
        for event in events:
            # Old seasons carry the occasional stub event with no competition
            # attached — a cancelled or relocated game. Skip rather than guess.
            try:
                row = espn._game_row(event, week)
            except (KeyError, IndexError, TypeError):
                skipped.append(event.get("id", "?"))
                continue
            row["season"] = season
            rows.append(row)
        time.sleep(_PAUSE)
    if skipped:
        print(f"    {season}: skipped {len(skipped)} malformed event(s)")
    if not rows:
        return pd.DataFrame()
    return (pd.DataFrame(rows)
            .sort_values(["week", "date_utc"])
            .reset_index(drop=True))


def backfill(first: int = FIRST_SEASON, last: int = None,
             refresh: bool = False) -> None:
    """Fetch and store every season in the range that is not already on disk."""
    last = last if last is not None else espn.SEASON - 1
    GAMES_DIR.mkdir(parents=True, exist_ok=True)
    for season in range(first, last + 1):
        path = season_path(season)
        if path.exists() and not refresh:
            print(f"  {season}: already on disk ({len(pd.read_parquet(path))} games)")
            continue
        frame = fetch_season(season)
        if frame.empty:
            print(f"  {season}: nothing returned")
            continue
        frame.to_parquet(path, index=False)
        played = frame["home_score"].notna().sum()
        print(f"  {season}: {len(frame)} games, {played} with a final score")


def load(first: int = FIRST_SEASON, last: int = None,
         played_only: bool = True) -> pd.DataFrame:
    """Every stored season stacked, with the model's own columns derived.

    Adds `margin` (home minus away) and `total`, the two things worth
    predicting, and pools non-FBS opponents into one identity.
    """
    last = last if last is not None else espn.SEASON
    frames = []
    for season in range(first, last + 1):
        path = season_path(season)
        if path.exists():
            frames.append(pd.read_parquet(path))
    if not frames:
        return pd.DataFrame()

    games = pd.concat(frames, ignore_index=True)
    if played_only:
        games = games.dropna(subset=["home_score", "away_score"])
        games = games[games["state"] == "post"]
        # ESPN marks a cancelled or postponed game "post" with a 0-0 score, and
        # the rescheduled meeting is filed separately, so the pair reads as a
        # real result plus a scoreless tie. College football has not had a tie
        # since overtime arrived in 1996 -- every 0-0 in this archive is a game
        # that was never played, and 119 of the 157 are the 2020 season, where
        # they were nearly a fifth of the schedule.
        games = games[(games["home_score"] > 0) | (games["away_score"] > 0)]

    games = games.copy()
    games["date"] = pd.to_datetime(games["date_utc"], format="ISO8601", utc=True)
    games["margin"] = games["home_score"] - games["away_score"]
    games["total"] = games["home_score"] + games["away_score"]

    fbs = _fbs_teams(games)
    for side in ("home", "away"):
        games[f"{side}_team"] = games[f"{side}_id"].where(
            games[f"{side}_id"].isin(fbs), FCS)
    return games.sort_values(["season", "date"]).reset_index(drop=True)


def team_names(games: pd.DataFrame = None) -> dict:
    """ESPN team id -> the most recent display name it played under.

    Ratings key on the id, which never moves; everything a human reads keys on
    this, which does. Most recent wins, so a team that rebranded shows up under
    the name it uses now rather than the one it used in 2014.
    """
    games = load() if games is None else games
    if games.empty:
        return {}
    sides = pd.concat([
        games[["date", "home_id", "home"]].rename(columns={"home_id": "id", "home": "name"}),
        games[["date", "away_id", "away"]].rename(columns={"away_id": "id", "away": "name"}),
    ]).sort_values("date")
    names = dict(zip(sides["id"], sides["name"]))     # later rows overwrite earlier
    names[FCS] = "FCS opponent"
    return names


def _fbs_teams(games: pd.DataFrame, min_games: int = 8) -> set:
    """Who is FBS: anyone appearing often enough in a season to be rated.

    ESPN does not label the tier on the scoreboard, and an FBS team plays a
    dozen of these games a year while a visiting FCS side plays one or two.
    Counting appearances separates them without a second data source.
    """
    keep = set()
    for _, season in games.groupby("season"):
        counts = pd.concat([season["home_id"], season["away_id"]]).value_counts()
        keep |= set(counts[counts >= min_games].index)
    return keep


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--backfill", action="store_true")
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--first", type=int, default=FIRST_SEASON)
    args = p.parse_args()
    if args.backfill:
        backfill(first=args.first, refresh=args.refresh)
    games = load(first=args.first)
    if games.empty:
        raise SystemExit("nothing on disk yet — run with --backfill")
    print(f"\n{len(games)} played games, {games['season'].nunique()} seasons")
    print(games.groupby("season").size().to_string())
