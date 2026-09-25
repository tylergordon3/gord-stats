"""
The most recent draft (src/) - the one the season has not graded yet.

The Draft Board section of Draft Analytics shows each past draft coloured by
how every pick finished. The draft just made has no finishes to show, so this
renders it the way the live board did while it was running: the snake grid
coloured by position, each pick carrying how far it landed from the player's
rank on the multi-site ADP board (fantasy.league.adp_board). Once the season
has games in it, the draft joins LEAGUE_IDS / DRAFT_IDS and the recap's
finish-based view takes over.

This replaced the live board (docs/fantasy/live/) after the 2026 draft: the
board polled Sleeper from the reader's browser, and with the draft over the
picks are a fact, so they are baked in at build time like everything else.

    python -m fantasy.site.draft_current      # prints the board, for a look
"""
from html import escape

import pandas as pd
import requests

from fantasy import sleeper_retry
from fantasy.config import (
    LEAGUE_TEAMS, LEAGUE_TZ, ROSTER_NAMES, UPCOMING_DRAFT_ID, UPCOMING_SEASON,
    UPCOMING_YEAR,
)
from fantasy.league.adp_board import board, last_updated
from fantasy.normalize import normalize_name
from fantasy.site import layout, styles

SLEEPER_API = "https://api.sleeper.app/v1"
_TIMEOUT = 20

# How far a pick has to sit from its board rank before the cell says so. A round
# is 10 picks in this league, so half a round is noise and anything more is
# somebody making a decision.
NUDGE = 5

_CSS = """<style>
table.draft-board td.cur-QB{background:#d3ddf5}
table.draft-board td.cur-RB{background:#d5efdd}
table.draft-board td.cur-WR{background:#fbeec2}
table.draft-board td.cur-TE{background:#fadfc8}
table.draft-board td.cur-DEF{background:#d4f0f7}
table.draft-board td.cur-K{background:#e6dff7}
table.draft-board td .v{font-size:11px;font-weight:700}
table.draft-board td .v.up{color:#1a7f4b}
table.draft-board td .v.down{color:#b3382c}
@media (prefers-color-scheme: dark){
  table.draft-board td.cur-QB{background:#1e2c52}
  table.draft-board td.cur-RB{background:#123c2e}
  table.draft-board td.cur-WR{background:#3d3413}
  table.draft-board td.cur-TE{background:#40280f}
  table.draft-board td.cur-DEF{background:#143a45}
  table.draft-board td.cur-K{background:#2e2450}
  table.draft-board td .v.up{color:#8ff0bd}
  table.draft-board td .v.down{color:#ffb4ab}
}
</style>"""


def _key(md: dict) -> str:
    """adp_board's join key for a Sleeper pick: normalized name, or dst + team."""
    pos = str(md.get("position") or "").upper()
    if pos in ("DEF", "DST"):
        return "dst" + str(md.get("team") or "").upper()
    return normalize_name(f"{md.get('first_name', '')} {md.get('last_name', '')}".strip()) or ""


def picks(draft_id: str = UPCOMING_DRAFT_ID) -> pd.DataFrame:
    """Every pick of the draft, graded against the ADP board.

    Columns: Pick, round, slot, Manager, Player, Pos, Team, ADP (board overall
    rank, NaN if the player was not on it) and Δ = Pick - ADP, so positive means
    the player lasted past where the market had him (a value) and negative
    means he was taken ahead of it (a reach).
    """
    raw = sleeper_retry.get_json(f"{SLEEPER_API}/draft/{draft_id}/picks",
                                 timeout=_TIMEOUT) or []
    if not raw:
        return pd.DataFrame()

    adp = board(UPCOMING_YEAR).set_index("merge_name")["Ovr"].astype(float)
    per_round = max(p["pick_no"] for p in raw if p["round"] == 1)

    rows = []
    for p in raw:
        md = p.get("metadata") or {}
        pos = str(md.get("position") or "").upper()
        name = f"{md.get('first_name', '')} {md.get('last_name', '')}".strip()
        if pos == "DEF":
            name = f"{md.get('last_name') or md.get('team')} D/ST"
        pick_in_round = p["pick_no"] - (p["round"] - 1) * per_round
        rows.append({
            "Pick": p["pick_no"],
            "round": p["round"],
            "slot": pick_in_round if p["round"] % 2 == 1 else per_round + 1 - pick_in_round,
            "Manager": ROSTER_NAMES.get(p.get("roster_id"), str(p.get("roster_id"))),
            "Player": name or f"Player {p.get('player_id')}",
            "Pos": pos,
            "Team": md.get("team") or "",
            "ADP": adp.get(_key(md)),
        })
    df = pd.DataFrame(rows)
    df["Δ"] = df["Pick"] - df["ADP"]
    return df


# --------------------------------------------------------------------------- #
# Views
# --------------------------------------------------------------------------- #

def _delta_tag(delta) -> str:
    if pd.isna(delta) or abs(delta) < NUDGE:
        return ""
    cls = "up" if delta > 0 else "down"
    return f"<div class='v {cls}'>{'+' if delta > 0 else '−'}{abs(int(delta))}</div>"


def grid(df: pd.DataFrame) -> str:
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
            odd = (f"<div class='t'>({p['Manager']})</div>"
                   if p["Manager"] != slot_owner[s] else "")
            cells.append(
                f"<td class='cur-{p['Pos']}'><div class='p'>{p['Player']}</div>"
                f"<div class='t'>{p['Pos']}{' · ' + p['Team'] if p['Team'] else ''}</div>"
                f"{_delta_tag(p['Δ'])}{odd}</td>")
        rows.append(f"<tr><th>Rd {rnd}</th>{''.join(cells)}</tr>")
    return (f"<table class='draft-board'><thead><tr><th></th>{header}</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>")


def pick_table(df: pd.DataFrame) -> str:
    out = df.sort_values("Pick").copy()
    # The pick number folds into the Player cell (.row-rank, same as the power
    # page): a leading Pick column would make the frozen first column a counter
    # while the player's name scrolled away.
    out["Player"] = [f'<span class="row-rank">{int(p)}</span>{escape(n)}'
                     for p, n in zip(out["Pick"], out["Player"])]
    out = out[["Player", "Manager", "Pos", "Team", "ADP", "Δ"]]
    styled = (out.style.hide(axis="index")
              .background_gradient(cmap="RdYlGn", subset=["Δ"], vmin=-3 * NUDGE, vmax=3 * NUDGE)
              .format({"ADP": lambda v: "—" if pd.isna(v) else f"{v:.0f}",
                       "Δ": lambda v: "—" if pd.isna(v) else f"{v:+.0f}"})
              .set_table_styles([styles.GRID_TD, styles.GRID_TH, styles.TABLE_STYLE],
                                overwrite=False)
              .set_table_attributes('class="sticky-table"'))
    return styled.to_html()


def manager_table(df: pd.DataFrame) -> str:
    """Each manager's draft against the board: average Δ, best value, biggest reach."""
    graded = df.dropna(subset=["Δ"])
    rows = []
    for mgr, g in graded.groupby("Manager"):
        best, worst = g.loc[g["Δ"].idxmax()], g.loc[g["Δ"].idxmin()]
        rows.append({
            "Manager": mgr,
            "Avg Δ": g["Δ"].mean(),
            "Values": int((g["Δ"] >= NUDGE).sum()),
            "Reaches": int((g["Δ"] <= -NUDGE).sum()),
            "Best value": f"{best['Player']} ({best['Δ']:+.0f})",
            "Biggest reach": f"{worst['Player']} ({worst['Δ']:+.0f})",
        })
    out = pd.DataFrame(rows).sort_values("Avg Δ", ascending=False)
    styled = (out.style.hide(axis="index")
              .background_gradient(cmap="RdYlGn", subset=["Avg Δ"], vmin=-NUDGE, vmax=NUDGE)
              .format({"Avg Δ": "{:+.1f}"})
              .set_table_styles([styles.GRID_TD, styles.GRID_TH, styles.TABLE_STYLE],
                                overwrite=False)
              .set_table_attributes('class="sticky-table"'))
    return styled.to_html()


def view() -> str:
    """The section body for the most recent draft, or a note if Sleeper is down."""
    try:
        df = picks()
    except Exception as exc:                      # network / HTTP - keep the page
        print(f"  ! could not read draft {UPCOMING_DRAFT_ID} ({exc})")
        return (f"<p>The {UPCOMING_SEASON} draft could not be read from Sleeper at "
                "build time. It will appear on the next build.</p>")
    if df.empty:
        return f"<p>The {UPCOMING_SEASON} draft has no picks yet.</p>"

    stamp = last_updated(UPCOMING_YEAR)
    when = (stamp.astimezone(LEAGUE_TZ).strftime("%b %-d, %-I:%M %p %Z")
            if stamp else "an earlier build")
    ungraded = int(df["ADP"].isna().sum())
    return (
        _CSS
        + "<h2>Draft Board</h2>"
        f"<p>The {UPCOMING_SEASON} draft, pick by pick. No finishes yet — the season "
        "has not started — so instead each cell is coloured by position and carries "
        "the pick against the player's rank on the multi-site ADP board "
        f"(pulled {when}): <span class='v up' style='font-weight:700;color:#1a7f4b'>+</span> "
        "lasted longer than the market said, "
        "<span style='font-weight:700;color:#b3382c'>−</span> a reach, shown past "
        f"{NUDGE} picks either way. Snake order, so even rounds run right to left."
        + (f" {ungraded} pick{'s' if ungraded != 1 else ''} had no ADP row and are ungraded."
           if ungraded else "")
        + "</p>"
        f'<div class="table-scroll">{grid(df)}</div>'
        + layout.details(
            "Managers vs the Board",
            "<p><strong>Avg Δ</strong> is the mean of (pick − board rank) across a "
            "manager's graded picks; positive means the room let value fall to them.</p>"
            f'<div class="table-scroll">{manager_table(df)}</div>')
        + layout.details(
            "Pick by Pick",
            "<p><strong>ADP</strong> is the player's overall rank on the board; "
            "<strong>Δ</strong> = pick − ADP.</p>"
            f'<div class="table-scroll">{pick_table(df)}</div>')
    )


if __name__ == "__main__":
    print(picks().to_string())
