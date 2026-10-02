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

A frame that carries `p_play` - the chance he plays that proj_week was priced
at (the NFL page's) - has it kept the same way, in its own file beside the
projections (chances_path), so the projection file stays {id: points} for
everything that reads it. Without it a frozen number was divided by today's
chance, which can have learned something after kickoff: a player listed on
the official report a day after his game read 9.0 / 0.649 = 13.9 "if he
plays". An archive from before the chances were kept has no such file, and
its started players keep today's chance, as they always did.

On the Pi a kept number also has an untracked copy (sidecar(); switched on by
GS_PREGAME_SIDECAR, which deploy/publish.sh exports). The live ticks commit
once an hour and start each run from `git checkout -- docs data`, so a number
kept at 12:50 for a 1:00 kickoff was thrown away by the 1:00 tick unless an
hourly commit fell in between - and after kickoff it can never be kept again.
The untracked copy survives the checkout; load() reads it over the tracked
file, and every write puts the merged numbers back in the tracked file, so
the next commit records them. Without the switch (the PC, the tests) only the
tracked file exists, as before.
"""
import json
import os
from pathlib import Path

import pandas as pd

SIDECAR_ENV = "GS_PREGAME_SIDECAR"


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text()) if path.exists() else {}
    except ValueError:
        return {}


def sidecar(path: Path):
    """The untracked copy of a kept file (data/<sport>/gs_proj_live/... for
    data/<sport>/gs_proj/...), or None where the switch is off."""
    if not os.environ.get(SIDECAR_ENV):
        return None
    parts = list(path.parts)
    if "gs_proj" in parts:
        parts[parts.index("gs_proj")] = "gs_proj_live"
        return Path(*parts)
    return path.with_name(path.stem + ".live" + path.suffix)


def load(path: Path) -> dict:
    """The kept numbers: the tracked file, with the untracked copy over it."""
    kept = _read(path)
    side = sidecar(path)
    if side is not None:
        kept.update(_read(side))
    return kept


def _store(path: Path, kept: dict) -> None:
    """Write `kept` wherever it differs from what is there - the tracked file
    included when a checkout has rolled it back, so a commit records it."""
    text = json.dumps(kept, indent=0, sort_keys=True)
    for where in (path, sidecar(path)):
        if where is None:
            continue
        if not where.exists() or _read(where) != kept:
            where.parent.mkdir(parents=True, exist_ok=True)
            where.write_text(text)


def chances_path(path: Path) -> Path:
    """Where the chances behind a projection file are kept: week_04.json's
    beside it as week_04_play.json."""
    return path.with_name(f"{path.stem}_play{path.suffix}")


def freeze_at(path: Path, wk: pd.DataFrame) -> pd.DataFrame:
    """`wk` with every started player's proj_week (and p_play, where the frame
    has one) as recorded before his kickoff, every unstarted player's current
    one recorded, and a `pregame` column saying which rows are honest. A
    started player with no record keeps the recomputed value and is marked
    so."""
    kept = load(path)
    has_p = "p_play" in wk.columns
    chances = load(chances_path(path)) if has_p else {}
    wk = wk.copy()
    state = wk["state"] if "state" in wk else pd.Series("pre", index=wk.index)
    pre = state.fillna("pre").eq("pre")
    changed = changed_p = False
    for pid in wk.index[pre]:
        v = wk.at[pid, "proj_week"]
        if pd.notna(v) and kept.get(str(pid)) != round(float(v), 2):
            kept[str(pid)] = round(float(v), 2)
            changed = True
        if has_p and pd.notna(v):
            p = wk.at[pid, "p_play"]
            if pd.notna(p) and chances.get(str(pid)) != round(float(p), 4):
                chances[str(pid)] = round(float(p), 4)
                changed_p = True
    wk["pregame"] = pre
    for pid in wk.index[~pre]:
        if str(pid) in kept:
            wk.at[pid, "proj_week"] = kept[str(pid)]
            wk.at[pid, "pregame"] = True
            if str(pid) in chances:
                wk.at[pid, "p_play"] = chances[str(pid)]
    # Written when something changed, or when the tracked file lags the merged
    # numbers (a checkout rolled it back) - _store writes only what differs.
    if changed or sidecar(path) is not None:
        if kept or path.exists():
            _store(path, kept)
    if has_p and (changed_p or sidecar(path) is not None):
        if chances or chances_path(path).exists():
            _store(chances_path(path), chances)
    return wk


def complete(wk: pd.DataFrame) -> bool:
    """Whether every projected player in `wk` has an honest pre-game number."""
    if "pregame" not in wk:
        return False
    projected = wk["proj_week"].notna()
    return bool(wk.loc[projected, "pregame"].all())
