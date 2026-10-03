"""
Will he play this week? The chance a player on the NFL injury report plays,
from the official reports and what happened after them.

Sleeper's tag alone used to price the week: Out or Doubtful a missed week,
Questionable a full one. The reports say more than the tag. Ten seasons of
them (nflverse's copy of the league's injury report, 2016-2025) against who
actually took an offensive snap give:

  * Doubtful is all but Out: 1-2% of tagged backs, receivers, tight ends and
    quarterbacks took a snap - not the one in four the old rule assumed.
  * Questionable is a coin weighted by the role he has and the last practice
    of the week: a lead player who practised in full plays about nine times
    in ten, a part-timer who sat out Friday about one in three.

The table (data/fantasy/availability.json) is P(plays | final game status,
his role, the last practice before it), each cell shrunk toward its parent
(status and role, then status) by PRIOR pseudo-observations, so a thin cell
borrows from a thick one.

    "Played"   at least one offensive snap (a kicker: one special-teams snap),
               from nflverse's weekly snap counts, joined through nflverse's
               player table (pfr id -> gsis id). Snap counts list everyone who
               took a snap whether or not he touched the ball; the weekly stat
               lines miss the receiver who ran routes and was never targeted.
    "Role"     his share of the team's offensive snaps over his last RECENT
               games this season before the week, or last season's last
               RECENT when he has none yet: lead >= 60%, share >= 35%, depth
               below, new with no snaps in either, kick for kickers. Teams dress
               a hurt starter more readily than a hurt part-timer: lead over
               share is 8 to 14 points at each practice level.
    "Practice" nflverse keeps one participation per player-week: the last
               practice before the final report (Friday for a Sunday game).
               There is no day-by-day pattern in the history to fit on, so the
               model uses the last day only.

This week's report: nflverse republishes the season's file daily (about a
day behind the league), so the build reads the final report's practice once
it is there; until it is (or when it disagrees with Sleeper's newer tag) the
chance comes from the status and role alone. Roles come from the season's
usage (fantasy.league.usage, Sleeper's snap counts) and last season's from
data/fantasy/availability_roles.json, written beside the table.

    python -m fantasy.league.availability            # refit, validate, write
    python -m fantasy.league.availability --show     # print the table
"""
import json
from datetime import date

import numpy as np
import pandas as pd

from fantasy import paths
from fantasy.config import UPCOMING_YEAR

TABLE_PATH = paths.DATA_DIR / "availability.json"
ROLES_PATH = paths.DATA_DIR / "availability_roles.json"

# Fitted through the last finished season: refit once a year (`python -m
# fantasy.league.availability`), which also writes that season's roles - the
# ones week 1 reads. Without the refit a new season's week 1 knows no roles and
# prices each player on his status alone.
FIRST_SEASON, LAST_SEASON = 2016, UPCOMING_YEAR - 1
SPLIT_SEASON = 2021             # validation: fit through this season, test after it
PRIOR = 20                      # pseudo-observations each cell borrows from its parent
LEAD, SHARE = 0.60, 0.35        # role cut-offs on the offensive snap share
RECENT = 4                      # games the role is read over

STATUSES = ("Questionable", "Doubtful", "Out")
#: The tags this model prices. Out and the reserve lists are a week off.
PRICED = ("Questionable", "Doubtful")
#: Sleeper tags that mean no game this week, whatever the table says.
ZERO = {"Out", "IR", "PUP", "NA", "Sus", "COV", "DNR"}
SKILL = ("QB", "RB", "WR", "TE")
POSITIONS = SKILL + ("K",)
ROLES = ("lead", "share", "depth", "new", "kick")
PRACTICE = {"Full Participation in Practice": "Full",
            "Limited Participation in Practice": "Limited",
            "Did Not Participate In Practice": "DNP"}
PRACTICE_WORDS = {"Full": "practiced in full", "Limited": "limited in practice",
                  "DNP": "did not practice"}
ROLE_WORDS = {"lead": "a lead player", "share": "a part-time player",
              "depth": "a depth player", "new": "a player with no snaps yet",
              "kick": "a kicker"}


# --------------------------------------------------------------------------- #
# The history
# --------------------------------------------------------------------------- #

def role_of(share) -> str:
    """lead / share / depth from an offensive snap share; new when unknown."""
    if share is None or pd.isna(share):
        return "new"
    return "lead" if share >= LEAD else "share" if share >= SHARE else "depth"


def _final_rows(injuries: pd.DataFrame) -> pd.DataFrame:
    """One row per player-week of the regular season: the last report filed.
    A player downgraded on a Saturday appears twice; the later one stands."""
    inj = injuries[injuries["game_type"].astype(str) == "REG"].copy()
    if "date_modified" in inj:
        inj = inj.sort_values("date_modified", kind="stable")
    inj["season"] = inj["season"].astype(int)
    inj["week"] = inj["week"].astype(int)
    return inj.drop_duplicates(["season", "week", "gsis_id"], keep="last")


def sample(injuries: pd.DataFrame, snaps: pd.DataFrame, players: pd.DataFrame) -> pd.DataFrame:
    """Every Q / D / Out tag on a fantasy position with what happened.

    injuries  nflverse load_injuries: season, week, game_type, gsis_id,
              position, report_status, practice_status[, date_modified]
    snaps     nflverse load_snap_counts: season, week, game_type,
              pfr_player_id, offense_snaps, offense_pct, st_snaps - the
              season before the first injury season included, for roles
    players   nflverse load_players: gsis_id, pfr_id

    Returns season, week, gsis_id, position, status, role, practice, played.
    A player with no pfr id is dropped: without one, "no snaps" could not be
    told from "not matched".
    """
    inj = _final_rows(injuries)
    inj = inj[inj["position"].isin(POSITIONS) & inj["report_status"].isin(STATUSES)].copy()
    pfr = (players.dropna(subset=["gsis_id", "pfr_id"]).drop_duplicates("gsis_id")
           .set_index("gsis_id")["pfr_id"])
    inj["pfr_id"] = inj["gsis_id"].map(pfr)
    inj = inj.dropna(subset=["pfr_id"])

    sn = snaps[snaps["game_type"].astype(str) == "REG"].copy()
    sn["season"] = sn["season"].astype(int)
    sn["week"] = sn["week"].astype(int)
    for col in ("offense_snaps", "offense_pct", "st_snaps"):
        sn[col] = pd.to_numeric(sn[col], errors="coerce").fillna(0.0)
    games = (sn.drop_duplicates(["season", "week", "pfr_player_id"])
             .set_index(["season", "week", "pfr_player_id"])[["offense_snaps", "st_snaps"]])
    took = inj.join(games, on=["season", "week", "pfr_id"])
    off = took["offense_snaps"].fillna(0.0)
    st = took["st_snaps"].fillna(0.0)

    on = sn[sn["offense_snaps"] > 0].sort_values(["season", "week"])
    hist = {k: g[["season", "week", "offense_pct"]].to_numpy(dtype=float)
            for k, g in on.groupby("pfr_player_id")}

    def share(pfr_id, season, week):
        h = hist.get(pfr_id)
        if h is None:
            return np.nan
        now = h[(h[:, 0] == season) & (h[:, 1] < week)]
        if len(now):
            return float(np.mean(now[-RECENT:, 2]))
        last = h[h[:, 0] == season - 1]
        return float(np.mean(last[-RECENT:, 2])) if len(last) else np.nan

    kicker = inj["position"].eq("K").to_numpy()
    roles = ["kick" if k else role_of(share(p, s, w))
             for k, p, s, w in zip(kicker, inj["pfr_id"], inj["season"], inj["week"])]
    return pd.DataFrame({
        "season": inj["season"].to_numpy(), "week": inj["week"].to_numpy(),
        "gsis_id": inj["gsis_id"].to_numpy(), "position": inj["position"].to_numpy(),
        "status": inj["report_status"].to_numpy(),
        "role": roles,
        "practice": inj["practice_status"].map(PRACTICE).to_numpy(),
        "played": np.where(kicker, st.to_numpy() > 0, off.to_numpy() > 0),
    })


def history(first: int = FIRST_SEASON, last: int = LAST_SEASON) -> tuple:
    """(injuries, snaps, players) from nflverse. Network; kept in nflreadpy's
    own cache, never in the repo."""
    import nflreadpy as nfl
    seasons = list(range(first, last + 1))
    injuries = nfl.load_injuries(seasons=seasons).to_pandas()
    snaps = nfl.load_snap_counts(seasons=[first - 1] + seasons).to_pandas()
    players = nfl.load_players().to_pandas()[["gsis_id", "pfr_id"]]
    return injuries, snaps, players


# --------------------------------------------------------------------------- #
# The table
# --------------------------------------------------------------------------- #

def _key(*parts) -> str:
    return "|".join(str(p) for p in parts)


def fit(frame: pd.DataFrame, prior: float = PRIOR) -> dict:
    """{"status|role|practice": [rate, n]} at three depths, each level shrunk
    toward the one above it by `prior` pseudo-observations; the status level
    toward an even chance by one."""
    rates = {}
    for status, g in frame.groupby("status"):
        top = (g["played"].sum() + 0.5) / (len(g) + 1.0)
        rates[_key(status)] = [round(float(top), 4), int(len(g))]
        for role, r in g.groupby("role"):
            mid = (r["played"].sum() + prior * top) / (len(r) + prior)
            rates[_key(status, role)] = [round(float(mid), 4), int(len(r))]
            for practice, c in r.dropna(subset=["practice"]).groupby("practice"):
                low = (c["played"].sum() + prior * mid) / (len(c) + prior)
                rates[_key(status, role, practice)] = [round(float(low), 4), int(len(c))]
    return rates


def lookup(rates: dict, status: str, role: str = None, practice: str = None) -> tuple:
    """(rate, n, key) at the deepest level the table has; None when the status
    is not in it."""
    for key in (_key(status, role, practice), _key(status, role), _key(status)):
        if key in rates:
            p, n = rates[key]
            return float(p), int(n), key
    return None, 0, None


def predict(rates: dict, frame: pd.DataFrame) -> np.ndarray:
    return np.array([lookup(rates, s, r, p if isinstance(p, str) else None)[0]
                     for s, r, p in zip(frame["status"], frame["role"], frame["practice"])],
                    dtype=float)


def _log_loss(p, y) -> float:
    p = np.clip(np.asarray(p, dtype=float), 1e-3, 1 - 1e-3)
    y = np.asarray(y, dtype=float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def validate(frame: pd.DataFrame, split: int = SPLIT_SEASON, prior: float = PRIOR) -> dict:
    """Fit on seasons <= split, score the seasons after it.

    Scored against two simpler answers - the old rule (Questionable plays,
    Doubtful a quarter, Out never) and the status alone - with a calibration
    row per Questionable / Doubtful cell: what the table said, what happened.
    """
    train, test = frame[frame["season"] <= split], frame[frame["season"] > split].copy()
    rates = fit(train, prior)
    test["p"] = predict(rates, test)
    status_only = test["status"].map(
        {s: lookup(rates, s)[0] for s in test["status"].unique()}).to_numpy(dtype=float)
    old = test["status"].map({"Questionable": 1.0, "Doubtful": 0.25, "Out": 0.0}).to_numpy()
    y = test["played"].to_numpy(dtype=float)
    q = (test["status"] == "Questionable").to_numpy()

    def scores(mask):
        return {"n": int(mask.sum()),
                "said": round(float(test["p"][mask].mean()), 3),
                "played": round(float(y[mask].mean()), 3),
                "log_loss": round(_log_loss(test["p"][mask], y[mask]), 4),
                "brier": round(float(np.mean((test["p"][mask] - y[mask]) ** 2)), 4),
                "status_only_log_loss": round(_log_loss(status_only[mask], y[mask]), 4),
                "status_only_brier": round(float(np.mean((status_only[mask] - y[mask]) ** 2)), 4),
                "old_rule_brier": round(float(np.mean((old[mask] - y[mask]) ** 2)), 4)}

    cells = []
    tagged = test[test["status"].isin(PRICED)]
    for (status, role, practice), g in tagged.groupby(
            ["status", "role", tagged["practice"].fillna("?")]):
        if len(g) >= 10:
            cells.append([status, role, practice, round(float(g["p"].mean()), 3),
                          round(float(g["played"].mean()), 3), int(len(g))])
    bins = []
    qt = test[q]
    for lo, hi in ((0, .4), (.4, .55), (.55, .7), (.7, .8), (.8, 1.01)):
        g = qt[(qt["p"] >= lo) & (qt["p"] < hi)]
        if len(g):
            bins.append([lo, min(hi, 1.0), round(float(g["p"].mean()), 3),
                         round(float(g["played"].mean()), 3), int(len(g))])
    return {"train": [int(frame["season"].min()), split],
            "test": [split + 1, int(frame["season"].max())],
            "all": scores(np.ones(len(test), dtype=bool)),
            "questionable": scores(q),
            "doubtful": scores((test["status"] == "Doubtful").to_numpy()),
            "cells": cells, "bins": bins}


def last_season_shares(snaps: pd.DataFrame, season: int, registry: pd.DataFrame) -> dict:
    """{sleeper id: offensive snap share over his last RECENT games of
    `season`} for the skill positions - the role a player carries into a new
    season before he has played in it."""
    sn = snaps[(snaps["game_type"].astype(str) == "REG") & (snaps["season"].astype(int) == season)
               & snaps["position"].isin(SKILL)].copy()
    sn = sn[pd.to_numeric(sn["offense_snaps"], errors="coerce").fillna(0) > 0]
    sn = sn.sort_values("week")
    share = sn.groupby("pfr_player_id")["offense_pct"].apply(
        lambda s: float(pd.to_numeric(s, errors="coerce").tail(RECENT).mean()))
    ids = (registry.dropna(subset=["pfr_id", "sleeper_id"]).drop_duplicates("pfr_id")
           .set_index("pfr_id")["sleeper_id"])
    out = {}
    for pfr_id, v in share.items():
        sid = ids.get(pfr_id)
        if sid is not None and not pd.isna(v):
            out[str(sid)] = round(float(v), 2)
    return dict(sorted(out.items()))


def refit(first: int = FIRST_SEASON, last: int = LAST_SEASON, split: int = SPLIT_SEASON,
          path=TABLE_PATH, roles_path=ROLES_PATH, frames: tuple = None) -> dict:
    """Refit on `first`..`last`, validate on the seasons after `split`, and
    write the table and last season's roles. Run once a year, after the
    season's last snap counts are in (and gordstats-annual-rollovers says so)."""
    injuries, snaps, players = frames or history(first, last)
    frame = sample(injuries, snaps, players)
    table = {
        "fitted": date.today().isoformat(),
        "seasons": [first, last],
        "prior": PRIOR,
        "role": {"lead": LEAD, "share": SHARE, "games": RECENT},
        "played": "an offensive snap (kickers: a special-teams snap), nflverse snap counts",
        "practice": "the last practice before the final report",
        "rates": fit(frame),
        "validation": validate(frame, split),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(table, indent=0, separators=(",", ":")) + "\n", encoding="utf-8")
    registry = pd.read_parquet(paths.PLAYERS_DIR / "registry.parquet",
                               columns=["pfr_id", "sleeper_id"])
    roles = {"season": last, "share": last_season_shares(snaps, last, registry)}
    roles_path.write_text(json.dumps(roles, separators=(",", ":")) + "\n", encoding="utf-8")
    _TABLE.clear()
    return table


_TABLE: dict = {}


def load_table(path=TABLE_PATH) -> dict:
    """The fitted table, read once per process."""
    key = str(path)
    if key not in _TABLE:
        _TABLE[key] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return _TABLE[key]


# --------------------------------------------------------------------------- #
# This week
# --------------------------------------------------------------------------- #

_REPORTS: dict = {}


def official_reports(year: int = UPCOMING_YEAR, frame: pd.DataFrame = None) -> dict:
    """{week: {sleeper id: {status, practice}}} from the season's official
    reports so far - final reports only: a row is kept when it carries a game
    status, which only the last report of the week does. Network (nflverse,
    about 30 KB); an empty dict when it cannot be read, and the chances fall
    back to status and role."""
    if frame is None:
        if year in _REPORTS:
            return _REPORTS[year]
        try:
            import nflreadpy as nfl
            frame = nfl.load_injuries(seasons=[year]).to_pandas()
        except Exception as exc:                            # noqa: BLE001
            print(f"  ! nflverse injury reports unavailable ({exc}); status and role only")
            _REPORTS[year] = {}
            return {}
    try:
        registry = pd.read_parquet(paths.PLAYERS_DIR / "registry.parquet",
                                   columns=["gsis_id", "sleeper_id"])
    except Exception:                                       # noqa: BLE001
        registry = pd.DataFrame(columns=["gsis_id", "sleeper_id"])
    out = reports_by_week(frame, registry)
    _REPORTS[year] = out
    return out


def reports_by_week(frame: pd.DataFrame, registry: pd.DataFrame) -> dict:
    """The pure half of official_reports: nflverse rows -> {week: {sleeper id:
    {status, practice}}}, for rows with a game status."""
    if frame is None or frame.empty:
        return {}
    ids = (registry.dropna(subset=["gsis_id", "sleeper_id"]).drop_duplicates("gsis_id")
           .set_index("gsis_id")["sleeper_id"])
    rows = _final_rows(frame)
    rows = rows[rows["report_status"].isin(STATUSES) & rows["position"].isin(POSITIONS)]
    out = {}
    for r in rows.itertuples(index=False):
        sid = ids.get(r.gsis_id)
        if sid is None:
            continue
        out.setdefault(int(r.week), {})[str(sid)] = {
            "status": r.report_status,
            "practice": PRACTICE.get(r.practice_status) if isinstance(r.practice_status, str)
            else None}
    return out


def last_season(year: int = UPCOMING_YEAR) -> dict | None:
    """{sleeper id: snap share} for the season before `year`, from the roles
    file refit() writes; None when the file is missing or is another season's."""
    try:
        saved = json.loads(ROLES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if int(saved.get("season") or 0) != year - 1:
        return None
    return saved.get("share") or {}


def snap_shares(week: int, year: int = UPCOMING_YEAR, usage: pd.DataFrame = None,
                last: dict = None) -> dict:
    """{sleeper id: offensive snap share} the way the table's roles were read:
    his last RECENT games this season before `week` (Sleeper's off_snp over
    tm_off_snp, fantasy.league.usage), else last season's from the roles file."""
    if usage is None:
        from fantasy.league import usage as usage_mod
        try:
            usage = usage_mod.load(year)
        except Exception:                                   # noqa: BLE001
            usage = pd.DataFrame()
    if last is None:
        last = last_season(year) or {}
    out = {str(k): float(v) for k, v in last.items()}
    if usage is not None and len(usage):
        u = usage[(usage["week"] < week) & (usage["off_snp"] > 0) & (usage["tm_off_snp"] > 0)]
        u = u.assign(share=u["off_snp"] / u["tm_off_snp"]).sort_values("week")
        for sid, s in u.groupby(u["sleeper_id"].astype(str))["share"]:
            out[sid] = float(s.tail(RECENT).mean())
    return out


def chance(status: str, role: str = None, practice: str = None, table: dict = None) -> dict:
    """{p, n, key} for one player: 0 for a tag that rules him out, the table's
    rate for Questionable or Doubtful, 1 otherwise."""
    if status in ZERO:
        return {"p": 0.0, "n": 0, "key": None}
    if status not in PRICED:
        return {"p": 1.0, "n": 0, "key": None}
    rates = (table if table is not None else load_table()).get("rates") or {}
    p, n, key = lookup(rates, status, role, practice)
    if p is None:                                   # no table on disk: the old rule
        p = {"Questionable": 1.0, "Doubtful": 0.25}[status]
    return {"p": p, "n": n, "key": key}


def week_chances(tags: dict, week: int, year: int = UPCOMING_YEAR, positions: dict = None,
                 reports: dict = None, shares: dict = None, table: dict = None) -> dict:
    """{sleeper id: {p, status, practice, role, n}} for every player Sleeper
    tags (or the official final report lists) this week; anyone absent plays.

    tags       {sleeper id: Sleeper's injury_status}
    positions  {sleeper id: position}, for kickers' role (optional)
    reports    {sleeper id: {status, practice}} - this week's final report
               (official_reports()[week]); read from nflverse when None
    shares     {sleeper id: snap share} (snap_shares()); read when None

    The status is Sleeper's tag, which moves within minutes of the news; the
    official report is a day behind on nflverse. Its practice is used only
    when its status says the same thing - the same report - and its status
    stands in for a tag Sleeper does not have.
    """
    positions = positions or {}
    if reports is None:
        reports = official_reports(year).get(int(week), {})
    # A player with no snaps anywhere is "new" - unless last season's roles
    # are missing, when no snaps says nothing and his status alone prices him.
    roles_known = True
    if shares is None:
        last = last_season(year)
        roles_known = last is not None
        shares = snap_shares(week, year, last=last or {})
    out = {}
    for sid in set(tags) | set(reports):
        sid = str(sid)
        tag = tags.get(sid) or ""
        rep = reports.get(sid) or {}
        status = tag or rep.get("status") or ""
        if status not in ZERO and status not in PRICED:
            continue
        practice = rep.get("practice") if rep.get("status") == status else None
        pos = positions.get(sid) or ""
        share = shares.get(sid)
        role = ("kick" if pos == "K" else
                role_of(share) if share is not None or roles_known else None)
        c = chance(status, role, practice, table)
        out[sid] = {"p": c["p"], "n": c["n"], "status": status, "practice": practice,
                    "role": role}
    return out


def apply(wk: pd.DataFrame, chances: dict, dips: dict = None) -> pd.DataFrame:
    """`wk` (fantasy.league.matchups.week_projections, computed without its
    injury factor) with `proj_full` - the projection if he plays - `p_play`,
    and proj_week = proj_full x p_play.

    `dips` is {sleeper id: multiplier} for players whose game this week is
    one of their first back from an injury (fantasy.league.return_dip
    .week_factors): if he plays, he plays part of the game, so it comes off
    proj_full. Kept as `dip` (1.0 for everyone else)."""
    wk = wk.copy()
    p = pd.Series({str(k): float(v["p"]) for k, v in chances.items()}, dtype=float)
    dip = pd.Series({str(k): float(v) for k, v in (dips or {}).items()}, dtype=float)
    wk["dip"] = dip.reindex(wk.index.astype(str)).fillna(1.0).to_numpy()
    wk["proj_full"] = wk["proj_week"] * wk["dip"]
    wk["p_play"] = p.reindex(wk.index.astype(str)).fillna(1.0).to_numpy()
    wk["proj_week"] = wk["proj_full"] * wk["p_play"]
    return wk


def playing(stats: dict = None, pts=None) -> bool:
    """Whether a started game shows him in it: Sleeper's stat line has him
    with a game played or points. Once he is out there, the chance is spent."""
    stats = stats or {}
    return bool(stats.get("gp")) or bool(pts)


# --------------------------------------------------------------------------- #
# Words
# --------------------------------------------------------------------------- #

def shown(p: float) -> int:
    """The percentage a reader sees: to the nearest five - the table is not
    surer than that."""
    return int(round(p * 20)) * 5


def label(p: float) -> str:
    """"plays 70%", with the ends said as ends."""
    if p < 0.05:
        return "plays <5%"
    if p > 0.95:
        return "plays >95%"
    return f"plays {shown(p)}%"


def level(p: float) -> str:
    """good / fair / poor for the badge's colour, on the figure it shows:
    green when he nearly always plays, amber for a real risk, red when he
    more likely sits."""
    pct = shown(p)
    return "good" if pct >= 85 else "fair" if pct >= 50 else "poor"


def tip(info: dict, table: dict = None) -> str:
    """One sentence for the badge's title: what the chance is read from."""
    table = table if table is not None else load_table()
    seasons = table.get("seasons") or [FIRST_SEASON, LAST_SEASON]
    what = info["status"]
    if info.get("practice"):
        what += f", {PRACTICE_WORDS[info['practice']]} before the final report"
    else:
        what += " (no final practice report yet)"
    n = info.get("n") or 0
    return (f"{what}, {ROLE_WORDS.get(info.get('role'), 'a player')}: "
            f"{info['p'] * 100:.0f}% of players like him played, "
            f"{seasons[0]}-{str(seasons[1])[-2:]}" + (f" ({n:,} cases)" if n else "") + ".")


def back_label(entry: dict, season_end: date = None, today: date = None,
               holds=None) -> str:
    """"back ~Nov 1" from ESPN's expected return date, "out for season" when
    it falls after the regular season, "" when there is nothing to say: no
    date, a status that holds nobody out (`holds`,
    fantasy.league.injury_report.HOLDS), or a date no later than `today` -
    which callers set to the week's last game, since ESPN dates a Doubtful
    player's return to the very game he is doubtful for, and the play chance
    already says what that week holds."""
    if not entry or not entry.get("back"):
        return ""
    if holds is None:
        from fantasy.league import injury_report
        holds = injury_report.HOLDS
    if entry.get("status") not in holds:
        return ""
    try:
        due = date.fromisoformat(str(entry["back"])[:10])
    except ValueError:
        return ""
    if due <= (today or date.today()):
        return ""
    if season_end and due > season_end:
        return "out for season"
    return f"back ~{due:%b} {due.day}"


def week_end(games: list) -> date | None:
    """The day of the week's last kickoff (UTC), from the scoreboard's games."""
    days = [str(g.get("date") or "")[:10] for g in games or [] if g.get("date")]
    try:
        return max(date.fromisoformat(d) for d in days) if days else None
    except ValueError:
        return None


def season_end(year: int = UPCOMING_YEAR) -> date | None:
    """The regular season's last game day, from the NFL schedule on disk."""
    try:
        from nfl import games
        frame = pd.read_parquet(games.season_path(year))
        frame = frame[frame["seasontype"] == 2]
        return pd.to_datetime(frame["date_utc"], utc=True).max().date()
    except Exception:                                       # noqa: BLE001
        return None


def return_labels(ids, year: int = UPCOMING_YEAR, report: dict = None,
                  after: date = None) -> dict:
    """{sleeper id: "back ~Nov 1" / "out for season"} for the ids ESPN holds
    out with a date past `after` (the week's last game; today when None),
    from fantasy.league.injury_report."""
    try:
        from fantasy.league import injury_report
        holds = injury_report.HOLDS
        if report is None:
            report = injury_report.report()
    except Exception as exc:                                # noqa: BLE001
        print(f"  ! ESPN injury report unavailable ({exc}); no return dates")
        return {}
    end = season_end(year)
    out = {}
    for sid in ids:
        text = back_label(report.get(str(sid)), end, today=after, holds=holds)
        if text:
            out[str(sid)] = text
    return out


def show(table: dict = None) -> None:
    table = table if table is not None else load_table()
    rates = table.get("rates") or {}
    print(f"fitted {table.get('fitted')} on {table.get('seasons')}, prior {table.get('prior')}")
    for status in PRICED:
        print(f"\n{status}: {lookup(rates, status)[0]:.1%}")
        for role in ROLES:
            row = [f"{role:>6}"]
            for practice in ("Full", "Limited", "DNP"):
                p, n, key = lookup(rates, status, role, practice)
                exact = key == _key(status, role, practice)
                row.append(f"{practice} {p:5.1%} ({n if exact else '-'})")
            print("  " + "  ".join(row))
    v = table.get("validation") or {}
    if v:
        q = v["questionable"]
        print(f"\nheld out {v['test']}: Questionable n={q['n']} said {q['said']:.1%} "
              f"played {q['played']:.1%}; log loss {q['log_loss']} (status only "
              f"{q['status_only_log_loss']}), Brier {q['brier']} (old rule {q['old_rule_brier']})")
        for status, role, practice, said, played, n in v["cells"]:
            print(f"  {status:<12} {role:<6} {practice:<8} said {said:5.1%}  played {played:5.1%}  n={n}")


if __name__ == "__main__":
    import sys
    if "--show" in sys.argv:
        show()
    else:
        show(refit())
