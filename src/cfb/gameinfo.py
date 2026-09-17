"""
What ESPN knows about a game beyond the schedule: its own win projection
(FPI), the DraftKings moneyline, the forecast, and how good a matchup it is.

All of it rides on the game summary endpoint, one request per game, free and
keyless:

    https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary?event=ID

`predictor` is ESPN's FPI win chance for each side; `pickcenter` the book's
spread, total and moneyline; `gameInfo.weather` an AccuWeather forecast
(temperature, condition code, gust, chance of rain) that appears about ten
days out. Matchup quality - ESPN's 0-100 "worth watching" number - lives on a
second, core-API endpoint and is fetched for games inside the forecast window
only.

The cache is data/cfb/gameinfo_{season}.json, one entry per game id, and an
entry is frozen once its game kicks off. That is not tidiness: after the game
ESPN's summary drops the predictor and prices the moneyline at -100000, so a
line refetched on Sunday would overwrite the one that was actually offered
with junk. The schedule page shows a finished game the numbers that were on
record before it started, which is the only version of them worth showing.

    python -m cfb.gameinfo              # refresh the window, print coverage
    python -m cfb.gameinfo --refresh
"""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

from cfb import espn
from cfb.config import DATA_DIR, SEASON

_SUMMARY = ("https://site.api.espn.com/apis/site/v2/sports/football/"
            "college-football/summary")
_PREDICTOR = ("https://sports.core.api.espn.com/v2/sports/football/leagues/"
              "college-football/events/{id}/competitions/{id}/predictor")
_TIMEOUT = 25
_WORKERS = 6

WINDOW_DAYS = 21          # lines and forecasts only exist this far out anyway
MAX_AGE_HOURS = 3         # inside the window, refetch this often
FAR_AGE_DAYS = 7          # beyond it, the FPI projection is all there is; weekly is plenty

# AccuWeather condition codes, which is what ESPN's `conditionId` carries.
CONDITIONS = {
    1: "Sunny", 2: "Mostly sunny", 3: "Partly sunny", 4: "Intermittent clouds",
    5: "Hazy sunshine", 6: "Mostly cloudy", 7: "Cloudy", 8: "Overcast",
    11: "Fog", 12: "Showers", 13: "Mostly cloudy, showers",
    14: "Partly sunny, showers", 15: "Thunderstorms",
    16: "Mostly cloudy, storms", 17: "Partly sunny, storms", 18: "Rain",
    19: "Flurries", 20: "Mostly cloudy, flurries", 21: "Partly sunny, flurries",
    22: "Snow", 23: "Mostly cloudy, snow", 24: "Ice", 25: "Sleet",
    26: "Freezing rain", 29: "Rain and snow", 30: "Hot", 31: "Cold", 32: "Windy",
    33: "Clear", 34: "Mostly clear", 35: "Partly cloudy", 36: "Intermittent clouds",
    37: "Hazy", 38: "Mostly cloudy", 39: "Partly cloudy, showers",
    40: "Mostly cloudy, showers", 41: "Partly cloudy, storms",
    42: "Mostly cloudy, storms", 43: "Mostly cloudy, flurries",
    44: "Mostly cloudy, snow",
}
_RAIN = {12, 13, 14, 18, 39, 40}
_STORM = {15, 16, 17, 41, 42}
_SNOW = {19, 20, 21, 22, 23, 24, 25, 26, 29, 43, 44}


def cache_path(season: int = SEASON):
    return DATA_DIR / f"gameinfo_{season}.json"


def load(season: int = SEASON) -> dict:
    """game id -> captured entry (see `_parse` for the keys)."""
    path = cache_path(season)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _get(url: str, params: dict = None) -> dict:
    r = requests.get(url, params=params, headers=espn._HEADERS, timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json()


def _num(value):
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def _parse(summary: dict, home_id: str, away_id: str) -> dict:
    """The parts of a summary worth keeping, as flat JSON-friendly values."""
    out = {"espn_home_wp": None, "book": None, "spread": None, "total": None,
           "ml_home": None, "ml_away": None, "weather": None,
           "last5_home": None, "last5_away": None}

    pred = summary.get("predictor") or {}
    for side, key in (("homeTeam", "home"), ("awayTeam", "away")):
        block = pred.get(side) or {}
        wp = _num(block.get("gameProjection"))
        if wp is not None and str(block.get("id", "")) in (home_id, away_id):
            # Keyed by which team it names, not which slot it sits in - both
            # sides carry an id, and only one of them is the home team.
            if str(block["id"]) == home_id:
                out["espn_home_wp"] = wp / 100
            elif out["espn_home_wp"] is None:
                out["espn_home_wp"] = 1 - wp / 100

    books = summary.get("pickcenter") or []
    book = next((b for b in books if b.get("spread") is not None), None)
    if book:
        home_odds = book.get("homeTeamOdds") or {}
        away_odds = book.get("awayTeamOdds") or {}
        spread = _num(book.get("spread"))
        favourite = home_odds.get("favorite")
        # Same cross-check cfb.odds makes: the sign has to agree with who the
        # payload says is favoured, or the line is not trusted at all.
        if (spread is not None and favourite is not None and spread != 0
                and (spread < 0) != bool(favourite)):
            spread = None
        out.update({
            "book": (book.get("provider") or {}).get("name") or None,
            "spread": spread,                       # home team, book convention
            "total": _num(book.get("overUnder")),
            "ml_home": _num(home_odds.get("moneyLine")),
            "ml_away": _num(away_odds.get("moneyLine")),
        })
        # A moneyline past +-10000 is ESPN's post-game placeholder, not a price.
        for key in ("ml_home", "ml_away"):
            if out[key] is not None and abs(out[key]) >= 10000:
                out[key] = None

    # Each side's last five results, as ESPN lists them (last season's games
    # early on). Which team a block belongs to is taken from the block's own
    # team id, or failing that the id common to every game in it.
    for block in summary.get("lastFiveGames") or []:
        events = block.get("events") or []
        tid = str((block.get("team") or {}).get("id") or "")
        if not tid and events:
            common = set.intersection(*[{str(e.get("homeTeamId")), str(e.get("awayTeamId"))}
                                        for e in events])
            tid = next(iter(common), "")
        side = "home" if tid == home_id else ("away" if tid == away_id else None)
        if side is None:
            continue
        games = []
        for e in events[:5]:
            opp = e.get("opponent") or {}
            games.append({"r": e.get("gameResult") or "", "s": e.get("score") or "",
                          "o": opp.get("abbreviation") or "", "v": e.get("atVs") or ""})
        out[f"last5_{side}"] = games or None

    wx = (summary.get("gameInfo") or {}).get("weather") or {}
    if wx.get("temperature") is not None or wx.get("conditionId") is not None:
        out["weather"] = {
            "temp": _num(wx.get("temperature")),
            "cond": int(wx["conditionId"]) if str(wx.get("conditionId", "")).isdigit() else None,
            "gust": _num(wx.get("gust")),
            "precip": _num(wx.get("precipitation")),      # chance of rain, percent
        }
    return out


def _matchup_quality(event_id: str):
    data = _get(_PREDICTOR.format(id=event_id))
    for side in ("homeTeam", "awayTeam"):
        for stat in (data.get(side) or {}).get("statistics", []):
            if stat.get("name") == "matchupQuality":
                return _num(stat.get("value"))
    return None


def _fetch(game: dict, want_quality: bool) -> dict | None:
    """One game's entry, or None when ESPN would not answer."""
    try:
        entry = _parse(_get(_SUMMARY, {"event": game["game_id"]}),
                       game["home_id"], game["away_id"])
    except (requests.RequestException, ValueError, KeyError):
        return None
    entry["mq"] = None
    if want_quality:
        try:
            entry["mq"] = _matchup_quality(game["game_id"])
        except (requests.RequestException, ValueError, KeyError):
            pass
    entry["kickoff"] = game["date_utc"]
    entry["captured"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return entry


def _stale(entry: dict | None, hours: float) -> bool:
    if not entry or not entry.get("captured"):
        return True
    try:
        taken = datetime.fromisoformat(entry["captured"])
    except ValueError:
        return True
    return (datetime.now(timezone.utc) - taken) > timedelta(hours=hours)


def _merge(old: dict | None, new: dict) -> dict:
    """The fresh entry, keeping any value the fresh fetch came back without.

    ESPN drops the predictor or the book from a payload now and then; a gap in
    one fetch should not blank a number that was there the last time.
    """
    if not old:
        return new
    out = dict(old)
    out.update({k: v for k, v in new.items() if v is not None})
    out["captured"] = new["captured"]
    return out


def capture(refresh: bool = False, season: int = SEASON) -> dict:
    """Bring the cache up to date for every game still to be played.

    Returns the whole cache. Games already kicked off are never touched.
    """
    schedule = espn.schedule()
    cache = load(season)
    if schedule.empty:
        return cache

    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=WINDOW_DAYS)
    kick = pd.to_datetime(schedule["date_utc"], utc=True, format="ISO8601")
    upcoming = schedule[(schedule["state"] == "pre") & (kick > now)].copy()
    upcoming["kick"] = kick[upcoming.index]

    todo = []
    for g in upcoming.itertuples():
        near = g.kick <= horizon
        old = cache.get(str(g.game_id))
        age = MAX_AGE_HOURS if near else FAR_AGE_DAYS * 24
        if refresh and near or _stale(old, age):
            todo.append(({"game_id": str(g.game_id), "home_id": str(g.home_id),
                          "away_id": str(g.away_id), "date_utc": str(g.date_utc)},
                         near))
    if not todo:
        return cache

    with ThreadPoolExecutor(_WORKERS) as pool:
        fetched = list(pool.map(lambda job: _fetch(*job), todo))

    for (game, _), entry in zip(todo, fetched):
        if entry is not None:
            cache[game["game_id"]] = _merge(cache.get(game["game_id"]), entry)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache_path(season).write_text(json.dumps(cache, indent=0), encoding="utf-8")
    return cache


def weather_text(wx: dict | None) -> str:
    """'Sunny' / 'Showers' etc. from a stored weather block."""
    if not wx or wx.get("cond") is None:
        return ""
    return CONDITIONS.get(int(wx["cond"]), "")


def weather_severity(wx: dict | None) -> float:
    """How much the weather is part of the game, 0 (nothing) to about 3.

    Snow and ice are the ceiling, storms and rain next, then wind and cold;
    the chance of rain and the gust speed nudge it, so a 40 mph forecast
    ranks above a 20 mph one. Meant for sorting and a "bad weather" cut at
    2, not for reading as a number.
    """
    if not wx:
        return 0.0
    # A dome has no weather, whatever the forecast for the car park says.
    if wx.get("indoors"):
        return 0.0
    cond = wx.get("cond")
    temp, gust, precip = wx.get("temp"), wx.get("gust"), wx.get("precip")
    score = 0.0
    if cond in _SNOW:
        score = 3.0
    elif cond in _STORM:
        score = 2.5
    elif cond in _RAIN:
        score = 2.0
    elif cond == 32:
        score = 2.0
    if precip is not None:
        score = max(score, 2.0 if precip >= 50 else (1.0 if precip >= 30 else 0.0))
        score += min(precip, 100) / 400            # 0.25 at most
    if gust is not None:
        score = max(score, 2.0 if gust >= 25 else (1.0 if gust >= 18 else 0.0))
        score += min(gust, 60) / 200               # 0.3 at most
    if temp is not None:
        if temp <= 32:
            score = max(score, 2.0) + (32 - temp) / 100
        elif temp <= 40:
            score = max(score, 1.0)
        elif temp >= 95:
            score = max(score, 1.0) + (temp - 95) / 100
    return round(score, 3)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--refresh", action="store_true")
    args = p.parse_args()
    started = time.time()
    cache = capture(refresh=args.refresh)
    with_wp = sum(1 for e in cache.values() if e.get("espn_home_wp") is not None)
    with_book = sum(1 for e in cache.values() if e.get("spread") is not None)
    with_wx = sum(1 for e in cache.values() if e.get("weather"))
    print(f"{len(cache)} games cached in {time.time() - started:.0f}s: "
          f"{with_wp} with an FPI projection, {with_book} with a book line, "
          f"{with_wx} with a forecast")
