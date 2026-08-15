"""
Waivers & Trades page (src/).

Three sections, all computed from data/transactions/<season>.json (plus
data/season/<season>.json for pickup production):
  * Manager activity - waiver claims, FAAB spent, free-agent adds, drops, trades.
  * Best pickups - in-season adds ranked by points scored in the starting lineup.
  * Trade log - who sent what to whom.

Every season lives on the one page (docs/transactions/index.html), picked with
the season buttons - same shape as the schedule page.

    python -m src.site.transactions
"""
import pandas as pd

from src.config import (
    DATA_DIR, FANTASY_REG_WEEKS, FORMAL_SEASON, LEAGUE_IDS, ROOT, ROSTER_NAMES, SEASON_DIR,
)
from src.identity.registry import load_registry
from src.site import layout, styles
from src.site.frontmatter import add_front_matter

_GRID = [styles.GRID_TD, styles.GRID_TH, styles.TABLE_STYLE]

# NFL team codes show up as "players" for team defenses (e.g. adds {"GB": 9}).
_DEF_LABEL = "{} D/ST"


def _load_tx(season_str: str) -> pd.DataFrame:
    df = pd.read_json(DATA_DIR / "transactions" / f"{season_str}.json")
    df["manager"] = df["roster_ids"].apply(
        lambda ids: ROSTER_NAMES.get(ids[0]) if ids else None)
    return df


def _player_names() -> dict:
    reg = load_registry()
    reg = reg[reg["sleeper_id"].notna()]
    return dict(zip(reg["sleeper_id"], zip(reg["full_name"], reg["position"])))


def _name(pid, names: dict) -> str:
    pid = str(pid)
    if pid in names:
        return names[pid][0]
    if pid.isalpha():                     # team defense: sleeper id is the team code
        return _DEF_LABEL.format(pid)
    return pid


def _pos(pid, names: dict) -> str:
    pid = str(pid)
    if pid in names:
        return names[pid][1] or ""
    return "DEF" if pid.isalpha() else ""


# --------------------------------------------------------------------------- #
# Manager activity summary
# --------------------------------------------------------------------------- #

def activity(tx: pd.DataFrame) -> pd.DataFrame:
    """Per-manager counts of every kind of roster move."""
    rows = []
    for roster_id, manager in ROSTER_NAMES.items():
        mine = tx[tx["roster_ids"].apply(lambda ids: roster_id in ids)]
        waivers = mine[mine["type"] == "waiver"]
        fas = mine[mine["type"] == "free_agent"]
        trades = mine[mine["type"] == "trade"]
        drops = sum(
            1 for _, t in mine.iterrows() if t["type"] != "trade"
            for r in (t["drops"] or {}).values() if r == roster_id)
        rows.append({
            "Manager": manager,
            "Waiver Claims": len(waivers),
            "FAAB Spent": int(waivers["waiver_bid"].fillna(0).sum()),
            "FA Adds": len(fas),
            "Total Adds": len(waivers) + len(fas),
            "Drops": drops,
            "Trades": len(trades),
        })
    out = pd.DataFrame(rows).set_index("Manager")
    if out["FAAB Spent"].sum() == 0:      # pre-FAAB season (priority waivers)
        out = out.drop(columns=["FAAB Spent"])
    return out.sort_values(["Total Adds", "Waiver Claims"], ascending=False)


# --------------------------------------------------------------------------- #
# Best pickups (points scored in the starting lineup after the add)
# --------------------------------------------------------------------------- #

def best_pickups(season_str: str, tx: pd.DataFrame, names: dict, top: int = 15) -> pd.DataFrame:
    """In-season adds ranked by points the player then scored as a starter.

    Counts weeks from the add through the earlier of: the manager dropping the
    player again, or the end of the fantasy regular season (the season file
    only stores weeks 1..14).
    """
    season = pd.read_json(SEASON_DIR / f"{season_str}.json")
    starters = {(r["roster_id"], r["week"]): r["starters_dict"] for _, r in season.iterrows()}
    max_week = season["week"].max()

    adds = tx[tx["type"].isin(["waiver", "free_agent"])]
    # When was (player, roster) dropped again? First drop after the add wins.
    drop_weeks = [(str(pid), r, t["leg"]) for _, t in adds.iterrows()
                  for pid, r in (t["drops"] or {}).items()]

    rows = []
    for _, t in adds.iterrows():
        for pid, roster_id in (t["adds"] or {}).items():
            pid = str(pid)
            until = min([w for p, r, w in drop_weeks
                         if p == pid and r == roster_id and w > t["leg"]] + [max_week + 1])
            pts, games = 0.0, 0
            for week in range(max(1, t["leg"]), min(until, max_week + 1)):
                week_starters = starters.get((roster_id, week), {})
                if pid in week_starters:
                    pts += week_starters[pid]
                    games += 1
            if games:
                via = (f"Waiver (${int(t['waiver_bid'])})"
                       if t["type"] == "waiver" and pd.notna(t["waiver_bid"]) and t["waiver_bid"] > 0
                       else "Waiver" if t["type"] == "waiver" else "Free Agent")
                rows.append({
                    "Player": _name(pid, names), "Pos": _pos(pid, names),
                    "Manager": ROSTER_NAMES.get(roster_id),
                    "Week Added": t["leg"], "Via": via,
                    "Starts": games, "Starter Pts": round(pts, 1),
                })
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows).sort_values("Starter Pts", ascending=False).head(top)
    out.insert(0, "Rank", range(1, len(out) + 1))
    return out.set_index("Rank")


# --------------------------------------------------------------------------- #
# Trade log
# --------------------------------------------------------------------------- #

def _trade_side(trade, roster_id: int, names: dict) -> str:
    """Everything one roster received in a trade, as a comma list."""
    got = [_name(pid, names) for pid, r in (trade["adds"] or {}).items() if r == roster_id]
    got += [f"${m['amount']} FAAB" for m in trade["faab_moves"] if m.get("receiver") == roster_id]
    for pick in trade["draft_picks"]:
        if pick.get("owner_id") == roster_id:
            frm = ROSTER_NAMES.get(pick.get("roster_id"), "?")
            got.append(f"{pick.get('season')} Rd {pick.get('round')} pick (orig. {frm})")
    return ", ".join(got) if got else "nothing"


def trade_log(tx: pd.DataFrame, names: dict) -> pd.DataFrame:
    trades = tx[tx["type"] == "trade"]
    rows = []
    for _, t in trades.iterrows():
        parties = t["roster_ids"]
        for roster_id in parties:
            rows.append({
                "Week": t["leg"],
                "Manager": ROSTER_NAMES.get(roster_id, "?"),
                "Received": _trade_side(t, roster_id, names),
            })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #

def _season_view(season_str: str, names: dict) -> str:
    tx = _load_tx(season_str)
    # reset_index() keeps Manager/Rank as real columns — a styled index
    # renders its name as a phantom second header row.
    act = (activity(tx).reset_index().style.set_table_styles(_GRID)
           .hide(axis="index").to_html())

    pickups = best_pickups(season_str, tx, names)
    pickups_html = (pickups.reset_index().style.set_table_styles(_GRID)
                    .hide(axis="index").format({"Starter Pts": "{:.1f}"}).to_html()
                    if not pickups.empty else "<p><em>No pickups started yet this season.</em></p>")

    trades = trade_log(tx, names)
    trades_html = (trades.style.set_table_styles(_GRID).hide(axis="index").to_html()
                   if not trades.empty else "<p><em>No trades this season. Cowards.</em></p>")

    faab_note = ("<p><strong>FAAB Spent</strong>: total winning free-agent budget bids.</p>"
                 if "FAAB Spent" in act else "")
    return (
        '<h2>Manager Activity</h2>'
        '<p>Completed roster moves only - failed waiver claims don\'t count.</p>'
        f'{faab_note}'
        f'<div class="table-scroll">{act}</div>'
        '<h2>Best Pickups</h2>'
        '<p>In-season adds ranked by points scored <em>in the starting lineup</em> after the add '
        '(until dropped, through week 14). Bench stashes score nothing here.</p>'
        f'<div class="table-scroll">{pickups_html}</div>'
        '<h2>Trade Log</h2>'
        f'<div class="table-scroll">{trades_html}</div>'
    )


def _all_time_view(names: dict) -> str:
    frames = [activity(_load_tx(s)) for s in LEAGUE_IDS]
    combined = pd.concat(frames)          # pre-FAAB seasons lack the FAAB column -> NaN
    total = combined.groupby("Manager").sum().astype(int).sort_values(
        ["Total Adds", "Waiver Claims"], ascending=False)
    html = (total.reset_index().style.set_table_styles(_GRID)
            .hide(axis="index").to_html())
    return (
        '<h2>All-Time Manager Activity</h2>'
        f'<p>Every completed move across all {len(LEAGUE_IDS)} seasons. '
        'FAAB totals only count seasons with bid waivers.</p>'
        f'<div class="table-scroll">{html}</div>'
    )


def generate():
    """Build and write docs/transactions/index.html - every season, switchable."""
    names = _player_names()
    views = [(s, FORMAL_SEASON[s], _season_view(s, names)) for s in LEAGUE_IDS]
    views.append(("all", "All-Time", _all_time_view(names)))
    body = layout.HEAD + layout.view_switcher(views, group="season", label="Season:")
    page = add_front_matter(body, "Waivers & Trades")

    out = ROOT / "docs" / "transactions" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"Wrote transactions page -> {out}")


if __name__ == "__main__":
    generate()
