"""
CBB game previews (/cbb/game/<theScore id>/): one page per men's game, our
call against the book's and the matchup unit by unit - the college basketball
twin of /cfb/game/ and /nfl/game/, drawn by the shared gordstats.preview_page.

Everything here is read, not refitted:

    the games   the live scoreboard Worker (render_watch.FEED), which cbb.live
                pushes every ten minutes in playing hours with every game two
                days back and a week ahead. Its ids are theScore's, so the
                watch guide (render_watch, built in the browser from the same
                feed) and the lines archive (cbb.lines, "men:<id>") name a game
                the way the page's address does. TV is the one thing the feed
                leaves out: one more request to theScore for the window's
                events, and a page without it if that fails.
    the call    cbb.game_model.predict - the scoreboard's own call - on the
                newest Torvik table dated on or before the game's day
                (data/men/torvik/<date>.json, T-Rank's preseason table before
                the first), so a final keeps the number it had at tip-off
                rather than one refitted on its own result. The book's line
                and total are the feed's before tip-off and the lines
                archive's close after it, each the other's fallback. The
                watch score is the guide's formula (render_watch's
                docstring), ported below.
    the units   Torvik's adjusted efficiency, tempo and - once he publishes
                {year}_fffinal.csv - the four factors, the same rows the Team
                Stats page draws (render_stats.rows), ranked across D-I.
    the form    data/schedule/men_season.json, the per-team results the daily
                run keeps (cbb.scrape.season), with the margin against our
                line from the table published before each game.

Which games: men's games from yesterday through tomorrow (Eastern), both
teams Division I (T-Rank rates both - otherwise there is no call and no
units, only a header), and at least one of them in T-Rank's top TOP or the
game a tournament's. Last season that was 23 games a day on average, 45 on
the 90th-percentile day and 81 at most, so ~70 pages are up at a time and
~200 on the busiest days, ~15 KB each; every two-team-from-the-bottom-half
game a day is left to the scoreboard. A finished game keeps its page for a
day, with the final and the marks; then prune() removes it, so the deploy
holds three days and never grows. The women's games are left out: the T-Rank
table and four-factors file this section caches are the men's, so a women's
page would be the call and nothing under it.

Builds after the rankings (it reads their T-Rank cache) and before the watch
guide, which links each card to its preview when one is on disk
(preview_page.built). No games in the window - the off-season, when the feed
still holds March - is a line saying so, and nothing written.

    python -m cbb.render.render_previews
"""
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import pandas as pd

from cbb import constants, game_model, paths, utils
from cbb.render import render_watch
from gordstats import preview_page
from gordstats.preview_page import ET, ordinal

SPORT = "cbb"
TOP = 150                  # T-Rank places: a game needs a team this high (or a tournament)
FORM_GAMES = 4
# Points between our margin and the book's before a lean is named - the NFL
# page's rule. The model is not yet graded against lines (cbb.lines keeps
# them from 2026-27), so no record link and no "slight" leans.
EDGE = 3.0
SCORE_EVENTS = "https://api.thescore.com/ncaab/events"
SCORE_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json",
                 "Referer": "https://www.thescore.com/"}

UNITS = [
    {"label": "Adj. efficiency", "off": "adjoe", "def": "adjde", "fmt": "num1",
     "off_phrase": "offense", "def_phrase": "defense"},
    {"label": "Effective FG%", "off": "efg", "def": "efg_d", "fmt": "pct1",
     "off_phrase": "shooting", "def_phrase": "shot defense"},
    {"label": "Turnovers", "off": "tov", "def": "tov_d", "fmt": "pct1",
     "off_phrase": "ball security", "def_phrase": "ball pressure"},
    {"label": "Offensive rebounding", "off": "orb", "def": "drb", "fmt": "pct1",
     "off_phrase": "offensive rebounding", "def_phrase": "defensive rebounding"},
    {"label": "Free-throw rate", "off": "ftr", "def": "ftr_d", "fmt": "pct1",
     "off_phrase": "free-throw rate", "def_phrase": "foul rate"},
    {"label": "3-point %", "off": "p3", "def": "p3_d", "fmt": "pct1",
     "off_phrase": "three-point shooting", "def_phrase": "three-point defense"},
]
# Offences high, defences low - except turnovers, which an offence avoids and
# a defence forces. Torvik's "DR%" (drb) is the share of their misses the
# opponents get back, so low is the good end, as for every other defence
# figure. Tempo ranks fastest first.
BETTER = {**{u["off"]: "high" for u in UNITS}, **{u["def"]: "low" for u in UNITS},
          "tov": "low", "tov_d": "high", "tempo": "high"}

NOTES = [
    ("The call", "GordStats' margin and win chance: each side's adjusted offense against the "
     "other's adjusted defense at the two teams' pace, with 2.5 points for home court - the "
     "scoreboard's own numbers. The book's line is theScore's."),
    ("Adj. efficiency", "Points per 100 possessions against an average D-I team on a neutral "
     "floor: the offense's scored, the defense's allowed."),
    ("Effective FG%", "Field-goal percentage with a made three counted as 1.5 makes."),
    ("Turnovers", "Per possession: the offense's committed, the defense's forced."),
    ("Offensive rebounding", "The share of its own misses the offense gets back, against the "
     "share the defense lets its opponents get back."),
    ("Free-throw rate", "Free throws attempted per field-goal attempt: drawn by the offense, "
     "allowed by the defense."),
]


def _v(x):
    return preview_page._v(x)


# --------------------------------------------------------------------------- #
# Names, logos, lines
# --------------------------------------------------------------------------- #

def master_lookup(master: dict) -> dict:
    """{"alias": {code or name: site name}, "logo": {site name: URL}} from
    master.json - the list that names every team on the scoreboard. An alias
    two teams share goes to the first, as cbb.scraper.getNameFromCode
    resolves it (which is how the feed named the team in the first place)."""
    alias, logo = {}, {}
    for key, team in (master.get("team") or {}).items():
        alias.setdefault(team, team)
        for a in (master.get("names") or {}).get(key) or []:
            alias.setdefault(a, team)
        path = (master.get("path") or {}).get(key)
        if path:
            logo[team] = "/assets/images/" + quote(path)
    return {"alias": alias, "logo": logo}


def site_name(trank_name: str, alias: dict) -> str:
    """A T-Rank name as the scoreboard spells it (cbb.constants.TORVIK_RENAMES
    where the two differ)."""
    name = constants.TORVIK_RENAMES.get(trank_name, trank_name)
    return alias.get(name, name)


_LINE = re.compile(r"\s*(\S.*?)\s+([+-]?\d+(?:\.\d+)?|pk|PK|EVEN|even)\s*")


def home_line(text, home: str, away: str, alias: dict) -> float | None:
    """theScore's "DUKE -6.5" as the home side's line (-6.5 for Duke at home,
    +6.5 for Duke away), or None when the code is neither team's."""
    m = _LINE.fullmatch(str(text or ""))
    if not m:
        return None
    code, num = m.groups()
    v = 0.0 if num.lower() in ("pk", "even") else float(num)
    team = alias.get(code)
    if team is not None and team == home:
        return v
    if team is not None and team == away:
        return -v
    return None


# --------------------------------------------------------------------------- #
# The feed's games
# --------------------------------------------------------------------------- #

def state(status) -> str | None:
    """theScore's status as pre / in / post, or None for a game called off
    (render_watch's rule)."""
    s = str(status or "").lower()
    if s in ("final", "closed"):
        return "post"
    if s in ("", "pre_game", "scheduled"):
        return "pre"
    if re.search(r"postpon|cancel|forfeit", s):
        return None
    return "in"


def tournament(g) -> int:
    """2 for the NCAA tournament, 1 for another (a conference's, the NIT, an
    early-season event marked postseason), else 0 - the guide's weights."""
    if g.get("is_mm") is True:
        return 2
    desc, kind = str(g.get("game_description") or ""), str(g.get("game_type") or "")
    if g.get("is_nit") is True or re.search("tournament", desc, re.I) \
            or re.search("postseason", kind, re.I):
        return 1
    return 0


def _days(now) -> list:
    today = pd.Timestamp(now).tz_convert(ET).date() if pd.Timestamp(now).tzinfo \
        else pd.Timestamp(now).date()
    return [(today + timedelta(days=d)).isoformat() for d in (-1, 0, 1)]


def window(feed: dict, now, trank: dict) -> list:
    """[(id, game)] that get a page: men's, yesterday to tomorrow (Eastern),
    not called off, both teams rated by T-Rank (`trank`: {site name: rank}),
    one of them in its top TOP or the game a tournament's."""
    days = set(_days(now))
    out = []
    for gid, g in ((feed or {}).get("men") or {}).items():
        if g.get("date") not in days or state(g.get("status")) is None:
            continue
        hr, ar = trank.get(g.get("home_team")), trank.get(g.get("away_team"))
        if hr is None or ar is None:
            continue
        if min(hr, ar) <= TOP or tournament(g):
            out.append((str(gid), g))
    return sorted(out, key=lambda x: (str(x[1].get("start_time_utc") or "9"), x[0]))


# --------------------------------------------------------------------------- #
# The watch score: the guide's (render_watch's docstring), in Python
# --------------------------------------------------------------------------- #

def watch_score(hm, am, p, top25: bool = False, tour: int = 0) -> tuple:
    """(score, tags) for one game from the two GordStats ranks and our home
    win chance - the formula the watch guide runs in the browser, on its
    constants."""
    def grade(rank):
        r = _v(rank)
        return 100 * 0.5 ** (((r if r else render_watch.UNRANKED) - 1) / render_watch.HALF_LIFE)

    a, b = grade(hm), grade(am)
    strength = 2 * a * b / (a + b)
    close = render_watch.NO_CALL if p is None else 100 * (1 - abs(2 * p - 1))
    s = strength * (0.5 + 0.5 * close / 100)
    tags, lifts = [], 0
    if top25:
        tags.append("Top 25 matchup")
        lifts += 1
    if tour:
        tags.append("Tournament")
        lifts += tour
    at = 1 if top25 else 0
    lo, hi = render_watch.TOSS_UP
    if p is not None and lo <= p <= hi:
        tags.insert(at, "Toss-up")
    elif p is not None and min(p, 1 - p) >= render_watch.UPSET_WATCH:
        tags.insert(at, "Upset watch")
    return round(s + (100 - s) * 0.25 * lifts, 1), tags


# --------------------------------------------------------------------------- #
# Records and form, from the season's results
# --------------------------------------------------------------------------- #

def record_before(log: dict, day: str) -> str:
    """W-L in this season's games before `day` from a team's results
    ({date: {win, score, ...}}), or "" before its first."""
    season = utils.season_year(day)
    w = l = 0
    for d, g in (log or {}).items():
        if d < day and utils.season_year(d) == season and g.get("score") is not None:
            if g.get("win"):
                w += 1
            else:
                l += 1
    return f"{w}-{l}" if w or l else ""


def form(logs: dict, team: str, day: str, table_on, neutral_on=None) -> list:
    """The team's last FORM_GAMES before `day`, newest first, in the shared
    form rows' shape - each with the margin against our line from the table
    published by its own day (none against a team T-Rank does not rate).
    `neutral_on(date, home, away)` says which were tournament games, where the
    scoreboard's call gives no home court."""
    season = utils.season_year(day)
    mine = [(d, g) for d, g in sorted((logs.get(team) or {}).items())
            if d < day and utils.season_year(d) == season and g.get("score") is not None]
    games = []
    for d, g in mine[-FORM_GAMES:]:
        home = g.get("location") != "away"
        h, a = (team, g["opponent"]) if home else (g["opponent"], team)
        hs, as_ = (g["score"], g["opponent_score"]) if home else (g["opponent_score"], g["score"])
        neutral = bool(neutral_on and neutral_on(d, h, a))
        pick = game_model.predict(h, a, table_on(d), neutral=neutral, gender="M")
        games.append({"date": d, "home_id": h, "away_id": a, "home": h, "away": a,
                      "home_score": hs, "away_score": as_, "played": True, "neutral": neutral,
                      "pred_margin": None if not pick else pick["pred_home"] - pick["pred_away"]})
    return preview_page.recent_form(games, team, day, FORM_GAMES)


# --------------------------------------------------------------------------- #
# One game
# --------------------------------------------------------------------------- #

def _team(g, side: str, lk: dict, logs: dict, mm_seed: bool) -> dict:
    name = str(g.get(f"{side}_team") or "TBD")
    rank = _v(g.get(f"{side}_rank"))
    rank = int(rank) if rank and rank > 0 else None
    rec = record_before(logs.get(name), str(g.get("date")))
    conf = str(g.get(f"conference_{side}") or "")
    abbr = str(g.get(f"{side}_abb") or "")
    return {"id": name, "name": name, "abbr": abbr or name,
            "logo": lk["logo"].get(name), "rank": None if mm_seed else rank,
            "rank_text": f"{rank} seed" if mm_seed and rank else "",
            "record": " · ".join(x for x in (rec, conf) if x), "href": None,
            "score": _v(g.get(f"{side}_score"))}


def _status(g, st: str) -> str:
    if st == "post":
        ot = g.get("overtime") is True or "OT" in str(g.get("period") or "")
        return "Final/OT" if ot else "Final"
    if st == "in":
        if "half" in str(g.get("status") or "").lower():
            return "Half"
        return " ".join(str(x) for x in (g.get("period"), g.get("clock")) if x)
    return ""


def _call(g, st: str, table: dict, lk: dict, archive: dict, gid: str, tour: int) -> dict:
    home, away = g.get("home_team"), g.get("away_team")
    neutral = g.get("neutral") is True
    pick = game_model.predict(home, away, table, neutral=neutral, gender="M") or {}
    margin = total = prob = None
    if pick:
        margin = round(pick["pred_home"] - pick["pred_away"], 1)
        total = round(pick["pred_home"] + pick["pred_away"], 1)
        prob = pick["home_win_prob"]
    # Before tip-off the feed's line is the latest; after it, the archive's is
    # the close (cbb.lines keeps only pregame lines), the feed's the fallback.
    kept = archive.get(f"men:{gid}") or {}
    live = (home_line(g.get("spread_close"), home, away, lk["alias"]), _v(g.get("total_close")))
    close = (home_line(kept.get("spread"), home, away, lk["alias"]), _v(kept.get("total")))
    first, second = (live, close) if st == "pre" else (close, live)
    spread = first[0] if first[0] is not None else second[0]
    book_total = first[1] if first[1] is not None else second[1]
    call = {"margin": margin, "prob": prob, "total": total, "spread": spread,
            "book_total": book_total, "book": "Book", "call_min": EDGE, "edge": EDGE,
            "record_url": None, "others": []}
    if st == "pre":
        mm, nit = g.get("is_mm") is True, g.get("is_nit") is True
        # In the NCAA tournament and the NIT theScore's ranking is the seed.
        top25 = not mm and not nit and bool(_v(g.get("home_rank"))) and bool(_v(g.get("away_rank")))
        call["watch"], call["tags"] = watch_score(g.get("home_model"), g.get("away_model"),
                                                  prob, top25, tour)
    return call


def _style(ranks: dict, row: dict) -> str:
    """Pace and the three-point lean - style, not quality, so not on the bars."""
    bits = []
    tempo = ranks.get("tempo")
    if tempo:
        bits.append(f"{tempo[0]:.1f} possessions a game ({ordinal(tempo[1])} fastest)")
    r3 = _v(row.get("r3"))
    if r3 is not None:
        bits.append(f"{r3 * 100:.0f}% of shots from three")
    return " · ".join(bits)


def build(data: dict, now) -> list:
    """The window's games in preview_page's shape. `data` is load()'s."""
    lk = data.get("lookup") or {"alias": {}, "logo": {}}
    trank = data.get("trank") or {}
    ranks, rows = data.get("ranks") or {}, data.get("rows") or {}
    logs = data.get("logs") or {}
    table_on = data.get("table_on") or (lambda day: {})
    neutral_on = data.get("neutral_on")
    tv = data.get("tv") or {}
    archive = data.get("lines") or {}
    played = data.get("played", True)
    out = []
    for gid, g in window(data.get("feed"), now, trank):
        st = state(g.get("status"))
        day = str(g["date"])
        tour = tournament(g)
        seeded = g.get("is_mm") is True or g.get("is_nit") is True
        away, home = _team(g, "away", lk, logs, seeded), _team(g, "home", lk, logs, seeded)
        aid, hid = away["id"], home["id"]
        ko = g.get("start_time_utc")
        desc = str(g.get("game_description") or "")
        out.append({
            "sport": SPORT, "id": gid, "label": "",
            "state": st, "status": _status(g, st),
            "ko": pd.Timestamp(ko) if ko else None, "tk": bool(ko),
            "tv": tv.get(gid, ""), "venue": str(g.get("venue") or ""),
            "place": str(g.get("location") or ""),
            "note": desc.replace(" | ", " · ") if tour else "",
            "neutral": g.get("neutral") is True, "weather": None,
            "away": away, "home": home,
            "call": _call(g, st, table_on(day), lk, archive, gid, tour),
            "units": {"away": preview_page.pair_units(UNITS, ranks.get(aid), ranks.get(hid)),
                      "home": preview_page.pair_units(UNITS, ranks.get(hid), ranks.get(aid))},
            "style": {side: _style(ranks.get(t["id"]) or {}, rows.get(t["id"]) or {})
                      for side, t in (("away", away), ("home", home))},
            "players": {},
            "form": {side: form(logs, t["id"], day, table_on, neutral_on)
                     for side, t in (("away", away), ("home", home))},
            "words": {"off": "offense", "def": "defense"},
            "schedule": None,
            "links": [("Scores", "/men/"), ("Watch Guide", "/cbb/watch/"),
                      ("Rankings", "/cbb/power/")],
            "notes": NOTES,
            "source": ("Bart Torvik's adjusted figures, ranked across Division I"
                       + ("." if played else " - his preseason projections until games are "
                          "played.")),
            "stats": "/cbb/stats/",
        })
    return out


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #

def feed() -> dict:
    """The scoreboard Worker's leagues ({men: {id: game}, women: ...}) and
    when it was pushed. Raises when it cannot be read."""
    import requests
    r = requests.get(render_watch.FEED, timeout=20)
    r.raise_for_status()
    data = r.json()
    return {"leagues": data.get("leagues") or {}, "generated": data.get("generated")}


def tv(ids: list) -> dict:
    """{id: "ESPN2, ESPN+"} from theScore's US listings, a batch of events at
    a time; whatever it could not read is left out."""
    import requests
    out = {}
    for i in range(0, len(ids), 120):
        try:
            r = requests.get(SCORE_EVENTS, params={"id.in": ",".join(ids[i:i + 120])},
                             headers=SCORE_HEADERS, timeout=15)
            r.raise_for_status()
            events = r.json()
        except Exception as exc:                # noqa: BLE001 - a page stands without TV
            print(f"  ! CBB previews: no TV listings ({exc})")
            continue
        for e in events or []:
            us = ((e.get("tv_listings_by_country_code") or {}).get("us")) or []
            names = list(dict.fromkeys(x.get("short_name") or x.get("long_name") or ""
                                       for x in us))
            names = [n for n in names if n][:2]
            if names and e.get("id") is not None:
                out[str(e["id"])] = ", ".join(names)
    return out


def tables(folder=paths.M_TOR_DIR):
    """table_on(day): cbb.game_model.ratings() of the newest Torvik table in
    `folder` dated on or before `day` in its season - what the scoreboard's
    call used that day (game_model.today_table) - else T-Rank's own table
    (its preseason projections) while it is that season's."""
    files = []
    for f in sorted(folder.glob("*.json")):
        try:
            files.append((f.stem, utils.season_year(f.stem), f))
        except ValueError:
            continue
    cache = {}

    def table_on(day: str) -> dict:
        season = utils.season_year(day)
        pick = None
        for stem, year, f in files:
            if year == season and stem <= day:
                pick = f
        key = str(pick) if pick else f"trank:{season}"
        if key not in cache:
            if pick:
                cache[key] = game_model.ratings(json.loads(pick.read_text(encoding="utf-8")))
            else:
                from datetime import date
                cache[key] = game_model.trank_table(date.fromisoformat(day))
        return cache[key]
    return table_on


def neutral_sites(archive: dict):
    """neutral_on(date, home, away) from the lines archive: a tournament game,
    which the scoreboard calls without home court. False for a game it does
    not hold."""
    tour = set()
    for row in (archive or {}).values():
        desc = str(row.get("game_description") or "")
        # cbb.live_scraper.format_event's rule for the call's neutral floor.
        if row.get("league") == "men" and ("Tournament" in desc or "NIT" in desc):
            tour.add((row.get("date"), row.get("home_team"), row.get("away_team")))
    return lambda d, h, a: (d, h, a) in tour


def _lines(season: int) -> dict:
    """The lines archive, the live file over the committed record."""
    from cbb import lines
    out = lines._load(lines._path(lines.RECORD_DIR, season))
    out.update(lines._load(lines._path(lines.LIVE_DIR, season)))
    return out


def load(now, got: dict) -> dict:
    """Everything build() reads, around the feed (`got`, feed()'s): the
    caches the daily run has just filled, and TV for the window's games."""
    from cbb.render import render_power, render_stats

    master = json.loads(paths.MASTER_DICT.read_text(encoding="utf-8"))
    lk = master_lookup(master)
    df = render_power.trank()
    trank = {site_name(str(t), lk["alias"]): int(r) for t, r in zip(df["team"], df["rank"])}
    data = {"feed": got["leagues"], "generated": got["generated"], "lookup": lk, "trank": trank}
    games = window(got["leagues"], now, trank)
    if not games:
        return data
    ff = render_stats.four_factors()
    rows = []
    for r in render_stats.rows(df, ff):
        rows.append({**r, "id": site_name(r["name"], lk["alias"])})
    try:
        logs = json.loads(paths.M_SCHEDULE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logs = {}
    season = utils.season_year(pd.Timestamp(now).tz_convert(ET).date().isoformat())
    archive = _lines(season)
    data.update({
        "ranks": preview_page.rank_table(rows, BETTER), "rows": {r["id"]: r for r in rows},
        "played": df["record"].astype(str).str.split("-").str[0].astype(int).sum() > 0,
        "logs": logs, "table_on": tables(), "lines": archive,
        "neutral_on": neutral_sites(archive), "tv": tv([gid for gid, _g in games]),
    })
    return data


def generate(now=None) -> list:
    """Write the window's previews and remove the rest; returns the ids written."""
    now = pd.Timestamp(now) if now is not None else pd.Timestamp(datetime.now(timezone.utc))
    if now.tzinfo is None:
        now = now.tz_localize(ET)
    import requests
    try:
        got = feed()
    except (requests.RequestException, ValueError) as exc:
        print(f"CBB previews: the scoreboard feed did not load ({exc}); "
              "nothing written, nothing removed")
        return []
    data = load(now, got)
    games = build(data, now)
    for g in games:
        kick = pd.Timestamp(g["ko"]).tz_convert(ET) if g.get("ko") is not None else None
        when = f", {kick:%a %b %-d}" if kick is not None else ""
        preview_page.write(
            g, subtitle="Men's college basketball preview",
            description=(f"{preview_page.title(g)}{when}: GordStats' pick against the line, "
                         "and how the offenses and defenses match up."))
    removed = preview_page.prune(SPORT, {g["id"] for g in games})
    tail = f"; removed {len(removed)} old" if removed else ""
    if not games:
        days = _days(now)
        pushed = str(data.get("generated") or "?")[:10]
        print(f"CBB previews: no men's games from {days[0]} to {days[-1]} in the scoreboard "
              f"feed (pushed {pushed}); nothing written{tail}")
        return []
    print(f"Wrote {len(games)} CBB game previews -> {preview_page.out_dir(SPORT)}{tail}")
    return [g["id"] for g in games]


if __name__ == "__main__":
    generate()
