"""
Weekly recap for the NFL league (docs/fantasy/recap/): each finished week's
scores, awards and lineup accuracy - gordstats.recap over the Sleeper week
archive (fantasy.league.matchups), which the matchups step has just refreshed.

A week is written once it is final (every NFL game over, every side scored),
so the first recap of a week lands with the build after Monday night's game.
/fantasy/recap/ is the newest week; /fantasy/recap/week-N/ is the link to send.

    python -m fantasy.site.recap
"""
from html import escape

import pandas as pd

from fantasy import paths, pregame
from fantasy.config import UPCOMING_YEAR
from fantasy.league import matchups as data_mod
from fantasy.site import layout
from fantasy.site import matchups as mu
from gordstats import pregame as frozen, recap
from gordstats.frontmatter import add_front_matter

BASE = "/fantasy/recap/"
OUT = paths.WEB_FANTASY_DIR / "recap"
# The flex slots the matchups page's best_lineup fills, and who may fill them.
FLEX = {"FLEX": data_mod.FLEX_POSITIONS}


def _season_key(year: int) -> str:
    return f"{str(year)[2:]}{str(year + 1)[2:]}"


_MOVE_COLS = ["week", "pid", "roster_id", "kind"]


def _adds(year: int) -> pd.DataFrame:
    """Every completed player add: [week, pid, roster_id, kind], kind "claim"
    (waiver or free agent) or "trade". `week` is Sleeper's `leg`: the week in
    force when the move was made, which for a Tuesday waiver claim is the week
    *before* the one he was claimed for - so it only places moves roughly;
    build_week works from the rosters themselves."""
    path = paths.DATA_DIR / "transactions" / f"{_season_key(year)}.json"
    if not path.exists():
        return pd.DataFrame(columns=_MOVE_COLS)
    tx = pd.read_json(path, dtype={"transaction_id": str})
    tx = tx[tx["type"].isin(["waiver", "free_agent", "trade"]) & tx["status"].eq("complete")]
    rows = [{"week": int(t.leg), "pid": str(pid), "roster_id": str(rid),
             "kind": "trade" if t.type == "trade" else "claim"}
            for t in tx.itertuples(index=False) for pid, rid in (t.adds or {}).items()]
    return pd.DataFrame(rows, columns=_MOVE_COLS)


def roster_ids(d: dict) -> dict:
    """{roster_id: every player id on the roster that week, IR included}."""
    return {str(s["roster_id"]): {str(p) for p in s.get("players") or []}
            for m in d.get("matchups") or [] for s in m["sides"]}


def _power(year: int) -> dict:
    """{week: {roster_id: rank}} - the published order at the last snapshot
    taken with that many weeks played; week 0 is preseason."""
    from fantasy.league import power
    out = {}
    pre = power._history_dir(year) / "preseason.parquet"
    if pre.exists():
        out[0] = power._rank_by_rating(pd.read_parquet(pre))
    for _, path in power._snapshots(year):
        frame = pd.read_parquet(path)
        if "week" in frame and len(frame):
            out[int(frame["week"].iloc[0])] = power._rank_by_rating(frame)
    return {w: {str(k): int(v) for k, v in r.items()} for w, r in out.items()}


def build_week(d: dict, slots: list, cards: dict, gs: dict, adds: pd.DataFrame,
               ranks: dict, prev: dict | None = None, playoff_start: int = 0) -> recap.Week:
    """One archived week as a recap.Week. `prev` is roster_ids() of the week
    before (None for week 1); `playoff_start` the league's first playoff week,
    from which there is no median game."""
    week = int(d["week"])
    teams = {str(k): recap.Team(t.get("name") or f"Team {k}", t.get("manager") or "",
                                t.get("avatar") or "")
             for k, t in (d.get("teams") or {}).items()}
    sides, games = {}, []
    for m in d.get("matchups") or []:
        if m.get("matchup_id") is None:
            continue                    # a playoff bye: no game, nothing to award
        keys = []
        for s in m["sides"]:
            key = str(s["roster_id"])
            reserve = (d.get("teams") or {}).get(key, {}).get("reserve") or []
            rows = mu.roster_rows(s, reserve, slots)
            pts = {str(p): float(v or 0) for p, v in (s.get("players_points") or {}).items()}

            def player(r, started):
                c = cards.get(r["pid"]) or {}
                return recap.Player(r["pid"], c.get("name") or r["pid"], c.get("pos") or "",
                                    pts.get(r["pid"], 0.0), r["slot"] if started else "")
            starters = [player(r, True) for r in rows
                        if r["slot"] not in ("BN", "IR") and r["pid"] != "0"]
            bench = [player(r, False) for r in rows if r["slot"] == "BN"]
            # Only an honest projection: every starter's number from before his
            # kickoff, or none - the archive began part-way through week 3.
            proj = (round(sum(gs[p.id] for p in starters), 2)
                    if starters and all(p.id in gs for p in starters) else None)
            sides[key] = recap.Side(key, float(s.get("points") or 0), starters, bench,
                                    mu.best_lineup(rows, cards, pts, slots), proj)
            keys.append(key)
        if len(keys) == 2:
            games.append(tuple(keys))
    # A pickup is a player on this week's roster who was not on it last week
    # and did not come in a trade - read off the rosters, because Sleeper's
    # `leg` files a Tuesday claim under the week before the one it was for
    # (the audit: week 2 missed two defenses that were started, and week 1
    # credited one claimed in August). Week 1 has no week before: its
    # pickups are the claims made since the draft.
    traded = {(a.roster_id, a.pid) for a in adds.itertuples(index=False)
              if a.kind == "trade" and week - 1 <= a.week <= week}
    pickups = []
    for key, side in sides.items():
        if prev is not None:
            new = {p.id for p in side.starters + side.bench
                   if p.id not in prev.get(key, set()) and (key, p.id) not in traded}
        else:
            new = {a.pid for a in adds.itertuples(index=False)
                   if a.kind == "claim" and a.roster_id == key and a.week <= week}
        on = {p.id for p in side.starters}
        pickups += [recap.Pickup(key, p, p.id in on) for p in side.starters + side.bench
                    if p.id in new]
    before, after = ranks.get(week - 1) or {}, ranks.get(week) or {}
    power = {k: (before[k], after[k]) for k in sides if k in before and k in after}
    # Sleeper plays the median in the regular season only.
    median = not playoff_start or week < playoff_start
    return recap.Week(week, teams, games, sides, median=median, flex=FLEX,
                      pickups=pickups, power=power)


def weeks(lg: dict, year: int = UPCOMING_YEAR) -> list:
    """Every final week of the season as a recap.Week, oldest first."""
    datas = [data_mod.week_matchups(w, year) for w in data_mod.archived_weeks(year)]
    datas = [d for d in datas if data_mod.week_final(d)]
    if not datas:
        return []
    slots = lg["roster_positions"] or mu.ctx_slots({})
    board = mu._board([], {})
    board = {str(r.sleeper_id): {"player": r.player, "pos": r.pos, "team": r.team}
             for r in board.drop_duplicates("sleeper_id").itertuples(index=False)}
    registry = mu._registry()
    adds, ranks = _adds(year), _power(year)
    by_week = {int(d["week"]): d for d in datas}
    out = []
    for d in datas:
        cards = {str(p): mu.player_card(str(p), d, board, registry)
                 for m in d["matchups"] for s in m["sides"] for p in s["players"]}
        gs = frozen.load(pregame.path(d["week"], year))
        before = by_week.get(int(d["week"]) - 1)
        out.append(build_week(d, slots, cards, gs, adds, ranks,
                              prev=roster_ids(before) if before else None,
                              playoff_start=int(lg.get("playoff_week_start") or 0)))
    return out


def _write(path, week: recap.Week, all_weeks: list, league_name: str) -> None:
    links = ('<p class="rc-note"><a href="/fantasy/matchups/">Every roster, player by player '
             '&rarr;</a></p>')
    html = add_front_matter(layout.HEAD + recap.page(week, all_weeks, BASE, links),
                            f"NFL Week {week.number} Recap", escape(league_name),
                            description=recap.headline(week))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def generate() -> None:
    lg = data_mod.league()
    all_weeks = weeks(lg)
    OUT.mkdir(parents=True, exist_ok=True)
    if not all_weeks:
        (OUT / "index.html").write_text(add_front_matter(
            layout.HEAD + "<p>The first recap is written once week 1 is over - after "
            "Monday night's game.</p>", "NFL Weekly Recap"), encoding="utf-8")
        recap.write_latest(OUT, None)
        print("Wrote Weekly Recap (no final week yet)")
        return
    name = lg.get("name") or ""
    for w in all_weeks:
        _write(OUT / f"week-{w.number}" / "index.html", w, all_weeks, name)
    _write(OUT / "index.html", all_weeks[-1], all_weeks, name)
    recap.write_latest(OUT, all_weeks[-1])
    print(f"Wrote Weekly Recap, weeks {all_weeks[0].number}-{all_weeks[-1].number} -> {OUT}")



def teaser() -> str:
    """League Home's and Matchups' pointer to the newest recap."""
    return recap.teaser(OUT, BASE)


if __name__ == "__main__":
    generate()
