"""
Draft vs Consensus ADP page (src/).

For a season, compares where the league drafted each player to the consensus
ADP (FantasyPros, averaged across ESPN/Sleeper/Yahoo/CBS/NFL/...), so you can
see who the league reached for and where it found value relative to the field.

Value = league pick - consensus ADP:
  * positive -> drafted LATER than consensus (value / waited)
  * negative -> drafted EARLIER than consensus (reach)

    python -m src.site.adp 2425
"""
import sys

import pandas as pd

from src import stats
from src.config import FORMAL_SEASON, ROOT, SEASON_YEAR
from src.league.adp import get_adp
from src.site import draft, styles
from src.site.frontmatter import add_front_matter

CUTOFF_ROWS = 15


def _picks_with_adp(season_str: str) -> pd.DataFrame:
    """Drafted players joined to consensus ADP.

    Both sides key through stats.cleaned_name so aliases the draft applies
    (e.g. Hollywood -> Marquise Brown) line up with the ADP names.
    """
    picks, _ = draft._build(season_str)
    picks[["overall_pick", "final_rank"]] = picks["Overall Rk"].str.split(" -> ", expand=True).astype(int)
    picks["key"] = picks["Name"].str.lower()

    adp = get_adp(SEASON_YEAR[season_str]).copy()
    adp["key"] = stats.cleaned_name(adp["player"]).str.lower()
    adp = adp.drop_duplicates(subset="key", keep="first")  # keep the higher-ADP of any name collision

    m = picks.merge(adp[["key", "adp", "adp_min", "adp_max"]], on="key", how="left")
    m["Value"] = (m["overall_pick"] - m["adp"]).round(1)
    rng = m["adp_min"].astype("Int64").astype(str) + "-" + m["adp_max"].astype("Int64").astype(str)
    m["ADP Range"] = rng.where(m["adp"].notna())
    return m


_COLS = ["Pick", "overall_pick", "Owner", "Name", "Pos.", "adp", "Value", "final_rank"]
_RENAME = {"overall_pick": "Overall", "Name": "Player", "Pos.": "Pos",
           "adp": "ADP", "final_rank": "Finish"}


def _main_table(matched: pd.DataFrame):
    cols = _COLS[:6] + ["ADP Range"] + _COLS[6:]   # insert ADP Range before Value
    df = matched.sort_values("overall_pick")[cols].rename(columns=_RENAME)
    return (df.style.hide(axis="index")
            .format({"ADP": "{:.1f}", "Value": "{:+.1f}"})
            .background_gradient(cmap="RdYlGn", subset=["Value"], vmin=-40, vmax=40)
            .set_table_styles([styles.GRID_TD, styles.GRID_TH, styles.TABLE_STYLE], overwrite=False)
            .set_table_attributes('class="sticky-table"'))


def _ranked(matched: pd.DataFrame, ascending: bool):
    df = matched.sort_values("Value", ascending=ascending).head(CUTOFF_ROWS)[_COLS].rename(columns=_RENAME)
    cmap = "Greens" if not ascending else "Reds_r"
    return (df.style.hide(axis="index")
            .format({"ADP": "{:.1f}", "Value": "{:+.1f}"})
            .background_gradient(cmap=cmap, subset=["Value"])
            .set_table_styles([styles.GRID_TD, styles.GRID_TH], overwrite=False)
            .set_table_attributes('class="sticky-table"'))


def _owner_summary(matched: pd.DataFrame):
    g = matched.groupby("Owner").agg(
        Picks=("Value", "count"),
        AvgValue=("Value", "mean"),
        Reaches=("Value", lambda v: int((v < -10).sum())),
        Values=("Value", lambda v: int((v > 10).sum())),
    ).reset_index()
    g["AvgValue"] = g["AvgValue"].round(1)
    g = g.rename(columns={"AvgValue": "Avg Value vs ADP", "Reaches": "Reaches (>10)", "Values": "Values (>10)"})
    g = g.sort_values("Avg Value vs ADP", ascending=False)
    return (g.style.hide(axis="index")
            .format({"Avg Value vs ADP": "{:+.1f}"})
            .background_gradient(cmap="RdYlGn", subset=["Avg Value vs ADP"])
            .set_table_styles([styles.GRID_TD, styles.GRID_TH, styles.TABLE_STYLE], overwrite=False)
            .set_table_attributes('class="sticky-table"'))


def generate(season_str: str):
    """Build and write docs/<season_str>/adp/index.html."""
    m = _picks_with_adp(season_str)
    matched = m[m["adp"].notna()].copy()
    unmatched = list(m[m["adp"].isna()]["Name"])

    html = (
        f"<p>How the league drafted vs <strong>consensus ADP</strong> (FantasyPros PPR, "
        f"averaged across ESPN/Sleeper/Yahoo/CBS/NFL). "
        f"<strong>Value</strong> = your pick minus consensus ADP: "
        f"<strong>+</strong> = drafted later than consensus (value), "
        f"<strong>-</strong> = drafted earlier (reach).</p>"
        f"<p>{len(matched)} of {len(m)} picks matched to ADP"
        + (f" (no ADP for: {', '.join(unmatched)})." if unmatched else ".") + "</p>"
        "<h2>Best Values vs Consensus</h2>"
        f'<div class="table-scroll">{_ranked(matched, ascending=False).to_html()}</div>'
        "<h2>Biggest Reaches vs Consensus</h2>"
        f'<div class="table-scroll">{_ranked(matched, ascending=True).to_html()}</div>'
        "<h2>By Owner</h2>"
        "<p>Average value vs ADP per manager (positive = tends to wait / find value; "
        "negative = tends to reach).</p>"
        f'<div class="table-scroll">{_owner_summary(matched).to_html()}</div>'
        "<h2>Full Draft vs ADP</h2>"
        f'<div class="table-scroll">{_main_table(matched).to_html()}</div>'
    )

    page = add_front_matter(html, f"Draft vs ADP - {FORMAL_SEASON[season_str]}")
    out = ROOT / "docs" / season_str / "adp" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"Wrote Draft vs ADP page -> {out}")


if __name__ == "__main__":
    generate(sys.argv[1] if len(sys.argv) > 1 else "2425")
