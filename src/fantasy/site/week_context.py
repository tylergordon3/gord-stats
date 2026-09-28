"""
The week's context, for a reader's own league.

The team dashboard and the matchups page render this site's league from
`fantasy.site.roster.Week`: every player's projection, every game's line and
forecast, and how each defence has been treating the position. A reader's
league is rendered in the browser from Sleeper, and none of that is in Sleeper.

So the same numbers are published, once a build:

    docs/fantasy/week-context.json
    {"week": 3, "year": 2026,
     "teams": {"BUF": {"opp": "LAC", "home": true, "state": "pre",
                       "when": "9/27 - 1:00 PM EDT", "for": 28.2,
                       "against": 21.2, "spread": "BUF -7", "total": 49.5,
                       "tv": "FOX", "gid": "401872953", "el": 0}},
     "wx":    {"401872953": {"indoors": false, "cond": "Clear", "temp": 66}},
     "dvp":   {"ARI": {"QB": [1.00, 17], ..., "games": 2}, "n": 32},
     "gs":    {"9221": 28.6},
     "late":  ["4984"],
     "ext":   {"ppr": {"max": {"WR": 57.9, ...}, "min": {"QB": -6.66, ...}}, ...}}

`gs` is this site's own weekly projection and covers the whole board - 1,231
players, not the 154 on this league's rosters - which is what makes it usable
for somebody else's league. A started player's is the number recorded before
his kickoff (fantasy.pregame); `late` names any started player with no such
record, whose number has seen his game. The other weekly sources (ESPN, FantasyPros) are
only collected for this league's players, so a reader's blend is the mean of
what exists for him rather than of four sources; `roster.Week.blend` already
works that way, so the rule is the same, only the inputs are fewer.

About 40 KB. Written after the matchups archive it reads.

    python -m fantasy.site.week_context
"""
import json

import pandas as pd

from fantasy import paths, pregame
from fantasy.config import UPCOMING_YEAR
from gordstats.pregame import load as load_pregame

OUT = paths.WEB_FANTASY_DIR / "week-context.json"


def build(year: int = UPCOMING_YEAR) -> dict:
    from fantasy.site.roster import Week

    wkd = Week()

    teams = {}
    for team, g in (wkd.by_team or {}).items():
        teams[team] = {
            "gid": g.get("game_id"), "opp": g.get("opp"), "home": bool(g.get("home")),
            "state": g.get("state") or "pre", "when": g.get("detail"),
            # This side's score and the other's, so a finished game reads
            # "W 35-14 at GB" rather than just naming the opponent.
            "sf": _round(g.get("score_for"), 0), "sa": _round(g.get("score_against"), 0),
            # The kickoff itself, so the browser can render both the long form
            # ("9/27 - 1:00 PM EDT") and the short one the cover column uses.
            "date": g.get("date"),
            # The share of the game already played, for the live expected
            # finals - fantasy.league.matchups.elapsed, computed once here
            # rather than from a period and a clock in the browser.
            "el": _round(g.get("elapsed"), 2),
            "for": _round(g.get("implied_for")), "against": _round(g.get("implied_against")),
            "spread": g.get("spread"), "total": _round(g.get("total")),
            "tv": g.get("tv"),
        }

    wx = {}
    for gid, entry in (wkd.weather or {}).items():
        if not entry:
            continue
        wx[str(gid)] = {"indoors": bool(entry.get("indoors")),
                        "cond": entry.get("cond"), "temp": _round(entry.get("temp"), 0),
                        "text": entry.get("text")}

    dvp = {}
    table = wkd.dvp
    if table is not None and not table.empty:
        for team in table.index:
            row = {"games": int(table.loc[team, "games"])}
            for pos in ("QB", "RB", "WR", "TE", "K", "DEF"):
                if pos in table.columns:
                    row[pos] = [round(float(table.loc[team, pos]), 2),
                                int(wkd.dvp_ranks[pos][team])]
            dvp[str(team)] = row
        dvp["n"] = int(len(table))

    # A started player's number as it stood before his kickoff, as on the
    # built matchups page; `late` lists the started ones with no record, so a
    # reader's page knows when not to say "going in". Read, never written:
    # the matchups step keeps the archive, and this reads the week's games
    # from its own fetch, so two writers would take turns overwriting it.
    gs, late = {}, []
    if wkd.wk is not None and not wkd.wk.empty and "proj_week" in wkd.wk:
        kept = load_pregame(pregame.path(wkd.week, year))
        state = (wkd.wk["state"] if "state" in wkd.wk
                 else pd.Series("pre", index=wkd.wk.index)).fillna("pre")
        for pid, value in wkd.wk["proj_week"].items():
            if pd.isna(value):
                continue
            if state.get(pid) != "pre":
                if str(pid) in kept:
                    value = kept[str(pid)]
                else:
                    late.append(str(pid))
            gs[str(pid)] = round(float(value), 2)

    return {"week": int(wkd.week), "year": int(year), "teams": teams,
            "wx": wx, "dvp": dvp, "gs": gs, "late": late, "ext": records()}


POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")


def records() -> dict:
    """{basis: {"max": {pos: pts}, "min": {pos: pts}}}: the best and worst week
    anyone at each position has had since 2018, on each of Sleeper's three
    scoring bases.

    The median tracker's ceilings and floors. The built league reads its own
    history for them; a reader's league has none this site can see, and with
    none the tracker called every team with a player left unbounded - a
    "hypothetical max" of Infinity, and a team with nobody left told it could
    still pass three teams that would each have had to lose thirty points.
    """
    frames = []
    for path in sorted(paths.POINTS_DIR.glob("*.parquet")):
        try:
            frames.append(pd.read_parquet(path, columns=["position", "fantasy_points",
                                                         "fantasy_points_ppr"]))
        except Exception as exc:                            # noqa: BLE001
            print(f"  ! {path.name} unreadable ({exc})")
    if not frames:
        return {}
    pts = pd.concat(frames, ignore_index=True)
    pts = pts[pts["position"].isin(POSITIONS)]
    pts["half"] = (pts["fantasy_points"] + pts["fantasy_points_ppr"]) / 2
    out = {}
    for basis, col in (("ppr", "fantasy_points_ppr"), ("half", "half"), ("std", "fantasy_points")):
        by = pts.groupby("position")[col]
        out[basis] = {"max": {k: round(float(v), 2) for k, v in by.max().items()},
                      "min": {k: round(float(v), 2) for k, v in by.min().items()}}
    return out


def _round(value, places: int = 1):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return round(float(value), places) if places else int(round(float(value)))
    except (TypeError, ValueError):
        return None


def generate(year: int = UPCOMING_YEAR) -> None:
    try:
        payload = build(year)
    except Exception as exc:                                # noqa: BLE001
        print(f"  ! week context not rebuilt ({exc}); keeping the last copy")
        return
    if not payload["gs"]:
        print("  ! week context has no projections; keeping the last copy")
        return
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote week context (week {payload['week']}, {len(payload['teams'])} games, "
          f"{len(payload['gs'])} projections) -> {OUT}")


if __name__ == "__main__":
    generate()
