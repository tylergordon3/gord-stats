"""
Draft vs Consensus ADP page (src/).

Compares where the league drafted each player to the consensus ADP (FantasyPros
PPR, averaged across ESPN/Sleeper/Yahoo/CBS/NFL). Two views, switchable with a
button on the page:

  * Overall    - league overall pick vs overall consensus ADP.
  * Positional - league positional draft rank vs consensus positional ADP rank.

Value = league rank - consensus rank (positive = drafted later than consensus =
value; negative = reach).

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
_GRID = [styles.GRID_TD, styles.GRID_TH]
_GRID_WIDE = _GRID + [styles.TABLE_STYLE]


def _picks_with_adp(season_str: str) -> pd.DataFrame:
    """Drafted players joined to consensus ADP (overall + positional ranks).

    Both sides key through stats.cleaned_name so the draft's aliases
    (e.g. Hollywood -> Marquise Brown) line up with the ADP names.
    """
    picks, _ = draft._build(season_str)
    picks[["overall_pick", "final_rank"]] = picks["Overall Rk"].str.split(" -> ", expand=True).astype(int)
    picks[["draft_pos_rank", "final_pos_rank"]] = picks["Position Rk"].str.split(" -> ", expand=True).astype(int)
    picks["key"] = picks["Name"].str.lower()

    adp = get_adp(SEASON_YEAR[season_str]).copy()
    adp["key"] = stats.cleaned_name(adp["player"]).str.lower()
    adp["adp_pos"] = adp["pos_rank"].str.extract(r"(\d+)")[0].astype("Int64")
    adp = adp.drop_duplicates(subset="key", keep="first")

    m = picks.merge(adp[["key", "adp", "adp_min", "adp_max", "adp_pos"]], on="key", how="left")
    m["OvrValue"] = (m["overall_pick"] - m["adp"]).round(1)
    m["PosValue"] = (m["draft_pos_rank"] - m["adp_pos"]).astype("Int64")
    rng = m["adp_min"].astype("Int64").astype(str) + "-" + m["adp_max"].astype("Int64").astype(str)
    m["ADP Range"] = rng.where(m["adp"].notna())
    return m


# --------------------------------------------------------------------------- #
# Shared styling
# --------------------------------------------------------------------------- #

def _style(df, value_fmt, cmap, vmin=None, vmax=None, wide=True):
    fmt = {"Value": value_fmt}
    if "ADP" in df.columns:
        fmt["ADP"] = "{:.1f}"
    return (df.style.hide(axis="index").format(fmt)
            .background_gradient(cmap=cmap, subset=["Value"], vmin=vmin, vmax=vmax)
            .set_table_styles(_GRID_WIDE if wide else _GRID, overwrite=False)
            .set_table_attributes('class="sticky-table"')).to_html()


def _owner(matched, value_col, fmt, threshold):
    g = matched.groupby("Owner").agg(
        Picks=(value_col, "count"),
        Avg=(value_col, "mean"),
        Reaches=(value_col, lambda v: int((v < -threshold).sum())),
        Values=(value_col, lambda v: int((v > threshold).sum())),
    ).reset_index()
    g["Avg"] = g["Avg"].round(1)
    g = g.rename(columns={"Avg": "Avg Value", "Reaches": f"Reaches (>{threshold})",
                          "Values": f"Values (>{threshold})"})
    g = g.sort_values("Avg Value", ascending=False)
    return (g.style.hide(axis="index").format({"Avg Value": fmt})
            .background_gradient(cmap="RdYlGn", subset=["Avg Value"])
            .set_table_styles(_GRID_WIDE, overwrite=False)
            .set_table_attributes('class="sticky-table"')).to_html()


def _assemble(values, reaches, owner, full, full_label):
    return (f"<h2>Best Values vs Consensus</h2><div class='table-scroll'>{values}</div>"
            f"<h2>Biggest Reaches vs Consensus</h2><div class='table-scroll'>{reaches}</div>"
            f"<h2>By Owner</h2><p>Average value vs consensus per manager "
            f"(positive = waits / finds value; negative = reaches).</p>"
            f"<div class='table-scroll'>{owner}</div>"
            f"<h2>Full Draft vs {full_label}</h2><div class='table-scroll'>{full}</div>")


# --------------------------------------------------------------------------- #
# Views
# --------------------------------------------------------------------------- #

_OVR_COLS = ["Pick", "overall_pick", "Owner", "Name", "Pos.", "adp", "OvrValue", "final_rank"]
_OVR_RENAME = {"overall_pick": "Overall", "Name": "Player", "Pos.": "Pos",
               "adp": "ADP", "OvrValue": "Value", "final_rank": "Finish"}

_POS_COLS = ["Pos.", "Name", "Owner", "draft_pos_rank", "overall_pick", "adp_pos", "PosValue", "final_pos_rank"]
_POS_RENAME = {"Pos.": "Pos", "Name": "Player", "draft_pos_rank": "Draft Pos",
               "overall_pick": "Overall", "adp_pos": "ADP Pos", "PosValue": "Value",
               "final_pos_rank": "Pos Finish"}


def _overall_view(matched):
    def rank(asc):
        df = matched.sort_values("OvrValue", ascending=asc).head(CUTOFF_ROWS)[_OVR_COLS].rename(columns=_OVR_RENAME)
        return _style(df, "{:+.1f}", "Reds_r" if asc else "Greens", wide=False)

    full_cols = _OVR_COLS[:6] + ["ADP Range"] + _OVR_COLS[6:]
    full = _style(matched.sort_values("overall_pick")[full_cols].rename(columns=_OVR_RENAME),
                  "{:+.1f}", "RdYlGn", vmin=-40, vmax=40)
    return _assemble(rank(False), rank(True), _owner(matched, "OvrValue", "{:+.1f}", 10), full, "ADP")


def _positional_view(matched):
    m = matched[matched["PosValue"].notna()]

    def rank(asc):
        df = m.sort_values("PosValue", ascending=asc).head(CUTOFF_ROWS)[_POS_COLS].rename(columns=_POS_RENAME)
        return _style(df, "{:+.0f}", "Reds_r" if asc else "Greens", wide=False)

    full = _style(m.sort_values(["Pos.", "draft_pos_rank"])[_POS_COLS].rename(columns=_POS_RENAME),
                  "{:+.0f}", "RdYlGn", vmin=-15, vmax=15)
    return _assemble(rank(False), rank(True), _owner(m, "PosValue", "{:+.1f}", 5), full, "Positional ADP")


# --------------------------------------------------------------------------- #
# Page (with view toggle)
# --------------------------------------------------------------------------- #

_TOGGLE = """
<style>
.view-toggle{margin:14px 0}
.view-toggle button{padding:7px 18px;margin-right:6px;cursor:pointer;border:1px solid #888;
  background:#eee;border-radius:5px;font-size:15px}
.view-toggle button.active{background:#3CB371;color:#fff;font-weight:bold;border-color:#2e8b57}
</style>
<div class="view-toggle">
  <button id="btn-overall" class="active" onclick="adpView('overall')">Overall</button>
  <button id="btn-positional" onclick="adpView('positional')">By Position</button>
</div>
<script>
function adpView(v){
  document.getElementById('view-overall').style.display = (v==='overall')?'':'none';
  document.getElementById('view-positional').style.display = (v==='positional')?'':'none';
  document.getElementById('btn-overall').classList.toggle('active', v==='overall');
  document.getElementById('btn-positional').classList.toggle('active', v==='positional');
}
</script>
"""


def generate(season_str: str):
    """Build and write docs/<season_str>/adp/index.html (overall + positional views)."""
    m = _picks_with_adp(season_str)
    matched = m[m["adp"].notna()].copy()
    unmatched = list(m[m["adp"].isna()]["Name"])

    intro = (
        "<p>How the league drafted vs <strong>consensus ADP</strong> (FantasyPros PPR, "
        "averaged across ESPN/Sleeper/Yahoo/CBS/NFL). <strong>Value</strong> = league rank minus "
        "consensus rank: <strong>+</strong> = drafted later than consensus (value), "
        "<strong>-</strong> = drafted earlier (reach). Switch between overall and positional ranks below.</p>"
        f"<p>{len(matched)} of {len(m)} picks matched to ADP"
        + (f" (no ADP for: {', '.join(unmatched)})." if unmatched else ".") + "</p>"
    )

    html = (
        intro + _TOGGLE
        + f'<div id="view-overall">{_overall_view(matched)}</div>'
        + f'<div id="view-positional" style="display:none">{_positional_view(matched)}</div>'
    )

    page = add_front_matter(html, f"Draft vs ADP - {FORMAL_SEASON[season_str]}")
    out = ROOT / "docs" / season_str / "adp" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"Wrote Draft vs ADP page -> {out}")


if __name__ == "__main__":
    generate(sys.argv[1] if len(sys.argv) > 1 else "2425")
