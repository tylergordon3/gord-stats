"""
Who is on the field and who the ball goes to (data/fantasy/usage/{year}.parquet).

Sleeper's weekly stats feed carries everything a usage table needs, per
player: offensive snaps beside the team's (`off_snp`, `tm_off_snp`), carries,
targets, air yards, and the red-zone looks (`rush_rz_att`, `rec_rz_tgt`). One
request a week, every player in the league's positions.

A finished week never changes, so each is fetched once; a week that has
started but not finished (Thursday is played, Sunday is not) is refetched on
every build so the table keeps up.

Shares divide by the team's own players added up - a player's carries over
his team's carries - the same rule the college usage table uses, so a share
can never exceed what the team ran.

    python -m fantasy.league.usage
"""
import pandas as pd

from fantasy import paths
from fantasy.config import UPCOMING_YEAR
from fantasy.league import matchups as matchups_mod

USAGE_DIR = paths.DATA_DIR / "usage"
POSITIONS = ("QB", "RB", "WR", "TE")
STATS = ["off_snp", "tm_off_snp", "pass_att", "pass_yd", "pass_td", "rush_att", "rush_yd",
         "rush_td", "rush_rz_att", "rec_tgt", "rec", "rec_yd", "rec_td", "rec_air_yd",
         "rec_rz_tgt", "pts_ppr"]


def path(year: int = UPCOMING_YEAR):
    return USAGE_DIR / f"{year}.parquet"


def load(year: int = UPCOMING_YEAR) -> pd.DataFrame:
    return pd.read_parquet(path(year)) if path(year).exists() else pd.DataFrame()


def week_rows(week: int, year: int) -> list:
    rows = matchups_mod._get(
        f"{matchups_mod.SLEEPER_ROOT}/stats/nfl/{year}/{week}?season_type=regular&"
        + "&".join(f"position[]={p}" for p in POSITIONS) + "&order_by=pts_ppr") or []
    out = []
    for r in rows:
        stats, who = r.get("stats") or {}, r.get("player") or {}
        if not r.get("team") or not stats.get("gp"):
            continue                                   # inactive, or a bye-week stub
        out.append({"week": week, "sleeper_id": str(r.get("player_id")),
                    "player": f"{who.get('first_name') or ''} {who.get('last_name') or ''}".strip(),
                    "pos": who.get("position") or "", "team": r["team"],
                    "opp": r.get("opponent") or "",
                    **{k: float(stats.get(k) or 0.0) for k in STATS}})
    return out


def capture(year: int = UPCOMING_YEAR, refresh: bool = False) -> pd.DataFrame:
    """Every started week on disk; finished weeks are fetched once."""
    have = pd.DataFrame() if refresh else load(year)
    seen = set(have["week"].unique()) if len(have) else set()
    todo = []
    for week in matchups_mod.archived_weeks(year):
        data = matchups_mod.week_matchups(week, year)
        if not matchups_mod.week_started(data):
            continue
        if week not in seen or not matchups_mod.week_final(data) or _partial(have, week, data):
            todo.append(week)
    rows = []
    for week in todo:
        got = week_rows(week, year)
        print(f"[usage] week {week}: {len(got)} player-games")
        rows.extend(got)
    if not rows:
        return have
    frame = pd.DataFrame(rows)
    if len(have):
        frame = pd.concat([have[~have["week"].isin(frame["week"].unique())], frame],
                          ignore_index=True)
    USAGE_DIR.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path(year), index=False)
    return frame


def _partial(have: pd.DataFrame, week: int, data: dict) -> bool:
    """A week archived while it was still being played has fewer teams than
    played it; fetch it once more now that it is final."""
    teams = {t for g in data.get("games") or [] for t in (g["home"], g["away"])}
    return len(have) > 0 and have.loc[have["week"] == week, "team"].nunique() < len(teams)


def shares(frame: pd.DataFrame, weeks: int = None) -> pd.DataFrame:
    """Per player: games, the counts, and his share of his team's snaps,
    carries, targets and air yards. `weeks` keeps the most recent N."""
    if frame.empty:
        return frame
    if weeks:
        frame = frame[frame["week"].isin(sorted(frame["week"].unique())[-weeks:])]
    frame = frame.copy()
    # A screen caught behind the line is negative air yards, and a team whose
    # total is small turns that into a share of -80%. Depth is what the column
    # is for, so only yards downfield count.
    frame["rec_air_yd"] = frame["rec_air_yd"].clip(lower=0)
    for col, total in (("rush_att", "tm_rush"), ("rec_tgt", "tm_tgt"),
                       ("rec_air_yd", "tm_air")):
        frame[total] = frame.groupby(["team", "week"])[col].transform("sum")
    # A traded player is one row per team he played for; the latest is his.
    agg = {c: (c, "sum") for c in STATS + ["tm_rush", "tm_tgt", "tm_air"]}
    out = frame.sort_values("week").groupby(["sleeper_id"], as_index=False).agg(
        player=("player", "last"), pos=("pos", "last"), team=("team", "last"),
        games=("week", "nunique"), **agg)
    for share, top, bottom in (("snap_share", "off_snp", "tm_off_snp"),
                               ("car_share", "rush_att", "tm_rush"),
                               ("tgt_share", "rec_tgt", "tm_tgt"),
                               ("air_share", "rec_air_yd", "tm_air")):
        out[share] = (out[top] / out[bottom]).where(out[bottom] > 0)
    return out


if __name__ == "__main__":
    table = shares(capture())
    print(table[table["pos"] == "RB"].nlargest(10, "car_share")[
        ["player", "team", "games", "snap_share", "rush_att", "car_share", "rec_tgt",
         "tgt_share"]].round(2).to_string(index=False) if len(table) else "nothing played yet")
