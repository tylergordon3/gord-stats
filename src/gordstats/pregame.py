"""
A projection as it stood before kickoff, kept - shared by both fantasy sections.

Both matchups pages said "GordStats had X going in" for a finished week, and
scored GordStats' accuracy, from numbers rebuilt with today's fit and board -
which had already seen the games. The outside sources' projections are
archived with the week; ours were not, so each week's honest number was lost.

`freeze_at` records the projection of every player whose game has not
started (overwriting as lines and injury news move) and, once it has, hands
back the last value recorded instead of today's. Rows need `proj_week` and the
game's `state` ("pre" / "in" / "post"; no state - a bye - counts as "pre").
"""
import json
from pathlib import Path

import pandas as pd


def load(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def freeze_at(path: Path, wk: pd.DataFrame) -> pd.DataFrame:
    """`wk` with every started player's proj_week as recorded before his
    kickoff, every unstarted player's current one recorded, and a `pregame`
    column saying which rows are honest. A started player with no record keeps
    the recomputed value and is marked so."""
    kept = load(path)
    wk = wk.copy()
    state = wk["state"] if "state" in wk else pd.Series("pre", index=wk.index)
    pre = state.fillna("pre").eq("pre")
    changed = False
    for pid in wk.index[pre]:
        v = wk.at[pid, "proj_week"]
        if pd.notna(v) and kept.get(str(pid)) != round(float(v), 2):
            kept[str(pid)] = round(float(v), 2)
            changed = True
    wk["pregame"] = pre
    for pid in wk.index[~pre]:
        if str(pid) in kept:
            wk.at[pid, "proj_week"] = kept[str(pid)]
            wk.at[pid, "pregame"] = True
    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(kept, indent=0, sort_keys=True))
    return wk


def complete(wk: pd.DataFrame) -> bool:
    """Whether every projected player in `wk` has an honest pre-game number."""
    if "pregame" not in wk:
        return False
    projected = wk["proj_week"].notna()
    return bool(wk.loc[projected, "pregame"].all())
