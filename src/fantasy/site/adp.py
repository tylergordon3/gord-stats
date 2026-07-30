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
from functools import lru_cache

import pandas as pd

from src import stats
from src.config import FORMAL_SEASON, LEAGUE_IDS, ROOT, ROSTER_NAMES, SEASON_YEAR
from src.league.adp import get_adp
from src.site import draft, layout, styles
from src.site.frontmatter import add_front_matter

CUTOFF_ROWS = 15
_GRID = [styles.GRID_TD, styles.GRID_TH]
_GRID_WIDE = _GRID + [styles.TABLE_STYLE]


@lru_cache(maxsize=None)
def _picks_with_adp(season_str: str) -> pd.DataFrame:
    """Drafted players joined to consensus ADP (overall + positional ranks).

    Both sides key through stats.cleaned_name so the draft's aliases
    (e.g. Hollywood -> Marquise Brown) line up with the ADP names.
    """
    picks = draft._build(season_str)[0].copy()  # _build is cached; don't mutate the shared frame
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
    # Finish vs ADP: consensus ADP minus actual finish (positive = beat consensus).
    m["BeatADP"] = (m["adp"] - m["final_rank"]).round(1)
    rng = m["adp_min"].astype("Int64").astype(str) + "-" + m["adp_max"].astype("Int64").astype(str)
    m["ADP Range"] = rng.where(m["adp"].notna())
    return m


# --------------------------------------------------------------------------- #
# Shared styling
# --------------------------------------------------------------------------- #

def _style(df, value_fmt, cmap, vmin=None, vmax=None, wide=True, grad_col="ADP Value"):
    fmt = {grad_col: value_fmt}
    if "ADP" in df.columns:
        fmt["ADP"] = "{:.1f}"
    return (df.style.hide(axis="index").format(fmt)
            .background_gradient(cmap=cmap, subset=[grad_col], vmin=vmin, vmax=vmax)
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
    g = g.rename(columns={"Avg": "Avg ADP Value", "Reaches": f"Reaches (>{threshold})",
                          "Values": f"Values (>{threshold})"})
    g = g.sort_values("Avg ADP Value", ascending=False)
    return (g.style.hide(axis="index").format({"Avg ADP Value": fmt})
            .background_gradient(cmap="RdYlGn", subset=["Avg ADP Value"])
            .set_table_styles(_GRID_WIDE, overwrite=False)
            .set_table_attributes('class="sticky-table"')).to_html()


def _assemble(values, reaches, owner, full, full_label):
    return (f"<h2>Best Values vs Consensus</h2><div class='table-scroll'>{values}</div>"
            f"<h2>Biggest Reaches vs Consensus</h2><div class='table-scroll'>{reaches}</div>"
            f"<h2>By Owner</h2><p>Average value vs consensus per manager "
            f"(positive = waits / finds value; negative = reaches).</p>"
            f"<div class='table-scroll'>{owner}</div>"
            + layout.details(f"Full Draft vs {full_label}",
                             f"<div class='table-scroll'>{full}</div>"))


# --------------------------------------------------------------------------- #
# Views
# --------------------------------------------------------------------------- #

_OVR_COLS = ["Pick", "overall_pick", "Owner", "Name", "Pos.", "adp", "OvrValue", "final_rank"]
_OVR_RENAME = {"overall_pick": "Overall Pick", "Name": "Player", "Pos.": "Pos",
               "adp": "ADP", "OvrValue": "ADP Value", "final_rank": "Fantasy Finish"}

_POS_COLS = ["Pos.", "Name", "Owner", "draft_pos_rank", "overall_pick", "adp_pos", "PosValue", "final_pos_rank"]
_POS_RENAME = {"Pos.": "Pos", "Name": "Player", "draft_pos_rank": "Draft Pos",
               "overall_pick": "Overall Pick", "adp_pos": "ADP Pos", "PosValue": "ADP Value",
               "final_pos_rank": "Positional Finish"}


def _overall_view(matched):
    def rank(asc):
        df = matched.sort_values("OvrValue", ascending=asc).head(CUTOFF_ROWS)[_OVR_COLS].rename(columns=_OVR_RENAME)
        return _style(df, "{:+.1f}", "Reds_r" if asc else "Greens", wide=False)

    full_cols = _OVR_COLS[:6] + ["ADP Range"] + _OVR_COLS[6:]
    full = _style(matched.sort_values("overall_pick")[full_cols].rename(columns=_OVR_RENAME),
                  "{:+.1f}", "RdYlGn", vmin=-40, vmax=40)
    body = _assemble(rank(False), rank(True), _owner(matched, "OvrValue", "{:+.1f}", 10), full, "ADP")
    return body + _outcomes(matched)


_OUT_COLS = ["Pick", "overall_pick", "Owner", "Name", "Pos.", "adp", "final_rank", "BeatADP"]
_OUT_RENAME = {"overall_pick": "Overall Pick", "Name": "Player", "Pos.": "Pos",
               "adp": "ADP", "final_rank": "Fantasy Finish", "BeatADP": "Finish vs ADP"}


def _payoff_buckets(d):
    """Bucket picks by reach/consensus/value and show avg ADP, finish, finish-vs-ADP."""
    def bucket(v):
        return "Reach (drafted early)" if v < -10 else "Value (drafted late)" if v > 10 else "On consensus"

    d = d.assign(Call=d["OvrValue"].apply(bucket))
    g = d.groupby("Call").agg(Picks=("OvrValue", "count"), AvgADP=("adp", "mean"),
                              AvgFinish=("final_rank", "mean"), FinishVsADP=("BeatADP", "mean")).reset_index()
    for c in ["AvgADP", "AvgFinish", "FinishVsADP"]:
        g[c] = g[c].round(1)
    order = {"Reach (drafted early)": 0, "On consensus": 1, "Value (drafted late)": 2}
    g = g.sort_values("Call", key=lambda s: s.map(order))
    g = g.rename(columns={"AvgADP": "Avg ADP", "AvgFinish": "Avg Fantasy Finish", "FinishVsADP": "Avg Finish vs ADP"})
    return (g.style.hide(axis="index")
            .format({"Avg ADP": "{:.1f}", "Avg Fantasy Finish": "{:.1f}", "Avg Finish vs ADP": "{:+.1f}"})
            .background_gradient(cmap="RdYlGn", subset=["Avg Finish vs ADP"])
            .set_table_styles(_GRID_WIDE, overwrite=False)
            .set_table_attributes('class="sticky-table"')).to_html()


def _outcomes(matched):
    """Overall pick vs ADP vs finish: did the league's draft calls pay off?"""
    d = matched.copy()
    summary = _payoff_buckets(d)
    steals = _style(d.sort_values("BeatADP", ascending=False).head(CUTOFF_ROWS)[_OUT_COLS].rename(columns=_OUT_RENAME),
                    "{:+.0f}", "Greens", wide=False, grad_col="Finish vs ADP")
    busts = _style(d.sort_values("BeatADP").head(CUTOFF_ROWS)[_OUT_COLS].rename(columns=_OUT_RENAME),
                   "{:+.0f}", "Reds_r", wide=False, grad_col="Finish vs ADP")

    return (
        "<h2>Did it pay off? Draft call vs finish</h2>"
        "<p>Players bucketed by how far from consensus they were drafted. "
        "<strong>Finish vs ADP</strong> = consensus ADP minus actual overall finish "
        "(positive = finished better than consensus expected).</p>"
        f"<div class='table-scroll'>{summary}</div>"
        + layout.details("Biggest Steals vs Consensus (finished well above ADP)",
                         f"<div class='table-scroll'>{steals}</div>")
        + layout.details("Biggest Busts vs Consensus (finished well below ADP)",
                         f"<div class='table-scroll'>{busts}</div>")
    )


def _positional_view(matched):
    m = matched[matched["PosValue"].notna()]

    def rank(asc):
        df = m.sort_values("PosValue", ascending=asc).head(CUTOFF_ROWS)[_POS_COLS].rename(columns=_POS_RENAME)
        return _style(df, "{:+.0f}", "Reds_r" if asc else "Greens", wide=False)

    full = _style(m.sort_values("overall_pick")[_POS_COLS].rename(columns=_POS_RENAME),
                  "{:+.0f}", "RdYlGn", vmin=-15, vmax=15)
    return _assemble(rank(False), rank(True), _owner(m, "PosValue", "{:+.1f}", 5), full, "Positional ADP")


# --------------------------------------------------------------------------- #
# All-time combined (across every season) - for the homepage
# --------------------------------------------------------------------------- #

_ALL_COLS = ["Season", "Manager", "Name", "Pos.", "overall_pick", "adp", "OvrValue", "final_rank"]
_ALL_RENAME = {"Name": "Player", "Pos.": "Pos", "overall_pick": "Overall Pick",
               "adp": "ADP", "OvrValue": "ADP Value", "final_rank": "Fantasy Finish"}


def matched_with_manager(season_str) -> pd.DataFrame:
    """One season's ADP-matched picks tagged with Season, stable Manager, and
    both success metrics: vsADP (pick - ADP) and vsFinish (pick - finish)."""
    m = _picks_with_adp(season_str)
    m = m[m["adp"].notna()].copy()
    m["Season"] = FORMAL_SEASON[season_str]
    m["Manager"] = m["roster_id"].map(ROSTER_NAMES)
    m["vsADP"] = m["OvrValue"]
    m["vsFinish"] = m["overall_pick"] - m["final_rank"]
    # Positional versions (comparable across positions; overall finish favors QBs).
    # PosValue already = draft_pos_rank - adp_pos. Exclude DNP (final_pos_rank sentinel 999).
    m["PosVsFinish"] = (m["draft_pos_rank"] - m["final_pos_rank"]).where(m["final_pos_rank"] < 900)
    return m


def _all_seasons() -> pd.DataFrame:
    """Every season's matched picks, tagged with Season + stable Manager name."""
    return pd.concat([matched_with_manager(s) for s in LEAGUE_IDS], ignore_index=True)


def _manager_summary(df):
    g = df.groupby("Manager").agg(
        Picks=("OvrValue", "count"),
        AvgValue=("OvrValue", "mean"),
        Reaches=("OvrValue", lambda v: int((v < -10).sum())),
        Values=("OvrValue", lambda v: int((v > 10).sum())),
        FinishVsADP=("BeatADP", "mean"),
    ).reset_index()
    g["AvgValue"] = g["AvgValue"].round(1)
    g["FinishVsADP"] = g["FinishVsADP"].round(1)
    g = g.rename(columns={"AvgValue": "Avg Value vs ADP", "Reaches": "Reaches (>10)",
                          "Values": "Values (>10)", "FinishVsADP": "Avg Finish vs ADP"})
    g = g.sort_values("Avg Value vs ADP", ascending=False)
    return (g.style.hide(axis="index")
            .format({"Avg Value vs ADP": "{:+.1f}", "Avg Finish vs ADP": "{:+.1f}"})
            .background_gradient(cmap="RdYlGn", subset=["Avg Value vs ADP"])
            .background_gradient(cmap="RdYlGn", subset=["Avg Finish vs ADP"])
            .set_table_styles(_GRID_WIDE, overwrite=False)
            .set_table_attributes('class="sticky-table"')).to_html()


def all_time_section() -> str:
    """Combined draft-vs-ADP summaries across every season (homepage section)."""
    df = _all_seasons()

    def ranked(asc, cmap):
        d = df.sort_values("OvrValue", ascending=asc).head(CUTOFF_ROWS)[_ALL_COLS].rename(columns=_ALL_RENAME)
        return _style(d, "{:+.1f}", cmap, wide=False)

    links = " &middot; ".join(f'<a href="/{s}/adp/">{FORMAL_SEASON[s]}</a>' for s in LEAGUE_IDS)
    return (
        "<p>Combined across every league season. <strong>ADP Value</strong> = pick minus consensus "
        "ADP (+ = value, - = reach); <strong>Finish vs ADP</strong> = ADP minus fantasy finish "
        "(+ = beat consensus).</p>"
        f"<p>Full draft-vs-ADP by season: {links}</p>"
        "<h2>Draft Tendencies by Manager</h2>"
        f"<div class='table-scroll'>{_manager_summary(df)}</div>"
        "<h2>Did it pay off? (all seasons)</h2>"
        f"<div class='table-scroll'>{_payoff_buckets(df)}</div>"
        "<h2>Best Values (all-time)</h2>"
        f"<div class='table-scroll'>{ranked(False, 'Greens')}</div>"
        "<h2>Biggest Reaches (all-time)</h2>"
        f"<div class='table-scroll'>{ranked(True, 'Reds_r')}</div>"
    )


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
        "averaged across ESPN/Sleeper/Yahoo/CBS/NFL). <strong>ADP Value</strong> = league rank minus "
        "consensus rank: <strong>+</strong> = drafted later than consensus (value), "
        "<strong>-</strong> = drafted earlier (reach). <strong>Fantasy Finish</strong> is the "
        "player's actual end-of-season rank. Switch between overall and positional ranks below.</p>"
        f"<p>{len(matched)} of {len(m)} picks matched to ADP"
        + (f" (no ADP for: {', '.join(unmatched)})." if unmatched else ".") + "</p>"
    )

    html = (
        layout.HEAD + intro + _TOGGLE
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
