"""
Manager Draft Report (src/).

Each manager's drafting success, measured two ways:
  * ADP Value = pick - consensus ADP   (+ = drafted value / waited)
  * vs Finish = pick - final finish    (+ = the pick outperformed its slot)

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
    plt.savefig(buf, format="png", bbox_inches="tight", dpi=110)
    plt.close()
    img = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f'<img src="data:image/png;base64,{img}" style="max-width:100%"/>'


def _style_summary(g):
    d = g.rename(columns={"ADPValue": "Avg ADP Value", "FinishValue": "Avg vs Finish"})
    return (d.style.hide(axis="index")
            .format({"Avg ADP Value": "{:+.1f}", "Avg vs Finish": "{:+.1f}"})
            .background_gradient(cmap="RdYlGn", subset=["Avg ADP Value"])
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
    overall_bars = summary.set_index("Manager")[["ADPValue", "FinishValue"]].rename(
        columns={"ADPValue": "vs ADP", "FinishValue": "vs Finish"})
    padp = _pivot_df(df, "PosValue")
    pfin = _pivot_df(df, "PosVsFinish")

    return (
        _section("Overall",
                 "<strong>vs ADP</strong> = Draft position &minus; consensus ADP.<br>"
                 "<strong>vs Fantasy Finish</strong> = Draft position &minus; fantasy finish.<br>"
                 "ADP Bars: Higher numbers indicate taking players later than ADP, lower numbers earlier than ADP.<br>"
                 "Fantasy Finish Bars: Higher numbers indicate players finished better than drafted, lower numbers mean worse.",
                 _bar(overall_bars, "Draft success by manager", "avg rank delta"),
                 _style_summary(summary))
        + _section("By Position &mdash; Draft Position vs ADP",
                   "Positional draft rank &minus; positional ADP. Positive = drafted later than ADP | Negative = drafted before ADP",
                   _bar(padp, "Draft Position vs ADP by manager", "avg (draft &minus; ADP)"),
                   _style_pivot(padp))
        + _section("By Position &mdash; Draft Position vs Fantasy Finish",
                   "Positional draft rank &minus; positional fantasy finish."
                   "Positive = Finished better than drafted | Negative = Finished worse than drafted",
                   _bar(pfin, "Draft Position vs Fantasy Finish by manager", "avg (draft - finish)"),
                   _style_pivot(pfin))
    )


def generate():
    """Build and write docs/draft-report/index.html."""
    views = [("alltime", "All-Time", _view(adp._all_seasons()))]
    for season_str in LEAGUE_IDS:
        views.append((season_str, FORMAL_SEASON[season_str], _view(adp.matched_with_manager(season_str))))

    intro = ("<p>How each manager drafts, measured against both consensus <strong>Average Draft Position (ADP)</strong> and how players "
             "actually finished. Switch between all-time and a single season below.<br>"
             "ADP data taken from FantasyPros for PPR leaguesaveraged across ESPN/Sleeper/Yahoo/CBS/NFL.</p>")
    html = layout.HEAD + intro + layout.view_switcher(views, group="report")

    page = add_front_matter(html, "Manager Draft Report")
    out = ROOT / "docs" / "draft-report" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"Wrote Manager Draft Report -> {out}")


if __name__ == "__main__":
    generate()
