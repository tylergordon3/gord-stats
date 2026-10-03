"""
CFB game previews (/cfb/game/<ESPN id>/): one page per FBS game, the matchup
unit by unit with our pick on top - drawn by the shared
gordstats.preview_page (NFL's twin: nfl.site.previews).

Everything here is read, not refitted. The pick, the book's line and total,
ESPN's FPI and the forecast are the schedule page's own (cfb.site.schedule's
frame: today's fit for a game still to play, the line on record before
kickoff for one that is over); the watch score is the watch guide's
(cfb.site.watch.judge on the same inputs); the units and players are
CollegeFootballData's season figures (cfb.advanced) - opponent-adjusted where
CFBD adjusts them, see SOURCE - ranked across FBS.

Which games: last week's, this week's, and next week's once the book has a
line on them - FBS against FBS only. An FCS side has no rating of its own (the
model pools FCS into one team), no CFBD figures and no team page, so its
preview would be a page of dashes. Last week's pages are rebuilt with the
final and the marks, so a link from the week just finished still lands on
something true. After that a finished game's page is left as it was - final,
marks and all, not rebuilt - for the rest of the season (finished()), so a
shared link or a search result still opens; prune removes only the pages of
games never played (postponed, cancelled) and, once next season's schedule
loads, last season's. A season is ~850 pages of ~20 KB, uploaded once each
(wrangler sends only changed files); the Jekyll build stays linear in pages
because the nav no longer loops over them (docs/_plugins/latest_predict.rb).

Builds after the team pages (it links to them) and before the pages that link
here - predictions, schedule, watch - which ask preview_page.exists() first.

    python -m cfb.site.previews
"""
from datetime import datetime, timezone

import pandas as pd

from cfb import advanced, espn, gameinfo, predict, results
from cfb.site import schedule, teams as teams_page, watch
from gordstats import logos, preview_meta, preview_page
from gordstats.preview_page import ordinal

SPORT = "cfb"
FBS_GAMES = 8             # a team on the schedule this often is FBS (cfb.predict.history)
FORM_GAMES = 4

# Offence against defence, row by row. The phrases word the biggest mismatch
# ("Ohio State's run game (4th) meets Purdue's run defence (98th)"); a row
# without them is shown but never named.
UNITS = [
    {"label": "EPA per play", "off": "adj_off", "def": "adj_def", "fmt": "epa",
     "off_phrase": "offense", "def_phrase": "defense"},
    {"label": "Run EPA", "off": "adj_off_rush", "def": "adj_def_rush", "fmt": "epa",
     "off_phrase": "run game", "def_phrase": "run defense"},
    {"label": "Pass EPA", "off": "adj_off_pass", "def": "adj_def_pass", "fmt": "epa",
     "off_phrase": "passing game", "def_phrase": "pass defense"},
    {"label": "Success rate", "off": "adj_sr", "def": "adj_sr_a", "fmt": "pct"},
    {"label": "Explosiveness", "off": "adj_expl", "def": "adj_expl_a", "fmt": "num2",
     "off_phrase": "big-play offense", "def_phrase": "big-play defense"},
    {"label": "Line yards", "off": "adj_line", "def": "adj_line_a", "fmt": "num2",
     "off_phrase": "offensive line", "def_phrase": "defensive front"},
    {"label": "Havoc", "off": "off_havoc", "def": "def_havoc", "fmt": "pct"},
    {"label": "Points per trip", "off": "off_ppo", "def": "def_ppo", "fmt": "num2"},
    {"label": "Third downs", "off": "third", "def": "third_a", "fmt": "pct",
     "off_phrase": "third-down offense", "def_phrase": "third-down defense"},
]
# Which way is better, for the ranks: offences high, defences low - but havoc
# is the defence's to make and the offence's to avoid.
BETTER = {**{u["off"]: "high" for u in UNITS}, **{u["def"]: "low" for u in UNITS},
          "off_havoc": "low", "def_havoc": "high", "plays_pg": "high"}

NOTES = [
    ("EPA", "Expected points added: what a play was worth in points, from the down, distance "
     "and field position before it to those after. Per play, adjusted for the opponents faced."),
    ("Success rate", "Plays that gain 50% of the yards needed on first down, 70% on second, "
     "all of them on third and fourth."),
    ("Explosiveness", "The average EPA of the successful plays: how big the good ones are."),
    ("Line yards", "Rushing yards credited to the offensive line, per carry."),
    ("Havoc", "Plays ending in a tackle for loss, a forced fumble, an interception or a pass "
     "broken up: the defense's rate made, the offense's allowed."),
    ("Points per trip", "Points per drive that reaches the opponent's 40."),
    ("Players", "EPA per play with garbage time out; ranked among FBS players with enough "
     "plays (QBs 80 dropbacks, backs 35 carries, receivers 15 targets)."),
]
# EPA, success rate, explosiveness and line yards are CFBD's opponent-adjusted
# figures; havoc and points per trip its raw splits, garbage time out; third
# downs the box score (cfb.advanced).
SOURCE = ("From CollegeFootballData: EPA, success rate, explosiveness and line yards "
          "adjusted for the opponents faced; havoc and points per trip as played, "
          "garbage time out; third downs from the box score.")
# The explainers (gordstats.how) the call's and the units' chips open.
HOW = {"call": "cfb-predictions", "units": "game-previews"}


def _v(x):
    return preview_page._v(x)


def _fbs(frame: pd.DataFrame) -> set:
    """ESPN ids on this season's schedule often enough to be FBS - the test
    cfb.predict uses to decide who gets a rating of their own. Never one of
    ESPN's placeholders: every bowl and CFP game is filed as -1 against -2
    ("TBD") until it is paired, which is fifty-odd appearances, and counted
    here they built "TBD at TBD" previews through December."""
    ids = pd.concat([frame["home_id"], frame["away_id"]]).astype(str)
    counts = ids[~predict._placeholder(ids)].value_counts()
    return set(counts[counts >= FBS_GAMES].index)


def _played(g) -> bool:
    """A real final: ESPN files a cancelled game as state=post with 0-0."""
    return (g.get("state") == "post" and _v(g.get("home_score")) is not None
            and _v(g.get("away_score")) is not None
            and _v(g["home_score"]) + _v(g["away_score"]) > 0
            and not any(w in str(g.get("detail") or "") for w in ("Cancel", "Postpon")))


def current_week(frame: pd.DataFrame, now) -> int:
    """The schedule page's current week (cfb.site.schedule._current_week) as
    of `now`: the first with a game on or still to come, else the last."""
    now = pd.Timestamp(now)
    kick = pd.to_datetime(frame["date_utc"], utc=True)
    pending = frame[(kick >= now) | (frame["state"] == "in")]
    return int(pending["week"].min()) if len(pending) else int(frame["week"].max())


def window(frame: pd.DataFrame, now) -> pd.DataFrame:
    """The games that get a page: last week's, this week's and next week's
    with a book line, FBS against FBS."""
    weeks = sorted(int(w) for w in frame["week"].unique())
    if not weeks:
        return frame.iloc[0:0]
    cur = current_week(frame, now)
    i = weeks.index(cur)
    prev = weeks[i - 1] if i > 0 else None
    nxt = weeks[i + 1] if i + 1 < len(weeks) else None
    fbs = _fbs(frame)
    both = frame["home_id"].astype(str).isin(fbs) & frame["away_id"].astype(str).isin(fbs)
    near = frame["week"].isin([w for w in (prev, cur) if w is not None])
    lined = (frame["week"] == nxt) & frame["dk_spread"].notna() if nxt is not None else False
    return frame[both & (near | lined)]


# --------------------------------------------------------------------------- #
# The pieces of one game
# --------------------------------------------------------------------------- #

def _weather(wx) -> dict | None:
    wx = wx if isinstance(wx, dict) else None
    if not wx:
        return None
    return preview_page.weather(wx, schedule._wx_icon(wx.get("cond")),
                                gameinfo.weather_text(wx) or wx.get("text") or "")


def _team(g, side: str, records: dict, pages: frozenset) -> dict:
    name = str(g[side])
    slug = teams_page.team_slug(name)
    rec = records.get(str(g["game_id"]), ("", ""))[0 if side == "away" else 1]
    rank = _v(g.get(f"{side}_rank"))
    return {"id": str(g[f"{side}_id"]), "name": name, "abbr": str(g.get(f"{side}_abbr") or ""),
            "logo": logos.url("ncaa", g[f"{side}_id"], 160), "rank": int(rank) if rank else None,
            "record": rec, "href": f"/cfb/teams/{slug}/" if slug in pages else None,
            "score": _v(g.get(f"{side}_score"))}


def _call(g, watch_inputs: dict, playoff: dict) -> dict:
    margin, prob = _v(g.get("gs_margin")), _v(g.get("gs_wp"))
    call = {"margin": margin, "prob": prob, "total": _v(g.get("gs_total")),
            "spread": _v(g.get("dk_spread")), "book_total": _v(g.get("dk_total")),
            "book": g.get("dk_book") or "DraftKings", "call_min": results.CALL_MIN,
            "edge": results.BET_MIN, "record_url": "/cfb/predictions/#how-it-has-gone",
            "others": []}
    fpi = _v(g.get("fpi_wp"))
    if fpi is not None:
        abbr = g["home_abbr"] if fpi >= 0.5 else g["away_abbr"]
        call["others"].append(("ESPN FPI", f"{abbr} {max(fpi, 1 - fpi):.0%}", "win chance"))
    if (g.get("state") or "pre") == "pre":
        # The watch guide's own score: its judge, on the inputs it reads -
        # the archived DraftKings spread, our fit, FPI, ESPN's matchup quality.
        call["watch"], call["tags"], _fav = watch.judge({
            "mq": _v(g.get("mq")), "sp": _v(watch_inputs.get("sp")), "margin": margin,
            "hw": prob, "fw": fpi, "hr": _v(g.get("home_rank")), "ar": _v(g.get("away_rank")),
            "hpo": _v(playoff.get(str(g["home_id"]))), "apo": _v(playoff.get(str(g["away_id"])))})
    return call


def _players(rows: list, qualified: dict, team: str) -> list:
    """The quarterback, the lead back and the top two targets of one team
    (CFBD's name), by volume - who will have the ball - with their EPA and
    where it ranks among FBS qualifiers."""
    mine = [r for r in rows if r.get("team") == team]
    picks = []
    for pos, kind, n in (("QB", "pass", 1), ("RB", "rush", 1), (("WR", "TE"), "pass", 2)):
        group = [r for r in mine if r.get("pos") in ((pos,) if isinstance(pos, str) else pos)
                 and (r.get(f"{kind}_n") or 0) > 0 and r.get(kind) is not None]
        group.sort(key=lambda r: -(r.get(f"{kind}_n") or 0))
        picks.extend((r, kind) for r in group[:n])
    out = []
    for r, kind in picks:
        unit = {"QB": "dropback", "RB": "carry"}.get(r["pos"], "target")
        vol = {"QB": "dropbacks", "RB": "carries"}.get(r["pos"], "targets")
        board = qualified.get(r["pos"]) or []
        place = next((i for i, q in enumerate(board, 1)
                      if q.get("name") == r["name"] and q.get("team") == team), None)
        out.append({"pos": r["pos"], "name": r["name"],
                    "stat": f"{r[kind]:+.2f} EPA a {unit} · {r[f'{kind}_n']} {vol}",
                    "rank": f"{ordinal(place)} of {len(board)} {r['pos']}s" if place else ""})
    return out


def _style(ranks: dict, row: dict) -> str:
    """Tempo and pass lean - style, not quality, so it is not on the bars."""
    bits = []
    plays = ranks.get("plays_pg")
    if plays:
        bits.append(f"{plays[0]:.0f} plays a game ({ordinal(plays[1])} most)")
    rate = _v(row.get("pass_rate"))
    if rate is not None:
        bits.append(f"passes on {rate * 100:.0f}% of plays")
    return " · ".join(bits)


def _time_known(g) -> bool:
    known = g.get("time_valid")
    return True if known is None or pd.isna(known) else bool(known)


def _games_list(frame: pd.DataFrame) -> list:
    """The season as plain dicts, for the records and the form."""
    out = []
    for g in frame.to_dict("records"):
        out.append({"game_id": str(g["game_id"]), "date": g["date_utc"],
                    "home_id": str(g["home_id"]), "away_id": str(g["away_id"]),
                    "home": g["home"], "away": g["away"], "neutral": bool(g.get("neutral")),
                    "home_score": g.get("home_score"), "away_score": g.get("away_score"),
                    "played": _played(g), "pred_margin": _v(g.get("gs_margin"))})
    return out


# --------------------------------------------------------------------------- #
# Loading and building
# --------------------------------------------------------------------------- #

def load() -> dict:
    """Everything the pages read, from the caches the build has just filled."""
    frame = schedule._frame()
    try:
        rows = advanced.teams()
    except Exception as exc:                    # noqa: BLE001 - the pages stand without it
        print(f"  ! previews: no advanced stats ({exc})")
        rows = []
    fbs_names = {r["name"] for r in rows}
    return {"frame": frame, "ranks": preview_page.rank_table(rows, BETTER),
            "rows": {str(r["id"]): r for r in rows},
            "names": {str(r["id"]): r["name"] for r in rows},
            "ppa": advanced._load("ppa_players") if rows else [],
            "qualified": advanced.players(fbs_names) if rows else {},
            "playoff": watch._playoff_odds(), "pages": schedule._team_pages()}


def build(data: dict, now) -> list:
    """The games in the window, in preview_page's shape."""
    frame = data["frame"]
    if frame is None or frame.empty:
        return []
    season = _games_list(frame)
    records = preview_page.records_going_in(season)
    ranks, names = data.get("ranks") or {}, data.get("names") or {}
    rows = data.get("rows") or {}
    pages = data.get("pages") or frozenset()
    out = []
    for g in window(frame, now).sort_values("date_utc").to_dict("records"):
        gid = str(g["game_id"])
        state = g.get("state") or "pre"
        if state == "post" and not _played(g):
            state = "pre"                                       # cancelled: never played
        away, home = _team(g, "away", records, pages), _team(g, "home", records, pages)
        aid, hid = away["id"], home["id"]
        units = {"away": preview_page.pair_units(UNITS, ranks.get(aid), ranks.get(hid)),
                 "home": preview_page.pair_units(UNITS, ranks.get(hid), ranks.get(aid))}
        players = {side: _players(data.get("ppa") or [], data.get("qualified") or {},
                                  names.get(t["id"], ""))
                   for side, t in (("away", away), ("home", home)) if names.get(t["id"])}
        out.append({
            "sport": SPORT, "id": gid, "label": espn.week_label(int(g["week"])),
            "state": state, "status": str(g.get("detail") or ""),
            "ko": g["date_utc"], "tk": _time_known(g),
            "tv": str(g.get("tv") or ""), "venue": str(g.get("venue") or ""),
            "place": str(g.get("place") or ""), "note": str(g.get("note") or ""),
            "neutral": bool(g.get("neutral")), "weather": _weather(g.get("weather")),
            "away": away, "home": home,
            "call": _call(g, {"sp": g.get("bd_spread")}, data.get("playoff") or {}),
            "units": units,
            "style": {side: _style(ranks.get(t["id"]) or {}, rows.get(t["id"]) or {})
                      for side, t in (("away", away), ("home", home))},
            "players": players,
            "form": {side: preview_page.recent_form(season, t["id"], g["date_utc"], FORM_GAMES)
                     for side, t in (("away", away), ("home", home))},
            "words": {"off": "offense", "def": "defense"},
            "schedule": f"/cfb/schedule/#w={int(g['week'])}&g={gid}",
            "notes": NOTES, "source": SOURCE, "stats": "/cfb/stats/",
            "how": HOW,
        })
    return out


def finished(frame: pd.DataFrame) -> set:
    """This season's games that have been played. Their pages stay up after
    the window moves on (prune keeps them), as they were last written: with
    the final, since a game is in the window for the week after it."""
    if frame is None or frame.empty:
        return set()
    played = frame.apply(_played, axis=1)
    return set(frame.loc[played, "game_id"].astype(str))


def generate(now=None) -> None:
    now = pd.Timestamp(now) if now is not None else pd.Timestamp(datetime.now(timezone.utc))
    data = load()
    if data["frame"] is None or data["frame"].empty:
        print("CFB previews: no schedule; nothing written, nothing removed")
        return
    games = build(data, now)
    for g in games:
        preview_page.write(g, subtitle=f"{g['label']} preview",
                           description=preview_meta.describe(g))
    removed = preview_page.prune(SPORT, {g["id"] for g in games} | finished(data["frame"]))
    print(f"Wrote {len(games)} CFB game previews -> {preview_page.out_dir(SPORT)}"
          + (f"; removed {len(removed)} old" if removed else ""))


if __name__ == "__main__":
    generate()
