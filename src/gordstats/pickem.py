"""
Reader pick'em: the weekly contest's slate, its results and the GordStats entry.

One combined contest a week: about ten featured college games and every NFL
game. A reader picks winners and ranks them by confidence - 1 to N, N the
number of games, each value once - and a correct pick earns its value. This
module is the pipeline half: it decides which games are in a week, keeps that
list frozen, records the finals and makes the model's own picks. Readers'
picks live in D1 and are graded in the browser's request by
functions/api/pickem.js, from the files written here. The page is
gordstats.pickem_page; the explainer is how.py's "pickem".

The week
    Tuesday 00:00 to the next Tuesday 00:00, Eastern - in practice the
    Thursday-to-Monday football week, but started on Tuesday so that no game
    falls between two weeks: the 2026 NFL season opens on a Wednesday, and
    Christmas games land midweek. Week 1 is the window holding the NFL's
    first regular-season game, so contest week N is NFL week N through the
    regular season (19 on are the playoffs, "NFL Wild Card" and on). The
    season ends with the Super Bowl's window; college weeks before the NFL
    opener are not in it. A window with no game in it (the week before the
    Super Bowl) has no slate and is skipped.

The slate (data/pickem/<season>/week_NN.json, committed: the record)
    Built at the first run inside the week, then only ever appended to: a game
    is added only before it locks, and never removed or reordered. Every NFL
    game in the window whose teams are known; the college games are the
    window's best ten by the watch guide's score (gordstats.watch_page, read
    from the guide's games.json this same run wrote), topped up later if the
    first look found fewer. N grows when a game is added; values already used
    stay valid.

Locking
    A game locks at its kickoff, and the Function enforces it from `lock` in
    the published file. Once a lock time has passed it never moves - a game
    postponed after kickoff does not reopen. Before then it follows a moved
    kickoff (flexed games), except that a game called off never gets a later
    lock, and one ESPN shows as started locks at once. A game with no kickoff
    time yet (ESPN files those at midnight Eastern) locks at that midnight:
    early, never late.

Grading (`res`): 'h' / 'a' for the winner, 'v' for a game that scores nothing
    - a tie, cancelled or postponed (cfb.predict.cancelled,
    nfl.games.called_off), moved out of the week, or still unplayed three days
    after the week ends - and null until then.

The GordStats entry
    Picks the model's favorite in every game, ranked by its win chance, under
    the readers' rules: each run re-ranks the still-open games with the values
    the locked ones left free, and a locked game's pick is never touched
    again. The chance is the last one archived before kickoff
    (cfb.results.on_record / nfl.results.on_record, the honest record the
    predictions pages grade), falling back to the watch guide's.

Published for the page and the Function (docs/, generated, not committed):
    docs/pickem/season.json            every week's games, compact, for grading
    docs/pickem/<season>/week_NN.json  one week's slate, for showing

    python -m gordstats.pickem
"""
from __future__ import annotations

import importlib
import json
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from gordstats import logos, paths, stable

ET = ZoneInfo("America/New_York")
DATA = paths.DATA / "pickem"
OUT = paths.DOCS / "pickem"
FEATURED = 10                   # college games a week
WEEK = timedelta(days=7)
# A game still without a result this long after its week ends was not played.
GRACE = timedelta(days=3)
SIDES = ("h", "a")


# --------------------------------------------------------------------------- #
# Weeks
# --------------------------------------------------------------------------- #

def first_window(opener: datetime) -> datetime:
    """Week 1's start: Tuesday 00:00 Eastern on or before the NFL opener."""
    day = pd.Timestamp(opener).tz_convert(ET).date()
    tuesday = day - timedelta(days=(day.weekday() - 1) % 7)
    return datetime(tuesday.year, tuesday.month, tuesday.day, tzinfo=ET)


def window(first: datetime, week: int) -> tuple[datetime, datetime]:
    """Week `week`'s [start, end). Wall-clock arithmetic in Eastern, so the
    window still starts at midnight after the clocks go back."""
    start = first + WEEK * (week - 1)
    start = datetime(start.year, start.month, start.day, tzinfo=ET)
    end = start + WEEK
    return start, datetime(end.year, end.month, end.day, tzinfo=ET)


def week_of(first: datetime, when) -> int:
    """The contest week a moment falls in (0 or less before week 1)."""
    t = pd.Timestamp(when).tz_convert(ET)
    local = datetime(t.year, t.month, t.day, tzinfo=ET)
    return (local.date() - first.date()).days // 7 + 1


def season_bounds(nfl: pd.DataFrame) -> tuple[datetime, int] | None:
    """(week 1's start, the last week) from the NFL's season: its first
    regular-season game and the last game on file (the Super Bowl)."""
    if nfl is None or nfl.empty:
        return None
    when = pd.to_datetime(nfl["date_utc"], utc=True, format="ISO8601")
    regular = when[nfl["seasontype"].astype(int) == 2]
    if regular.empty:
        return None
    first = first_window(regular.min())
    return first, week_of(first, when.max())


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def _iso(ts) -> str:
    return pd.Timestamp(ts).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def _ts(text) -> pd.Timestamp:
    t = pd.Timestamp(text)
    return t.tz_convert("UTC") if t.tzinfo else t.tz_localize("UTC")


def _num(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        return None
    f = float(v)
    return int(f) if f.is_integer() else round(f, 1)


def _text(v) -> str:
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)


def _rows(frame: pd.DataFrame | None) -> dict:
    """{game id: row dict} for a schedule frame."""
    if frame is None or frame.empty:
        return {}
    return {str(r["game_id"]): r for r in frame.to_dict("records")}


def _unknown_team(r: dict, sport: str) -> bool:
    """A game whose sides are not set yet (a playoff slot), or the Pro Bowl."""
    for side in ("home", "away"):
        ident = _text(r.get(f"{side}_id"))
        abbr = _text(r.get(f"{side}_abbr")).upper()
        name = _text(r.get(side)).upper()
        if not ident or ident.startswith("-") or "TBD" in (abbr, name):
            return True
        if sport == "nfl" and abbr in ("AFC", "NFC"):
            return True
    return False


def _time_known(r: dict, sport: str) -> bool:
    if sport == "nfl":
        return _text(r.get("detail")).strip().upper() != "TBD"
    tv = r.get("time_valid", True)
    return True if tv is None or (isinstance(tv, float) and pd.isna(tv)) else bool(tv)


def _team(r: dict, side: str, sport: str, watch_side: dict | None = None) -> dict:
    abbr = _text(r.get(f"{side}_abbr"))
    ident = _text(r.get(f"{side}_id"))
    out = {"id": ident, "nm": _text(r.get(side)), "ab": abbr}
    if sport == "cfb":
        out["lg"] = (watch_side or {}).get("lg") or logos.url("ncaa", ident, 80)
        rank = (watch_side or {}).get("rk", r.get(f"{side}_rank"))
        out["rk"] = _num(rank)
    else:
        out["lg"] = logos.url("nfl", abbr.lower(), 80)
        out["rec"] = _text(r.get(f"{side}_record"))
    return out


def _played_nfl(r: dict) -> bool:
    hs, as_ = _num(r.get("home_score")), _num(r.get("away_score"))
    return (bool(r.get("completed")) and r.get("state") == "post" and hs is not None
            and as_ is not None and (hs > 0 or as_ > 0))


def _called_off(r: dict, sport: str) -> bool:
    """Closed by ESPN without a result: cfb.predict.cancelled and
    nfl.games.called_off, for one row."""
    if r.get("state") != "post":
        return False
    if sport == "nfl":
        return not _played_nfl(r)
    hs, as_ = _num(r.get("home_score")) or 0, _num(r.get("away_score")) or 0
    detail = _text(r.get("detail"))
    return hs + as_ <= 0 or "Cancel" in detail or "Postpon" in detail


def _status(r: dict, sport: str, kick: pd.Timestamp, end: datetime) -> dict:
    """state, detail, score and result for one game from its schedule row."""
    state = _text(r.get("state")) or "pre"
    hs, as_ = _num(r.get("home_score")), _num(r.get("away_score"))
    out = {"st": state, "det": _text(r.get("detail")),
           "score": ({"h": hs, "a": as_} if state != "pre" and hs is not None
                     and as_ is not None else None),
           "res": None}
    if kick >= pd.Timestamp(end):
        out["res"] = "v"                    # moved out of the week
    elif _called_off(r, sport):
        out["res"] = "v"
    elif state == "post" and out["score"]:
        out["res"] = "v" if hs == as_ else ("h" if hs > as_ else "a")
    return out


# --------------------------------------------------------------------------- #
# One week
# --------------------------------------------------------------------------- #

def _labels(games: list, cfb: dict, nfl: dict) -> str:
    """"NFL Week 5 · CFB Week 6", from the games in the slate."""
    from cfb import espn
    from nfl import games as nfl_games

    parts = []
    nfl_weeks = [nfl[g["id"][4:]] for g in games if g["sp"] == "nfl" and g["id"][4:] in nfl]
    if nfl_weeks:
        r = nfl_weeks[0]
        if int(r.get("seasontype") or 2) == 3:
            parts.append("NFL " + nfl_games.ROUND_NAMES.get(nfl_games.round_of(r), "Playoffs"))
        else:
            parts.append(f"NFL Week {int(r['week'])}")
    cfb_weeks = sorted({int(cfb[g["id"][4:]]["week"]) for g in games
                        if g["sp"] == "cfb" and g["id"][4:] in cfb})
    if cfb_weeks:
        parts.append("CFB " + espn.week_label(cfb_weeks[0]))
    return " · ".join(parts)


def _new_game(sport: str, gid: str, r: dict, now: datetime, end: datetime,
              watch: dict | None = None) -> dict:
    kick = _ts(r["date_utc"])
    g = {"id": f"{sport}:{gid}", "sp": sport, "ko": _iso(kick),
         "tk": _time_known(r, sport), "lock": _iso(kick),
         "tv": _text(r.get("tv")), "note": _text(r.get("note")),
         "n": bool(r.get("neutral")),
         "h": _team(r, "home", sport, (watch or {}).get("h")),
         "a": _team(r, "away", sport, (watch or {}).get("a")),
         "added": _iso(now)}
    if watch is not None and watch.get("score") is not None:
        g["watch"] = float(watch["score"])
    g.update(_status(r, sport, kick, end))
    g["gs"] = None
    return g


def _refresh(g: dict, r: dict | None, now: datetime, end: datetime) -> None:
    """Bring one slate game up to date: kickoff, lock, state and result."""
    sport = g["sp"]
    lock = _ts(g["lock"])
    open_ = lock > pd.Timestamp(now)
    if r is None:
        # ESPN no longer lists it. Kept as it was; after the grace period a
        # game nobody can show was played scores nothing.
        if g.get("res") is None and pd.Timestamp(now) > pd.Timestamp(end) + GRACE:
            g["res"] = "v"
        return
    kick = _ts(r["date_utc"])
    g["ko"], g["tk"] = _iso(kick), _time_known(r, sport)
    g["tv"] = _text(r.get("tv")) or g.get("tv", "")
    if open_:
        # Team lines (rank, record) follow the week until the game locks;
        # the logo stays the one the slate was built with.
        for side, name in (("h", "home"), ("a", "away")):
            fresh = _team(r, name, sport)
            g[side] = {**fresh, "lg": g[side].get("lg") or fresh["lg"]}
    g.update(_status(r, sport, kick, end))
    if g["res"] is None and pd.Timestamp(now) > pd.Timestamp(end) + GRACE:
        g["res"] = "v"
    if open_:
        started = g["st"] == "in" or (g["st"] == "post" and g["res"] in SIDES)
        if started:
            lock = min(lock, pd.Timestamp(now).tz_convert("UTC"))
        elif g["res"] == "v":
            lock = min(lock, kick)          # called off: never a later lock
        else:
            lock = kick
        g["lock"] = _iso(lock)


def _model_picks(games: list, now: datetime, probs: dict) -> None:
    """The GordStats entry, under the readers' rules (see the module doc)."""
    n = len(games)
    t = pd.Timestamp(now)
    locked = [g for g in games if _ts(g["lock"]) <= t]
    open_ = [g for g in games if _ts(g["lock"]) > t]
    used = {g["gs"]["c"] for g in locked if g.get("gs")}
    chances = []
    for g in open_:
        p = probs.get(g["id"])
        if p is None and g.get("gs"):
            p = g["gs"].get("p")            # the last pre-kickoff number we had
        if p is None or pd.isna(p):
            g["gs"] = None
            continue
        p = round(float(p), 3)
        chances.append((max(p, 1 - p), g, p))
    chances.sort(key=lambda c: (-c[0], c[1]["ko"], c[1]["id"]))
    free = sorted(set(range(1, n + 1)) - used, reverse=True)
    for (_conf, g, p), value in zip(chances, free):
        g["gs"] = {"s": "h" if p >= 0.5 else "a", "c": value, "p": p}


def update_week(slate: dict | None, *, season: int, week: int, start: datetime,
                end: datetime, now: datetime, cfb: dict, nfl: dict, watch: list,
                probs: dict) -> dict | None:
    """The week's slate as of `now`: the stored one brought up to date and
    added to, or a new one. None for a week with no game in it."""
    t = pd.Timestamp(now)
    lo, hi = pd.Timestamp(start), pd.Timestamp(end)
    games = [dict(g) for g in (slate or {}).get("games", [])]
    have = {g["id"] for g in games}
    sources = {"cfb": cfb, "nfl": nfl}

    for g in games:
        _refresh(g, sources[g["sp"]].get(g["id"][4:]), now, end)

    # Every NFL game in the window, once its teams are known - only before it locks.
    for gid, r in sorted(nfl.items(), key=lambda kv: (_text(kv[1]["date_utc"]), kv[0])):
        kick = _ts(r["date_utc"])
        if f"nfl:{gid}" in have or not (lo <= kick < hi) or kick <= t:
            continue
        if _unknown_team(r, "nfl") or r.get("state", "pre") != "pre":
            continue
        games.append(_new_game("nfl", gid, r, now, end))
        have.add(f"nfl:{gid}")

    # The college games: the window's best by the watch score, up to FEATURED.
    room = FEATURED - sum(1 for g in games if g["sp"] == "cfb")
    if room > 0:
        picks = []
        for w in watch or []:
            gid = str(w.get("id", ""))
            r = cfb.get(gid)
            if not r or f"cfb:{gid}" in have or w.get("score") is None:
                continue
            kick = _ts(r["date_utc"])
            if not (lo <= kick < hi) or kick <= t or r.get("state", "pre") != "pre":
                continue
            if _unknown_team(r, "cfb"):
                continue
            picks.append((-float(w["score"]), _iso(kick), gid, r, w))
        for _s, _k, gid, r, w in sorted(picks)[:room]:
            games.append(_new_game("cfb", gid, r, now, end, w))
            have.add(f"cfb:{gid}")

    if not games:
        return None
    _model_picks(games, now, probs)
    featured = [g for g in games if g["sp"] == "cfb" and g.get("watch") is not None]
    best = max(featured, key=lambda g: (g["watch"], g["id"]), default=None)
    for g in games:
        g.pop("gotw", None)
        if best is not None and g is best:
            g["gotw"] = True
    return {
        "season": season, "week": week, "label": f"Week {week}",
        "sub": _labels(games, cfb, nfl) or (slate or {}).get("sub", ""),
        "start": start.isoformat(), "end": end.isoformat(),
        "opened": (slate or {}).get("opened") or _iso(now),
        "n": len(games), "games": games,
    }


def done(slate: dict) -> bool:
    """Every game graded (a winner, or void)."""
    return all(g.get("res") is not None for g in slate.get("games", []))


# --------------------------------------------------------------------------- #
# The season
# --------------------------------------------------------------------------- #

def index(season: int, slates: dict, now: datetime, first: datetime) -> dict:
    """docs/pickem/season.json: every week's games in the compact form the
    Function grades with - [id, lock (epoch seconds), result, GordStats side,
    GordStats value] - and which week is current."""
    weeks = sorted(slates)
    cur = week_of(first, now)
    if cur not in slates:
        later = [w for w in weeks if w > cur]
        cur = later[0] if later else (weeks[-1] if weeks else None)
    out = []
    for w in weeks:
        s = slates[w]
        out.append({
            "w": w, "label": s["label"], "sub": s.get("sub", ""), "n": len(s["games"]),
            "start": s["start"], "end": s["end"], "done": done(s),
            "g": [[g["id"], int(_ts(g["lock"]).timestamp()), g.get("res"),
                   (g.get("gs") or {}).get("s"), (g.get("gs") or {}).get("c")]
                  for g in s["games"]],
        })
    return {"season": season, "current": cur, "weeks": out}


def _week_name(week: int) -> str:
    return f"week_{week:02d}.json"


def sidecar(season: int):
    """The untracked copy of the slates (data/pickem_live/<season>/), or None
    where gordstats.pregame's switch is off (the PC, the tests). The live
    tick starts from `git checkout -- docs data` and commits once an hour, so
    a game added or a GordStats pick fixed at its lock by one tick would be
    thrown away by the next - after its lock, for good. As with the pre-kickoff
    projections, the copy outside git survives; load() takes whichever copy is
    further on (`v`), and every write goes to both, so the next commit
    records it."""
    from gordstats.pregame import SIDECAR_ENV

    return paths.DATA / "pickem_live" / str(season) if os.environ.get(SIDECAR_ENV) else None


def load(season: int) -> dict:
    """The stored slates, {week: slate}: of the tracked file and the
    untracked copy, the one written later (the higher `v`)."""
    out = {}
    for folder in (DATA / str(season), sidecar(season)):
        if folder is None or not folder.is_dir():
            continue
        for path in sorted(folder.glob("week_*.json")):
            try:
                slate = json.loads(path.read_text(encoding="utf-8"))
                week = int(slate["week"])
            except (OSError, ValueError, KeyError) as exc:
                print(f"  ! pickem: {path.name} unreadable ({exc}); left alone")
                continue
            if week not in out or int(slate.get("v", 0)) > int(out[week].get("v", 0)):
                out[week] = slate
    return out


def _save(season: int, week: int, old: dict | None, slate: dict) -> dict:
    """Write a week's slate to data/ (and the untracked copy). `v` counts the
    changes, so an unchanged week is an unchanged file."""
    same = old is not None and {k: v for k, v in old.items() if k != "v"} == slate
    slate = {**slate, "v": int((old or {}).get("v", 0)) + (0 if same else 1)}
    text = json.dumps(slate, indent=1, ensure_ascii=False) + "\n"
    stable.write_text(text, DATA / str(season) / _week_name(week))
    side = sidecar(season)
    if side is not None:
        stable.write_text(text, side / _week_name(week))
    return slate


def _inputs(season: int) -> dict:
    """What a build reads, all from disk: this run's sections have refreshed it."""
    from cfb.config import DATA_DIR as CFB_DATA
    from nfl import games as nfl_games

    def frame(path):
        return pd.read_parquet(path) if path.exists() else pd.DataFrame()

    nfl = frame(nfl_games.season_path(season))
    cfb = frame(CFB_DATA / f"schedule_{season}.parquet")
    watch = []
    try:
        watch = json.loads((paths.DOCS / "cfb" / "watch" / "games.json")
                           .read_text(encoding="utf-8")).get("games") or []
    except (OSError, ValueError):
        print("  ! pickem: no CFB watch guide games; no college games added this run")
    return {"nfl": nfl, "cfb": cfb, "watch": watch, "probs": probabilities(watch)}


def probabilities(watch: list) -> dict:
    """{"cfb:<id>" / "nfl:<id>": our home win chance}: the last prediction
    archived before kickoff, else the watch guide's (this run's model)."""
    out = {}
    try:
        nfl_watch = json.loads((paths.DOCS / "nfl" / "watch" / "games.json")
                               .read_text(encoding="utf-8")).get("games") or []
    except (OSError, ValueError):
        nfl_watch = []
    for sport, games in (("cfb", watch), ("nfl", nfl_watch)):
        for w in games:
            if w.get("hw") is not None:
                out[f"{sport}:{w['id']}"] = float(w["hw"])
    for sport in ("cfb", "nfl"):
        try:
            rec = importlib.import_module(f"{sport}.results").on_record()
        except Exception as exc:                        # noqa: BLE001
            print(f"  ! pickem: no {sport} prediction archive ({exc})")
            continue
        for gid, p in zip(rec.get("game_id", []), rec.get("home_win_prob", [])):
            if p is not None and not pd.isna(p):
                out[f"{sport}:{gid}"] = float(p)
    return out


def build(now: datetime | None = None, season: int | None = None,
          inputs: dict | None = None) -> dict | None:
    """Bring this season's slates up to date and publish them. Returns the
    season index, or None outside a season with nothing on file."""
    from nfl.config import SEASON

    now = now or datetime.now(timezone.utc)
    season = season or SEASON
    inputs = inputs if inputs is not None else _inputs(season)
    bounds = season_bounds(inputs["nfl"])
    slates = load(season)
    if bounds is None:
        print("  pickem: no NFL season on file; nothing to build")
        return None
    first, last = bounds
    nfl, cfb = _rows(inputs["nfl"]), _rows(inputs["cfb"])
    todo = {w for w, s in slates.items() if not done(s)}
    cur = week_of(first, now)
    if 1 <= cur <= last:
        todo.add(cur)
    for w in sorted(todo):
        start, end = window(first, w)
        slate = update_week(slates.get(w), season=season, week=w, start=start, end=end,
                            now=now, cfb=cfb, nfl=nfl, watch=inputs.get("watch") or [],
                            probs=inputs.get("probs") or {})
        if slate is None:
            continue
        slates[w] = _save(season, w, slates.get(w), slate)
    if not slates:
        return None
    return publish(season, slates, now, first)


def publish(season: int, slates: dict, now: datetime, first: datetime) -> dict:
    """The files the page and the Function read (docs/pickem/, generated)."""
    idx = index(season, slates, now, first)
    for w, slate in slates.items():
        stable.write_text(json.dumps(slate, separators=(",", ":"), ensure_ascii=False),
                          OUT / str(season) / _week_name(w))
    stable.write_text(json.dumps(idx, separators=(",", ":"), ensure_ascii=False),
                      OUT / "season.json")
    return idx


def generate(now: datetime | None = None) -> None:
    """The daily run's and the CFB live tick's entry: slates, then the page."""
    from gordstats import pickem_page

    idx = build(now)
    pickem_page.generate()
    if idx:
        cur = idx["current"]
        print(f"Wrote pick'em -> week {cur} of {len(idx['weeks'])} on file")


if __name__ == "__main__":
    generate()
