"""
Who to add, and who to drop, in the NFL league.

Sleeper has no free-agent endpoint: a free agent is a player in the league's
player universe that nobody's roster holds, so the pool is set subtraction and
the ranking is the same projection board the power rankings run on
(`fantasy.projections`, blended into this season's form). Sleeper's own weekly
projection rides along as the second opinion, since it is already fetched for
the matchups page.

The drop side is deliberately the same number over the rosters that exist, so
"worth adding" and "worth dropping" are comparable rather than two different
opinions printed next to each other.

    python -m fantasy.league.suggestions
"""
import pandas as pd

from fantasy import projections
from fantasy.config import ROSTER_NAMES, UPCOMING_YEAR
from fantasy.identity.registry import load_registry
from fantasy.league import matchups as matchups_mod
from fantasy.league import power

# Positions the league starts. Sleeper's universe also carries every practice
# squad linebacker in the NFL, which is not a waiver decision.
POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")
# A designation that means the player is not available to help this week.
OUT = {"IR", "PUP", "NA", "Sus", "DNR", "Out", "Doubtful", "COV"}
TOP_ADDS = 15
DROPS_PER_TEAM = 3
# A projection with nothing behind it. The board prices every player it has
# heard of, and a third-string quarterback nobody has projected gets the
# position's mean - which is why a first cut of this list was fifteen backup
# QBs all projected 16.57. Those are not waiver claims.
FILLER = {"replacement", "positional mean"}


def _board(year: int = UPCOMING_YEAR) -> pd.DataFrame:
    """The projection board, pulled toward this season's form once it exists."""
    board = projections.load(year)
    through = projections.completed_weeks(year)
    if through > 0:
        try:
            board = projections.current_form(board, year, refresh=False,
                                             through_week=through)
        except Exception as exc:                        # noqa: BLE001
            print(f"[suggestions] preseason board only ({exc})")
    return board


def _rostered() -> dict:
    """{sleeper_id: roster_id} for every player somebody holds."""
    frame = power.rosters()
    if frame.empty:
        return {}
    return {str(r["sleeper_id"]): int(r["roster_id"]) for _, r in frame.iterrows()}


def pools(year: int = UPCOMING_YEAR, week: int = None) -> tuple:
    """(free agents, rostered players), both scored the same way.

    Each row: sleeper_id, player, pos, team, mu (our points per game), week
    (Sleeper's projection for the coming week, where there is one), injury,
    and for rostered players the manager holding them.
    """
    board = _board(year)
    held = _rostered()
    registry = load_registry()
    names = {str(r["sleeper_id"]): r for _, r in
             registry[registry["sleeper_id"].notna()].iterrows()}

    week_proj = {}
    if week:
        try:                                            # every player, not just the rostered
            week_proj = matchups_mod.sleeper_projections(week, year)
        except Exception as exc:                        # noqa: BLE001
            print(f"[suggestions] no Sleeper week projection ({exc})")

    rows = []
    for _, p in board.iterrows():
        pid = str(p["sleeper_id"])
        pos = str(p["pos"] or "")
        if pos not in POSITIONS:
            continue
        meta = names.get(pid)
        live = week_proj.get(pid) or {}
        rows.append({
            "sleeper_id": pid,
            "basis": str(p.get("basis") or ""),
            "active": bool(p.get("active", True)),
            "vor": float(p["vor"]) if pd.notna(p.get("vor")) else None,
            "replacement": float(p["replacement"]) if pd.notna(p.get("replacement")) else 0.0,
            "player": p.get("player") or (meta or {}).get("full_name") or pid,
            "pos": pos, "team": p.get("team") or live.get("team") or "",
            "mu": float(p["mu"]) if pd.notna(p.get("mu")) else None,
            "week": live.get("pts"), "injury": live.get("injury") or "",
            "roster_id": held.get(pid),
            "manager": ROSTER_NAMES.get(held.get(pid)),
        })
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame, frame
    free = frame[frame["roster_id"].isna()].sort_values("mu", ascending=False)
    owned = frame[frame["roster_id"].notna()].sort_values("mu")
    return free.reset_index(drop=True), owned.reset_index(drop=True)


def _scored(frame: pd.DataFrame) -> pd.DataFrame:
    """`points` is what the player is expected to score - Sleeper's number for
    the coming week where it has one, ours otherwise - and `score` is that
    against what the position hands out for free.

    The over-replacement step is the whole ranking. On raw points a league
    that starts one quarterback would be told to add fifteen quarterbacks,
    because a quarterback outscores a running back and always will; what
    decides a waiver claim is the gap to the next man at that position.
    """
    out = frame.dropna(subset=["mu"]).copy()
    out["points"] = out["week"].where(out["week"].notna(), out["mu"])
    out["score"] = out["points"] - out["replacement"]
    return out


def adds(free: pd.DataFrame, owned: pd.DataFrame = None, top: int = TOP_ADDS) -> pd.DataFrame:
    """The free agents worth a claim, best first."""
    if free.empty:
        return free
    real = free[free["active"] & ~free["basis"].isin(FILLER)]
    out = _scored(real).sort_values("score", ascending=False).head(top)
    # A player nobody can start this week (out, IR) is still worth naming, but
    # the reason belongs on the row.
    out = out.copy()
    out["flag"] = out["injury"].where(out["injury"].isin(OUT), "")
    return out.reset_index(drop=True)


def drops(owned: pd.DataFrame, per_team: int = DROPS_PER_TEAM) -> pd.DataFrame:
    """The weakest holdings on each roster, scored the same way as the adds,
    so the two tables can be read against each other.

    Kickers and defences are left out: every roster needs one of each, they
    are priced at replacement by construction (no predictive signal), and a
    list that told all ten managers to drop their kicker would be noise.
    """
    if owned.empty:
        return owned
    scored = _scored(owned[~owned["pos"].isin(("K", "DEF"))]).sort_values(["manager", "score"])
    return scored.groupby("manager", as_index=False, group_keys=False).head(per_team)


def current_week() -> int:
    """The week the league is about to play - the same one the matchups page
    treats as current, so the two pages never disagree about the week."""
    try:
        return matchups_mod.current_week()
    except Exception:                                   # noqa: BLE001
        return 0


if __name__ == "__main__":
    week = current_week()
    free, owned = pools(week=week)
    print(f"week {week}")
    print(adds(free)[["player", "pos", "team", "score", "points", "mu", "week"]]
          .to_string(index=False))
    print(drops(owned).head(9)[["manager", "player", "pos", "score"]].to_string(index=False))
