"""
The market's opinion, archived weekly — the benchmark the model is judged by.

ESPN's scoreboard carries a DraftKings spread and total for nearly every
upcoming game, free and keyless, on the request `cfb.espn` already makes. Its
*historical* odds are not available — `pickcenter` comes back empty for games
already played — so a line that is not captured before kickoff is gone. This
archives them, one file per season, appending each time it runs.

Read `odds[0]["spread"]`, never `details`. The details string names the
favourite by an abbreviation that is not always ESPN's own: Buffalo appears as
"BUF -24.5" while the same payload calls the team "BUFF", and matching on it
silently flips the sign, turning a 24-point favourite into a 24-point dog. The
`spread` field is already relative to the home team. The sign is cross-checked
against `homeTeamOdds.favorite` and contradictory rows are dropped rather than
guessed at.

    python -m cfb.odds
"""
from datetime import datetime, timezone

import pandas as pd

from cfb import espn
from cfb.config import DATA_DIR, SEASON

ODDS_DIR = DATA_DIR / "odds"


def _rows(week: int, season: int) -> list:
    data = espn._get({"groups": espn._FBS, "week": week, "dates": season,
                      "seasontype": 2, "limit": 500})
    captured = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out = []
    for event in data.get("events", []):
        comp = event["competitions"][0]
        book = (comp.get("odds") or [None])[0]
        if not book or book.get("spread") is None:
            continue
        spread = float(book["spread"])
        favourite = (book.get("homeTeamOdds") or {}).get("favorite")
        if favourite is not None and spread != 0 and (spread < 0) != bool(favourite):
            continue                    # the payload contradicts itself; do not guess
        sides = {c["homeAway"]: c for c in comp["competitors"]}
        out.append({
            "season": season, "week": week, "captured": captured,
            "date_utc": event["date"], "state": comp.get("status", {}).get("type", {}).get("state"),
            "home_id": str(sides["home"]["team"]["id"]),
            "away_id": str(sides["away"]["team"]["id"]),
            "home": sides["home"]["team"].get("shortDisplayName"),
            "away": sides["away"]["team"].get("shortDisplayName"),
            "book": (book.get("provider") or {}).get("name", ""),
            "spread": spread,                       # home team, book convention
            "total": book.get("overUnder"),
        })
    return out


def capture(weeks=None, season: int = SEASON) -> pd.DataFrame:
    """Append the current board to this season's archive and return what was added."""
    weeks = weeks or [w["week"] for w in espn.weeks()]
    rows = []
    for week in weeks:
        rows.extend(_rows(week, season))
    fresh = pd.DataFrame(rows)
    if fresh.empty:
        return fresh

    ODDS_DIR.mkdir(parents=True, exist_ok=True)
    path = ODDS_DIR / f"{season}.parquet"
    if path.exists():
        fresh = pd.concat([pd.read_parquet(path), fresh], ignore_index=True)
    # One line per game per capture run; re-running the same day is not new data.
    fresh["day"] = fresh["captured"].str[:10]
    fresh = fresh.drop_duplicates(subset=["season", "home_id", "away_id", "day"], keep="last")
    fresh.drop(columns="day").to_parquet(path, index=False)
    return fresh


def latest(season: int = SEASON) -> pd.DataFrame:
    """The most recent captured line per game: game key, spread, total."""
    path = ODDS_DIR / f"{season}.parquet"
    if not path.exists():
        return pd.DataFrame(columns=["home_id", "away_id", "spread", "total", "book"])
    frame = pd.read_parquet(path).sort_values("captured")
    return frame.drop_duplicates(subset=["home_id", "away_id"], keep="last")


if __name__ == "__main__":
    frame = capture()
    print(f"{len(frame)} lines archived for {SEASON}")
    if not frame.empty:
        print(frame.groupby("week").size().to_string())
