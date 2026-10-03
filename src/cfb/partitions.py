"""
Season archives kept as one file per capture day, so a commit rewrites only
the day it captured.

The Pi commits data/ after every run, and a parquet file is compressed: git
cannot delta one version against the last, so every rewrite of a season file
is stored whole. The prediction and odds archives were one file per season,
appended to by every daily run - by October 2026 the NFL one was rewritten ~14
times a day at 135 KB and growing, ~1 MB of history a day for rows that, but
for the day's own, had not changed since they were taken. Split by the UTC day
of `captured`, a run rewrites one ~20 KB file and every closed day is
byte-for-byte what it was.

The rules are the ones the single file had (gordstats.stable): one row per key
per day, the newest - except that a same-day capture saying what the last one
said keeps the last one, and its time.

    data/<sport>/predictions/2026.parquet       the old single file
    data/<sport>/predictions/2026/<day>.parquet one per capture day

`read` returns the whole season either way, so a caller never knows; a
machine still holding the single file (a checkout from before the split, or a
rebase that kept origin's copy) has it folded into the days by the next
`record`, checked, and then removed.

Writes go to `<name>.partial` beside the file and are renamed into place: a
new day's file is untracked until the run commits it, so the deploy's
`git checkout -- data` would not put back one a killed run had half-written.

    python -m cfb.partitions        # fold any single season file into days
"""
import io
import os
import time
from pathlib import Path

import pandas as pd

from gordstats import stable

PARTIAL = ".partial"            # gitignored


def directory(legacy) -> Path:
    """data/x/2026.parquet -> data/x/2026/"""
    return Path(legacy).with_suffix("")


def day_files(legacy) -> list:
    folder = directory(legacy)
    return sorted(folder.glob("*.parquet")) if folder.is_dir() else []


def _day(frame: pd.DataFrame) -> pd.Series:
    return frame["captured"].astype(str).str[:10]


def _fold(frame: pd.DataFrame, key: list) -> pd.DataFrame:
    """The newest row per key per day, in capture order. Rows of a run share
    one `captured`, so a stable sort keeps each run's own order - the order
    the single file had them in."""
    frame = frame.sort_values("captured", kind="mergesort").drop_duplicates()
    day = _day(frame).rename("_day")
    keep = ~pd.concat([frame[key], day], axis=1).duplicated(keep="last")
    return frame[keep.to_numpy()].reset_index(drop=True)


def _read(path: Path):
    """A partition, or None when it is missing or unreadable (a run killed
    before the rename leaves only a .partial, never a torn file - but a torn
    file must not stop every later run either)."""
    if not path.exists():
        return None
    try:
        return pd.read_parquet(path)
    except Exception as exc:                            # noqa: BLE001
        print(f"  ! unreadable archive file {path.name} ({exc}); treated as empty")
        return None


def write_parquet(frame: pd.DataFrame, path, sort_by=None) -> bool:
    """gordstats.stable.write_parquet, renamed into place rather than written
    over: skipped when the file already holds exactly `frame` (its mtime is
    still touched), and never left half-written."""
    path = Path(path)
    if sort_by:
        cols = [c for c in sort_by if c in frame.columns]
        frame = frame.sort_values(cols, kind="mergesort").reset_index(drop=True)
    old = _read(path)
    if old is not None:
        try:
            buf = io.BytesIO()
            frame.to_parquet(buf, index=False)
            buf.seek(0)
            if pd.read_parquet(buf).equals(old):
                os.utime(path)            # still "fresh" to caches that age on mtime
                return False
        except Exception:                               # noqa: BLE001
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + PARTIAL)
    frame.to_parquet(tmp, index=False)
    os.replace(tmp, path)
    return True


def write_text(path, text: str) -> bool:
    """Write `text` unless the file already says it; renamed into place."""
    path = Path(path)
    try:
        if path.exists() and path.read_text(encoding="utf-8") == text:
            return False
    except (OSError, UnicodeDecodeError):
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + PARTIAL)
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return True


_MEMO: dict = {}
# A file's mtime ticks coarsely (a few ms on this kernel), so two writes of the
# same size inside one tick look alike. A season is only kept in memory once
# every file under it is older than this - any later write then has to show.
_SETTLED_SECONDS = 2.0


def _signature(paths: list) -> tuple:
    out = []
    for p in paths:
        st = p.stat()
        out.append((str(p), st.st_mtime_ns, st.st_size, st.st_ino))
    return tuple(out)


def read(legacy, key: list):
    """The whole season - the single file if this machine still has one, and
    every day's file - oldest first; None when there is nothing at all.

    Read several times a build (each page asks for the record on its own, and
    by December there are ~150 day files), so the frame is kept until a file
    under it changes; callers get a copy."""
    legacy = Path(legacy)
    paths = ([legacy] if legacy.exists() else []) + day_files(legacy)
    if not paths:
        return None
    sig = _signature(paths)
    hit = _MEMO.get(str(legacy))
    if hit is not None and hit[0] == sig:
        return hit[1].copy()
    frames = [f for f in (_read(p) for p in paths) if f is not None]
    if not frames:
        return None
    whole = frames[0] if len(frames) == 1 else pd.concat(frames, ignore_index=True)
    if legacy.exists() and len(frames) > 1:
        # Not folded in yet: the same capture can be in both.
        whole = _fold(whole, key)
    if time.time() - max(s[1] for s in sig) / 1e9 > _SETTLED_SECONDS:
        _MEMO[str(legacy)] = (sig, whole)
    return whole.copy()


def record(legacy, fresh: pd.DataFrame, key: list):
    """Fold one capture run into its day's file; returns the whole season.

    `fresh` carries an ISO `captured`; every other column but `key` is what is
    compared to decide whether a same-day capture is new (stable.drop_repeats).
    """
    migrate(legacy, key)
    if fresh is not None and not fresh.empty:
        folder = directory(legacy)
        for day, rows in fresh.groupby(_day(fresh), sort=True):
            path = folder / f"{day}.parquet"
            old = _read(path)
            if old is None:
                merged = rows
            else:
                # An unchanged same-day capture keeps the row already there.
                merged = pd.concat([old, stable.drop_repeats(old, rows, key)],
                                   ignore_index=True)
            # One row per key per capture day: the last.
            merged = merged[~pd.concat([merged[key], _day(merged).rename("_day")],
                                       axis=1).duplicated(keep="last").to_numpy()]
            write_parquet(merged.reset_index(drop=True), path)
    return read(legacy, key)


def migrate(legacy, key: list) -> bool:
    """Split a single season file into day files, check every row arrived,
    and remove it. Day files already there are merged with it (newest row per
    key per day), so a rebase that kept origin's single file beside the day
    files loses nothing. Returns whether it removed the single file."""
    legacy = Path(legacy)
    whole = _read(legacy)
    if whole is None:
        return False
    if whole.empty:
        legacy.unlink()
        return True
    before = {p.name for p in day_files(legacy)}
    folder = directory(legacy)
    for day, rows in whole.groupby(_day(whole), sort=True):
        path = folder / f"{day}.parquet"
        old = _read(path)
        part = rows if old is None else _fold(pd.concat([old, rows], ignore_index=True), key)
        write_parquet(part.reset_index(drop=True), path)

    back = pd.concat([pd.read_parquet(p) for p in day_files(legacy)], ignore_index=True)
    if not before:
        ok = _same(back, whole)
    else:
        # Merged with day files already there: every (key, day) the single
        # file had is on record at least as late as it had it.
        def latest(frame):
            f = frame.assign(_day=_day(frame))
            return f.groupby(key + ["_day"])["captured"].max()
        have, need = latest(back), latest(whole)
        joined = need.to_frame("need").join(have.rename("have"), how="left")
        ok = bool((joined["have"].notna() & (joined["have"] >= joined["need"])).all())
    if not ok:
        print(f"  ! {legacy}: day files do not hold every row; keeping the single file")
        return False
    legacy.unlink()
    _MEMO.pop(str(legacy), None)
    print(f"  {legacy.name} split into {len(day_files(legacy))} day files under {folder.name}/")
    return True


def _same(a: pd.DataFrame, b: pd.DataFrame) -> bool:
    try:
        pd.testing.assert_frame_equal(a.reset_index(drop=True), b.reset_index(drop=True))
        return True
    except AssertionError:
        return False


def migrate_all() -> None:
    """Every archive this applies to (python -m cfb.partitions)."""
    from cfb import gameinfo, odds, results
    from nfl import results as nfl_results
    for season_path, key in ((results.season_path(), results.KEY),
                             (odds.season_path(), odds.ARCHIVE_KEY),
                             (nfl_results.season_path(), nfl_results.KEY)):
        migrate(season_path, key)
        if Path(season_path).exists():
            raise SystemExit(f"{season_path} was not split")
    gameinfo.migrate()


if __name__ == "__main__":
    migrate_all()
