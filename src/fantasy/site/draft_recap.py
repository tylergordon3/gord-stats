"""
Draft Recap page (src/).

One view per season, picked with the season buttons:
  * Draft Board - the full snake grid (rounds x slots). Every cell carries the
    pick's positional tier at draft (RBs taken 1-10 = RB1, 11-20 = RB2, ...)
    and the tier the player actually finished in, colored by the move:
    green = finished tiers better than his draft cost, red = worse.
  * Pick-by-Pick - every pick as a row with exact position finish and the
    tier move highlighted.

Unlike the Draft vs ADP page this keeps K / team defenses - it is a record of
the whole draft, not a skill-position value judgement.

    python -m fantasy.site.draft_recap
"""
import re

import matplotlib as mpl
from matplotlib.colors import Normalize, rgb2hex

from fantasy import paths
from fantasy.config import FORMAL_SEASON, LEAGUE_IDS, LEAGUE_TEAMS, ROOT, ROSTER_NAMES
from fantasy.site import draft, layout, styles
from gordstats.frontmatter import add_front_matter

# Tier moves at or beyond +/- TIER_SPAN get the strongest green/red.
TIER_SPAN = 3
_CMAP = mpl.colormaps["RdYlGn"]
_NORM = Normalize(vmin=-TIER_SPAN, vmax=TIER_SPAN)

_BOARD_CSS = """<style>
table.draft-board{border-collapse:collapse;font-size:12px;margin:6px auto}
table.draft-board th{border:1px solid #e2e8f0;padding:6px 8px;background:#eef2f7;color:#334155;
  font-size:11px;text-transform:uppercase;letter-spacing:.03em}
table.draft-board td{border:1px solid #e5e7eb;padding:5px 7px;text-align:center;min-width:96px}
table.draft-board td .p{font-weight:600;white-space:nowrap}
table.draft-board td .t{font-size:11px;white-space:nowrap}
</style>"""


def _tier(rank: int) -> int:
    return (rank - 1) // LEAGUE_TEAMS + 1


def _display_name(row) -> str:
    """Sleeper's spelling of the pick; defenses stay as short team codes."""
    if row["Pos."] == "DEF":
        return f"{row['Name']} D/ST"
    return row["Display Name"] or re.sub(r"(?<=[a-z])(?=[A-Z])", " ", row["Name"])


def _picks(season_str: str):
    """Full draft with parsed ranks, tiers and board coordinates."""
    df = draft._build(season_str, keep_streamers=True)[0].copy()
    df[["overall_pick", "final_rank"]] = df["Overall Rk"].str.split(" -> ", expand=True).astype(int)
    df[["draft_pos", "final_pos"]] = df["Position Rk"].str.split(" -> ", expand=True).astype(int)

    per_round = int(df.groupby("round")["overall_pick"].count().max())
    df["pick_in_round"] = df["overall_pick"] - (df["round"] - 1) * per_round
    # Column on the board = the manager's seat: snake rounds count backwards.
    df["slot"] = df.apply(
        lambda x: x["pick_in_round"] if x["round"] % 2 == 1
        else per_round + 1 - x["pick_in_round"], axis=1)

    df["Manager"] = df["roster_id"].map(ROSTER_NAMES)
    df["Player"] = df.apply(_display_name, axis=1)
    df["draft_tier"] = df["draft_pos"].map(_tier)
    df["finish_tier"] = df["final_pos"].map(_tier)
    df["Tier Δ"] = df["draft_tier"] - df["finish_tier"]     # + = finished better
    df["Drafted"] = df["Pos."] + df["draft_tier"].astype(str)
    df["Finished"] = (df["Pos."] + df["finish_tier"].astype(str)
                      + " (#" + df["final_pos"].astype(str) + ")")
    return df


def _cell_colors(delta: int) -> str:
    rgb = _CMAP(_NORM(delta))[:3]
    return f"background-color:{rgb2hex(rgb)};color:{styles._font_for_bg(rgb)}"


# --------------------------------------------------------------------------- #
# Draft board grid
# --------------------------------------------------------------------------- #

def board(df) -> str:
    slot_owner = (df[df["round"] == 1].sort_values("slot")
                  .set_index("slot")["Manager"].to_dict())
    header = "".join(f"<th>{slot_owner.get(s, '?')}</th>" for s in sorted(slot_owner))

    rows = []
    for rnd, grp in df.groupby("round"):
        by_slot = grp.set_index("slot")
        cells = []
        for s in sorted(slot_owner):
            if s not in by_slot.index:
                cells.append("<td></td>")
                continue
            p = by_slot.loc[s]
            # Traded pick: the cell belongs to the column's seat but was made
            # by someone else - name them.
            odd = (f"<div class='t'>({p['Manager']})</div>"
                   if p["Manager"] != slot_owner[s] else "")
            cells.append(
                f"<td style=\"{_cell_colors(p['Tier Δ'])}\">"
                f"<div class='p'>{p['Player']}</div>"
                f"<div class='t'>{p['Drafted']} → {p['Pos.']}{p['finish_tier']}</div>{odd}</td>")
        rows.append(f"<tr><th>Rd {rnd}</th>{''.join(cells)}</tr>")

    return (f"<table class='draft-board'><thead><tr><th></th>{header}</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>")


# --------------------------------------------------------------------------- #
# Pick-by-pick table
# --------------------------------------------------------------------------- #

def pick_table(df) -> str:
    cols = ["Pick", "Manager", "Player", "Pos.", "Drafted", "Finished", "Tier Δ", "Pts."]
    out = df.sort_values("overall_pick")[cols]
    styled = (out.style.hide(axis="index")
              .background_gradient(cmap="RdYlGn", subset=["Tier Δ"],
                                   vmin=-TIER_SPAN, vmax=TIER_SPAN)
              .format({"Pts.": "{:.0f}", "Tier Δ": "{:+d}"})
              .set_table_styles([styles.GRID_TD, styles.GRID_TH, styles.TABLE_STYLE],
                                overwrite=False)
              .set_table_attributes('class="sticky-table"'))
    return styled.to_html()


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #

def _season_view(season_str: str) -> str:
    df = _picks(season_str)
    return (
        '<h2>Draft Board</h2>'
        f'<p>Positional tier at draft (first {LEAGUE_TEAMS} RBs off the board = RB1, '
        f'next {LEAGUE_TEAMS} = RB2, ...) → tier the player finished the season in. '
        'Green = outplayed his draft cost, red = fell short.</p>'
        f'<div class="table-scroll">{board(df)}</div>'
        '<h2>Pick by Pick</h2>'
        '<p><strong>Finished</strong> shows the tier plus the exact position finish '
        'by total points; <strong>Tier Δ</strong> is tiers gained (+) or lost (-).</p>'
        f'<div class="table-scroll">{pick_table(df)}</div>'
    )


def body() -> str:
    """This section's content, for the combined draft page or a standalone one.

    The switcher group is "recap" rather than "season" so it can share a page
    with the other draft sections without their controls colliding.
    """
    views = [(s, FORMAL_SEASON[s], _season_view(s)) for s in LEAGUE_IDS]
    return _BOARD_CSS + layout.view_switcher(views, group="recap", label="Season:")


def generate():
    """Build and write the standalone Draft Recap page."""
    page = add_front_matter(layout.HEAD + body(), "Draft Recap")

    out = paths.WEB_DRAFT_RECAP
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"Wrote draft recap page -> {out}")


if __name__ == "__main__":
    generate()
