"""
Who to add and who to drop in the Yahoo college league.

Yahoo answers the league's available-player list without a token
(`league/{key}/players;status=A` - see cfb.yahoo.free_agents), and this site
already projects every board player for a given week (cfb.weekly). Put the two
together and the waiver question answers itself: the best projection in the
pool, against the weakest thing on each roster.

Ranked inside each position rather than across them. A quarterback outscores a
running back every week of the year, so one combined list would recommend
quarterbacks and nothing else - and unlike the NFL side there is no fitted
replacement level for college positions to subtract.

    python -m cfb.waivers
"""
import pandas as pd

from cfb import predict, projections, weekly, yahoo

# Slots that hold a real player; BN/IL are where a drop candidate lives.
BENCH = {"BN", "IL", "IR"}
TOP_PER_POS = 5
DROPS_PER_TEAM = 2
POSITIONS = ("QB", "RB", "WR", "TE", "DEF")


def _week(data: dict, board: pd.DataFrame, frame: pd.DataFrame, lg: dict) -> pd.DataFrame:
    statuses = {p["yahoo_id"]: p["status"] for roster in data["rosters"].values()
                for p in roster if p.get("status")}
    return weekly.week_projections(data["week_start"], data["week_end"], board=board,
                                   league=lg, frame=frame, injuries=statuses)


def pools(week: int = None) -> tuple:
    """(available, rostered, week number) with a projection on every row.

    Both sides are priced by the same weekly projection, so the two tables can
    be read against each other; a player the board has never heard of (past
    Yahoo's ~500-deep walk) has no projection and is left out rather than
    ranked at zero.
    """
    lg = yahoo.league()
    weeks = yahoo.archived_weeks()
    week = week or (weeks[-1] if weeks else int(lg.get("current_week") or 1))
    data = yahoo.week_matchups(week)
    frame, _model, _names = predict.season()
    board = projections.value_board(frame=frame)
    wk = _week(data, board, frame, lg)

    def proj(pid):
        if pid in wk.index and pd.notna(wk.loc[pid, "proj_week"]):
            return float(wk.loc[pid, "proj_week"])
        return None

    free = yahoo.free_agents()
    rows = []
    for _, p in free.iterrows():
        rows.append({"yahoo_id": str(p["yahoo_id"]), "player": p["player"],
                     "pos": str(p["pos"]).split(",")[0], "team": p["team"],
                     "proj": proj(str(p["yahoo_id"])), "rank": int(p["rank"])})
    available = pd.DataFrame(rows).dropna(subset=["proj"])

    held = []
    for key, roster in data["rosters"].items():
        for p in roster:
            held.append({"yahoo_id": p["yahoo_id"], "player": p["player"],
                         "pos": str(p["pos"]).split(",")[0], "team": p["team"],
                         "team_key": key, "slot": p["slot"],
                         "status": p.get("status") or "",
                         "proj": proj(p["yahoo_id"])})
    rostered = pd.DataFrame(held).dropna(subset=["proj"])
    return available, rostered, week


def adds(available: pd.DataFrame, top: int = TOP_PER_POS) -> dict:
    """{position: the best available, best projection first}."""
    out = {}
    for pos in POSITIONS:
        rows = available[available["pos"] == pos].nlargest(top, "proj")
        if not rows.empty:
            out[pos] = rows.reset_index(drop=True)
    return out


def drops(rostered: pd.DataFrame, per_team: int = DROPS_PER_TEAM) -> pd.DataFrame:
    """The weakest player each roster is holding, bench first.

    A defence is never suggested: every roster has to field one, and a college
    defence's projection is a bracket calculation rather than a read on the
    player. Anyone Yahoo has flagged (O, IR) sorts to the top of a team's list
    - that is the roster spot doing nothing at all.
    """
    if rostered.empty:
        return rostered
    live = rostered[rostered["pos"] != "DEF"].copy()
    live["flagged"] = live["status"].astype(bool)
    live = live.sort_values(["team_key", "flagged", "proj"],
                            ascending=[True, False, True])
    return live.groupby("team_key", as_index=False, group_keys=False).head(per_team)


if __name__ == "__main__":
    available, rostered, week = pools()
    print(f"week {week}: {len(available)} available with a projection")
    for pos, rows in adds(available).items():
        print(pos, ", ".join(f"{r['player']} ({r['team']}) {r['proj']:.1f}"
                             for _, r in rows.iterrows()))
    print(drops(rostered).head(8)[["team_key", "player", "pos", "slot", "proj"]]
          .to_string(index=False))
