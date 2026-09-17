"""
The lineup a roster should set this week, and the order to set it in.

Two questions, answered separately because they are separate:

  * Who starts. The best projection at each dedicated slot, then the flex
    slots to the best skill players left - cfb.site.matchups.best_lineup's
    rule, except that a player whose game has kicked off is locked where he
    sits: a starter stays a starter, a bench player cannot come in.

  * Which slot each starter goes in. Yahoo locks a player at his own kickoff,
    so the slot a late player occupies is the slot that is still open when
    news breaks. A flex slot takes any back, receiver or tight end; a
    dedicated slot takes one position. So among the starters at a position the
    earliest kickoffs take the dedicated slots and the latest ones go to the
    flex - if Saturday night's receiver is scratched at 9pm, the hole is a flex
    and anyone left on the bench can fill it. How many of a position sit in
    the flex is fixed by who starts; only *which* of them is free, and that is
    the choice made here.

`cover` names the best bench player who could still step into each starter's
slot: eligible for it, projected to score, and not kicking off before the
starter does.

    python -m cfb.lineup
"""
import pandas as pd

from cfb import projections

BENCH = {"BN", "IL", "IR"}
RESERVE = {"IL", "IR"}
FLEX = projections.FLEX_SLOT
FLEX_POSITIONS = set(projections.FLEX_POSITIONS)
_FAR = pd.Timestamp("2100-01-01", tz="UTC")


def _kick(value):
    """A kickoff as a sortable timestamp; a bye or an unknown game sorts last,
    which is also the right place for it - it locks nothing."""
    if value is None or pd.isna(value):
        return _FAR
    return pd.Timestamp(value)


def _points(value) -> float:
    return 0.0 if value is None or pd.isna(value) else float(value)


def plan(players: list, roster_slots: list, proj: dict, kickoff: dict, locked: set) -> dict:
    """The recommended lineup for one roster.

    players       the week archive's roster rows (yahoo_id, pos, slot, status)
    roster_slots  the league's [{position, count}]
    proj          {yahoo_id: projected points}; missing counts as zero
    kickoff       {yahoo_id: kickoff timestamp}; missing is a bye
    locked        yahoo_ids whose game has started - they stay where they are

    Returns {"slot": {yahoo_id: recommended slot}, "start": set of starters,
    "cover": {yahoo_id: [bench yahoo_ids that could replace him, best first]}}.
    """
    value = {p["yahoo_id"]: _points(proj.get(p["yahoo_id"])) for p in players}
    by_id = {p["yahoo_id"]: p for p in players}
    open_slots = {s["position"]: int(s["count"]) for s in roster_slots
                  if s["position"] not in BENCH}
    slot, pool = {}, []
    for p in players:
        pid = p["yahoo_id"]
        if pid in locked:
            slot[pid] = p["slot"]
            if p["slot"] in open_slots:
                open_slots[p["slot"]] -= 1
        elif p["slot"] in RESERVE:
            slot[pid] = p["slot"]                     # on the injured list: not available
        else:
            pool.append(pid)

    # Who starts: dedicated slots by projection, then the flex.
    ranked = {}
    for pid in sorted(pool, key=lambda i: -value[i]):
        ranked.setdefault(by_id[pid]["pos"], []).append(pid)
    chosen = {}
    for pos, n in open_slots.items():
        if pos != FLEX:
            chosen[pos] = ranked.get(pos, [])[:max(n, 0)]
    flex = []
    for _ in range(max(open_slots.get(FLEX, 0), 0)):
        best = None
        for pos in FLEX_POSITIONS:
            rest = ranked.get(pos, [])[len(chosen.get(pos, [])):]
            rest = [i for i in rest if i not in flex]
            if rest and (best is None or value[rest[0]] > value[best]):
                best = rest[0]
        if best is None:
            break
        flex.append(best)

    # Which slot: pool a position's starters, latest kickoffs to the flex.
    for pos in set(chosen) | {by_id[i]["pos"] for i in flex}:
        group = chosen.get(pos, []) + [i for i in flex if by_id[i]["pos"] == pos]
        n_flex = sum(1 for i in flex if by_id[i]["pos"] == pos)
        # Latest first; between equal kickoffs the weaker projection takes the
        # flex (he is the likelier swap), and a player already there stays.
        order = sorted(group, key=lambda i: (-_kick(kickoff.get(i)).value, value[i],
                                             by_id[i]["slot"] != FLEX))
        for n, pid in enumerate(order):
            slot[pid] = FLEX if n < n_flex else pos
    for pid in pool:
        slot.setdefault(pid, "BN")

    start = {pid for pid, s in slot.items() if s not in BENCH}
    bench = [pid for pid in pool if slot[pid] == "BN"]
    cover = {}
    for pid in start:
        if pid in locked:
            continue
        mine = by_id[pid]
        ok = [b for b in bench
              if value[b] > 0 and (by_id[b]["pos"] == mine["pos"]
                  or (slot[pid] == FLEX and by_id[b]["pos"] in FLEX_POSITIONS))
              and kickoff.get(b) is not None and not pd.isna(kickoff.get(b))
              and _kick(kickoff.get(b)) >= _kick(kickoff.get(pid))]
        cover[pid] = sorted(ok, key=lambda i: -value[i])
    return {"slot": slot, "start": start, "cover": cover}


def total(players: list, slots: dict, proj: dict) -> float:
    """Projected points of whoever `slots` starts."""
    return sum(_points(proj.get(p["yahoo_id"])) for p in players
               if slots.get(p["yahoo_id"], "BN") not in BENCH)


if __name__ == "__main__":
    from cfb import predict, weekly, yahoo
    from cfb.config import MY_TEAM

    lg = yahoo.league()
    data = yahoo.week_matchups(yahoo.archived_weeks()[-1])
    frame, _m, _n = predict.season()
    wk = weekly.week_projections(data["week_start"], data["week_end"], league=lg, frame=frame)
    key = next(t["team_key"] for t in lg["teams"] if t["name"] == MY_TEAM)
    roster = data["rosters"][key]
    ids = [p["yahoo_id"] for p in roster if p["yahoo_id"] in wk.index]
    proj = {i: wk.loc[i, "proj_week"] for i in ids}
    kick = {i: wk.loc[i, "kickoff"] for i in ids}
    locked = {i for i in ids if wk.loc[i, "state"] in ("in", "post")}
    got = plan(roster, lg["roster"], proj, kick, locked)
    for p in sorted(roster, key=lambda p: got["slot"][p["yahoo_id"]]):
        pid = p["yahoo_id"]
        print(f"{got['slot'][pid]:6s} (now {p['slot']:6s}) {p['player']:24s} {p['pos']:3s} "
              f"{proj.get(pid, 0) or 0:5.1f}  {kick.get(pid)}")
