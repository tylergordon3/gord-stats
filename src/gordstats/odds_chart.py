"""
Playoff and title odds over the season - one chart on each fantasy league's
Power page (fantasy.site.power for the NFL league, cfb.site.league_power for
the college one), drawn from the snapshots those pages already keep
(data/fantasy/power/<year>/*.parquet, data/cfb/league_power_history/<year>/).

One point a week, not one a build: the last build of each week, so a line is
the week's football and not the intraday wobble of a re-simulation. Which
week a build belongs to is the adapter's call - the NFL snapshot says how
many weeks its model had counted; a college build is placed by the clock
against the league's week windows. The point for the week still being played
is provisional (its dot hollow) and settles when the week does.

All ten teams on one pair of axes, the reader's team picked out in the one
emphasis colour and the rest kept as grey context - on a phone the
league-wide shape (who is pulling away, who has fallen out) reads at a glance,
which ten 170px panels did not give; the Team menu picks out anyone else.
Small multiples were drawn too, at 390px, and rejected for that and their
height (five rows). The reader's team is the one their team dashboard
remembers (`nflMyTeam` / `cfbMyTeam`), else the site owner's.

The chart is HTML and inline SVG, drawn here, not a picture: the lines are an
SVG stretched to the plot box (non-scaling strokes), and every word on it -
axis labels, the end value - is HTML laid over it, so type stays 12px at any
width. The box's height is fixed in CSS, so nothing below moves when the
script picks out a different team. Playoffs/Title is a pair of radio buttons
(no script); the numbers behind both charts are in a table under each.

The browser half is docs/assets/js/gs-odds-chart.js (JS inline for tests,
JS_TAG on the pages).
"""
import re
from datetime import datetime
from html import escape, unescape

import pandas as pd

from gordstats import js_assets

JS = js_assets.inline("gs-odds-chart.js")
JS_TAG = js_assets.tag("gs-odds-chart.js")

PRE = "Pre"            # the x label of the point before any week was played


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #

def by_week(rows: pd.DataFrame) -> dict | None:
    """The last snapshot of each week.

    `rows`: one row per team per snapshot - `taken` (when), `week` (the week
    it belongs to, 0 before any is played), `key` (team id), `playoff`,
    `title` (chances 0-1). Returns {"weeks": [..], "taken": [..],
    "playoff": {key: [per week]}, "title": {key: [...]}} - None for a team a
    week's snapshot left out - or None when there is nothing to draw.
    """
    if rows is None or rows.empty:
        return None
    rows = rows.dropna(subset=["taken", "week", "key", "playoff"]).copy()
    if rows.empty:
        return None
    rows["week"] = rows["week"].astype(int)
    rows["key"] = rows["key"].astype(str)
    last = rows.groupby("week")["taken"].max()
    keep = (rows[rows["taken"] == rows["week"].map(last)]
            .drop_duplicates(["week", "key"], keep="last"))
    weeks = sorted(int(w) for w in last.index)
    keys = list(dict.fromkeys(keep.sort_values("taken")["key"]))
    out = {"weeks": weeks, "taken": [pd.Timestamp(last[w]).to_pydatetime() for w in weeks]}
    for metric in ("playoff", "title"):
        grid = (keep.pivot(index="key", columns="week", values=metric)
                .reindex(index=keys, columns=weeks))
        out[metric] = {k: [None if pd.isna(v) else float(v) for v in grid.loc[k]] for k in keys}
    return out


def week_of(taken: datetime, starts: list) -> int:
    """The week a build belongs to: the latest week whose first game had
    kicked off by then, 0 before the first. `starts`: [(week, first kickoff)]
    in the snapshots' own clock."""
    return max((int(w) for w, kick in starts if kick is not None and kick <= taken), default=0)


# --------------------------------------------------------------------------- #
# Drawing
# --------------------------------------------------------------------------- #

CSS = """<style>
.oc{--oc-em:#2a78d6;--oc-on:#fff;--oc-ctx:#cdd5e0;--oc-grid:#e2e8f0;--oc-ink:#0f172a;
  --oc-bg:#f7f9fc;margin:10px 0 18px;max-width:760px}
@media (prefers-color-scheme: dark){
  .oc{--oc-em:#60a5fa;--oc-on:#0b1220;--oc-ctx:#3a4868;--oc-grid:#26324d;--oc-ink:#f1f5f9;
    --oc-bg:#16203a}
  .oc-pick select{background:#0f172a;border:1px solid #334155;color:#e2e8f0}
}
.oc-r{position:absolute;opacity:0;width:1px;height:1px;margin:0;pointer-events:none}
.oc-bar{display:flex;flex-wrap:wrap;align-items:center;gap:8px 14px;margin:0 0 6px}
.oc-seg{display:inline-flex;border:1px solid var(--oc-grid);border-radius:8px;overflow:hidden}
.oc-seg label{display:inline-flex;align-items:center;padding:5px 12px;font-size:13px;
  font-weight:600;cursor:pointer;color:var(--gs-muted,#5d6b7e);margin:0;line-height:1.4}
.oc-rp:checked ~ .oc-bar .oc-lp,.oc-rt:checked ~ .oc-bar .oc-lt{
  background:var(--oc-em);color:var(--oc-on)}
.oc-rp:focus-visible ~ .oc-bar .oc-lp,.oc-rt:focus-visible ~ .oc-bar .oc-lt{
  outline:2px solid var(--oc-em);outline-offset:-2px}
.oc-pick{font-size:13px;color:var(--gs-muted,#5d6b7e);margin:0;display:inline-flex;
  align-items:center;gap:6px;min-width:0}
.oc-pick select{max-width:190px;padding:3px 4px}
.oc-fig{margin:0}
.oc-ft,.oc-rt:checked ~ .oc-fp{display:none}
.oc-rt:checked ~ .oc-ft{display:block}
.oc-plot{position:relative;height:240px;margin:10px 46px 46px 40px}
.oc-plot svg{position:absolute;inset:0;width:100%;height:100%;overflow:visible}
.oc-grid line{stroke:var(--oc-grid);stroke-width:1}
.oc-ln{fill:none;stroke:var(--oc-ctx);stroke-width:1.25;stroke-linejoin:round;
  stroke-linecap:round;pointer-events:none}
.oc-ln.oc-on{stroke:var(--oc-em);stroke-width:2.5}
.oc-hit{fill:none;stroke:transparent;stroke-width:14;pointer-events:stroke;cursor:pointer}
.oc-y,.oc-x,.oc-xt,.oc-end{position:absolute;font-size:12px;line-height:1;white-space:nowrap;
  color:var(--gs-muted,#5d6b7e);font-variant-numeric:tabular-nums}
.oc-y{right:calc(100% + 6px);transform:translateY(-50%)}
.oc-x{top:calc(100% + 7px);transform:translateX(-50%)}
.oc-xt{top:calc(100% + 25px);left:50%;transform:translateX(-50%)}
.oc-end{left:calc(100% + 9px);transform:translateY(-50%);font-weight:700;
  color:var(--oc-ink);font-size:13px}
.oc-dot{position:absolute;width:8px;height:8px;margin:-4px 0 0 -4px;border-radius:50%;
  background:var(--oc-em);box-shadow:0 0 0 2px var(--oc-bg);pointer-events:none}
.oc-dot.oc-live{background:var(--oc-bg);box-shadow:inset 0 0 0 2px var(--oc-em),
  0 0 0 2px var(--oc-bg)}
.oc-cap{font-size:14px;margin:0 0 6px}
.oc-note{font-size:13px;color:var(--gs-muted,#5d6b7e);margin:0 0 6px}
.oc-num summary{font-size:13px;cursor:pointer;color:var(--gs-muted,#5d6b7e)}
.oc-num table{border-collapse:collapse;font-size:13px;margin:6px 0;
  font-variant-numeric:tabular-nums}
.oc-num th,.oc-num td{padding:4px 8px;text-align:right;white-space:nowrap;
  background:transparent;color:inherit;border:0;border-bottom:1px solid var(--oc-grid)}
.oc-num th{color:var(--gs-muted,#5d6b7e);font-weight:600}
.oc-num th:first-child,.oc-num td:first-child{text-align:left;max-width:150px;
  overflow:hidden;text-overflow:ellipsis}
.oc-num tr.oc-on td{font-weight:700}
@media (min-width:601px){ .oc-pick select{font-size:14px} }
@media (max-width:600px){
  .oc-plot{height:200px;margin:8px 42px 46px 36px}
  .oc-pick select{max-width:160px}
  .oc-seg label{min-height:40px;padding:0 14px}
  .oc-x2{display:none}
}
</style>"""


def _pct(v: float) -> str:
    """A chance as the tables print it: never a flat 0% or 100% for what is
    only very unlikely or very likely."""
    if v is None:
        return "—"
    if 0 < v < 0.005:
        return "<1%"
    if 0.995 < v < 1:
        return ">99%"
    return f"{v:.0%}"


# (ceiling, tick step): the title chart's y axis is cut to the leader, since
# on 0-100% a 30% favourite and a 3% long shot look alike.
_SCALES = [(0.1, 0.025), (0.2, 0.05), (0.25, 0.05), (0.3, 0.1), (0.4, 0.1), (0.5, 0.1),
           (0.6, 0.2), (0.8, 0.2), (1.0, 0.25)]


def scale(values) -> tuple:
    """(ceiling, step) for a chart whose largest value is max(values)."""
    top = max((v for v in values if v is not None), default=0.0)
    for ceiling, step in _SCALES:
        if top <= ceiling * 0.97 or ceiling == 1.0:
            return ceiling, step
    return 1.0, 0.25


def _xs(n: int) -> list:
    return [0.0] if n == 1 else [i * 100.0 / (n - 1) for i in range(n)]


def _coords(vals: list, xs: list, ceiling: float) -> list:
    return [(x, (1.0 - min(v, ceiling) / ceiling) * 100.0)
            for x, v in zip(xs, vals) if v is not None]


def _markers(pts: list, end: str, live: bool) -> str:
    """The picked-out team's dots and its end value (gs-odds-chart.js redraws
    them for another team the same way)."""
    out = []
    for i, (x, y) in enumerate(pts):
        cls = "oc-dot oc-live" if live and i == len(pts) - 1 else "oc-dot"
        out.append(f'<span class="{cls}" style="left:{x:.2f}%;top:{y:.2f}%"></span>')
    if pts:
        out.append(f'<span class="oc-end" style="top:{pts[-1][1]:.2f}%">{escape(end)}</span>')
    return "".join(out)


def _week_label(w: int) -> str:
    return PRE if w == 0 else str(w)


def _change(series: dict, names: dict, metric_word: str) -> str:
    """"Biggest riser since the preseason: X, 34% -> 71%. Biggest faller: ..." -
    the chart's story in words, for every reader and for a screen reader."""
    moves = {k: (v[0], v[-1]) for k, v in series.items()
             if k in names and v and v[0] is not None and v[-1] is not None}
    if not moves:
        return ""
    up = max(moves, key=lambda k: moves[k][1] - moves[k][0])
    down = min(moves, key=lambda k: moves[k][1] - moves[k][0])

    def one(k):
        a, b = moves[k]
        # The two figures stay on one line: "17% →" then ">99%" alone reads badly.
        return (f"<strong>{escape(names[k])}</strong>, "
                f"{escape(_pct(a))}\u00a0\u2192\u00a0{escape(_pct(b))}")
    if moves[up][1] - moves[up][0] < 0.005 and moves[down][1] - moves[down][0] > -0.005:
        return f"No team's {metric_word} odds have moved since the preseason."
    parts = []
    if moves[up][1] - moves[up][0] >= 0.005:
        parts.append(f"Biggest riser since the preseason: {one(up)}.")
    if moves[down][1] - moves[down][0] <= -0.005:
        parts.append(f"Biggest faller: {one(down)}.")
    return " ".join(parts)


def _table(series: dict, weeks: list, names: dict, order: list, on: str) -> str:
    head = "".join(f"<th>{_week_label(w)}</th>" for w in weeks)
    body = []
    for k in order:
        vals = series.get(k) or []
        cls = ' class="oc-on"' if k == on else ""
        body.append(f'<tr data-k="{escape(k, quote=True)}"{cls}><td>{escape(names[k])}</td>'
                    + "".join(f"<td>{escape(_pct(v))}</td>" for v in vals) + "</tr>")
    return ("<details class='oc-num'><summary>Week by week</summary>"
            "<div class='table-scroll'><table><thead><tr><th>Team</th>" + head
            + "</tr></thead><tbody>" + "".join(body) + "</tbody></table></div></details>")


def _figure(metric: str, data: dict, names: dict, on: str, live: bool) -> str:
    series = {k: v for k, v in data[metric].items() if k in names}
    weeks = data["weeks"]
    xs = _xs(len(weeks))
    ceiling, step = (1.0, 0.25) if metric == "playoff" else scale(
        v for vals in series.values() for v in vals)
    word = "playoff" if metric == "playoff" else "title"
    # Current odds, best first: the table's order, and the draw order (the
    # picked-out line goes last, on top).
    now = {k: (v[-1] if v and v[-1] is not None else -1.0) for k, v in series.items()}
    order = sorted(series, key=lambda k: (-now[k], names[k].lower()))

    grid, ylab = [], []
    ticks = round(ceiling / step)
    for i in range(ticks + 1):
        v = i * step
        y = (1.0 - v / ceiling) * 100.0
        grid.append(f'<line x1="0" x2="100" y1="{y:.2f}" y2="{y:.2f}" '
                    'vector-effect="non-scaling-stroke"/>')
        ylab.append(f'<span class="oc-y" style="top:{y:.2f}%">{v * 100:.0f}%</span>'
                    if step >= 0.05 else
                    f'<span class="oc-y" style="top:{y:.2f}%">{v * 100:.1f}%</span>')
    # A season's fifteen labels crowd a phone's plot: there every other one
    # goes (never the last - the week the chart has reached).
    dense = len(weeks) > 10
    xlab = "".join(
        f'<span class="oc-x{" oc-x2" if dense and i % 2 and i != len(weeks) - 1 else ""}" '
        f'style="left:{x:.2f}%">{_week_label(w)}</span>'
        for i, (x, w) in enumerate(zip(xs, weeks)))
    lines, hits, mark = [], [], ""
    for k in [k for k in order if k != on] + ([on] if on in series else []):
        pts = _coords(series[k], xs, ceiling)
        if not pts:
            continue
        # Its latest value - a team a snapshot left out ends where it was last seen.
        end = _pct(next(v for v in reversed(series[k]) if v is not None))
        cls = "oc-ln oc-on" if k == on else "oc-ln"
        lines.append(f'<polyline class="{cls}" data-k="{escape(k, quote=True)}" '
                     f'data-end="{escape(end, quote=True)}" vector-effect="non-scaling-stroke" '
                     'points="' + " ".join(f"{x:.2f},{y:.2f}" for x, y in pts) + '"/>')
        # A wider, invisible twin takes the tap: a 2px line is no target.
        hits.append(f'<polyline class="oc-hit" data-k="{escape(k, quote=True)}" '
                    'vector-effect="non-scaling-stroke" points="'
                    + " ".join(f"{x:.2f},{y:.2f}" for x, y in pts) + '"/>')
        if k == on:
            mark = _markers(pts, end, live)

    story = _change(series, names, word)
    label = (f"{word.capitalize()} odds of every team, one point a week from the preseason "
             f"to week {weeks[-1]}. ") + _plain(story)
    note = (f"<p class='oc-note'>Week {weeks[-1]} is still being played: its point "
            "(the hollow dot) moves until the week's last game is over.</p>" if live else "")
    cls = "oc-fp" if metric == "playoff" else "oc-ft"
    return (f'<figure class="oc-fig {cls}">'
            f'<div class="oc-plot" role="img" aria-label="{escape(label, quote=True)}">'
            '<svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true" '
            'focusable="false"><g class="oc-grid">' + "".join(grid) + "</g>"
            + "".join(lines) + '<g class="oc-hits">' + "".join(hits) + "</g></svg>"
            + "".join(ylab) + xlab + '<span class="oc-xt">after week</span>' + mark + "</div>"
            + (f"<figcaption class='oc-cap'>{story}</figcaption>" if story else "")
            + note + _table(series, weeks, names, order, on) + "</figure>")


def _plain(html: str) -> str:
    return unescape(re.sub(r"<[^>]+>", "", html))


def section(data: dict | None, names: dict, mine: str = "", storage: str = "",
            sid: str = "oc", live: bool = False) -> str:
    """The chart: Playoffs/Title switch, the Team menu, one figure per metric.

    `data` from by_week; `names` {key: team name} (teams not in it are left
    out); `mine` the team picked out until the reader's own is known;
    `storage` the localStorage key that remembers the reader's team; `sid`
    a page-unique id; `live` that the last week is still being played."""
    names = {str(k): str(v) for k, v in (names or {}).items()}
    if not data or len(data.get("weeks") or []) < 2:
        return ("<p class='oc-note'>Each team's playoff and title odds, week by week - the "
                "chart starts once the first week is played.</p>")
    keys = [k for k in data["playoff"] if k in names]
    if not keys:
        return ""
    if mine not in keys:
        latest = {k: (data["playoff"][k][-1] or 0.0) for k in keys}
        mine = max(keys, key=lambda k: latest[k])
    options = "".join(
        f'<option value="{escape(k, quote=True)}"{" selected" if k == mine else ""}>'
        f"{escape(names[k])}</option>"
        for k in sorted(keys, key=lambda k: names[k].lower()))
    sid = escape(sid, quote=True)
    return (CSS
            + f'<div class="oc" id="{sid}" data-store="{escape(storage, quote=True)}" '
            f'data-on="{escape(mine, quote=True)}"{" data-live" if live else ""}>'
            f'<input type="radio" class="oc-r oc-rp" name="{sid}-m" id="{sid}-p" checked>'
            f'<input type="radio" class="oc-r oc-rt" name="{sid}-m" id="{sid}-t">'
            '<div class="oc-bar"><span class="oc-seg">'
            f'<label class="oc-lp" for="{sid}-p">Playoffs</label>'
            f'<label class="oc-lt" for="{sid}-t">Title</label></span>'
            f'<label class="oc-pick">Team <select>{options}</select></label></div>'
            + _figure("playoff", data, names, mine, live)
            + _figure("title", data, names, mine, live)
            + "</div>")
