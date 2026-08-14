"""
Draft vs Consensus ADP page (src/).

Compares where the league drafted each player to the consensus ADP (FantasyPros
PPR, averaged across ESPN/Sleeper/Yahoo/CBS/NFL). Two views, switchable with a
button on the page:

  * Overall    - league overall pick vs overall consensus ADP.
  * Positional - league positional draft rank vs consensus positional ADP rank.

Value = league rank - consensus rank (positive = drafted later than consensus =
value; negative = reach).

Seasons a player mostly missed are left off the page entirely - see
_injury_shortened. Nobody's draft grade should hinge on a torn ACL.

Every season lives on the one page (docs/adp/index.html), picked with the season
buttons - same shape as the draft report.

    python -m src.site.adp
"""
from functools import lru_cache

import pandas as pd

from src import stats
from src.config import FORMAL_SEASON, LEAGUE_IDS, ROOT, ROSTER_NAMES, SEASON_YEAR
from src.league.adp import get_adp
from src.site import draft, layout, styles
from src.site.frontmatter import add_front_matter

CUTOFF_ROWS = 15
# A drafted player is dropped from the page when he missed this many of the
# scored weeks *and* finished below his ADP - see _injury_shortened. Set at
# "more than 8 games", so it only catches seasons that were essentially lost,
# not the two- or three-week absences every roster deals with.
INJURY_GAMES_MISSED = 9
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

    # adp_player carries the source's display spelling ("Ja'Marr Chase"), since
    # picks["Name"] is the CamelCase join key ("JaMarrChase").
    adp = adp.rename(columns={"player": "adp_player"})
    m = picks.merge(adp[["key", "adp_player", "adp", "adp_min", "adp_max", "adp_pos"]],
                    on="key", how="left")
    m["OvrValue"] = (m["overall_pick"] - m["adp"]).round(1)
    m["PosValue"] = (m["draft_pos_rank"] - m["adp_pos"]).astype("Int64")
    # Finish vs ADP: consensus ADP minus actual finish (positive = beat consensus).
    m["BeatADP"] = (m["adp"] - m["final_rank"]).round(1)
    rng = m["adp_min"].astype("Int64").astype(str) + "-" + m["adp_max"].astype("Int64").astype(str)
    m["ADP Range"] = rng.where(m["adp"].notna())
    m["Injured"] = _injury_shortened(m)
    return m


def _injury_shortened(m: pd.DataFrame) -> pd.Series:
    """True where a bad season looks like games missed rather than a bad pick.

    Two conditions, because either alone is the wrong call: a player who missed
    half the year and still finished ahead of his ADP says nothing bad about the
    manager, and a healthy bust says everything.

      * he missed at least INJURY_GAMES_MISSED of the scored weeks, and
      * he finished below consensus ADP.

    Games played is the only availability signal in the data (it is what the
    homepage injury section runs on too), so this catches holdouts and benchings
    along with injuries - all cases where the manager drafted a player who was
    then not on the field.
    """
    played = pd.to_numeric(m["Games Played"], errors="coerce")
    missed = played.max() - played
    return (missed >= INJURY_GAMES_MISSED) & (m["BeatADP"] < 0)


def _matched(season_str) -> pd.DataFrame:
    """The picks every table on the page is built from: matched to an ADP, and
    with the injury-shortened seasons taken out."""
    m = _picks_with_adp(season_str)
    return m[m["adp"].notna() & ~m["Injured"]].copy()


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
    return _assemble(rank(False), rank(True), _owner(matched, "OvrValue", "{:+.1f}", 10), full, "ADP")


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

_ALL_COLS = ["Season", "Manager", "Name", "Pos.", "overall_pick", "final_rank", "vsFinish", "adp"]
_ALL_RENAME = {"Name": "Player", "Pos.": "Pos", "overall_pick": "Overall Pick",
               "final_rank": "Fantasy Finish", "vsFinish": "Finish vs Pick", "adp": "ADP"}


def matched_with_manager(season_str) -> pd.DataFrame:
    """One season's ADP-matched picks tagged with Season, stable Manager, and
    both success metrics: vsADP (pick - ADP) and vsFinish (pick - finish).

    Injury-shortened seasons are dropped here as well as on the page itself, so
    the all-time manager numbers aren't dragged down by picks that never got a
    chance to work out.
    """
    m = _matched(season_str)
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
        Picks=("vsFinish", "count"),
        AvgFinish=("vsFinish", "mean"),
        Busts=("vsFinish", lambda v: int((v < -10).sum())),
        Values=("vsFinish", lambda v: int((v > 10).sum())),
        AvgADP=("OvrValue", "mean"),
    ).reset_index()
    g["AvgFinish"] = g["AvgFinish"].round(1)
    g["AvgADP"] = g["AvgADP"].round(1)
    g = g.rename(columns={"AvgFinish": "Avg Finish vs Pick", "Busts": "Busts (>10)",
                          "Values": "Values (>10)", "AvgADP": "Avg Value vs ADP"})
    g = g.sort_values("Avg Finish vs Pick", ascending=False)
    return (g.style.hide(axis="index")
            .format({"Avg Finish vs Pick": "{:+.1f}", "Avg Value vs ADP": "{:+.1f}"})
            .background_gradient(cmap="RdYlGn", subset=["Avg Finish vs Pick"])
            .set_table_styles(_GRID_WIDE, overwrite=False)
            .set_table_attributes('class="sticky-table"')).to_html()


def all_time_section() -> str:
    """Combined draft value/bust summaries across every season (homepage section)."""
    df = _all_seasons()

    def ranked(asc, cmap):
        d = df.sort_values("vsFinish", ascending=asc).head(CUTOFF_ROWS)[_ALL_COLS].rename(columns=_ALL_RENAME)
        return _style(d, "{:+.0f}", cmap, wide=False, grad_col="Finish vs Pick")

    link = layout.internal_link("/adp/", "Draft vs ADP")
    return (
        "<p>Combined across every league season. <strong>Finish vs Pick</strong> = draft position "
        "minus fantasy finish: <strong>+</strong> = the player finished better than where he was "
        "taken (a value), <strong>-</strong> = worse (a bust). Consensus <strong>ADP</strong> is "
        "shown as draft-day context only.</p>"
        f"<p>Full draft-vs-ADP by season: {link}</p>"
        "<h2>Draft Tendencies by Manager</h2>"
        f"<div class='table-scroll'>{_manager_summary(df)}</div>"
        "<h2>Best Values (all-time)</h2>"
        f"<div class='table-scroll'>{ranked(False, 'Greens')}</div>"
        "<h2>Biggest Busts (all-time)</h2>"
        f"<div class='table-scroll'>{ranked(True, 'Reds_r')}</div>"
    )


# --------------------------------------------------------------------------- #
# Page (season x view grid)
# --------------------------------------------------------------------------- #

def _match_note(m, matched) -> str:
    """What was left out of this season, and why: no ADP, or too hurt to judge."""
    unmatched = list(m[m["adp"].isna()]["Name"])
    hurt = sorted(m[m["adp"].notna() & m["Injured"]]["adp_player"].dropna())
    note = (f"<p>{len(matched)} of {len(m)} picks shown"
            + (f" (no ADP for: {', '.join(unmatched)})." if unmatched else "."))
    if hurt:
        note += (f" Another {len(hurt)} sat out too much of the season to grade the pick on "
                 f"and are left off: {', '.join(hurt)}.")
    return note + "</p>"


def generate():
    """Build and write docs/adp/index.html (season x overall/positional views)."""
    seasons = [(s, FORMAL_SEASON[s]) for s in LEAGUE_IDS]
    views = [("overall", "Overall"), ("positional", "By Position")]

    content = {}
    for season_str, _ in seasons:
        m = _picks_with_adp(season_str)
        matched = _matched(season_str)
        note = _match_note(m, matched)
        content[(season_str, "overall")] = note + _overall_view(matched)
        content[(season_str, "positional")] = note + _positional_view(matched)

    intro = (
        "<p>How the league drafted vs <strong>consensus ADP</strong> (FantasyPros PPR, "
        "averaged across ESPN/Sleeper/Yahoo/CBS/NFL). <strong>ADP Value</strong> = league rank minus "
        "consensus rank: <strong>+</strong> = drafted later than consensus (value), "
        "<strong>-</strong> = drafted earlier (reach). <strong>Fantasy Finish</strong> is the "
        "player's actual end-of-season rank. Pick a season and a view below.</p>"
        f"<p>Players who missed more than {INJURY_GAMES_MISSED - 1} games and finished below "
        "their ADP are left out: a season lost to injury says nothing about the pick. Each "
        "season notes who was dropped.</p>"
    )

    html = layout.HEAD + intro + layout.two_axis_switcher(
        seasons, views, content, row_label="Season:", col_label="View:", group="adp")

    page = add_front_matter(html, "Draft vs ADP")
    out = ROOT / "docs" / "adp" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"Wrote Draft vs ADP page -> {out}")


if __name__ == "__main__":
    generate()
