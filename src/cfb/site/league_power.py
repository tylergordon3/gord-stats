"""
League power rankings (docs/cfb/league-power/) - the ten fantasy rosters.

Every roster priced the way the draft board priced the players: the best
starting lineup it can field, in projected season points under this league's
own scoring and slots. Follows Yahoo's live rosters, so waivers and trades
move the rankings all season; fresh off the draft (before Yahoo populates the
roster feed) the draft results stand in.

Tracked over the season the same way the other rating pages are: every build
archives team -> rank (gordstats.rankmoves, data/cfb/league_power_history/),
and the Move columns say who climbed since the last build and the last week.

    python -m cfb.site.league_power     # rebuild the page
"""
from datetime import datetime

import pandas as pd

from cfb import projections, yahoo
from cfb.config import DATA_DIR, LEAGUE_TZ, SEASON, WEB_DIR
from cfb.site import write_page
from gordstats import rankmoves

HISTORY_DIR = DATA_DIR / "league_power_history" / str(SEASON)
OUTPUT = WEB_DIR / "league-power" / "index.html"

_CSS = """<style>
table.lg-table{width:100%;border-collapse:collapse;font-size:14px}
table.lg-table th{background:#eef2f7;color:#334155;padding:7px 10px;text-align:center;
  font-size:12px;text-transform:uppercase;letter-spacing:.03em;white-space:nowrap;
  border:1px solid #e2e8f0}
table.lg-table td{padding:6px 10px;border:1px solid #eef2f7;color:#0f172a;
  background:#fff;text-align:center;white-space:nowrap}
table.lg-table td.lg-team{text-align:left}
table.lg-table tbody tr:nth-child(even) td{background:#f8fafc}
table.lg-table img.lg-logo{width:22px;height:22px;border-radius:50%;
  vertical-align:middle;margin:0 7px 0 0;border:none;padding:0;box-shadow:none}
/* Team leads the table, so pinning first-child holds the identity column
   while the rest scrolls on a phone. The cells already carry opaque themed
   backgrounds (zebra and dark) from the rules above. */
table.lg-table td:first-child,table.lg-table th:first-child{
  position:sticky;left:0;z-index:1}
.mu-note{font-size:13px;color:#4a5a68;margin:4px 0 10px}
""" + rankmoves.CSS + """
@media (prefers-color-scheme: dark){
  table.lg-table th{background:#223052;color:#dde5ef;border-color:#2b3852}
  table.lg-table td{background:#16203a;border-color:#2b3852;color:#dde5ef}
  table.lg-table tbody tr:nth-child(even) td{background:#1b2540}
  .mu-note{color:#aab7c9}
}
</style>"""


def team_rosters() -> dict:
    """{team_key: [player_id, ...]} - live rosters, or the draft while
    Yahoo's roster feed still lags it (it stays empty until the draft
    completes; verified during the 2026 one)."""
    rosters = yahoo.rosters()
    if any(rosters.values()):
        return rosters
    out = {}
    for p in yahoo.draft_results():
        pid = str(p["player_key"] or "").rsplit(".", 1)[-1]
        out.setdefault(p["team_key"], []).append(pid)
    return out


def best_lineup(players: pd.DataFrame, lg: dict) -> dict:
    """The best starting lineup this roster supports.

    Dedicated slots take the top projections at their position; the flex slots
    then take the best skill player left - the same fill the live board used,
    because it is what a manager setting a lineup does. A slot nobody fills
    counts zero, which is what makes a thin roster rank honestly low.
    """
    pools = {p: players[players["pos"] == p].sort_values("proj", ascending=False)
             for p in projections.POSITIONS}
    used = {p: 0 for p in pools}
    by_pos = {p: 0.0 for p in pools}
    starters, flex_n = [], 0
    for slot in lg["roster"]:
        pos, n = slot["position"], int(slot["count"])
        if pos == projections.FLEX_SLOT:
            flex_n += n
            continue
        if pos not in pools:
            continue
        for _ in range(n):
            pool = pools[pos]
            if used[pos] < len(pool):
                by_pos[pos] += float(pool.iloc[used[pos]]["proj"])
                starters.append(pool.index[used[pos]])
            used[pos] += 1
    for _ in range(flex_n):
        best_pos = None
        best = 0.0
        for pos in projections.FLEX_POSITIONS:
            pool = pools[pos]
            if used[pos] < len(pool) and float(pool.iloc[used[pos]]["proj"]) > best:
                best, best_pos = float(pool.iloc[used[pos]]["proj"]), pos
        if best_pos is None:
            continue
        by_pos[best_pos] += best
        starters.append(pools[best_pos].index[used[best_pos]])
        used[best_pos] += 1

    lineup = players.loc[starters]
    bench = players.drop(starters)
    weight = lineup["proj"].sum()
    ratio = (lineup["proj"] * lineup["playoff_ratio"].fillna(1.0)).sum() / weight \
        if weight else 1.0
    return {
        "total": float(sum(by_pos.values())),
        "by_pos": by_pos,
        "bench": float(bench["vorp"].clip(lower=0).sum()),
        "playoff": float(ratio),
        "anchor": (lineup.loc[lineup["vorp"].idxmax()] if len(lineup) else None),
    }


def ranked_teams(lg: dict) -> list[dict]:
    """Every team's roster priced, best lineup first."""
    rosters = team_rosters()
    if not any(rosters.values()):
        return []
    board = (projections.value_board().drop_duplicates("yahoo_id")
             .set_index("yahoo_id"))
    names = {t["team_key"]: t for t in lg["teams"]}
    rows = []
    for key, ids in rosters.items():
        have = [i for i in dict.fromkeys(ids) if i in board.index]
        r = best_lineup(board.loc[have], lg)
        r["key"] = key
        r["team"] = names.get(key, {"name": key})
        r["unrated"] = len(set(ids)) - len(have)
        rows.append(r)
    rows.sort(key=lambda r: r["total"], reverse=True)
    return rows


def _move(baseline, key, rank):
    if baseline is None or key not in baseline.index:
        return ""
    return rankmoves.cell(baseline.get(key) - rank)


def body() -> str:
    lg = yahoo.league()
    rows = ranked_teams(lg)
    if not rows:
        return (_CSS + "<p>Nothing to rank yet — the rankings appear on the "
                "first rebuild after the draft, priced off the same "
                "projections as the draft board.</p>")

    avg = sum(r["total"] for r in rows) / len(rows)
    best_pos = {p: max(r["by_pos"][p] for r in rows) for p in projections.POSITIONS}
    moves = rankmoves.movement(HISTORY_DIR)
    prev = moves.get("prev")
    week = (moves.get("prev7")
            if moves.get("prev7_at") != moves.get("prev_at") else None)

    cells = []
    for i, r in enumerate(rows, 1):
        t = r["team"]
        logo = (f'<img class="lg-logo" src="{t["logo"]}" alt="" loading="lazy">'
                if t.get("logo") else "")
        pos_tds = "".join(
            f"<td>{'<b>' if r['by_pos'][p] == best_pos[p] and r['by_pos'][p] else ''}"
            f"{r['by_pos'][p]:.0f}"
            f"{'</b>' if r['by_pos'][p] == best_pos[p] and r['by_pos'][p] else ''}</td>"
            for p in projections.POSITIONS)
        anchor = (f"{r['anchor']['player']} ({r['anchor']['pos']})"
                  if r["anchor"] is not None else "—")
        move_tds = (f"<td>{_move(prev, r['key'], i)}</td>" if prev is not None else "") \
            + (f"<td>{_move(week, r['key'], i)}</td>" if week is not None else "")
        cells.append(
            f'<tr><td class="lg-team"><span class="row-rank">{i}</span>'
            f'{logo}{t["name"]}'
            + (f' <span class="mu-note">({r["unrated"]} unrated)</span>'
               if r["unrated"] else "") + f"</td>{move_tds}"
            f"<td><b>{r['total']:.0f}</b></td>"
            f"<td>{r['total'] - avg:+.0f}</td>{pos_tds}"
            f"<td>{r['bench']:.0f}</td>"
            f"<td>{(r['playoff'] - 1) * 100:+.0f}%</td>"
            f'<td class="lg-team">{anchor}</td></tr>')

    move_heads = ("<th title='Since the previous build'>Move</th>" if prev is not None else "") \
        + ("<th title='Since a week ago'>7d</th>" if week is not None else "")

    rankmoves.snapshot(HISTORY_DIR, pd.Series(
        {r["key"]: i for i, r in enumerate(rows, 1)}))

    built = datetime.now(LEAGUE_TZ).strftime("%b %-d, %-I:%M %p %Z")
    return (
        _CSS
        + f'<p><a href="{lg["url"]}"><strong>{lg["name"]}</strong></a> — every '
        "roster priced the way the draft board priced the players: the best "
        "starting lineup it can field, in projected season points under this "
        "league's scoring. <b>Bench</b> is the value over replacement sitting "
        f"behind the starters; <b>Wks {lg['playoff_start_week']}–"
        f"{lg['end_week']}</b> is how the lineup's schedule tilts across the "
        "fantasy playoffs. Follows the live rosters, so waivers and trades "
        f"move it — rebuilt daily (last: {built}), every build archived, and "
        "the Move columns track the climb: <b>Move</b> is places climbed "
        "since the previous build, <b>7d</b> since a week ago. "
        "<b>Lineup</b> is that best startable lineup's projected points, "
        "<b>±Avg</b> the same against the league average, and "
        "<b>Anchor</b> the roster's most valuable player.</p>"
        '<div class="table-scroll"><table class="lg-table">'
        f"<thead><tr><th>Team</th>{move_heads}<th>Lineup</th>"
        "<th>±Avg</th><th>QB</th><th>RB</th><th>WR</th><th>TE</th><th>DEF</th>"
        f"<th>Bench</th><th>Wks {lg['playoff_start_week']}–{lg['end_week']}</th>"
        "<th>Anchor</th></tr></thead>"
        f'<tbody>{"".join(cells)}</tbody></table></div>'
        '<p class="mu-note">Projection-based for now: it prices rosters, not '
        "records. Standings live on the "
        '<a href="/cfb/league/">league dashboard</a>; the '
        '<a href="/cfb/live/">draft review</a> grades how these rosters were '
        "assembled.</p>")


def generate():
    write_page(OUTPUT, f"CFB League Power Rankings {SEASON}", body())


if __name__ == "__main__":
    generate()
