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


def _power(start: str, end: str) -> dict:
    """{team_key: (rank before, rank after)} from the league power archive:
    the last snapshot before the week's Thursday, and the last one after its
    Saturday but before the next Thursday - no games in either."""
    snaps = rankmoves._snaps(HISTORY_DIR)
    before = [p for t, p in snaps if t < _day(start) + timedelta(days=4)]
    after = [p for t, p in snaps
             if _day(end) + timedelta(days=1) <= t < _day(end) + timedelta(days=5)]
    if not before or not after:
        return {}
    a, b = rankmoves._load(before[-1]), rankmoves._load(after[-1])
    return {k: (int(a[k]), int(b[k])) for k in b.index if k in a.index}


def _adds(tx: list, start: str, end: str, names: dict) -> list:
    """[(team_key, player name, school)] added during the week (Sunday to
    Saturday, Eastern). Yahoo files a move by the team's name, not its key."""
    lo, hi = _day(start), _day(end) + timedelta(days=1)
    out = []
    for t in tx:
        if t.get("status") != "successful" or not t.get("timestamp"):
            continue
        when = datetime.fromtimestamp(t["timestamp"], ET).replace(tzinfo=None)
        if not lo <= when < hi:
            continue
        for p in t.get("players") or []:
            key = names.get(p.get("destination"))
            if p.get("type") == "add" and key:
                out.append((key, p.get("player"), p.get("team")))
    return out


def build_week(d: dict, lg: dict, gs: dict, tx: list, power: dict) -> recap.Week:
    """One archived week as a recap.Week."""
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
    names = {t.name: k for k, t in teams.items()}
    pickups = []
    for key, name, school in _adds(tx, d["week_start"], d["week_end"], names):
        side = sides.get(key)
        hit = side and next((p for p in side.starters + side.bench if p.name == name), None)
        if hit:
            pickups.append(recap.Pickup(key, hit, hit in side.starters))
    return recap.Week(int(d["week"]), teams, games, sides,
                      median=bool(lg.get("uses_median_score")), flex=FLEX,
                      pickups=pickups, power=power)


def weeks() -> list:
    """Every final week of the season as a recap.Week, oldest first."""
    datas = [yahoo.week_matchups(w) for w in yahoo.archived_weeks()]
    datas = [d for d in datas if yahoo.week_final(d)]
    if not datas:
        return []
    lg = yahoo.league()
    tx = yahoo.transactions()
    return [build_week(d, lg, frozen.load(pregame.path(d["week"])), tx,
                       _power(d["week_start"], d["week_end"])) for d in datas]


def _write(path, week: recap.Week, all_weeks: list, league_name: str) -> None:
    links = ('<p class="rc-note"><a href="/cfb/matchups/">Every roster, player by player '
             '&rarr;</a></p>')
    html = add_front_matter(recap.page(week, all_weeks, BASE, links),
                            f"Week {week.number} Recap", league_name,
                            description=recap.headline(week))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def generate() -> None:
    all_weeks = weeks()
    OUT.mkdir(parents=True, exist_ok=True)
    if not all_weeks:
        (OUT / "index.html").write_text(add_front_matter(
            "<p>The first recap is written once week 1 is final.</p>", "Weekly Recap"),
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
