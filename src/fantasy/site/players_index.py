"""
Two small files the browser fetches when someone is looking at their own
league: a player index, and this week's projections.

docs/fantasy/players-index.json - Sleeper player id -> [name, position, team].

The matchups page can show a reader's own league, and a league's rosters are
just player ids. Names have to come from somewhere, and Sleeper's own player
endpoint is about 5 MB, which is not a thing to download on a phone to read a
scoreboard.

So the index is written here instead, from the player table the build already
keeps: every active player at a fantasy position, about 3,200 of them and
about 110 KB. It is fetched lazily by the browser and only when someone is
actually looking at their own league, so it costs a normal reader nothing.

docs/fantasy/espn-ids.json - ESPN player id -> Sleeper player id.

For a reader whose league is on ESPN (gordstats.league_api): ESPN's rosters
name players by ESPN's own ids, and every projection and index here is keyed
by Sleeper's. From the player registry, every fantasy-position player both
ids are known for, retired ones included, since a league's history reaches
back. About 60 KB, fetched only for an ESPN league.

docs/fantasy/week-projections.json - this week's projections and kickoffs.

Sleeper's own projections endpoint cannot be used from a browser: it answers a
cross-origin request with every player id mapped to an empty object, stats
stripped, where the same URL from a server returns the numbers. So the build
writes what the browser needs instead:

    {"week": 4, "year": 2026,
     "kick": {"SEA": "<kickoff iso>", ...},          team -> kickoff
     "proj": {"4034": [ppr, half, std, "SEA", ""], ...}}
                                   the three bases, his team, his injury status

All three scoring bases, because the reader's league may not be the PPR this
site plays. Sleeper prices each player under all three, so half-PPR and
standard leagues cost one extra number each rather than a re-scoring; the
league's own `scoring_settings.rec` picks the column. A league with genuinely
custom scoring (six-point passing touchdowns, reception bonuses) is still
approximate, and the page says so rather than quietly being wrong.

Kickoffs are here because the lineup planner needs to know whose game has
started: a player already playing cannot be moved. The injury status is here
because the waiver section should not offer a player who is out.

    python -m fantasy.site.players_index
"""
import json

import pandas as pd

from fantasy import paths
from fantasy.config import UPCOMING_YEAR

FANTASY_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")
OUT = paths.WEB_FANTASY_DIR / "players-index.json"
PROJ_OUT = paths.WEB_FANTASY_DIR / "week-projections.json"
ESPN_OUT = paths.WEB_FANTASY_DIR / "espn-ids.json"
POINTS_DIR = paths.WEB_FANTASY_DIR / "season-points"
# How far back season totals are written. Sleeper's own season endpoint is
# 2.3 MB a year, so a reader looking at four seasons of drafts would pull 9 MB
# to find out what the picks returned; these are about 25 KB each and fetched
# one season at a time.
FIRST_POINTS_SEASON = 2020


def build() -> dict:
    frame = pd.read_parquet(paths.DATA_DIR / "players" / "sleeper.parquet")
    keep = frame[frame["position"].isin(FANTASY_POSITIONS)]
    if "active" in keep.columns:
        keep = keep[keep["active"].fillna(False).astype(bool)]
    out = {}
    for row in keep.itertuples():
        pid = getattr(row, "sleeper_id", None)
        name = getattr(row, "full_name", None)
        if pid is None or pd.isna(pid) or not name or pd.isna(name):
            continue
        team = getattr(row, "team", None)
        # The team is here for the players this week's projections do not
        # cover - a bench player on a bye, or one nobody projects. Without it
        # his row has no logo and no game, which reads as missing data rather
        # than as a quiet week.
        out[str(pid)] = [str(name), str(row.position),
                         "" if team is None or pd.isna(team) else str(team)]
    return out


def projections(week: int = None, year: int = UPCOMING_YEAR) -> dict:
    """This week's three scoring bases per player, and every kickoff.

    Fetched raw rather than through `sleeper_projections`, which keeps only the
    PPR figure - the archive has no use for the other two and there is no
    reason to widen it.
    """
    from fantasy.league import matchups as matchups_mod
    if week is None:
        weeks = matchups_mod.archived_weeks(year)
        if not weeks:
            return {}
        week = weeks[-1]

    url = (f"{matchups_mod.SLEEPER_ROOT}/projections/nfl/{year}/{week}"
           f"?season_type=regular&{matchups_mod._positions_param()}&order_by=pts_ppr")
    rows = matchups_mod._get(url) or []
    proj, pos = {}, {}
    for r in rows:
        st, pid = r.get("stats") or {}, str(r.get("player_id") or "")
        if not pid or st.get("pts_ppr") is None:
            continue
        pos[pid] = (r.get("player") or {}).get("position") or ""
        proj[pid] = [round(float(st.get("pts_ppr") or 0), 2),
                     round(float(st.get("pts_half_ppr") or 0), 2),
                     round(float(st.get("pts_std") or 0), 2),
                     r.get("team") or "",
                     (r.get("player") or {}).get("injury_status") or ""]

    kick = {}
    try:
        for g in matchups_mod.espn_games(week, year):
            for side in ("home", "away"):
                if g.get(side) and g.get("date"):
                    kick[g[side]] = g["date"]
    except Exception as exc:                                # noqa: BLE001
        print(f"  ! kickoffs unavailable ({exc}); lineups will not lock")

    # This week's chance each listed player plays (fantasy.league.availability:
    # status, role and the last practice, measured 2016-2025), and when ESPN
    # has the ones held out coming back - so a reader's own league reads the
    # same expected points and the same pills as this site's pages.
    play, back = {}, {}
    try:
        from fantasy.league import availability as av
        chances = av.week_chances({p: v[4] for p, v in proj.items() if v[4]}, int(week),
                                  int(year), positions=pos)
        play = {p: round(c["p"], 3) for p, c in chances.items()
                if c["status"] in av.PRICED and p in proj}
        back = av.return_labels([p for p, c in chances.items() if c["status"] != "Questionable"],
                                int(year), after=av.week_end([{"date": d} for d in kick.values()]))
    except Exception as exc:                                # noqa: BLE001
        print(f"  ! play chances unavailable ({exc})")
    return {"week": int(week), "year": int(year), "kick": kick, "proj": proj,
            "play": play, "back": back}


def season_points(year: int) -> dict:
    """{player_id: [ppr, half, std]} for a whole season."""
    from fantasy.league import matchups as matchups_mod
    url = (f"{matchups_mod.SLEEPER_ROOT}/stats/nfl/{year}"
           f"?season_type=regular&{matchups_mod._positions_param()}&order_by=pts_ppr")
    rows = matchups_mod._get(url) or []
    out = {}
    for r in rows:
        st, pid = r.get("stats") or {}, str(r.get("player_id") or "")
        if not pid or st.get("pts_ppr") is None:
            continue
        out[pid] = [round(float(st.get("pts_ppr") or 0), 1),
                    round(float(st.get("pts_half_ppr") or 0), 1),
                    round(float(st.get("pts_std") or 0), 1)]
    return out


def write_season_points(year: int = None) -> None:
    """Season totals per player, one file a year.

    A finished season never changes, so it is written once and skipped after;
    the season being played is rewritten every build.
    """
    POINTS_DIR.mkdir(parents=True, exist_ok=True)
    now = UPCOMING_YEAR
    years = [year] if year else range(FIRST_POINTS_SEASON, now + 1)
    for y in years:
        path = POINTS_DIR / f"{y}.json"
        if path.exists() and y != now:
            continue                                  # a finished season is finished
        try:
            points = season_points(y)
        except Exception as exc:                      # noqa: BLE001
            print(f"  ! {y} season points unavailable ({exc})")
            continue
        if not points:
            continue
        path.write_text(json.dumps(points, separators=(",", ":")), encoding="utf-8")
        print(f"Wrote {y} season points ({len(points)} players) -> {path}")


def espn_ids(frame: pd.DataFrame = None) -> dict:
    """{espn id: sleeper id} for every fantasy-position player with both."""
    if frame is None:
        path = paths.PLAYERS_DIR / "registry.parquet"
        if not path.exists():
            return {}
        frame = pd.read_parquet(path, columns=["sleeper_id", "espn_id", "position"])
    frame = frame[frame["position"].isin(FANTASY_POSITIONS)].dropna(subset=["sleeper_id", "espn_id"])
    out = {}
    for r in frame.itertuples(index=False):
        try:
            espn = str(int(float(r.espn_id)))
        except (TypeError, ValueError):
            continue
        out.setdefault(espn, str(r.sleeper_id))
    return dict(sorted(out.items(), key=lambda kv: int(kv[0])))


def generate():
    index = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    # Compact: these are fetched, not read.
    OUT.write_text(json.dumps(index, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote player index ({len(index)} players) -> {OUT}")
    ids = espn_ids()
    if ids:
        ESPN_OUT.write_text(json.dumps(ids, separators=(",", ":")), encoding="utf-8")
        print(f"Wrote ESPN id map ({len(ids)} players) -> {ESPN_OUT}")

    try:
        proj = projections()
    except Exception as exc:                                # noqa: BLE001
        print(f"  ! week projections unavailable ({exc}); keeping the last copy")
        return
    if proj.get("proj"):
        PROJ_OUT.write_text(json.dumps(proj, separators=(",", ":")), encoding="utf-8")
        print(f"Wrote week {proj['week']} projections ({len(proj['proj'])} players, "
              f"{len(proj['kick'])} kickoffs) -> {PROJ_OUT}")

    write_season_points()


if __name__ == "__main__":
    generate()
