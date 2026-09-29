"""
Weekly recap for the college league (docs/cfb/recap/): each finished week's
scores, awards and lineup accuracy - gordstats.recap over the Yahoo week
archive (cfb.yahoo.week_matchups), the twin of fantasy.site.recap.

A week is written once Yahoo marks every matchup in it final (the Sunday after
Saturday's games). /cfb/recap/ is the newest week; /cfb/recap/week-N/ is the
link to send.

    python -m cfb.site.recap
"""
from datetime import datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

from cfb import pregame, projections, yahoo
from cfb.config import SEASON, WEB_DIR
from cfb.site.matchups import best_lineup
from cfb.site.league_power import HISTORY_DIR
from gordstats import pregame as frozen, rankmoves, recap
from gordstats.frontmatter import add_front_matter

BASE = "/cfb/recap/"
OUT = WEB_DIR / "recap"
FLEX = {projections.FLEX_SLOT: tuple(projections.FLEX_POSITIONS)}
# Not in a lineup: the bench, and the injured list nobody can start from.
BENCH, RESERVE = {"BN"}, {"IL", "IR"}
ET = ZoneInfo("America/New_York")


def _day(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d")


def _after(end: str):
    """The first league power snapshot once a week is over: the morning after
    its last day (Yahoo's weeks are not Sunday-Saturday - week 1 ran Thursday
    to Monday, week 2 Tuesday to Saturday)."""
    cut = _day(end) + timedelta(days=1, hours=3)
    return next((p for t, p in rankmoves._snaps(HISTORY_DIR) if t >= cut), None)


def _header(path) -> str:
    with open(path, encoding="utf-8") as f:
        return f.readline().strip()


def _power(start: str, end: str, prev_end: str | None = None) -> dict:
    """{team_key: (rank before, rank after)}: after the week before (or, for
    the first week, the last snapshot before it began) against after this one."""
    if prev_end:
        before = _after(prev_end)
    else:
        earlier = [p for t, p in rankmoves._snaps(HISTORY_DIR) if t < _day(start)]
        before = earlier[-1] if earlier else None
    after = _after(end)
    if before is None or after is None or before == after:
        return {}
    # The ranking itself has changed method twice (rank alone, then season
    # lineup value, then points a week - see a file's header): a move across a
    # change is the method's, not the team's.
    if _header(before) != _header(after):
        return {}
    a, b = rankmoves._load(before), rankmoves._load(after)
    return {k: (int(a[k]), int(b[k])) for k in b.index if k in a.index}


def _moves(tx: list, lo: datetime, hi: datetime, names: dict, kind: str) -> set:
    """{(team_key, player name)} for Yahoo moves of `kind` ("add" or "trade")
    made between lo and hi (Eastern). Yahoo files a move by the team's name."""
    out = set()
    for t in tx:
        if t.get("status") != "successful" or not t.get("timestamp"):
            continue
        when = datetime.fromtimestamp(t["timestamp"], ET).replace(tzinfo=None)
        if not lo <= when < hi:
            continue
        for p in t.get("players") or []:
            key = names.get(p.get("destination"))
            if key and (p.get("type") == kind or (kind == "trade" and t.get("type") == "trade")):
                out.add((key, p.get("player")))
    return out


def build_week(d: dict, lg: dict, gs: dict, tx: list, power: dict,
               prev: dict | None = None) -> recap.Week:
    """One archived week as a recap.Week; `prev` is the week before's archive
    (None for the first week)."""
    teams = {t["team_key"]: recap.Team(t.get("name") or t["team_key"], t.get("manager") or "",
                                       t.get("logo") or "")
             for t in lg.get("teams") or []}
    sides, games = {}, []
    for m in d.get("matchups") or []:
        keys = []
        for t in m.get("teams") or []:
            key = t["team_key"]
            teams.setdefault(key, recap.Team(t.get("name") or key))
            roster = (d.get("rosters") or {}).get(key) or []
            pts = {p["yahoo_id"]: float(p.get("points") or 0) for p in roster}

            def player(p, started):
                return recap.Player(p["yahoo_id"], p.get("player") or "", p.get("pos") or "",
                                    pts[p["yahoo_id"]], p["slot"] if started else "")
            starters = [player(p, True) for p in roster if p.get("slot") not in BENCH | RESERVE]
            bench = [player(p, False) for p in roster if p.get("slot") in BENCH]
            proj = (round(sum(gs[p.id] for p in starters), 2)
                    if starters and all(p.id in gs for p in starters) else None)
            sides[key] = recap.Side(key, float(t.get("points") or 0), starters, bench,
                                    best_lineup(roster, lg, pts), proj)
            keys.append(key)
        if len(keys) == 2:
            games.append(tuple(keys))
    # A pickup is a player on this week's roster who was not on last week's
    # and did not come in a trade; the first week's are the adds since the draft.
    names = {t.name: k for k, t in teams.items()}
    end = _day(d["week_end"]) + timedelta(days=1)
    pickups = []
    if prev is not None:
        had = {k: {p["yahoo_id"] for p in r} for k, r in (prev.get("rosters") or {}).items()}
        traded = _moves(tx, _day(prev["week_start"]), end, names, "trade")
        for key, side in sides.items():
            for p in side.starters + side.bench:
                if p.id not in had.get(key, set()) and (key, p.name) not in traded:
                    pickups.append(recap.Pickup(key, p, p in side.starters))
    else:
        added = _moves(tx, datetime(1970, 1, 1), end, names, "add")
        for key, side in sides.items():
            for p in side.starters + side.bench:
                if (key, p.name) in added:
                    pickups.append(recap.Pickup(key, p, p in side.starters))
    # Yahoo plays the median in the regular season only.
    median = bool(lg.get("uses_median_score")) and not d.get("is_playoffs")
    return recap.Week(int(d["week"]), teams, games, sides, median=median, flex=FLEX,
                      pickups=pickups, power=power)


def weeks() -> list:
    """Every final week of the season as a recap.Week, oldest first."""
    datas = [yahoo.week_matchups(w) for w in yahoo.archived_weeks()]
    datas = [d for d in datas if yahoo.week_final(d)]
    if not datas:
        return []
    lg = yahoo.league()
    tx = yahoo.transactions()
    by_week = {int(d["week"]): d for d in datas}
    out = []
    for d in datas:
        prev = by_week.get(int(d["week"]) - 1)
        out.append(build_week(d, lg, frozen.load(pregame.path(d["week"])), tx,
                              _power(d["week_start"], d["week_end"],
                                     prev["week_end"] if prev else None), prev))
    return out


def _write(path, week: recap.Week, all_weeks: list, league_name: str) -> None:
    links = ('<p class="rc-note"><a href="/cfb/matchups/">Every roster, player by player '
             '&rarr;</a></p>')
    html = add_front_matter(recap.page(week, all_weeks, BASE, links),
                            f"CFB Week {week.number} Recap", escape(league_name),
                            description=recap.headline(week),
                            image=recap.card(week, "cfb-recap", "CFB Fantasy", league_name))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def generate() -> None:
    all_weeks = weeks()
    OUT.mkdir(parents=True, exist_ok=True)
    if not all_weeks:
        (OUT / "index.html").write_text(add_front_matter(
            "<p>The first recap is written once week 1 is final.</p>", "CFB Weekly Recap"),
            encoding="utf-8")
        recap.write_latest(OUT, None)
        print("Wrote CFB Weekly Recap (no final week yet)")
        return
    name = yahoo.league().get("name") or ""
    for w in all_weeks:
        _write(OUT / f"week-{w.number}" / "index.html", w, all_weeks, name)
    _write(OUT / "index.html", all_weeks[-1], all_weeks, name)
    recap.write_latest(OUT, all_weeks[-1])
    print(f"Wrote CFB Weekly Recap, weeks {all_weeks[0].number}-{all_weeks[-1].number} -> {OUT}")



def teaser() -> str:
    """League Home's and Matchups' pointer to the newest recap."""
    return recap.teaser(OUT, BASE)


if __name__ == "__main__":
    generate()
