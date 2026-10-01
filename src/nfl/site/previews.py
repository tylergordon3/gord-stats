"""
NFL game previews (/nfl/game/<ESPN id>/): one page per game, the matchup unit
by unit with our pick on top - the twin of /cfb/game/, drawn by the shared
gordstats.preview_page.

Read, not refitted. The pick and the book's line and total are what the
schedule shows (nfl.site.schedule._call: today's fit and line for a game still
to play, the numbers on record before kickoff for one that has started); the
watch score is the watch guide's (nfl.site.watch.judge on ESPN's matchup
quality, fetched the way the guide fetches it); the units and players are
nfl.advanced's nflverse figures - opponent-adjusted EPA, the splits, the red
zone, sacks and giveaways - ranked across the 32; the forecast is the one the
fantasy matchups archive keeps from ESPN's scoreboard.

Which games: last week's, this week's, and next week's once the book has a
line. Last week's are rebuilt with the final and the marks; older ones are
removed (preview_page.prune).

Builds after the team pages (it links to them) and before the pages that link
here - predictions, watch, schedule - which ask preview_page.exists() first.

    python -m nfl.site.previews
"""
import json
from datetime import datetime, timezone

import pandas as pd

from gordstats import logos, preview_page
from gordstats.preview_page import ordinal
from nfl import advanced, predict, results
from nfl.config import SEASON
from nfl.site import schedule as sched, teams as teams_page, watch
from nfl.site.predictions import EDGE

SPORT = "nfl"
FORM_GAMES = 4

UNITS = [
    {"label": "EPA per play", "off": "off_adj", "def": "def_adj", "fmt": "epa",
     "off_phrase": "offense", "def_phrase": "defense"},
    {"label": "Pass EPA", "off": "off_pass", "def": "def_pass", "fmt": "epa",
     "off_phrase": "passing game", "def_phrase": "pass defense"},
    {"label": "Run EPA", "off": "off_rush", "def": "def_rush", "fmt": "epa",
     "off_phrase": "run game", "def_phrase": "run defense"},
    {"label": "Success rate", "off": "off_sr", "def": "def_sr", "fmt": "pct"},
    {"label": "Explosive plays", "off": "off_xpl", "def": "def_xpl", "fmt": "pct",
     "off_phrase": "big-play offense", "def_phrase": "big-play defense"},
    {"label": "Points per drive", "off": "off_ppd", "def": "def_ppd", "fmt": "num2",
     "off_phrase": "scoring offense", "def_phrase": "scoring defense"},
    {"label": "Red zone TD", "off": "off_rz", "def": "def_rz", "fmt": "pct",
     "off_phrase": "red-zone offense", "def_phrase": "red-zone defense"},
    {"label": "Third downs", "off": "off_third", "def": "def_third", "fmt": "pct",
     "off_phrase": "third-down offense", "def_phrase": "third-down defense"},
    {"label": "Sacks", "off": "off_sack", "def": "def_sack", "fmt": "pct",
     "off_phrase": "pass protection", "def_phrase": "pass rush"},
    {"label": "Turnovers", "off": "off_to", "def": "def_to", "fmt": "pct",
     "off_phrase": "ball security", "def_phrase": "takeaway defense"},
]
# Offenses high, defenses low - except sacks and giveaways, which an offense
# avoids and a defense makes. Pace ranks fastest first (fewest seconds).
BETTER = {**{u["off"]: "high" for u in UNITS}, **{u["def"]: "low" for u in UNITS},
          "off_sack": "low", "off_to": "low", "def_sack": "high", "def_to": "high",
          "off_pace": "low"}

NOTES = [
    ("EPA", "Expected points added per play: how much a snap changed the points the offense "
     "could expect from the drive. EPA per play is adjusted for the opponents faced; the "
     "splits are as played, garbage time out."),
    ("Success rate", "Share of plays with positive EPA."),
    ("Explosive plays", "Dropbacks of 20+ yards and runs of 10+, per play."),
    ("Red zone TD", "Possessions with a snap inside the 20 that end in a touchdown."),
    ("Sacks", "Per dropback: the offense's taken, the defense's made."),
    ("Turnovers", "Possessions ending in an interception or a lost fumble: the offense's "
     "giveaways, the defense's takeaways."),
    ("Players", "QBs on EPA per dropback (CPOE is completion percentage over expected), backs "
     "per carry, receivers per target; ranked among the leaderboard qualifiers."),
]


def _v(x):
    return preview_page._v(x)


def window(frame: pd.DataFrame, now) -> pd.DataFrame:
    """The games that get a page: last week's, this week's and next week's
    with a book line - never a playoff game whose teams are not set."""
    frame = frame[~frame.apply(sched._tbd, axis=1)] if len(frame) else frame
    if frame.empty:
        return frame
    keys = [sched.week_key(w, s) for w, s in zip(frame["week"], frame["seasontype"])]
    frame = frame.assign(_key=keys)
    order = sorted(set(keys))
    week, seasontype = predict.current_week(frame, pd.Timestamp(now))
    cur = sched.week_key(week, seasontype)
    i = order.index(cur)
    prev = order[i - 1] if i > 0 else None
    nxt = order[i + 1] if i + 1 < len(order) else None
    near = frame["_key"].isin([k for k in (prev, cur) if k is not None])
    lined = (frame["_key"] == nxt) & frame["book_spread"].notna() if nxt is not None else False
    return frame[near | lined]


# --------------------------------------------------------------------------- #
# The pieces of one game
# --------------------------------------------------------------------------- #

def weather_by_game(weeks) -> dict:
    """{game id: forecast} from the fantasy matchups archive, which keeps
    ESPN's scoreboard weather for each week (fantasy.league.matchups)."""
    from cfb import gameinfo
    from cfb.site import schedule as cfb_schedule
    from fantasy.league import matchups as mdata

    out = {}
    for week in sorted(set(int(w) for w in weeks)):
        try:
            games = json.loads(mdata._path(week, SEASON).read_text(encoding="utf-8")).get("games")
        except (OSError, ValueError):
            continue
        for g in games or []:
            wx = g.get("weather")
            if wx:
                text = wx.get("text") or gameinfo.weather_text(wx)
                out[str(g.get("game_id"))] = preview_page.weather(
                    wx, cfb_schedule._wx_icon(wx.get("cond")), text)
    return out


def _team(g, side: str, records: dict, names: dict, root=None) -> dict:
    tid = str(g[f"{side}_id"])
    name = (names.get(tid) or (str(g[side]),))[0]
    page = teams_page.OUT_DIR / teams_page.team_slug(name) / "index.html"
    rec = records.get(str(g["game_id"]), ("", ""))[0 if side == "away" else 1]
    return {"id": tid, "name": str(g[side]), "abbr": str(g[f"{side}_abbr"]),
            "logo": logos.url("nfl", g[f"{side}_abbr"], 160), "rank": None, "record": rec,
            "href": teams_page.url(name) if page.exists() else None,
            "score": _v(g.get(f"{side}_score"))}


def _call(g, record: dict, now, quality: dict) -> dict:
    """The schedule card's numbers (nfl.site.schedule._call), ESPN's win
    chance and the watch guide's score."""
    c = sched._call(g, record, now) or {}
    # Our total beside it, from the same source as the margin: the record
    # once the game has kicked off, today's fit before.
    rec = record.get(str(g["game_id"]))
    kicked = g["date"] <= now or bool(g["played"]) or g.get("state") in ("in", "post")
    total = (_v(rec["pred_total"]) if rec is not None else None) if kicked \
        else _v(g.get("pred_total"))
    call = {"margin": c.get("margin"), "prob": c.get("prob"), "total": total if c else None,
            "spread": c.get("spread"), "book_total": c.get("total"), "book": "Book",
            "call_min": EDGE, "edge": EDGE, "record_url": "/nfl/", "others": []}
    e = quality.get(str(g["game_id"])) or {}
    fw = _v(e.get("fw"))
    if fw is not None:
        abbr = g["home_abbr"] if fw >= 0.5 else g["away_abbr"]
        call["others"].append(("ESPN", f"{abbr} {max(fw, 1 - fw):.0%}", "win chance"))
    if (g.get("state") or "pre") == "pre" and c:
        call["watch"], call["tags"], _fav = watch.judge({
            "mq": e.get("mq"), "sp": _v(g.get("book_spread")), "margin": _v(g.get("pred_margin")),
            "hw": _v(g.get("home_win_prob")), "fw": fw,
            "hrec": g.get("home_record") or "", "arec": g.get("away_record") or ""})
    return call


def _ranked(board: list, row: dict) -> str:
    place = next((i for i, q in enumerate(board, 1) if q.get("id") == row.get("id")), None)
    if place is None:
        return ""
    return (f"{ordinal(place)} of {len(board)}" if len(board) < advanced.KEEP
            else f"{ordinal(place)} in EPA")


def _players(data: dict, abbr: str) -> list:
    """The QB, the lead back and the top two targets on the leaderboards
    (nfl.advanced: qualifiers only), by volume."""
    boards = data.get("players") or {}
    out = []
    for key, n in (("qb", 1), ("rb", 1), ("wr", 2)):
        board = boards.get(key) or []
        mine = sorted((p for p in board if p.get("team") == abbr), key=lambda p: -(p.get("n") or 0))
        for p in mine[:n]:
            epa = _v(p.get("epa"))
            if epa is None:
                continue
            if key == "qb":
                cpoe = _v(p.get("cpoe"))
                stat = (f"{epa:+.2f} EPA a dropback"
                        + (f" · CPOE {cpoe:+.1f}" if cpoe is not None else "")
                        + f" · {p['n']} dropbacks")
            elif key == "rb":
                ypc = _v(p.get("ypc"))
                stat = (f"{epa:+.2f} EPA a carry"
                        + (f" · {ypc:.1f} yds" if ypc is not None else "")
                        + f" · {p['n']} carries")
            else:
                catch = _v(p.get("catch"))
                stat = (f"{epa:+.2f} EPA a target"
                        + (f" · {catch:.0%} caught" if catch is not None else "")
                        + f" · {p['n']} targets")
            out.append({"pos": p.get("pos") or key.upper(), "name": p.get("name") or "",
                        "stat": stat, "rank": _ranked(board, p)})
    return out


def _style(ranks: dict, row: dict) -> str:
    bits = []
    pace = ranks.get("off_pace")
    if pace:
        bits.append(f"{pace[0]:.1f} sec a snap ({ordinal(pace[1])} fastest)")
    proe = _v(row.get("off_proe"))
    if proe is not None:
        bits.append(f"passes {abs(proe) * 100:.0f}% {'more' if proe >= 0 else 'less'} "
                    "than expected")
    return " · ".join(bits)


def _games_list(frame: pd.DataFrame, record: dict) -> list:
    out = []
    for g in frame.to_dict("records"):
        rec = record.get(str(g["game_id"]))
        out.append({"game_id": str(g["game_id"]), "date": g["date"],
                    "home_id": str(g["home_id"]), "away_id": str(g["away_id"]),
                    "home": g["home"], "away": g["away"], "neutral": bool(g.get("neutral")),
                    "home_score": g.get("home_score"), "away_score": g.get("away_score"),
                    "played": bool(g.get("played")),
                    "pred_margin": None if rec is None else _v(rec["pred_margin"])})
    return out


# --------------------------------------------------------------------------- #
# Loading and building
# --------------------------------------------------------------------------- #

def _stats() -> dict:
    """nfl.advanced's cache as the stats page left it (it refreshes when
    stale); downloaded only when there is none at all."""
    data = advanced._read(advanced.cache_path(SEASON))
    return data if data else (advanced.refresh() or {})


def load(now, quality=None) -> dict:
    """Everything the pages read. `quality` is watch.quality()'s answer for
    the games still to play; fetched here when not given."""
    frame, _model, names = predict.season()
    record = {str(r["game_id"]): r for _, r in results.on_record(SEASON).iterrows()}
    stats = _stats()
    by_abbr = {abbr: tid for tid, (_name, abbr) in names.items() if teams_page._real(tid)}
    rows = []
    for t in stats.get("teams") or []:
        tid = by_abbr.get(teams_page._ESPN_ABBR.get(t["abbr"], t["abbr"]))
        if tid:
            rows.append({**t, "id": tid})
    games = window(frame, now)
    if quality is None:
        pending = [str(g) for g in games.loc[games["state"] == "pre", "game_id"]]
        quality = watch.quality(pending) if pending else {}
    return {"frame": frame, "names": names, "record": record, "stats": stats,
            "ranks": preview_page.rank_table(rows, BETTER),
            "rows": {r["id"]: r for r in rows},
            "nflverse": {r["id"]: r["abbr"] for r in rows},
            "quality": quality,
            "weather": weather_by_game(games.loc[games["seasontype"] == 2, "week"])}


def build(data: dict, now) -> list:
    frame = data["frame"]
    if frame is None or frame.empty:
        return []
    now = pd.Timestamp(now)
    record, names = data.get("record") or {}, data.get("names") or {}
    season = _games_list(frame, record)
    records = preview_page.records_going_in(season)
    ranks, rows = data.get("ranks") or {}, data.get("rows") or {}
    out = []
    for _, g in window(frame, now).sort_values("date").iterrows():
        gid = str(g["game_id"])
        away = _team(g, "away", records, names)
        home = _team(g, "home", records, names)
        aid, hid = away["id"], home["id"]
        key = sched.week_key(g["week"], g["seasontype"])
        out.append({
            "sport": SPORT, "id": gid, "label": sched.week_label(key),
            "state": g.get("state") or "pre", "status": str(g.get("detail") or ""),
            "ko": g["date"], "tk": sched._time_known(g), "tv": str(g.get("tv") or ""),
            "venue": str(g.get("venue") or ""), "place": str(g.get("place") or ""), "note": "",
            "neutral": bool(g.get("neutral")),
            "weather": ({"indoors": True} if g.get("indoor") else
                        (data.get("weather") or {}).get(gid)),
            "away": away, "home": home,
            "call": _call(g, record, now, data.get("quality") or {}),
            "units": {"away": preview_page.pair_units(UNITS, ranks.get(aid), ranks.get(hid)),
                      "home": preview_page.pair_units(UNITS, ranks.get(hid), ranks.get(aid))},
            "style": {side: _style(ranks.get(t["id"]) or {}, rows.get(t["id"]) or {})
                      for side, t in (("away", away), ("home", home))},
            "players": {side: _players(data.get("stats") or {},
                                       (data.get("nflverse") or {}).get(t["id"], ""))
                        for side, t in (("away", away), ("home", home))},
            "form": {side: preview_page.recent_form(season, t["id"], g["date"], FORM_GAMES)
                     for side, t in (("away", away), ("home", home))},
            "words": {"off": "offense", "def": "defense"},
            "schedule": f"/nfl/schedule/#wk-{key}",
            "notes": NOTES,
            "source": "From nflverse play-by-play.", "stats": "/nfl/stats/",
        })
    return out


def generate(now=None) -> None:
    now = pd.Timestamp(now) if now is not None else pd.Timestamp(datetime.now(timezone.utc))
    data = load(now)
    if data["frame"] is None or data["frame"].empty:
        print("NFL previews: no schedule; nothing written, nothing removed")
        return
    games = build(data, now)
    for g in games:
        kick = pd.Timestamp(g["ko"]).tz_convert(preview_page.ET)
        preview_page.write(
            g, subtitle=f"{g['label']} preview",
            description=(f"{preview_page.title(g)}, {kick:%a %b %-d}: GordStats' pick against "
                         "the line, and how the offenses and defenses match up."))
    removed = preview_page.prune(SPORT, {g["id"] for g in games})
    print(f"Wrote {len(games)} NFL game previews -> {preview_page.out_dir(SPORT)}"
          + (f"; removed {len(removed)} old" if removed else ""))


if __name__ == "__main__":
    generate()
