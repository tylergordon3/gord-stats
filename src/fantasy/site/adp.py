"""
Draft values and busts, by where players actually finished (src/).

Once the Draft vs ADP page: it ranked every pick by how far from consensus ADP
it was taken, which grades the draft against the market rather than against
the season. That is now the Values & Busts section of the Draft Analytics page,
and it ranks on the outcome instead:

    Finish vs Pick = overall pick - fantasy finish
        + = the player finished better than where he was taken (a value)
        - = worse (a bust)

Consensus ADP (FantasyPros PPR, averaged across ESPN/Sleeper/Yahoo/CBS/NFL) is
still on every row as draft-day context, and the positional view does the same
on positional ranks, which is the fairer comparison across positions.

Seasons a player mostly missed are left off entirely - see _injury_shortened.
Nobody's draft grade should hinge on a torn ACL.

The season-keyed frames built here (`_picks_with_adp`, `matched_with_manager`)
are also what the Manager Draft Report and Draft DNA sections compute from.
"""
from functools import lru_cache

import pandas as pd

from fantasy import stats
from fantasy.config import FORMAL_SEASON, LEAGUE_IDS, LOST_SEASON_GAMES, ROSTER_NAMES, SEASON_YEAR
from fantasy.league.adp import get_adp
from fantasy.site import draft, layout, styles

CUTOFF_ROWS = 15
_GRID = [styles.GRID_TD, styles.GRID_TH]


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

      * he played fewer than LOST_SEASON_GAMES (the site-wide line for a lost
        season, see fantasy.config), and
      * he finished below consensus ADP.

    Games played is the only availability signal in the data (it is what the
    homepage injury section runs on too), so this catches holdouts and benchings
    along with injuries - all cases where the manager drafted a player who was
    then not on the field.
    """
    played = pd.to_numeric(m["Games Played"], errors="coerce")
    return (played < LOST_SEASON_GAMES) & (m["BeatADP"] < 0)


def _matched(season_str) -> pd.DataFrame:
    """The picks every table on the page is built from: matched to an ADP, and
    with the injury-shortened seasons taken out."""
    m = _picks_with_adp(season_str)
    m = m[m["adp"].notna() & ~m["Injured"]].copy()
    # The stable manager name, like every other section; "Owner" is the Sleeper
    # team name, which changes yearly and reads as a stranger's.
    m["Manager"] = m["roster_id"].map(ROSTER_NAMES)
    return m


# --------------------------------------------------------------------------- #
# Shared styling
# --------------------------------------------------------------------------- #

def _style(df, value_fmt, cmap, grad_col):
    """Gradient on one column; used by the homepage's all-time tables."""
    fmt = {grad_col: value_fmt}
    if "ADP" in df.columns:
        fmt["ADP"] = "{:.1f}"
    return (df.style.hide(axis="index").format(fmt)
            .background_gradient(cmap=cmap, subset=[grad_col])
            .set_table_styles(_GRID, overwrite=False)
            .set_table_attributes('class="sticky-table"')).to_html()


def _assemble(values, busts):
    return (f"<h2>Best Values</h2><div class='table-scroll'>{values}</div>"
            f"<h2>Biggest Busts</h2><div class='table-scroll'>{busts}</div>")


# --------------------------------------------------------------------------- #
# Views
# --------------------------------------------------------------------------- #

# Ranked and coloured on the outcome column; ADP and the gap to it stay on the
# row so a bust that consensus also liked reads differently from a pure reach.
_OVR_COLS = ["Pick", "overall_pick", "Manager", "Name", "Pos.", "final_rank", "vsFinish",
             "adp", "OvrValue"]
_OVR_RENAME = {"overall_pick": "Overall Pick", "Name": "Player", "Pos.": "Pos",
               "final_rank": "Fantasy Finish", "vsFinish": "Finish vs Pick",
               "adp": "ADP", "OvrValue": "ADP Value"}

_POS_COLS = ["Pos.", "Name", "Manager", "draft_pos_rank", "overall_pick", "final_pos_rank",
             "PosVsFinish", "adp_pos", "PosValue"]
_POS_RENAME = {"Pos.": "Pos", "Name": "Player", "draft_pos_rank": "Draft Pos",
               "overall_pick": "Overall Pick", "final_pos_rank": "Positional Finish",
               "PosVsFinish": "Finish vs Draft Pos", "adp_pos": "ADP Pos",
               "PosValue": "ADP Value"}


def _ranked(frame, value_col, cols, rename, best: bool, value_fmt, adp_fmt):
    df = (frame.sort_values(value_col, ascending=not best).head(CUTOFF_ROWS)[cols]
          .rename(columns=rename))
    grad = rename[value_col]
    fmt = {grad: value_fmt, "ADP Value": adp_fmt}
    if "ADP" in df.columns:
        fmt["ADP"] = "{:.1f}"
    return (df.style.hide(axis="index").format(fmt, na_rep="—")
            .background_gradient(cmap="Greens" if best else "Reds_r", subset=[grad])
            .set_table_styles(_GRID, overwrite=False)
            .set_table_attributes('class="sticky-table"')).to_html()


def _overall_view(matched):
    m = matched.copy()
    m["vsFinish"] = m["overall_pick"] - m["final_rank"]
    return _assemble(_ranked(m, "vsFinish", _OVR_COLS, _OVR_RENAME, True, "{:+.0f}", "{:+.1f}"),
                     _ranked(m, "vsFinish", _OVR_COLS, _OVR_RENAME, False, "{:+.0f}", "{:+.1f}"))


def _positional_view(matched):
    # 900+ is fantasy.site.draft's sentinel for a player with no positional finish.
    m = matched[matched["final_pos_rank"] < 900].copy()
    m["PosVsFinish"] = m["draft_pos_rank"] - m["final_pos_rank"]
    return _assemble(_ranked(m, "PosVsFinish", _POS_COLS, _POS_RENAME, True, "{:+.0f}", "{:+.0f}"),
                     _ranked(m, "PosVsFinish", _POS_COLS, _POS_RENAME, False, "{:+.0f}", "{:+.0f}"))


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
            .set_table_styles(_GRID + [styles.TABLE_STYLE], overwrite=False)
            .set_table_attributes('class="sticky-table"')).to_html()


def all_time_section() -> str:
    """Combined draft value/bust summaries across every season (homepage section)."""
    df = _all_seasons()
    # "WR5 → WR38": positional rank at draft vs positional fantasy finish.
    # 900+ is the sentinel for a player with no positional finish (never played).
    df["Pos Draft → Finish"] = (
        df["Pos."] + df["draft_pos_rank"].astype(str) + " → "
        + (df["Pos."] + df["final_pos_rank"].astype(str)).where(df["final_pos_rank"] < 900, "—"))

    def ranked(asc, cmap, cols=_ALL_COLS):
        d = df.sort_values("vsFinish", ascending=asc).head(CUTOFF_ROWS)[cols].rename(columns=_ALL_RENAME)
        return _style(d, "{:+.0f}", cmap, grad_col="Finish vs Pick")

    bust_cols = _ALL_COLS[:6] + ["Pos Draft → Finish"] + _ALL_COLS[6:]

    link = layout.internal_link("/fantasy/draft/#values", "Draft Analytics")
    return (
        "<p>Combined across every league season. <strong>Finish vs Pick</strong> = draft position "
        "minus fantasy finish: <strong>+</strong> = the player finished better than where he was "
        "taken (a value), <strong>-</strong> = worse (a bust). Consensus <strong>ADP</strong> is "
        "shown as draft-day context only.</p>"
        f"<p>Every season's values and busts, with the board they came off: {link}</p>"
        "<h2>Draft Tendencies by Manager</h2>"
        f"<div class='table-scroll'>{_manager_summary(df)}</div>"
        "<h2>Best Values (all-time)</h2>"
        f"<div class='table-scroll'>{ranked(False, 'Greens')}</div>"
        "<h2>Biggest Busts (all-time)</h2>"
        f"<div class='table-scroll'>{ranked(True, 'Reds_r', bust_cols)}</div>"
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


def body() -> str:
    """The Values & Busts section of the Draft Analytics page."""
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
        "<p>Every pick against where the player actually finished. <strong>Finish vs Pick</strong> "
        "= draft slot minus end-of-season rank: <strong>+</strong> = finished better than where "
        "he was taken (a value), <strong>-</strong> = worse (a bust). Consensus <strong>ADP</strong> "
        "(FantasyPros PPR, averaged across ESPN/Sleeper/Yahoo/CBS/NFL) and <strong>ADP Value</strong> "
        "(pick minus ADP, + = taken later than consensus) are on each row as draft-day context. "
        "<strong>By Position</strong> does the same on positional ranks, which is the fairer "
        "comparison across positions: an overall finish always favours quarterbacks.</p>"
        f"<p>Players who played fewer than {LOST_SEASON_GAMES} games and finished below "
        "their ADP are left out: a season lost to injury says nothing about the pick. Each "
        "season notes who was dropped.</p>"
    )
    return intro + layout.two_axis_switcher(
        seasons, views, content, row_label="Season:", col_label="View:", group="adp")
