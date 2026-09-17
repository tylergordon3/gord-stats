"""
The lineup a roster should set this week, and the order to set it in.

Two questions, answered separately because they are separate:

  * Who starts. The best projection at each dedicated slot, then the flex
    slots to the best skill players left - the matchup pages' best_lineup rule, except that a player whose game has kicked off is locked where he
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

Shared by both fantasy sections: the college league's Yahoo slots (W/R/T)
and the NFL league's Sleeper slots (FLEX) differ only in names, which the
caller passes in.
"""
import pandas as pd

_FAR = pd.Timestamp("2100-01-01", tz="UTC")


def _kick(value):
    """A kickoff as a sortable timestamp; a bye or an unknown game sorts last,
    which is also the right place for it - it locks nothing."""
    if value is None or pd.isna(value):
        return _FAR
    return pd.Timestamp(value)


def _points(value) -> float:
    return 0.0 if value is None or pd.isna(value) else float(value)


def plan(players: list, slot_counts: dict, proj: dict, kickoff: dict, locked: set,
         flex: str, flex_positions, bench: str = "BN", reserve=("IL", "IR")) -> dict:
    """The recommended lineup for one roster.

    players        [{"id", "pos", "slot"}] - where each player sits now
    slot_counts    {starting slot: how many}, the flex included
    proj           {id: projected points}; missing counts as zero
    kickoff        {id: kickoff timestamp}; missing is a bye
    locked         ids whose game has started - they stay where they are
    flex           the flex slot's name, and `flex_positions` who may fill it
    bench/reserve  the bench slot's name, and the slots nobody can start from

    Returns {"slot": {id: recommended slot}, "start": set of starters,
    "cover": {id: [bench ids that could replace him, best first]}}.
    """
    flex_positions = set(flex_positions)
    value = {p["id"]: _points(proj.get(p["id"])) for p in players}
    by_id = {p["id"]: p for p in players}
    open_slots = dict(slot_counts)
    slot, pool = {}, []
    for p in players:
        pid = p["id"]
        if pid in locked:
            slot[pid] = p["slot"]
            if p["slot"] in open_slots:
                open_slots[p["slot"]] -= 1
        elif p["slot"] in reserve:
            slot[pid] = p["slot"]                     # on the injured list: not available
        else:
            pool.append(pid)

    # Who starts: dedicated slots by projection, then the flex.
    ranked = {}
    for pid in sorted(pool, key=lambda i: -value[i]):
        ranked.setdefault(by_id[pid]["pos"], []).append(pid)
    chosen = {}
    for pos, n in open_slots.items():
        if pos != flex:
            chosen[pos] = ranked.get(pos, [])[:max(n, 0)]
    flexed = []
    for _ in range(max(open_slots.get(flex, 0), 0)):
        best = None
        for pos in flex_positions:
            rest = ranked.get(pos, [])[len(chosen.get(pos, [])):]
            rest = [i for i in rest if i not in flexed]
            if rest and (best is None or value[rest[0]] > value[best]):
                best = rest[0]
        if best is None:
            break
        flexed.append(best)

    # Which slot: pool a position's starters, latest kickoffs to the flex.
    for pos in set(chosen) | {by_id[i]["pos"] for i in flexed}:
        group = chosen.get(pos, []) + [i for i in flexed if by_id[i]["pos"] == pos]
        n_flex = sum(1 for i in flexed if by_id[i]["pos"] == pos)
        # Latest first. Between equal kickoffs whoever is already in the flex
        # stays - moving him buys nothing - and after that the weaker
        # projection takes it, as the likelier swap.
        order = sorted(group, key=lambda i: (-_kick(kickoff.get(i)).value,
                                             by_id[i]["slot"] != flex, value[i]))
        for n, pid in enumerate(order):
            slot[pid] = flex if n < n_flex else pos
    for pid in pool:
        slot.setdefault(pid, bench)

    off = {bench, *reserve}
    start = {pid for pid, s in slot.items() if s not in off}
    sitting = [pid for pid in pool if slot[pid] == bench]
    cover = {}
    for pid in start:
        if pid in locked:
            continue
        mine = by_id[pid]
        ok = [b for b in sitting
              if value[b] > 0 and (by_id[b]["pos"] == mine["pos"]
                                   or (slot[pid] == flex and by_id[b]["pos"] in flex_positions))
              and kickoff.get(b) is not None and not pd.isna(kickoff.get(b))
              and _kick(kickoff.get(b)) >= _kick(kickoff.get(pid))]
        cover[pid] = sorted(ok, key=lambda i: -value[i])
    return {"slot": slot, "start": start, "cover": cover}


def change(now_slot: str, new_slot: str, off) -> str:
    """What the plan does with a player against where he sits now: "in" (bench
    to a starting slot), "out" (starter to the bench), "swap" (starter to a
    different starting slot, which only kickoff order asks for), or ""."""
    was, will = now_slot in off, new_slot in off
    if was != will:
        return "out" if will else "in"
    return "swap" if (not was and new_slot != now_slot) else ""
