"""
Combining rankings that were never built to be combined.

Three sources rate the same ten rosters and none of them agree. Ours simulates
the season (`fantasy.league.power`); FantasyPros scores roster value
(`fantasy.league.external`); The Fantasy Footballers grade a roster and publish
a projected points-per-game. They cannot be averaged as they arrive — one is
simulated points per week, one is a value index, one is PPG — but each is, in
its own units, a statement about how far above or below the league a roster is.

So each source is rescaled to the same footing: 100 is the league average and
every point is one percent better than that. Ranks are deliberately not what
gets averaged. A rank throws away the only thing worth keeping — that Max is
not a normal tenth, he is eleven points below the field, and that the teams
ranked two through nine are separated by less than that gap between them.

Two products come out of this:

  * `freeze()` writes the draft consensus, all three sources as of draft week,
    once. It is a historical record and refuses to overwrite itself, because a
    draft ranking that quietly restated itself in November would be worthless.
  * `combined()` is the live blend of our simulation and FantasyPros, which is
    what the power page ranks on. The Footballers are not in it: a screenshot
    cannot be refetched, and a stale third of a live number is worse than two
    fresh ones.
"""
import json
from datetime import date

import pandas as pd

from fantasy import paths
from fantasy.config import UPCOMING_YEAR
from fantasy.league import external

# Ours and FantasyPros, equally weighted. Ours is the only one that models byes,
# injuries, the real schedule and a legal weekly lineup; theirs is the only one
# that is not ours. Neither advantage is obviously worth more than the other.
LIVE_WEIGHTS = {"us": 1.0, "FP": 1.0}


def _dir(year: int):
    return paths.DATA_DIR / "power" / str(year)


def draft_path(year: int = UPCOMING_YEAR):
    return _dir(year) / "draft_consensus.json"


def footballers_path(year: int = UPCOMING_YEAR):
    return _dir(year) / "footballers.json"


def centred(values: pd.Series) -> pd.Series:
    """Rescale so 100 is the league average and a point is one percent."""
    return 100.0 * values / values.mean()


def blend(ratings: dict, weights: dict = None) -> pd.DataFrame:
    """{source: Series by roster_id} -> a frame of each source plus `combined`.

    Every source is centred first, so a source with a wider spread does not
    get a louder vote purely because of the units it happened to arrive in.
    """
    weights = weights or {}
    frame = pd.DataFrame({name: centred(series) for name, series in ratings.items()})
    used = [w for w in (weights.get(name, 1.0) for name in frame.columns)]
    frame["combined"] = (frame * used).sum(axis=1) / sum(used)
    frame["rank"] = frame["combined"].rank(ascending=False, method="min").astype(int)
    return frame.sort_values("combined", ascending=False)


def footballers(year: int = UPCOMING_YEAR) -> pd.DataFrame:
    """The hand-entered Footballers grades, or empty."""
    path = footballers_path(year)
    if not path.exists():
        return pd.DataFrame(columns=["roster_id", "ff_rank", "ff_ppg", "ff_grade"])
    snap = json.loads(path.read_text(encoding="utf-8"))
    return pd.DataFrame([{"roster_id": int(t["team_id"]), "ff_rank": int(t["rank"]),
                          "ff_ppg": float(t["ppg"]), "ff_grade": t.get("grade", "")}
                         for t in snap["teams"]])


def combined(table: pd.DataFrame, ext: pd.DataFrame) -> pd.DataFrame:
    """Our table plus a `combined` rating and rank. Ours alone if FP is missing."""
    table = table.copy()
    if ext.empty or "ext_vorp" not in ext.columns:
        table["combined"] = centred(table["power"]).to_numpy()
        table["combined_rank"] = table["combined"].rank(ascending=False,
                                                        method="min").astype(int)
        return table

    table = table.merge(ext, on="roster_id", how="left")
    ours = table.set_index("roster_id")["power"]
    theirs = table.set_index("roster_id")["ext_vorp"]
    if theirs.isna().any():                    # a roster the source does not carry
        theirs = theirs.fillna(centred(ours).reindex(theirs.index))

    mixed = blend({"us": ours, "FP": theirs}, LIVE_WEIGHTS)
    table["combined"] = table["roster_id"].map(mixed["combined"])
    table["combined_rank"] = table["roster_id"].map(mixed["rank"])
    return table


def freeze(year: int = UPCOMING_YEAR, force: bool = False) -> dict:
    """Write the three-source draft consensus, once.

    Refuses to overwrite: this is the record of what everyone thought coming
    out of the draft, and its whole value is that it does not move. Pass
    `force` only to correct a mistake made the same day it was written.
    """
    path = draft_path(year)
    if path.exists() and not force:
        return json.loads(path.read_text(encoding="utf-8"))

    from fantasy.league import power                    # heavy; only needed here
    table, _, _ = power.rankings(year)
    ext = external.load(year)
    ff = footballers(year)
    if ext.empty or ff.empty:
        raise ValueError("the draft consensus needs all three sources present")

    ratings = {"us": table.set_index("roster_id")["power"],
               "FP": ext.set_index("roster_id")["ext_vorp"],
               "FF": ff.set_index("roster_id")["ff_ppg"]}
    mixed = blend(ratings)

    names = external.team_names()
    managers = table.set_index("roster_id")["manager"]
    ff_rank = ff.set_index("roster_id")["ff_rank"]
    ext_rank = ext.set_index("roster_id")["ext_rank"]
    our_rank = table.set_index("roster_id")["rank"]

    snap = {
        "title": "Draft consensus",
        "note": ("What our simulation, FantasyPros and The Fantasy Footballers each "
                 "made of these rosters coming out of the draft. Frozen on the date "
                 "below and never recomputed."),
        "season": year,
        "frozen": date.today().isoformat(),
        "sources": ["us", "FP", "FF"],
        "teams": [{"roster_id": int(rid),
                   "manager": managers.get(rid, ""),
                   "team": names.get(rid, ""),
                   "rank": int(row["rank"]),
                   "combined": round(float(row["combined"]), 2),
                   "us": round(float(row["us"]), 2),
                   "fp": round(float(row["FP"]), 2),
                   "ff": round(float(row["FF"]), 2),
                   "us_rank": int(our_rank.get(rid, 0)),
                   "fp_rank": int(ext_rank.get(rid, 0)),
                   "ff_rank": int(ff_rank.get(rid, 0))}
                  for rid, row in mixed.iterrows()],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snap, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return snap


def draft(year: int = UPCOMING_YEAR) -> dict:
    """The frozen draft consensus, or {} if it was never written."""
    path = draft_path(year)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
