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
    data = espn._get({"groups": espn._FBS, "dates": season, "limit": 500,
                      **espn.query(week)})
    captured = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out = []
    for event in data.get("events", []):
        if not event.get("competitions"):      # ESPN's empty stub events
            continue
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
            # Where the book opened, and the moneyline: the movement between
            # open and now is half of what a bettor looks at.
            "spread_open": _line(book, "pointSpread", "home", "open"),
            "total_open": _line(book, "total", "over", "open"),
            "ml_home": _line(book, "moneyline", "home", "close", "odds"),
            "ml_away": _line(book, "moneyline", "away", "close", "odds"),
            "ml_home_open": _line(book, "moneyline", "home", "open", "odds"),
            "ml_away_open": _line(book, "moneyline", "away", "open", "odds"),
        })
    return out


def _line(book: dict, market: str, side: str, when: str, field: str = "line"):
    """One number out of ESPN's nested open/close blocks, or None.

    Lines arrive as strings like "+7", "-7", "o53.5", "u53.5" or "+205";
    the letter prefix on a total is stripped. A post-game placeholder past
    +-10000 on a moneyline is not a price and is dropped.
    """
    raw = (((book.get(market) or {}).get(side) or {}).get(when) or {}).get(field)
    if raw in (None, ""):
        return None
    try:
        value = float(str(raw).lstrip("ou").replace("EVEN", "100"))
    except ValueError:
        return None
    if field == "odds" and abs(value) >= 10000:
        return None
    return value


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
    fresh = fresh.drop_duplicates(subset=["season", "week", "home_id", "away_id", "day"],
                                  keep="last")
    fresh.drop(columns="day").to_parquet(path, index=False)
    return fresh


# A game is (week, home, away), never (home, away) alone: every season has a
# conference title game or two that repeats a regular-season pairing (2025:
# Texas Tech-BYU, Boise-UNLV), and keyed on the pair the December line wrote
# over September's - its cover ticks and both teams' ATS records with it.
KEY = ["week", "home_id", "away_id"]

_LATEST_COLS = ["week", "home_id", "away_id", "spread", "total", "book", "spread_open",
                "total_open", "ml_home", "ml_away", "ml_home_open", "ml_away_open"]


def latest(season: int = SEASON) -> pd.DataFrame:
    """The most recent captured line per game: game key, spread, total, and
    the open/moneyline columns (NaN on rows captured before those existed)."""
    path = ODDS_DIR / f"{season}.parquet"
    if not path.exists():
        return pd.DataFrame(columns=_LATEST_COLS)
    frame = pd.read_parquet(path).sort_values("captured")
    for col in _LATEST_COLS:
        if col not in frame.columns:
            frame[col] = pd.NA
    frame["week"] = frame["week"].astype(int)
    return frame.drop_duplicates(subset=KEY, keep="last")


def history(season: int = SEASON) -> pd.DataFrame:
    """Every capture of every game, oldest first - for a line-movement strip."""
    path = ODDS_DIR / f"{season}.parquet"
    if not path.exists():
        return pd.DataFrame(columns=["week", "home_id", "away_id", "captured", "spread", "total"])
    return pd.read_parquet(path).sort_values("captured")


if __name__ == "__main__":
    frame = capture()
    print(f"{len(frame)} lines archived for {SEASON}")
    if not frame.empty:
        print(frame.groupby("week").size().to_string())
