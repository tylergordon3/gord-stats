"""
Cached weekly fantasy points, in this league's scoring, one parquet per season.

`fantasy.stats.player_points` computes these from nflverse every time it is
called, which costs a full stats + team-stats + schedule pull per season. The
projection model behind the power rankings trains on five seasons at once, so
it reads them from here instead: past seasons never change, and the current one
re-fetches on demand.

    python -m fantasy.league.weekly_points            # fill any missing seasons
    python -m fantasy.league.weekly_points --refresh  # re-pull them all

Only the columns the model uses are stored. nflverse's weekly table is 150
columns wide and the model reads twenty of them; keeping the rest would be
30MB of parquet nothing opens.
"""
import argparse

import pandas as pd

from fantasy import paths, stats

# Identity, then the volume columns the projection model regresses on. Points
# come in both flavours because the league is PPR for skill players but the
# kicker and DST columns carry the custom scoring, which `stats` writes into
# both.
COLUMNS = [
    "season", "week", "sleeper_id", "gsis_id", "cleaned_name",
    "player_display_name", "position", "team",
    "fantasy_points", "fantasy_points_ppr",
    "targets", "receptions", "receiving_yards", "receiving_air_yards",
    "receiving_tds", "target_share", "air_yards_share", "wopr",
    "carries", "rushing_yards", "rushing_tds",
    "attempts", "passing_yards", "passing_tds",
]

# Weeks 18+ are rested-starter football and the league's season ends at 14
# anyway, so they are dropped rather than allowed to drag every projection down.
MAX_WEEK = 17


def path(season: int):
    return paths.POINTS_DIR / f"{season}.parquet"


def build(season: int, refresh: bool = False) -> pd.DataFrame:
    """Fetch and store one season's weekly points (cached unless `refresh`)."""
    out = path(season)
    if out.exists() and not refresh:
        return pd.read_parquet(out)

    df = stats.player_points(season)
    df["season"] = season
    df = df[df["week"] <= MAX_WEEK]
    df = df[[c for c in COLUMNS if c in df.columns]]

    paths.POINTS_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    print(f"[points] {season} -> {out} ({len(df)} rows)")
    return df


def load(seasons, refresh: bool = False) -> pd.DataFrame:
    """Weekly points for several seasons, stacked (fetching any not cached)."""
    return pd.concat([build(int(s), refresh=refresh) for s in seasons],
                     ignore_index=True)


def available() -> list:
    """Seasons already stored, ascending."""
    if not paths.POINTS_DIR.exists():
        return []
    return sorted(int(p.stem) for p in paths.POINTS_DIR.glob("*.parquet"))


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("--seasons", nargs="+", type=int,
                   help="Seasons to store. Default: the model's training window.")
    p.add_argument("--refresh", action="store_true", help="Re-pull cached seasons.")
    args = p.parse_args()

    from fantasy.projections import TRAIN_SEASONS
    load(args.seasons or TRAIN_SEASONS, refresh=args.refresh)


if __name__ == "__main__":
    main()
