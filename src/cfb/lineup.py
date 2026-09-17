"""
The college league's lineup planner: gordstats.lineup with Yahoo's slot names.

Who starts and which slot each starter takes (latest kickoffs in the W/R/T
flex, so a late scratch leaves a slot anyone can fill) is worked out in
gordstats.lineup, which the NFL dashboard shares; this adapts the week
archive's roster rows to it.

    python -m cfb.lineup
"""
from cfb import projections
from gordstats import lineup as shared
from gordstats.lineup import _points

BENCH = {"BN", "IL", "IR"}
RESERVE = {"IL", "IR"}
FLEX = projections.FLEX_SLOT
FLEX_POSITIONS = set(projections.FLEX_POSITIONS)


def plan(players: list, roster_slots: list, proj: dict, kickoff: dict, locked: set) -> dict:
    """The recommended lineup for one roster (see gordstats.lineup.plan).

    players       the week archive's roster rows (yahoo_id, pos, slot)
    roster_slots  the league's [{position, count}]
    """
    counts = {s["position"]: int(s["count"]) for s in roster_slots
              if s["position"] not in BENCH}
    rows = [{"id": p["yahoo_id"], "pos": p["pos"], "slot": p["slot"]} for p in players]
    return shared.plan(rows, counts, proj, kickoff, locked, flex=FLEX,
                       flex_positions=FLEX_POSITIONS, bench="BN", reserve=RESERVE)


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
