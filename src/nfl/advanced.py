"""
NFL advanced stats from nflverse play-by-play: every team's EPA, success and
explosive rates, the situational rates, opponent-adjusted EPA, and the QB, RB
and receiver leaderboards - what /nfl/stats/ (nfl.site.stats) draws.

A season's play-by-play is a few MB and about a second to download
(nflreadpy), so it is fetched whole, at most every STALE_HOURS, and never
kept: data/ is committed by the Pi. Only the aggregates are, in
data/nfl/advanced_<season>.json (tens of KB), rewritten only when a figure
moves; a failed download leaves the last file standing.

The conventions are nflverse's (rbsdm.com's), so the figures can be checked
against theirs:

    a play          a pass (sacks and scrambles included) or a designed run,
                    penalties that wiped one out included; not two-point
                    tries, kneels or spikes. Regular season only.
    success         EPA above zero
    explosive       a pass play of 20+ yards or a run of 10+
    garbage time    fourth-quarter snaps with the offence's win chance under
                    5% or over 95%: left out of EPA, success and explosive
                    rate (team and player); the rest - drives, third downs,
                    red zone, sacks, plays - count every snap, like a box score
    neutral         1st or 2nd down, win chance 20-80%, outside the last two
                    minutes of a half (pass rate, PROE, pace)

Defence is the same figures for what opponents did against a team.

    python -m nfl.advanced             # refresh if stale, print the table
    python -m nfl.advanced --force
"""
import argparse
import json
import os
import time
from collections import defaultdict
from datetime import datetime

import numpy as np
import pandas as pd

from nfl import games as games_mod
from nfl.config import DATA_DIR, SEASON, TZ

STALE_HOURS = 12

GARBAGE_WP = 0.05
NEUTRAL_WP = (0.20, 0.80)
EXPLOSIVE_PASS, EXPLOSIVE_RUSH = 20, 10

# How much an opponent's measured EPA/play is pulled toward average: as if it
# had this many more plays of league-average football. Split-half reliability
# of team EPA/play over 2023-25 (odd weeks against even) puts an offence's at
# n/(n+~250) and a defence's at n/(n+~1,300-12,000) - EPA allowed is mostly
# noise for months - so the adjustment for defences faced stays small until the
# season is long, and the one for offences faced grows by midseason.
PRIOR_OFF, PRIOR_DEF = 250, 1500
ROUNDS = 30

# Player minimums, per game the player's team has played.
MIN_PER_GAME = {"qb": 15, "rb": 6, "wr": 3}
KEEP = 40


def cache_path(season: int = SEASON):
    return DATA_DIR / f"advanced_{season}.json"


def _download(season: int):
    """(play-by-play, rosters, teams) for `season`, as pandas frames."""
    import nflreadpy as nfl

    return (nfl.load_pbp(seasons=[season]).to_pandas(),
            nfl.load_rosters([season]).to_pandas(),
            nfl.load_teams().to_pandas())


# --------------------------------------------------------------------------- #
# Plays and drives
# --------------------------------------------------------------------------- #

def _flag(frame, col) -> pd.Series:
    return frame[col].fillna(0).astype(float) == 1 if col in frame else \
        pd.Series(False, index=frame.index)


def regular(pbp: pd.DataFrame) -> pd.DataFrame:
    return pbp[pbp["season_type"] == "REG"] if "season_type" in pbp else pbp


def plays(pbp: pd.DataFrame) -> pd.DataFrame:
    """The scrimmage plays, with the flags every figure is built from."""
    pbp = regular(pbp)
    p = pbp[(_flag(pbp, "pass") | _flag(pbp, "rush")) & pbp["epa"].notna()
            & ~_flag(pbp, "two_point_attempt")].copy()
    p["is_pass"], p["is_rush"] = _flag(p, "pass"), _flag(p, "rush")
    wp = p["wp"].astype(float)
    p["garbage"] = (p["qtr"] == 4) & ((wp < GARBAGE_WP) | (wp > 1 - GARBAGE_WP))
    p["ok"] = p["epa"] > 0
    yards = p["yards_gained"].fillna(0)
    p["explosive"] = (p["is_pass"] & (yards >= EXPLOSIVE_PASS)) | \
        (p["is_rush"] & (yards >= EXPLOSIVE_RUSH))
    p["neutral"] = p["down"].isin([1, 2]) & wp.between(*NEUTRAL_WP) & \
        (p["half_seconds_remaining"] > 120)
    # A penalty that wiped the play out still counts for the team (its EPA is
    # the penalty's), but it is no one's carry or target.
    p["stood"] = p["play_type"].isin(["pass", "run"])
    return p


def drives(pbp: pd.DataFrame) -> pd.DataFrame:
    """One row a possession: offence, defence, points, reached the red zone,
    ended in a touchdown, gave the ball away.

    A possession is an nflverse fixed_drive with a snap (a pass, run, field
    goal or punt): a kickoff returned for a score and a kneel-down drive are
    not the offence's work. Points are the offence's own score changes on the
    drive's plays - the try after a touchdown included, a pick-six not."""
    pbp = regular(pbp)
    snap = ((_flag(pbp, "pass") | _flag(pbp, "rush")) & ~_flag(pbp, "two_point_attempt")) | \
        pbp["play_type"].isin(["field_goal", "punt"])
    s = pbp[snap & pbp["posteam"].notna()].copy()
    key = ["game_id", "fixed_drive", "posteam"]
    s["lost"] = (_flag(s, "interception") | _flag(s, "fumble_lost")) & \
        (_flag(s, "pass") | _flag(s, "rush"))
    s["rz"] = s["yardline_100"] <= 20
    d = s.groupby(key).agg(defteam=("defteam", "first"), rz=("rz", "any"), lost=("lost", "any"),
                           result=("fixed_drive_result", "last")).reset_index()

    scored = pbp[pbp["posteam"].notna()].copy()
    scored["pts"] = (scored["posteam_score_post"] - scored["posteam_score"]).clip(lower=0).fillna(0)
    pts = scored.groupby(key)["pts"].sum()
    d = d.join(pts, on=key)
    d["pts"] = d["pts"].fillna(0)
    d["td"] = d["result"] == "Touchdown"
    return d


def games(pbp: pd.DataFrame) -> pd.DataFrame:
    """One row a team a game played: team, opp, game_id, week, pf, pa."""
    g = regular(pbp).groupby("game_id").agg(
        week=("week", "first"), home=("home_team", "first"), away=("away_team", "first"),
        hs=("home_score", "first"), as_=("away_score", "first")).reset_index()
    home = g.rename(columns={"home": "team", "away": "opp", "hs": "pf", "as_": "pa"})
    away = g.rename(columns={"away": "team", "home": "opp", "as_": "pf", "hs": "pa"})
    cols = ["team", "opp", "game_id", "week", "pf", "pa"]
    return pd.concat([home, away], ignore_index=True)[cols]


# --------------------------------------------------------------------------- #
# Opponent adjustment
# --------------------------------------------------------------------------- #

def adjust(p: pd.DataFrame, prior_off: float = PRIOR_OFF, prior_def: float = PRIOR_DEF,
           rounds: int = ROUNDS) -> dict:
    """{team: (adjusted offence EPA/play, adjusted EPA/play allowed)}.

    A team's raw EPA/play less how much better or worse than average the
    defences it met have been (and allowed, less the offences it met). Each
    opponent is measured on its *other* games - a defence the team shredded is
    not made to look bad by that same game, which would give the team back its
    own credit - with those games themselves adjusted for who that opponent
    met, a few rounds over, and pulled toward average (PRIOR_OFF/PRIOR_DEF)
    while there is little of it."""
    g = p[~p["garbage"]]
    mu = float(g["epa"].mean())
    off = g.groupby(["posteam", "game_id"])["epa"].agg(["sum", "size"])
    # team -> [(game, opp, offence EPA sum, plays, EPA allowed sum, plays)]
    rows = defaultdict(list)
    opp_of = g.groupby(["posteam", "game_id"])["defteam"].first()
    for (team, game), r in off.iterrows():
        opp = opp_of[(team, game)]
        against = off.loc[(opp, game)] if (opp, game) in off.index else None
        rows[team].append((game, opp, r["sum"], r["size"],
                           0.0 if against is None else against["sum"],
                           0.0 if against is None else against["size"]))

    # Deviation from average of each team's offence and defence, measured on
    # every game but the one keyed: (team, game) -> EPA/play above average.
    off_loo = defaultdict(float)
    def_loo = defaultdict(float)
    plays_off = {(team, r[0]): r[3] for team, games_ in rows.items() for r in games_}
    plays_def = {(team, r[0]): r[5] for team, games_ in rows.items() for r in games_}
    for _ in range(rounds):
        new_off, new_def = {}, {}
        for team, games_ in rows.items():
            o = [(gm, s - n * (mu + def_loo[(opp, gm)]), n) for gm, opp, s, n, _ds, _dn in games_]
            d = [(gm, s - n * (mu + off_loo[(opp, gm)]), n) for gm, opp, _os, _on, s, n in games_]
            so, no = sum(x[1] for x in o), sum(x[2] for x in o)
            sd, nd = sum(x[1] for x in d), sum(x[2] for x in d)
            for gm, res, n in o:
                new_off[(team, gm)] = (so - res) / (no - n + prior_off)
            for gm, res, n in d:
                new_def[(team, gm)] = (sd - res) / (nd - n + prior_def)
        # Offence-plus-defence only knows their sum game by game: every offence
        # a shade better and every defence the same shade worse fits as well,
        # and unanchored the rounds drift along that line. Centring each side
        # on the league pins it.
        off_loo = defaultdict(float, _centred(new_off, plays_off))
        def_loo = defaultdict(float, _centred(new_def, plays_def))

    out = {}
    for team, games_ in rows.items():
        on = sum(r[3] for r in games_)
        dn = sum(r[5] for r in games_)
        adj_off = sum(s - n * def_loo[(opp, gm)] for gm, opp, s, n, _a, _b in games_) / on
        adj_def = (sum(s - n * off_loo[(opp, gm)] for gm, opp, _a, _b, s, n in games_) / dn
                   if dn else None)
        out[team] = (adj_off, adj_def)
    return out


def _centred(values: dict, weights: dict) -> dict:
    total = sum(weights[k] for k in values)
    mean = sum(v * weights[k] for k, v in values.items()) / total if total else 0.0
    return {k: v - mean for k, v in values.items()}


# --------------------------------------------------------------------------- #
# Teams
# --------------------------------------------------------------------------- #

def _side(p: pd.DataFrame, d: pd.DataFrame, side: str, n_games: pd.Series) -> pd.DataFrame:
    """Every per-team figure for one side: `side` is posteam (offence) or
    defteam (what was done against the team)."""
    g = p[~p["garbage"]]
    by = g.groupby(side)
    dr = d.groupby(side)
    rz = d[d["rz"]].groupby(side)["td"]
    third = p[(p["down"] == 3) & (_flag(p, "third_down_converted") | _flag(p, "third_down_failed"))]
    dropbacks = p[_flag(p, "qb_dropback")]
    return pd.DataFrame({
        "epa": by["epa"].mean(),
        "pass": g[g["is_pass"]].groupby(side)["epa"].mean(),
        "rush": g[g["is_rush"]].groupby(side)["epa"].mean(),
        "sr": by["ok"].mean(),
        "xpl": by["explosive"].mean(),
        "sack": _flag(dropbacks, "sack").groupby(dropbacks[side]).mean(),
        "to": dr["lost"].mean(),
        "ppd": dr["pts"].mean(),
        "rz": rz.mean(),
        "third": _flag(third, "third_down_converted").groupby(third[side]).mean(),
        "ppg": p[p["stood"]].groupby(side).size() / n_games,
    })


def pace(p: pd.DataFrame) -> pd.Series:
    """Seconds of game clock between an offence's snaps in neutral situations
    (win chance 20-80%, outside the last two minutes of a half), within a
    drive and a quarter. The game clock, so incompletions read as quick."""
    s = p.sort_values(["game_id", "play_id"])
    key = [s["game_id"], s["fixed_drive"], s["posteam"], s["qtr"]]
    gap = s.groupby(key)["game_seconds_remaining"].shift(1) - s["game_seconds_remaining"]
    wp = s.groupby(key)["wp"].shift(1)
    left = s.groupby(key)["half_seconds_remaining"].shift(1)
    ok = gap.between(1, 60) & wp.between(*NEUTRAL_WP) & (left > 120)
    return gap[ok].groupby(s.loc[ok, "posteam"]).mean()


def teams(pbp: pd.DataFrame, info: pd.DataFrame) -> list:
    """One dict a team: identity, record, and every figure, offence (off_*)
    and defence (def_*)."""
    p = plays(pbp)
    d = drives(pbp)
    tg = games(pbp)
    n_games = tg.groupby("team").size()
    off = _side(p, d, "posteam", n_games)
    dfn = _side(p, d, "defteam", n_games)
    adj = adjust(p)
    neutral = p[p["neutral"]]
    npr = neutral.groupby("posteam")["is_pass"].mean()
    xp = neutral[neutral["xpass"].notna()] if "xpass" in neutral else neutral.iloc[0:0]
    proe = (xp["is_pass"].astype(float) - xp["xpass"]).groupby(xp["posteam"]).mean() \
        if len(xp) else pd.Series(dtype=float)
    secs = pace(p)

    info = info.drop_duplicates("team_abbr", keep="last").set_index("team_abbr")
    out = []
    for team in sorted(n_games.index):
        mine = tg[tg["team"] == team]
        w, l = int((mine["pf"] > mine["pa"]).sum()), int((mine["pf"] < mine["pa"]).sum())
        t = int((mine["pf"] == mine["pa"]).sum())
        meta = info.loc[team] if team in info.index else {}
        row = {"abbr": team, "name": _get(meta, "team_nick") or team,
               "full": _get(meta, "team_name") or team,
               "conf": _get(meta, "team_conf"), "div": _get(meta, "team_division"),
               "g": int(len(mine)), "w": w, "l": l, "t": t,
               "pf": int(mine["pf"].sum()), "pa": int(mine["pa"].sum())}
        for prefix, frame in (("off", off), ("def", dfn)):
            for col in frame.columns:
                row[f"{prefix}_{col}"] = _num(frame[col].get(team))
        a_off, a_def = adj.get(team, (None, None))
        row["off_adj"], row["def_adj"] = _num(a_off), _num(a_def)
        row["net_adj"] = _num(None if a_off is None or a_def is None else a_off - a_def)
        row["net_epa"] = _num(None if row["off_epa"] is None or row["def_epa"] is None
                              else row["off_epa"] - row["def_epa"])
        row["off_npr"], row["off_proe"] = _num(npr.get(team)), _num(proe.get(team))
        row["off_pace"] = _num(secs.get(team), 2)
        out.append(row)
    return out


def _get(meta, key):
    v = meta.get(key) if hasattr(meta, "get") else None
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else str(v)


def _num(v, places: int = 4):
    if v is None:
        return None
    v = float(v)
    return None if np.isnan(v) else round(v, places)


# --------------------------------------------------------------------------- #
# Players
# --------------------------------------------------------------------------- #

def players(pbp: pd.DataFrame, rosters: pd.DataFrame) -> dict:
    """{"qb": [...], "rb": [...], "wr": [...]}: the qualifiers, best first.

    Garbage time and plays a penalty wiped out are left out. QBs are rated on
    qb_epa, nflverse's EPA that does not charge a passer for his receiver's
    fumble; runners and receivers on plain EPA."""
    p = plays(pbp)
    p = p[~p["garbage"] & p["stood"]]
    n_games = games(pbp).groupby("team").size()
    ros = rosters.dropna(subset=["gsis_id"]).drop_duplicates("gsis_id", keep="last") \
        .set_index("gsis_id") if len(rosters) else pd.DataFrame()

    def who(frame, id_col, name_col):
        # The team of his latest snap: a player traded midseason is listed
        # where he plays now.
        last = frame.sort_values(["week", "game_id", "play_id"]).groupby(id_col).tail(1) \
            .set_index(id_col)
        return last["posteam"], last[name_col]

    def listing(frame, id_col, name_col, pos, key, per_game, stats):
        frame = frame[frame[id_col].notna()]
        if frame.empty:
            return []
        team, pbp_name = who(frame, id_col, name_col)
        grouped = frame.groupby(id_col)
        n = grouped.size()
        figures = stats(grouped)
        rows = []
        for pid, count in n.items():
            position = ros["position"].get(pid) if "position" in ros else None
            if pos and position not in pos:
                continue
            tm = team.get(pid)
            need = per_game * int(n_games.get(tm, 0))
            if count < max(need, 1):
                continue
            name = ros["full_name"].get(pid) if "full_name" in ros else None
            if not isinstance(name, str) or not name:
                name = pbp_name.get(pid)
            rows.append({"id": pid, "name": name, "team": tm, "pos": position, "n": int(count),
                         **{k: _num(v.get(pid)) for k, v in figures.items()}})
        rows.sort(key=lambda r: -(r[key] if r[key] is not None else -9))
        return rows[:KEEP]

    drop = p[p["is_pass"]].copy()
    drop["qb_ok"] = drop["qb_epa"] > 0
    qb = listing(drop, "passer_id", "passer", {"QB"}, "epa", MIN_PER_GAME["qb"],
                 lambda g: {"epa": g["qb_epa"].mean(), "sr": g["qb_ok"].mean(),
                            "cpoe": g["cpoe"].mean()})
    runs = p[p["is_rush"]]
    rb = listing(runs, "rusher_player_id", "rusher_player_name", {"RB", "FB"}, "epa",
                 MIN_PER_GAME["rb"],
                 lambda g: {"epa": g["epa"].mean(), "sr": g["ok"].mean(),
                            "ypc": g["yards_gained"].mean()})
    tgt = p[p["is_pass"] & p["receiver_player_id"].notna()].copy()
    tgt["caught"] = _flag(tgt, "complete_pass")
    wr = listing(tgt, "receiver_player_id", "receiver_player_name", {"WR", "TE"}, "epa",
                 MIN_PER_GAME["wr"],
                 lambda g: {"epa": g["epa"].mean(), "catch": g["caught"].mean(),
                            "adot": g["air_yards"].mean()})
    return {"qb": qb, "rb": rb, "wr": wr}


# --------------------------------------------------------------------------- #
# The cache
# --------------------------------------------------------------------------- #

def complete_through(reg: pd.DataFrame, schedule: pd.DataFrame = None) -> int:
    """The last week whose every game is in the play-by-play, every week
    before it complete too. The newest week with any play was the old
    answer, and on a Friday - Thursday night's game in, the other fifteen to
    come - the stats page said "through Week 4". `schedule` is ESPN's
    (nfl.games), a game called off not owed; without one, the newest week."""
    if not len(reg):
        return 0
    have = reg.groupby("week")["game_id"].nunique()
    if schedule is None or schedule.empty:
        return int(have.index.max())
    owed = schedule[(schedule["seasontype"] == 2) & ~games_mod.called_off(schedule)]
    owed = owed.groupby("week").size()
    done = 0
    for week in sorted(owed.index):
        if int(have.get(week, 0)) < int(owed[week]):
            break
        done = int(week)
    return done


def _scheduled(season: int) -> pd.DataFrame | None:
    """ESPN's schedule for the season as nfl.games keeps it beside this
    cache (data/nfl/games/), read and never fetched: the section's build has
    refreshed it before the stats are asked for."""
    path = DATA_DIR / games_mod.GAMES_DIR.name / f"{season}.parquet"
    try:
        return pd.read_parquet(path)
    except Exception:                                   # noqa: BLE001 - the newest week, then
        return None


def aggregate(pbp: pd.DataFrame, rosters: pd.DataFrame, info: pd.DataFrame,
              season: int = SEASON, schedule: pd.DataFrame = None) -> dict:
    """Everything the page draws, JSON-ready. `schedule` (ESPN's) says which
    weeks are complete (complete_through)."""
    reg = regular(pbp)
    p = plays(pbp)
    g = p[~p["garbage"]]
    return {
        "season": season,
        "through_week": complete_through(reg, schedule),
        "games": int(reg["game_id"].nunique()),
        "league": {"epa": _num(g["epa"].mean()), "sr": _num(g["ok"].mean()),
                   "plays": int(len(p))},
        "teams": teams(pbp, info),
        "players": players(pbp, rosters),
    }


def _read(path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def refresh(season: int = SEASON, force: bool = False) -> dict | None:
    """The aggregates, downloaded again if the cache is older than
    STALE_HOURS (or `force`); the cache as it stands if the download fails.

    The file is rewritten only when a figure moved, so the Pi commits it once
    a game week rather than every run; an unchanged download just touches it,
    which is what the staleness check reads."""
    path = cache_path(season)
    cached = _read(path)
    if cached and not force and time.time() - path.stat().st_mtime < STALE_HOURS * 3600:
        return cached
    try:
        fresh = aggregate(*_download(season), season=season, schedule=_scheduled(season))
    except Exception as exc:                            # noqa: BLE001
        print(f"  ! nflverse play-by-play failed ({exc}); keeping the last stats")
        return cached
    if not fresh["games"]:
        return cached
    if cached and {k: v for k, v in cached.items() if k != "updated"} == fresh:
        os.utime(path)
        return cached
    fresh["updated"] = datetime.now(TZ).isoformat(timespec="minutes")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fresh, separators=(",", ":")), encoding="utf-8")
    return fresh


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    data = refresh(force=ap.parse_args().force)
    if not data:
        raise SystemExit("no stats")
    frame = pd.DataFrame(data["teams"]).set_index("abbr")
    cols = ["w", "l", "net_adj", "off_adj", "off_epa", "def_adj", "def_epa", "off_sr", "off_ppd",
            "def_ppd"]
    print(f"Through week {data['through_week']}, {data['games']} games, league EPA/play "
          f"{data['league']['epa']:+.3f}")
    print(frame[cols].sort_values("net_adj", ascending=False).round(3).to_string())
