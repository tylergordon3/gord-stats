"""
Manager Draft Report (src/).

Each manager's drafting success, measured two ways:
  * vs Finish = pick - final finish    (+ = the pick outperformed its slot; primary)
  * ADP Value = pick - consensus ADP   (+ = drafted value / waited; secondary context)

Switchable All-Time / per-year, with positional breakdowns so you can see which
managers draft each position well or poorly. Each section shows a bar chart with
the data table collapsed underneath.

    python -m src.site.draft_report
"""
import base64
import io

import matplotlib
matplotlib.use("Agg")            # non-interactive backend
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np               # noqa: E402

from src.config import FORMAL_SEASON, LEAGUE_IDS, ROOT  # noqa: E402
from src.site import adp, layout, styles                # noqa: E402
from src.site.frontmatter import add_front_matter        # noqa: E402

_POS_ORDER = ["QB", "RB", "WR", "TE"]
_GRID = [styles.GRID_TD, styles.GRID_TH, styles.TABLE_STYLE]


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #

def _summary_df(df):
    g = df.groupby("Manager").agg(
        Picks=("vsADP", "count"), ADPValue=("vsADP", "mean"), FinishValue=("vsFinish", "mean")
    ).round(1).reset_index()
    return g.sort_values("FinishValue", ascending=False)


def _pivot_df(df, value_col):
    p = df.pivot_table(index="Manager", columns="Pos.", values=value_col, aggfunc="mean").round(1)
    p = p.reindex(columns=[c for c in _POS_ORDER if c in p.columns])
    p.columns.name = None
    return p


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

def _bar(df, title, ylabel) -> str:
    ax = df.plot(kind="bar", figsize=(10, 4.3), width=0.8, edgecolor="#333",
                 title=title, colormap="tab10")
    ax.axhline(0, color="#333", linewidth=0.9)
    ax.set_xlabel("")
    ax.set_ylabel(ylabel)
    ax.tick_params(axis="x", labelrotation=35)
    ax.legend(fontsize=9, ncol=min(4, max(1, len(df.columns))))
    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight", dpi=90)  # 60 charts on the page; keep bytes down
    plt.close()
    img = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f'<img src="data:image/png;base64,{img}" style="max-width:100%"/>'


def _style_summary(g):
    d = g.rename(columns={"ADPValue": "Avg ADP Value", "FinishValue": "Avg vs Finish"})
    d = d[["Manager", "Picks", "Avg vs Finish", "Avg ADP Value"]]
    return (d.style.hide(axis="index")
            .format({"Avg ADP Value": "{:+.1f}", "Avg vs Finish": "{:+.1f}"})
            .background_gradient(cmap="RdYlGn", subset=["Avg vs Finish"])
            .set_table_styles(_GRID, overwrite=False)
            .set_table_attributes('class="sticky-table"')).to_html()


def _style_pivot(p):
    bound = np.nanmax(np.abs(p.to_numpy(dtype="float64"))) if p.size else 1.0
    bound = bound if bound and not np.isnan(bound) else 1.0
    return (p.style.format("{:+.1f}", na_rep="—")
            .background_gradient(cmap="RdYlGn", axis=None, vmin=-bound, vmax=bound)
            .set_table_styles(_GRID, overwrite=False)
            .set_table_attributes('class="sticky-table"')).to_html()


def _section(title, desc, chart, table) -> str:
    return (f"<h3>{title}</h3><p>{desc}</p>{chart}"
            + layout.details("Show data table", f"<div class='table-scroll'>{table}</div>"))


def _view(df) -> str:
    summary = _summary_df(df)
    overall_bars = summary.set_index("Manager")[["FinishValue", "ADPValue"]].rename(
        columns={"FinishValue": "vs Finish", "ADPValue": "vs ADP"})
    padp = _pivot_df(df, "PosValue")
    pfin = _pivot_df(df, "PosVsFinish")

    return (
        _section("Overall",
                 "<strong>vs Fantasy Finish</strong> = Draft position &minus; fantasy finish. "
                 "Higher numbers indicate players finished better than drafted, lower numbers mean worse. "
                 "This is the metric that matters: did the pick outperform its slot?<br>"
                 "<strong>vs ADP</strong> (secondary, draft-day context) = Draft position &minus; consensus ADP. "
                 "Higher numbers indicate taking players later than ADP, lower numbers earlier than ADP.",
                 _bar(overall_bars, "Draft success by manager", "avg rank delta"),
                 _style_summary(summary))
        + _section("By Position &mdash; Draft Position vs Fantasy Finish",
                   "Positional draft rank &minus; positional fantasy finish. "
                   "Positive = Finished better than drafted | Negative = Finished worse than drafted",
                   _bar(pfin, "Draft Position vs Fantasy Finish by manager", "avg (draft - finish)"),
                   _style_pivot(pfin))
        + _section("By Position &mdash; Draft Position vs ADP (secondary)",
                   "Positional draft rank &minus; positional ADP. Positive = drafted later than ADP | Negative = drafted before ADP",
                   _bar(padp, "Draft Position vs ADP by manager", "avg (draft &minus; ADP)"),
                   _style_pivot(padp))
    )


# Round filters: (id, label, (low, high) inclusive).
_ROUND_FILTERS = [
    ("all", "All Rounds", (1, 99)),
    ("r1_2", "Rounds 1-2", (1, 2)),
    ("r1_4", "Rounds 1-4", (1, 4)),
    ("r1_8", "Rounds 1-8", (1, 8)),
    ("r4_8", "Rounds 4-8", (4, 8)),
]


def _seasons_df(year_id):
    return adp._all_seasons() if year_id == "alltime" else adp.matched_with_manager(year_id)


def generate():
    """Build and write docs/draft-report/index.html (year x round-filter views)."""
    years = [("alltime", "All-Time")] + [(s, FORMAL_SEASON[s]) for s in LEAGUE_IDS]
    rounds = [(rid, label) for rid, label, _ in _ROUND_FILTERS]

    content = {}
    for year_id, _ in years:
        base = _seasons_df(year_id)
        for rid, _, (lo, hi) in _ROUND_FILTERS:
            df = base[(base["round"] >= lo) & (base["round"] <= hi)]
            content[(year_id, rid)] = _view(df)

    intro = ("<p>How each manager drafts, measured first by <strong>how players actually finished "
             "relative to where they were drafted</strong>. Consensus <strong>Average Draft "
             "Position (ADP)</strong> appears as secondary, draft-day context. Filter by season "
             "and by draft rounds below.<br>ADP data from FantasyPros PPR, averaged across "
             "ESPN/Sleeper/Yahoo/CBS/NFL.</p>")
    switcher = layout.two_axis_switcher(years, rounds, content,
                                        row_label="Season:", col_label="Rounds:", group="report")
    html = layout.HEAD + intro + switcher

    page = add_front_matter(html, "Manager Draft Report")
    out = ROOT / "docs" / "draft-report" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"Wrote Manager Draft Report -> {out}")


if __name__ == "__main__":
    generate()
