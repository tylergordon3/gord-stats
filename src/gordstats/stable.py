"""
Writes that leave a data file alone when nothing in it changed.

The Pi commits data/ after every run, and a parquet file is compressed: git
cannot delta one version against the last, so every rewrite is stored whole.
Rewrites that changed nothing were most of the repository's growth - about
7 MB a day in September 2026 (the 2026-09-28 audit): the CFB usage table came
back in a different row order each run (identical once sorted), and the
prediction and odds archives restamped every game's same-day capture with a
new time and a last-decimal wobble.

    write_parquet(frame, path, sort_by=...)   skip the write if the file
                                              already holds this frame (the
                                              mtime is still touched, since
                                              several caches age on it)
    drop_repeats(old, fresh, key)             an archive's new captures, less
                                              the ones that only restate the
                                              same day's last capture
"""
import io
import os
from pathlib import Path

import pandas as pd


def _roundtrip(frame: pd.DataFrame) -> pd.DataFrame:
    buf = io.BytesIO()
    frame.to_parquet(buf, index=False)
    buf.seek(0)
    return pd.read_parquet(buf)


def write_parquet(frame: pd.DataFrame, path, sort_by=None) -> bool:
    """Write `frame` to `path` unless the file already holds exactly it.
    Returns whether it wrote. `sort_by` fixes the row order first, so a
    source that returns rows in any order still writes the same file."""
    path = Path(path)
    if sort_by:
        cols = [c for c in sort_by if c in frame.columns]
        frame = frame.sort_values(cols, kind="mergesort").reset_index(drop=True)
    if path.exists():
        try:
            if _roundtrip(frame).equals(pd.read_parquet(path)):
                os.utime(path)            # still "fresh" to caches that age on mtime
                return False
        except Exception:                                   # noqa: BLE001
            pass                          # unreadable or a different shape: rewrite
    frame.to_parquet(path, index=False)
    return True


def _signature(row, cols, places: int) -> tuple:
    out = []
    for c in cols:
        v = row[c]
        if v is None or (not isinstance(v, (list, dict)) and pd.isna(v)):
            out.append(None)
        elif isinstance(v, float):
            out.append(round(v, places))
        else:
            out.append(v)
    return tuple(out)


def drop_repeats(old: pd.DataFrame | None, fresh: pd.DataFrame, key: list,
                 places: int = 3) -> pd.DataFrame:
    """`fresh` without the rows that say what `old` already says for the same
    game on the same day - the capture archives keep one row per game per day,
    and replacing an unchanged one only moved its timestamp. Both frames carry
    an ISO `captured` column; every other column but `key` is compared,
    floats to `places` decimals."""
    if old is None or old.empty or fresh.empty:
        return fresh
    cols = [c for c in fresh.columns if c not in key and c != "captured" and c in old.columns]
    last = {}
    for r in old.to_dict("records"):
        last[tuple(r[k] for k in key) + (str(r["captured"])[:10],)] = _signature(r, cols, places)
    keep = []
    for _, row in fresh.iterrows():
        k = tuple(row[c] for c in key) + (str(row["captured"])[:10],)
        keep.append(last.get(k) != _signature(row, cols, places))
    return fresh[keep]
