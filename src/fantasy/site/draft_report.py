"""
Manager Draft Report (src/).

Each manager's drafting success, measured two ways:
  * vs ADP    = pick - consensus ADP   (+ = drafted value / waited)
  * vs Finish = pick - final finish    (+ = the pick outperformed its slot)

Switchable All-Time / per-year, with positional breakdowns so you can see which
managers draft each position well or poorly.

    python -m src.site.draft_report
"""
import numpy as np
import pandas as pd

from src.config import FORMAL_SEASON, LEAGUE_IDS, ROOT
from src.site import adp, layout, styles
from src.site.frontmatter import add_front_matter

_POS_ORDER = ["QB", "RB", "WR", "TE"]
_GRID = [styles.GRID_TD, styles.GRID_TH, styles.TABLE_STYLE]


def _summary(df):
    g = df.groupby("Manager").agg(
        Picks=("vsADP", "count"), vsADP=("vsADP", "mean"), vsFinish=("vsFinish", "mean")
    ).reset_index()
    g["vsADP"] = g["vsADP"].round(1)
    g["vsFinish"] = g["vsFinish"].round(1)
    g = g.rename(columns={"vsADP": "Avg vs ADP", "vsFinish": "Avg vs Finish"})
    g = g.sort_values("Avg vs Finish", ascending=False)
    return (g.style.hide(axis="index")
            .format({"Avg vs ADP": "{:+.1f}", "Avg vs Finish": "{:+.1f}"})
            .background_gradient(cmap="RdYlGn", subset=["Avg vs ADP"])
            .background_gradient(cmap="RdYlGn", subset=["Avg vs Finish"])
            .set_table_styles(_GRID, overwrite=False)
            .set_table_attributes('class="sticky-table"')).to_html()


def _pos_pivot(df, value_col):
    p = df.pivot_table(index="Manager", columns="Pos.", values=value_col, aggfunc="mean").round(1)
    p = p.reindex(columns=[c for c in _POS_ORDER if c in p.columns])
    p.columns.name = None
    bound = np.nanmax(np.abs(p.to_numpy(dtype="float64")))
    bound = bound if bound and not np.isnan(bound) else 1.0
    return (p.style.format("{:+.1f}", na_rep="—")
            .background_gradient(cmap="RdYlGn", axis=None, vmin=-bound, vmax=bound)
            .set_table_styles(_GRID, overwrite=False)
            .set_table_attributes('class="sticky-table"')).to_html()


def _view(df) -> str:
    return (
        "<h3>Overall</h3>"
        "<p><strong>vs ADP</strong> = pick &minus; consensus ADP (+ = value drafted). "
        "<strong>vs Finish</strong> = pick &minus; finish (+ = outperformed the pick).</p>"
        f"<div class='table-scroll'>{_summary(df)}</div>"
        "<h3>By Position &mdash; Value vs ADP</h3>"
        "<p>Average positional draft rank &minus; positional ADP. Green = drafts that position "
        "for value; red = reaches. (e.g. drafting the WR20 when consensus had them WR12.)</p>"
        f"<div class='table-scroll'>{_pos_pivot(df, 'PosValue')}</div>"
        "<h3>By Position &mdash; Result vs Finish</h3>"
        "<p>Average positional draft rank &minus; positional finish (players who played). "
        "Green = that position's picks finished above where drafted.</p>"
        f"<div class='table-scroll'>{_pos_pivot(df, 'PosVsFinish')}</div>"
    )


def generate():
    """Build and write docs/draft-report/index.html."""
    views = [("alltime", "All-Time", _view(adp._all_seasons()))]
    for season_str in LEAGUE_IDS:
        views.append((season_str, FORMAL_SEASON[season_str], _view(adp.matched_with_manager(season_str))))

    intro = ("<p>How each manager drafts, measured against both consensus ADP and how players "
             "actually finished. Switch between all-time and a single season below.</p>")
    html = layout.HEAD + intro + layout.view_switcher(views, group="report")

    page = add_front_matter(html, "Manager Draft Report")
    out = ROOT / "docs" / "draft-report" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"Wrote Manager Draft Report -> {out}")


if __name__ == "__main__":
    generate()
