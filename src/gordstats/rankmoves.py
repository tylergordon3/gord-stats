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


def snapshot(history_dir, ranks: pd.Series, now=None, extra: pd.DataFrame = None):
    """Archive key->rank, unless one was taken in the last GAP_HOURS.

    `extra` (indexed by key) rides along in the same CSV - a rating, a name -
    so a trend chart can draw more than the rank. `movement` reads only
    key and rank, so older files without the columns still serve it.
    """
    now = now or datetime.now()
    snaps = _snaps(history_dir)
    if snaps and now - snaps[-1][0] < timedelta(hours=GAP_HOURS):
        return
    history_dir.mkdir(parents=True, exist_ok=True)
    out = ranks.rename("rank").rename_axis("key").reset_index()
    out["key"] = out["key"].astype(str)
    if extra is not None and len(extra):
        more = extra.copy()
        more.index = more.index.astype(str)
        out = out.join(more, on="key")
    out.to_csv(history_dir / f"{now:{_FMT}}.csv", index=False)
    cutoff = now - timedelta(days=KEEP_DAYS)
    for taken, path in snaps:
        if taken < cutoff:
            path.unlink()


def history(history_dir) -> pd.DataFrame:
    """Every snapshot stacked, with `taken` - for a trend chart.

    Columns are whatever each file holds (key, rank, and any extras it was
    written with); a column absent from an older file is NaN there.
    """
    frames = []
    for taken, path in _snaps(history_dir):
        frames.append(pd.read_csv(path, dtype={"key": str}).assign(taken=taken))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# --------------------------------------------------------------------------- #
# Change over a window the reader picks
# --------------------------------------------------------------------------- #
#
# The Move/7d pair answers two fixed questions. A page with a season of
# snapshots behind it can answer "since when?" instead: these windows, each
# resolved to the newest snapshot old enough to serve as its baseline, and
# de-duplicated so a young archive does not offer three buttons that all
# point at the same file. A page renders every window's figure into the cell
# and the reader's button choice shows one; nothing is refetched.

WINDOWS = [
    ("last", "Last build", None),
    ("1d", "1 day", 1),
    ("3d", "3 days", 3),
    ("7d", "1 week", 7),
    ("14d", "2 weeks", 14),
    ("30d", "1 month", 30),
    ("60d", "2 months", 60),
    ("90d", "3 months", 90),
    ("season", "Season start", "oldest"),
]


def _load_full(path) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"key": str}).set_index("key")


def baselines(history_dir, now=None) -> dict:
    """{window key: {label, at, frame}} for every window the archive can serve.

    `frame` is the baseline snapshot indexed by key (rank plus whatever extras
    it was written with). "last" is the newest snapshot at least GAP_HOURS old,
    "season" the oldest such snapshot, the rest the newest at least N days
    old. A window whose baseline another window already uses is dropped.
    """
    now = now or datetime.now()
    snaps = [s for s in _snaps(history_dir) if s[0] <= now - timedelta(hours=GAP_HOURS)]
    if not snaps:
        return {}
    out, used = {}, set()
    for key, label, days in WINDOWS:
        if days == "oldest":
            pick = snaps[0]
        elif days is None:
            pick = snaps[-1]
        else:
            eligible = [s for s in snaps if s[0] <= now - timedelta(days=days)]
            if not eligible:
                continue
            pick = eligible[-1]
        if pick[1] in used:
            continue
        used.add(pick[1])
        out[key] = {"label": label, "at": pick[0], "frame": _load_full(pick[1])}
    return out


def _signed(v, dec: int) -> str:
    if v is None or pd.isna(v):
        return ""
    if abs(v) < 0.5 * 10 ** -dec:
        return "<span class='mv-flat'>&middot;</span>"
    cls = "mv-up" if v > 0 else "mv-down"
    return f"<span class='{cls}'>{v:+.{dec}f}</span>"


def move_spans(bases: dict, key: str, rank: int) -> tuple:
    """Every window's places-climbed for one key, as hidden spans the button
    bar reveals one at a time; and the first window's delta, for the sort."""
    key = str(key)
    parts, first = [], None
    for i, (win, b) in enumerate(bases.items()):
        frame = b["frame"]
        delta = (int(frame.loc[key, "rank"]) - rank) if key in frame.index else None
        if first is None and delta is not None:
            first = delta
        parts.append(f"<span data-win='{win}' data-v='{'' if delta is None else delta}'"
                     f"{' class=on' if i == 0 else ''}>{cell(delta)}</span>")
    return "".join(parts), first


def delta_spans(bases: dict, key: str, value: float, col: str, dec: int = 1) -> tuple:
    """Same, for a rating column carried in the snapshots' extras."""
    key = str(key)
    parts, first = [], None
    for i, (win, b) in enumerate(bases.items()):
        frame = b["frame"]
        delta = None
        if col in frame.columns and key in frame.index and not pd.isna(frame.loc[key, col]):
            delta = float(value) - float(frame.loc[key, col])
        if first is None and delta is not None:
            first = round(delta, dec)
        parts.append(f"<span data-win='{win}' data-v='{'' if delta is None else round(delta, dec)}'"
                     f"{' class=on' if i == 0 else ''}>{_signed(delta, dec)}</span>")
    return "".join(parts), first


def window_switch(bases: dict, label: str = "Change since:") -> str:
    """The button bar. Empty when the archive offers nothing to compare to."""
    if not bases:
        return ""
    def text(win, b):
        # The date is the point; "Last build" said nothing about when that was.
        if win == "last":
            return f"{b['at']:%b %-d, %-I:%M %p}"
        return f"{b['label']} <span class='win-when'>{b['at']:%b %-d}</span>"
    buttons = "".join(
        f'<button type="button" class="win-btn{" active" if i == 0 else ""}" data-win="{win}" '
        f'title="Since {b["at"]:%b %-d, %-I:%M %p}">{text(win, b)}</button>'
        for i, (win, b) in enumerate(bases.items()))
    return f'<div class="view-switch win-switch"><span class="switch-label">{label}</span>{buttons}</div>'


def window_tips(bases: dict, what: str) -> str:
    """A title attribute per window for a Move column header, as JSON."""
    import json
    return json.dumps({win: f"{what} since {b['at']:%b %-d}" for win, b in bases.items()})


WINDOW_CSS = """
.win-cell span[data-win]{display:none}
.win-cell span[data-win].on{display:inline}
.win-btn .win-when{font-weight:400;opacity:.75;font-size:12px;margin-left:3px}
"""

# Reveals the chosen window in every .win-cell, carries its figure into the
# cell's data-sort so a sortable table sorts by it, retitles the headers, and
# tells the page (winchange) in case a live sort should rerun.
WINDOW_JS = """<script>
(function(){
  var btns=document.querySelectorAll('.win-btn');if(!btns.length)return;
  function pick(win){
    Array.prototype.forEach.call(btns,function(b){b.classList.toggle('active',b.getAttribute('data-win')===win);});
    Array.prototype.forEach.call(document.querySelectorAll('.win-cell'),function(td){
      var on=null;
      Array.prototype.forEach.call(td.querySelectorAll('span[data-win]'),function(sp){
        var hit=sp.getAttribute('data-win')===win;sp.classList.toggle('on',hit);if(hit)on=sp;});
      if(on){var v=on.getAttribute('data-v');if(v==='')td.removeAttribute('data-sort');else td.setAttribute('data-sort',v);}
    });
    Array.prototype.forEach.call(document.querySelectorAll('th.win-th[data-tips]'),function(th){
      try{var tips=JSON.parse(th.getAttribute('data-tips'));if(tips[win])th.title=tips[win];}catch(e){}
    });
    document.dispatchEvent(new CustomEvent('winchange',{detail:win}));
  }
  Array.prototype.forEach.call(btns,function(b){b.addEventListener('click',function(){pick(b.getAttribute('data-win'));});});
})();
</script>"""


def cell(delta) -> str:
    """A Move cell: green up-arrow, red down-arrow, or a quiet dot."""
    if delta is None or pd.isna(delta) or int(delta) == 0:
        return "<span class='mv-flat'>&middot;</span>" if delta is not None and not pd.isna(delta) else ""
    d = int(delta)
    if d > 0:
        return f"<span class='mv-up'>&#9650;{d}</span>"
    return f"<span class='mv-down'>&#9660;{-d}</span>"


# The classes cell() emits, for a page to include beside its own table CSS.
CSS = WINDOW_CSS + """
.mv-up{color:#1a7f4b;font-weight:700;font-size:12px}
.mv-down{color:#b3382c;font-weight:700;font-size:12px}
.mv-flat{color:#93a1ad}
@media (prefers-color-scheme: dark){
  .mv-up{color:#6ee7b7}
  .mv-down{color:#ff9b91}
}"""
