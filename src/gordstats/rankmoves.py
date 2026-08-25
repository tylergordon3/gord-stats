"""
Rank-movement bookkeeping shared by the rating pages.

The ADP board and the fantasy power rankings each grew their own snapshot
archive; the college power pages are the third and fourth customers, so the
pattern lives here once. A page passes its current key->rank mapping:
`snapshot` archives it (at most one per GAP_HOURS, pruned after KEEP_DAYS),
and `movement` answers what the ranks were a build ago and a week ago, so
the page can print Move columns.

Snapshots are tiny CSVs named by timestamp under the directory the page
chooses - data that should be committed, since it is the only record of what
the page said before today.
"""
from datetime import datetime, timedelta

import pandas as pd

_FMT = "%Y%m%d-%H%M%S"
GAP_HOURS = 12          # four builds a day at most; one snapshot morning + evening
KEEP_DAYS = 400         # a full season plus the preseason drift before it


def _snaps(history_dir):
    out = []
    for path in sorted(history_dir.glob("*.csv")):
        try:
            out.append((datetime.strptime(path.stem, _FMT), path))
        except ValueError:
            continue
    return out


def _load(path) -> pd.Series:
    # Keys are always compared as strings: an ESPN team id round-trips
    # through CSV as an integer, and a lookup by the string it started as
    # then silently misses every row.
    df = pd.read_csv(path, dtype={"key": str})
    return df.set_index("key")["rank"]


def movement(history_dir, now=None) -> dict:
    """Baselines for the Move columns.

    'prev' is the newest snapshot at least GAP_HOURS old - the previous build
    that wasn't this one. 'prev7' is the newest at least a week old, falling
    back to the oldest on hand so a young archive still reports something;
    'prev7_at' says how far back it really goes.
    """
    now = now or datetime.now()
    snaps = _snaps(history_dir)
    out = {}
    older = [s for s in snaps if s[0] <= now - timedelta(hours=GAP_HOURS)]
    if older:
        out["prev"], out["prev_at"] = _load(older[-1][1]), older[-1][0]
    week = [s for s in snaps if s[0] <= now - timedelta(days=7)]
    # The fallback draws from `older`, not from every snapshot: on the very
    # first build the only file on disk is the one this build just wrote, and
    # a page comparing itself to itself rendered a column of dots.
    base = week[-1] if week else (older[0] if older else None)
    if base:
        out["prev7"], out["prev7_at"] = _load(base[1]), base[0]
    return out


def snapshot(history_dir, ranks: pd.Series, now=None):
    """Archive key->rank, unless one was taken in the last GAP_HOURS."""
    now = now or datetime.now()
    snaps = _snaps(history_dir)
    if snaps and now - snaps[-1][0] < timedelta(hours=GAP_HOURS):
        return
    history_dir.mkdir(parents=True, exist_ok=True)
    out = ranks.rename("rank").rename_axis("key").reset_index()
    out["key"] = out["key"].astype(str)
    out.to_csv(history_dir / f"{now:{_FMT}}.csv", index=False)
    cutoff = now - timedelta(days=KEEP_DAYS)
    for taken, path in snaps:
        if taken < cutoff:
            path.unlink()


def cell(delta) -> str:
    """A Move cell: green up-arrow, red down-arrow, or a quiet dot."""
    if delta is None or pd.isna(delta) or int(delta) == 0:
        return "<span class='mv-flat'>&middot;</span>" if delta is not None and not pd.isna(delta) else ""
    d = int(delta)
    if d > 0:
        return f"<span class='mv-up'>&#9650;{d}</span>"
    return f"<span class='mv-down'>&#9660;{-d}</span>"


# The classes cell() emits, for a page to include beside its own table CSS.
CSS = """
.mv-up{color:#1a7f4b;font-weight:700;font-size:12px}
.mv-down{color:#b3382c;font-weight:700;font-size:12px}
.mv-flat{color:#93a1ad}
@media (prefers-color-scheme: dark){
  .mv-up{color:#6ee7b7}
  .mv-down{color:#ff9b91}
}"""
