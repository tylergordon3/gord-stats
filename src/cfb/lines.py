"""
Historical betting lines from CollegeFootballData — the benchmark to beat.

`cfb.odds` archives this season's board from ESPN going forward, because ESPN
serves no odds for a game once it has been played. CFBD does keep them, which
is the whole reason for the key: it makes the market available for every season
the model is backtested on, instead of one that has to be waited out.

    https://api.collegefootballdata.com/lines?year=YYYY&week=N

A game carries a line from each of several books, and they disagree by half a
point or so. The consensus taken here is the median spread and median total
across whichever books covered the game, which is steadier than trusting one
book to have priced every game in a decade.

`spread` is relative to the home team in book convention: negative means the
home side is favoured, so it is the negative of the margin the market expects.
That sign is the only genuinely dangerous field in this module and it is
converted once, here, into `market_margin`, which points the same way as
everything else in the codebase.

CFBD keys games on ESPN's event id, so these join to data/cfb/games exactly.

    python -m cfb.lines --backfill
"""
import os
import time

import pandas as pd
import requests
from dotenv import load_dotenv

from cfb.config import DATA_DIR
from cfb.games import FIRST_SEASON
from gordstats import paths

LINES_DIR = DATA_DIR / "lines"
API = "https://api.collegefootballdata.com/lines"
_TIMEOUT = 40
_PAUSE = 0.4
MAX_WEEK = 17


def _key() -> str:
    load_dotenv(paths.ROOT / ".env")
    key = os.getenv("CFBD_KEY")
    if not key:
        raise RuntimeError("CFBD_KEY is not set; put it in .env")
    return key


def season_path(season: int):
    return LINES_DIR / f"{season}.parquet"


def fetch_season(season: int) -> pd.DataFrame:
    """Every game of a season with a consensus spread and total."""
    headers = {"Authorization": f"Bearer {_key()}"}
    rows = []
    for week in range(1, MAX_WEEK + 1):
        r = requests.get(API, headers=headers, timeout=_TIMEOUT,
                         params={"year": season, "week": week, "seasonType": "regular"})
        r.raise_for_status()
        for game in r.json():
            books = [b for b in (game.get("lines") or []) if b.get("spread") is not None]
            if not books:
                continue
            spreads = pd.Series([float(b["spread"]) for b in books])
            totals = pd.Series([float(b["overUnder"]) for b in books
                                if b.get("overUnder") is not None])
            rows.append({
                "game_id": str(game["id"]),
                "season": season,
                "week": week,
                "home": game.get("homeTeam"),
                "away": game.get("awayTeam"),
                "home_class": game.get("homeClassification"),
                "away_class": game.get("awayClassification"),
                # Book convention is the negative of a margin: flip it once, here.
                "market_margin": -float(spreads.median()),
                "market_total": float(totals.median()) if len(totals) else None,
                "books": len(books),
            })
        time.sleep(_PAUSE)
    return pd.DataFrame(rows)


def backfill(first: int = FIRST_SEASON, last: int = None, refresh: bool = False) -> None:
    last = last if last is not None else 2025
    LINES_DIR.mkdir(parents=True, exist_ok=True)
    for season in range(first, last + 1):
        path = season_path(season)
        if path.exists() and not refresh:
            print(f"  {season}: already on disk ({len(pd.read_parquet(path))} games)")
            continue
        frame = fetch_season(season)
        if frame.empty:
            print(f"  {season}: no lines returned")
            continue
        frame.to_parquet(path, index=False)
        print(f"  {season}: {len(frame)} games, median {frame['books'].median():.0f} books")


def load(first: int = FIRST_SEASON, last: int = 2025) -> pd.DataFrame:
    frames = [pd.read_parquet(season_path(s)) for s in range(first, last + 1)
              if season_path(s).exists()]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--backfill", action="store_true")
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--first", type=int, default=FIRST_SEASON)
    args = p.parse_args()
    if args.backfill:
        backfill(first=args.first, refresh=args.refresh)
    frame = load(first=args.first)
    print(f"\n{len(frame)} games with lines")
    if not frame.empty:
        print(frame.groupby("season").size().to_string())
