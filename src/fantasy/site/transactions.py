"""
Waivers & Trades page (src/).

Three sections, all computed from data/transactions/<season>.json (plus
data/season/<season>.json for pickup production):
  * Manager activity - waiver claims, FAAB spent, free-agent adds, drops, trades.
  * Best pickups - in-season adds ranked by points scored in the starting lineup.
  * Trade log - who sent what to whom.

Every season lives on the one page (docs/transactions/index.html), picked with
the season buttons - same shape as the schedule page.

The season being played is handled here, whether or not it has been added to
LEAGUE_IDS (see fantasy.config): its log is pulled from Sleeper on every build, its pickups are
scored from the weekly matchup archive (data/fantasy/matchups/<year>/) rather
than a season file, and it carries a move-by-move Waiver Log while the season
is young enough that few pickups have started a game.

    python -m fantasy.site.transactions
"""
from html import escape

import json

import pandas as pd

from fantasy import paths
from fantasy.config import (
    DATA_DIR, FANTASY_REG_WEEKS, FORMAL_SEASON, LEAGUE_IDS, ROOT, ROSTER_NAMES, SEASON_DIR,
    UPCOMING_LEAGUE_ID, UPCOMING_SEASON, UPCOMING_YEAR,
)
from fantasy.league import suggestions as suggest
from fantasy.league import transactions as transactions_data
from fantasy.league.matchups import MATCHUPS_DIR
from fantasy.identity.registry import load_registry
from fantasy.site import layout, styles
from gordstats.frontmatter import add_front_matter

_GRID = [styles.GRID_TD, styles.GRID_TH, styles.TABLE_STYLE]

# NFL team codes show up as "players" for team defenses (e.g. adds {"GB": 9}).
_DEF_LABEL = "{} D/ST"

# The season being played, in the same "2627" shape as LEAGUE_IDS' keys.
CURRENT = f"{UPCOMING_YEAR % 100:02d}{(UPCOMING_YEAR + 1) % 100:02d}"


def _refresh_current() -> bool:
    """Pull the live season's log into data/transactions/<CURRENT>.json.
    False when there is neither a fresh pull nor an earlier copy to show.

    Pulled on every build, whether or not the season has been promoted into
    LEAGUE_IDS. It used to hand a promoted season to data_manager, but the
    scheduled preset runs no data jobs - so from the 2026-09-25 rollover the
    log stopped at that day and the page lost its Waiver Watch and Log.
    """
    path = DATA_DIR / "transactions" / f"{CURRENT}.json"
    try:
        df = transactions_data.get_transactions(UPCOMING_LEAGUE_ID)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_json(path)
    except Exception as exc:
        print(f"[transactions] {CURRENT} pull failed ({exc})"
              + ("; using the saved copy" if path.exists() else ""))
    return path.exists()


def _archive_starters() -> tuple[dict, int]:
    """({(roster_id, week): {player_id: points}}, last week) for the live
    season, from the weekly matchup archive - the season file's shape."""
    starters, last = {}, 0
    for f in sorted((MATCHUPS_DIR / str(UPCOMING_YEAR)).glob("week_*.json")):
        wk = json.loads(f.read_text(encoding="utf-8"))
        played = False
        for m in wk.get("matchups") or []:
            for side in m.get("sides") or []:
                pts = side.get("players_points") or {}
                starters[(side["roster_id"], wk["week"])] = {
                    pid: pts.get(pid, 0.0) for pid in side.get("starters") or []}
                played = played or any(pts.values())
        if played:
            last = max(last, wk["week"])
    return starters, min(last, FANTASY_REG_WEEKS)


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

def best_pickups(season_str: str, tx: pd.DataFrame, names: dict, top: int = 15,
                 starters: dict = None, max_week: int = None) -> pd.DataFrame:
    """In-season adds ranked by points the player then scored as a starter.

    Counts weeks from the add through the earlier of: the manager dropping the
    player again, or the end of the fantasy regular season (the season file
    only stores weeks 1..14).
    """
    if starters is None:
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
    # Rank folds into the Player cell (.row-rank, same as the power page): a
    # leading Rank column would make the frozen first column a counter while
    # the player's name scrolled away.
    out["Player"] = [f'<span class="row-rank">{n}</span>{escape(p)}'
                     for n, p in enumerate(out["Player"], start=1)]
    return out


# --------------------------------------------------------------------------- #
# Who to add, who to drop
# --------------------------------------------------------------------------- #

def _fmt_player(name: str, flag: str = "") -> str:
    tag = f" <span class='tx-flag'>{escape(str(flag))}</span>" if flag else ""
    return f"{escape(str(name))}{tag}"


def waiver_watch() -> str:
    """The free agents worth a claim, and the roster spots they would take.

    Both tables are the same number: points expected next week (Sleeper's
    projection where it has one, ours otherwise) less what the position hands
    out for free, so an add and a drop can be read against each other.
    """
    week = suggest.current_week()
    try:
        free, owned = suggest.pools(week=week)
    except Exception as exc:                            # noqa: BLE001
        print(f"[transactions] no waiver suggestions ({exc})")
        return ""
    add_rows, drop_rows = suggest.adds(free), suggest.drops(owned)
    if add_rows.empty:
        return ""

    adds_html = pd.DataFrame({
        "Player": [f'<span class="row-rank">{i}</span>{_fmt_player(r["player"], r["flag"])}'
                   for i, (_, r) in enumerate(add_rows.iterrows(), 1)],
        "Pos": add_rows["pos"].values, "Team": add_rows["team"].values,
        "Proj": add_rows["points"].values, "Over repl.": add_rows["score"].values,
    })
    drops_html = pd.DataFrame({
        "Manager": drop_rows["manager"].values,
        "Player": [_fmt_player(n) for n in drop_rows["player"]],
        "Pos": drop_rows["pos"].values,
        "Proj": drop_rows["points"].values, "Over repl.": drop_rows["score"].values,
    })

    def table(frame, gradient_low: bool):
        styled = (frame.style.set_table_styles(_GRID)
                  .set_table_attributes('class="sticky-table"')
                  .hide(axis="index").format({"Proj": "{:.1f}", "Over repl.": "{:+.1f}"})
                  .background_gradient(text_color_threshold=styles.GRADIENT_INK, cmap="RdYlGn_r" if gradient_low else "RdYlGn",
                                       subset=["Over repl."]))
        return f'<div class="table-scroll">{styles.to_html(styled)}</div>'

    return (
        '<h2>Waiver Watch</h2>'
        f'<p>The best free agents in the pool for week {week}, and the weakest player on '
        'each roster. <strong>Proj</strong> is points expected next week &mdash; '
        "Sleeper's projection where it has one, this site's per-game number otherwise "
        "&mdash; and <strong>Over repl.</strong> is that against what the position hands "
        "out for free, which is what actually decides a claim: a quarterback outscores a "
        "running back and always will.</p>"
        '<h3>Worth adding</h3>' + table(adds_html, False)
        + '<h3>Weakest rostered</h3>'
        '<p>Kickers and defenses are left out &mdash; every roster needs one of each.</p>'
        + table(drops_html, True))


# --------------------------------------------------------------------------- #
# Waiver log (the live season)
# --------------------------------------------------------------------------- #

def waiver_log(tx: pd.DataFrame, names: dict) -> pd.DataFrame:
    """Every completed add/drop, newest first."""
    moves = tx[tx["type"].isin(["waiver", "free_agent"])].sort_values(
        ["leg", "created"], ascending=False)
    rows = []
    for _, t in moves.iterrows():
        def players(side):
            return ", ".join(f"{_name(pid, names)} ({_pos(pid, names)})" if _pos(pid, names)
                             else _name(pid, names) for pid in (t[side] or {}))
        bid = t["waiver_bid"]
        via = ("Free Agent" if t["type"] == "free_agent"
               else f"Waiver (${int(bid)})" if pd.notna(bid) and bid > 0 else "Waiver")
        rows.append({"Week": t["leg"], "Manager": t["manager"], "Added": players("adds"),
                     "Dropped": players("drops"), "Via": via})
    return pd.DataFrame(rows)


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

def _table(frame: pd.DataFrame) -> str:
    return styles.to_html(frame.style.set_table_styles(_GRID).set_table_attributes('class="sticky-table"')
                          .hide(axis="index"))


def _current_view(names: dict) -> str:
    """The season being played: the same three sections, plus its waiver log."""
    tx = _load_tx(CURRENT)
    starters, last = _archive_starters()
    view = _season_view(CURRENT, names, tx=tx, starters=starters, max_week=last)
    log = waiver_log(tx, names)
    log_html = (_table(log) if not log.empty
                else "<p><em>No completed waiver claims or free-agent adds yet.</em></p>")
    return (waiver_watch() + '<h2>Waiver Log</h2>'
            f'<p>Every completed claim and free-agent add in {UPCOMING_SEASON}, newest first'
            + (f', through week {last}' if last else '') + '.</p>'
            f'<div class="table-scroll">{log_html}</div>' + view)


def _season_view(season_str: str, names: dict, tx: pd.DataFrame = None,
                 starters: dict = None, max_week: int = None) -> str:
    tx = _load_tx(season_str) if tx is None else tx
    # reset_index() keeps Manager as a real column — a styled index renders
    # its name as a phantom second header row.
    act = styles.to_html(activity(tx).reset_index().style.set_table_styles(_GRID)
                         .set_table_attributes('class="sticky-table"')
                         .hide(axis="index"))

    pickups = best_pickups(season_str, tx, names, starters=starters, max_week=max_week)
    pickups_html = (styles.to_html(pickups.style.set_table_styles(_GRID)
                                   .set_table_attributes('class="sticky-table"')
                                   .hide(axis="index").format({"Starter Pts": "{:.1f}"}))
                    if not pickups.empty else "<p><em>No pickups started yet this season.</em></p>")

    trades = trade_log(tx, names)
    trades_html = (styles.to_html(trades.style.set_table_styles(_GRID)
                                  .set_table_attributes('class="sticky-table"')
                                  .hide(axis="index"))
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


def _all_time_view(names: dict, seasons: list) -> str:
    frames = [activity(_load_tx(s)) for s in seasons]
    combined = pd.concat(frames)          # pre-FAAB seasons lack the FAAB column -> NaN
    total = combined.groupby("Manager").sum().astype(int).sort_values(
        ["Total Adds", "Waiver Claims"], ascending=False)
    html = styles.to_html(total.reset_index().style.set_table_styles(_GRID)
                          .set_table_attributes('class="sticky-table"')
                          .hide(axis="index"))
    return (
        '<h2>All-Time Manager Activity</h2>'
        f'<p>Every completed move across all {len(seasons)} seasons. '
        'FAAB totals only count seasons with bid waivers.</p>'
        f'<div class="table-scroll">{html}</div>'
    )


def generate():
    """Build and write docs/transactions/index.html - every season, switchable."""
    names = _player_names()
    seasons = [s for s in LEAGUE_IDS if s != CURRENT]
    views = [(s, FORMAL_SEASON[s], _season_view(s, names)) for s in seasons]
    # The season being played gets the live view - Waiver Watch, the log,
    # pickups scored from the matchup archive - in or out of LEAGUE_IDS.
    if _refresh_current():
        views.insert(0, (CURRENT, UPCOMING_SEASON, _current_view(names)))
        seasons.insert(0, CURRENT)
    views.append(("all", "All-Time", _all_time_view(names, seasons)))
    body = layout.HEAD + layout.view_switcher(views, group="season", label="Season:", pin=True)
    page = add_front_matter(
        body, "Waivers & Trades",
        description="Every waiver claim, free-agent add and trade in our fantasy league, season by "
                    "season: the best pickups by points started and each manager's FAAB spending.")

    out = paths.WEB_TRANSACTIONS
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"Wrote transactions page -> {out}")


if __name__ == "__main__":
    generate()
