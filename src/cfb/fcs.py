"""
The FCS's own games, so an FCS opponent is rated as itself.

The training set (cfb.games) is every game with an FBS team in it, which
gives an FCS side one or two games a season - too few to rate, so every FCS
team was pooled into one generic opponent. That priced Montana State, who
won at Nevada by 13, the way it priced Mississippi Valley State, who lost by
52: through four weeks of 2026 the games with an FCS side were a third of the
board and missed by 3.2 points a game more than the book, against 1.4 on the
rest.

ESPN's FCS scoreboard (groups=81) serves the division's own games the way
the FBS one does, and with them each FCS team has ten or eleven games a
season against opponents that are themselves rated. `prepare` hands
cfb.ratings every Division I team under its own ESPN id - FBS and FCS on one
scale, each pulled toward its own conference's average rather than toward
the whole field's - with anyone below Division I pooled as NON_D1.

Walk-forward, every week fitted only on what came before it and the
efficiency correction refitted each season on the new ratings (cfb.backtest),
margin RMSE against the final, measured 2026-10-03:

                              2016-19          2020-25          2026, wks 1-5
    every game, before        16.94            16.33            17.21
    every game, with this     16.37            15.90            15.67
    FBS vs FBS only           16.64 -> 16.41   16.07 -> 15.88   15.91 -> 15.22
    the closing line          15.78            15.36            14.65

Better in nine of the ten earlier seasons (2020, when most of the FCS played
in the spring, is the exception) and most in weeks 1-4, where the gap to the
book was widest (17.55 -> 16.42 on 2016-25). On 2026's board the average
miss went from 13.7 to 12.7 points (the book's 11.6); on the games with an
FCS side, from 16.0 to 14.0. Totals are unchanged - the total model still
pools the FCS (cfb.ratings._fit_levels says why). Against the spread it is
still a coin flip: closer to the book, not ahead of it.

    data/cfb/fcs_games/<season>.parquet   one row per FCS-division game

    python -m cfb.fcs                     backfill and refresh the archive
"""
import time

import pandas as pd

from cfb import espn
from cfb.config import DATA_DIR, SEASON
from cfb.games import FCS, FIRST_SEASON, MAX_WEEK
from gordstats import stable

ARCHIVE = DATA_DIR / "fcs_games"
GROUP = 81                     # ESPN's group id for the FCS slate
MIN_GAMES = 6                  # a team on the FCS schedule this often is FCS
NON_D1 = "Non-D1"              # every opponent below Division I, pooled
_PAUSE = 0.3


def season_path(season: int):
    return ARCHIVE / f"{season}.parquet"


def fetch_season(season: int) -> pd.DataFrame:
    """Every regular-season game ESPN files under the FCS, one request a week -
    scheduled ones too, which is what membership is counted from."""
    rows = []
    for week in range(1, MAX_WEEK + 1):
        data = espn._get({"groups": GROUP, "week": week, "dates": season,
                          "seasontype": 2, "limit": 500})
        for event in data.get("events", []):
            if not event.get("competitions"):
                continue
            try:
                row = espn._game_row(event, week)
            except (KeyError, IndexError, TypeError):
                continue
            row["season"] = season
            rows.append(row)
        time.sleep(_PAUSE)
    return pd.DataFrame(rows)


def capture(refresh: bool = False) -> None:
    """Past seasons fetched once, when missing (the first run backfills all
    of them, ~200 requests); this one again on `refresh` or once its file is
    older than the schedule's own (espn.MAX_AGE_HOURS). A fetch that fails
    keeps the last copy, and the next run tries again."""
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    # Newest first: a backfill cut short still has the seasons that weigh most.
    for season in range(SEASON, FIRST_SEASON - 1, -1):
        path = season_path(season)
        if path.exists() and (season < SEASON or not refresh
                              and espn._is_fresh(path, espn.MAX_AGE_HOURS)):
            continue
        frame = fetch_season(season)
        if not frame.empty:
            stable.write_parquet(frame, path)     # unchanged: mtime only


def load(first: int = FIRST_SEASON, last: int = SEASON) -> pd.DataFrame:
    """Every stored season's rows, scheduled and played; empty when the
    archive has not been fetched. Never fetches."""
    frames = []
    for season in range(first, last + 1):
        path = season_path(season)
        if path.exists():
            try:
                frames.append(pd.read_parquet(path))
            except (OSError, ValueError) as exc:
                print(f"  ! FCS archive {season} unreadable ({exc})")
    if not frames:
        return pd.DataFrame()
    rows = pd.concat(frames, ignore_index=True)
    for side in ("home", "away"):
        rows[f"{side}_id"] = rows[f"{side}_id"].astype(str)
        conf = f"{side}_conf_id"
        rows[conf] = rows[conf].fillna("").astype(str) if conf in rows else ""
    return rows


def played(rows: pd.DataFrame) -> pd.DataFrame:
    """Finished games with a score, shaped like cfb.games.load(): no 0-0
    "finals" and nothing called off (the same traps as the FBS archive)."""
    if rows.empty:
        return rows
    done = rows[(rows["state"] == "post") & rows["home_score"].notna()
                & rows["away_score"].notna()
                & ((rows["home_score"] > 0) | (rows["away_score"] > 0))]
    detail = (done["detail"] if "detail" in done else pd.Series("", index=done.index))
    done = done[~detail.fillna("").astype(str).str.contains("Cancel|Postpon")].copy()
    done["date"] = pd.to_datetime(done["date_utc"], format="ISO8601", utc=True)
    done["margin"] = done["home_score"] - done["away_score"]
    done["total"] = done["home_score"] + done["away_score"]
    return done


def _season_rows(rows: pd.DataFrame, season: int) -> pd.DataFrame:
    """The season's schedule, or the latest one before it on file (a
    season ESPN has not published yet)."""
    have = rows[rows["season"] <= season]
    if have.empty:
        return have
    return have[have["season"] == have["season"].max()]


def members(rows: pd.DataFrame, season: int) -> set:
    """The FCS teams of `season`, by ESPN id: on its FCS schedule (or the
    one before it) MIN_GAMES times or more - an FBS side or a lower-division
    visitor appears once or twice. The season before counts too because one
    season can be short: in the autumn of 2020 most of the FCS did not play,
    and rating only the dozen teams that did pooled the rest - and all their
    earlier seasons - with Division II."""
    block = _season_rows(rows, season)
    if block.empty:
        return set()
    latest = int(block["season"].max())
    block = rows[rows["season"].isin([latest, latest - 1])]
    out = set()
    for _, one in block.groupby("season"):
        counts = pd.concat([one["home_id"], one["away_id"]]).value_counts()
        out |= set(counts[counts >= MIN_GAMES].index)
    return out


def conferences(rows: pd.DataFrame, season: int = None) -> dict:
    """ESPN id -> conference id, as of `season` (every season when None) -
    the most frequent one a team is filed under."""
    block = rows if season is None else _season_rows(rows, season)
    sides = pd.concat([
        block[["home_id", "home_conf_id"]].set_axis(["id", "conf"], axis=1),
        block[["away_id", "away_conf_id"]].set_axis(["id", "conf"], axis=1)])
    return most_common(sides)


def most_common(sides: pd.DataFrame) -> dict:
    """{id: the conf it is filed under most often} from (id, conf) rows,
    blanks ignored."""
    sides = sides.astype(str)
    sides = sides[sides["conf"].str.len() > 0]
    if sides.empty:
        return {}
    counts = sides.value_counts().reset_index(name="n")
    top = counts.sort_values(["n", "conf"], ascending=[False, True]).drop_duplicates("id")
    return dict(zip(top["id"], top["conf"]))


def conference_history(games: pd.DataFrame, rows: pd.DataFrame) -> dict:
    """{season: {ESPN id: conference id}} from every row that names one: the
    FBS archive where it carries ESPN's conference ids, and the FCS archive,
    whose games against FBS teams name the FBS side's conference too."""
    out = {}
    for table in (rows, games):
        if table is None or table.empty or "home_conf_id" not in table.columns:
            continue
        for season, block in table.groupby("season"):
            block = block.copy()
            for side in ("home", "away"):
                block[f"{side}_id"] = block[f"{side}_id"].astype(str)
                block[f"{side}_conf_id"] = block[f"{side}_conf_id"].fillna("").astype(str)
            out.setdefault(int(season), {}).update(conferences(block))
    return out


def fbs_conferences(games: pd.DataFrame, season: int, history: dict) -> dict:
    """A past season's FBS teams (cfb.games' own per-season classification)
    -> their conference that season, or the nearest season that names one."""
    block = games[games["season"] == season]
    teams = (set(block["home_team"]) | set(block["away_team"])) - {FCS}
    order = sorted(history, key=lambda s: (abs(s - season), s > season))
    out = {}
    for team in teams:
        out[str(team)] = next((history[s][str(team)] for s in order
                               if str(team) in history[s]), "")
    return out


def prepare(games: pd.DataFrame, asof, fbs_conf: dict, season: int,
            rows: pd.DataFrame = None):
    """(games to fit on, levels, divisions) for cfb.ratings.fit, or None when
    there is no FCS archive to add - the ratings then fit as they always have.

    `games` is the FBS archive (raw ESPN ids in home_id/away_id) and
    `fbs_conf` this season's FBS teams with their conferences. Every game in
    either archive before `asof` is keyed by who its teams are *this* season:
    an FBS or FCS team by its id, everyone else NON_D1 - so a school that has
    moved up keeps its whole record, as cfb.predict already does for the FBS.
    """
    rows = load(FIRST_SEASON, season) if rows is None else rows
    if rows.empty or games.empty or "home_id" not in games or "away_id" not in games:
        return None
    fbs = {str(t) for t in fbs_conf}
    fcs = members(rows, season) - fbs
    if not fcs:
        return None
    fcs_conf = conferences(rows, season)

    own = games[["date", "game_id", "home_id", "away_id", "neutral", "margin", "total"]]
    extra = played(rows)
    extra = extra[~extra["game_id"].astype(str).isin(set(own["game_id"].astype(str)))]
    both = pd.concat([own, extra[own.columns]], ignore_index=True)
    both = both[both["date"] < asof].copy()

    def key(ids: pd.Series) -> pd.Series:
        ids = ids.astype(str)
        return ids.where(ids.isin(fbs) | ids.isin(fcs), NON_D1)

    both["home_team"] = key(both["home_id"])
    both["away_team"] = key(both["away_id"])
    both["neutral"] = both["neutral"].fillna(False).astype(bool)
    divisions = {t: "fbs" for t in fbs}
    divisions.update({t: "fcs" for t in fcs})
    divisions[NON_D1] = "nond1"
    levels = {str(t): f"fbs:{c or '-'}" for t, c in fbs_conf.items()}
    levels.update({t: f"fcs:{fcs_conf.get(t) or '-'}" for t in fcs})
    levels[NON_D1] = "nond1"
    return both.reset_index(drop=True), levels, divisions


if __name__ == "__main__":
    capture()
    stored = load()
    if stored.empty:
        raise SystemExit("nothing on disk")
    print(stored.groupby("season").size().to_string())
    print(f"\n{FCS} teams this season: {len(members(stored, SEASON))}")
