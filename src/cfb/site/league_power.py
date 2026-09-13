"""
League power rankings - the ten fantasy rosters, a section of the league
dashboard (docs/cfb/league/, cfb.site.league) since 2026-09-08; the old
/cfb/league-power/ URL redirects there.

Every roster priced the way the draft board priced the players: the best
starting lineup it can field, in projected season points under this league's
own scoring and slots, with each player's preseason projection updated by
his real scoring so far (in_season_board). Follows Yahoo's live rosters, so waivers and trades
move the rankings all season; fresh off the draft (before Yahoo populates the
roster feed) the draft results stand in.

Tracked over the season the same way the other rating pages are: every build
archives team -> rank and lineup points (gordstats.rankmoves,
data/cfb/league_power_history/), the Move columns say who climbed since the
last build and the last week, and a Through the Season chart - one panel per
team with the league behind it in grey, the NFL power page's chart - draws
each roster's points against the league average build by build. Until two
builds carry the points, the panels draw rank instead, which every snapshot
has.

    python -m cfb.site.league_power     # the section as a page of its own
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates                    # noqa: E402
import matplotlib.pyplot as plt                      # noqa: E402
import numpy as np                                   # noqa: E402
import pandas as pd                                  # noqa: E402

from cfb import projections, yahoo                   # noqa: E402
from cfb.config import DATA_DIR, SEASON, WEB_DIR             # noqa: E402
from cfb.site import write_page                      # noqa: E402
from gordstats import charts, palette, rankmoves     # noqa: E402

HISTORY_DIR = DATA_DIR / "league_power_history" / str(SEASON)
OUTPUT = WEB_DIR / "league-power" / "index.html"
_SECTION = "cfb-league-power"

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
.lg-chart{margin:10px 0 18px}
.lg-chart img{border:none;padding:0;box-shadow:none;background:none;border-radius:0}
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


# How many games of the preseason projection a player's real scoring is
# weighed against. Estimated 2026-09-13 from the first two weeks of every
# rostered player (146 with two games): week-to-week noise sd 8.3 pts/game,
# true spread around the preseason per-game projection sd 3.8, so
# noise_var / prior_var ~ 4.7. After five games the season so far counts as
# much as the draft-day projection.
PRIOR_GAMES = 5.0


def season_so_far() -> pd.DataFrame:
    """yahoo_id -> points and games played, from the weekly matchup archive.

    A week counts as a game only when Yahoo has any stat for the player -
    byes, injuries and games not yet kicked off come back empty, so an
    in-progress week counts just the games already played. Only weeks a player
    spent on a league roster are seen; free-agent weeks are not."""
    seen = {}
    for w in yahoo.archived_weeks():
        for roster in yahoo.week_matchups(w)["rosters"].values():
            for p in roster:
                if p.get("stats"):
                    seen[(w, str(p["yahoo_id"]))] = float(p["points"] or 0.0)
    if not seen:
        return pd.DataFrame(columns=["points", "played"])
    pts = pd.Series(seen)
    return pts.groupby(level=1).agg(points="sum", played="count")


def in_season_board(board: pd.DataFrame) -> pd.DataFrame:
    """The value board with each projection updated by what the player has
    actually scored: per-game rate = (preseason rate x PRIOR_GAMES + points)
    / (PRIOR_GAMES + games), back on the season scale so the Lineup column and
    the archive keep their units."""
    so_far = season_so_far().reindex(board.index)
    played = so_far["played"].fillna(0.0)
    if not played.any():
        return board
    board = board.copy()
    prior = board["proj"] / board["games"]
    rate = (prior * PRIOR_GAMES + so_far["points"].fillna(0.0)) / (PRIOR_GAMES + played)
    scale = (rate / prior).where(prior > 0, 1.0)
    for col in ("proj", "floor", "ceiling"):
        board[col] = board[col] * scale
    board["vorp"] = board["proj"] - board["replacement"]
    board["played"] = played
    return board


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
    board = in_season_board(projections.value_board().drop_duplicates("yahoo_id")
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


def _record(team: dict) -> str:
    if team.get("wins") is None:
        return "\u2014"
    w, l, t = (int(team.get(k) or 0) for k in ("wins", "losses", "ties"))
    return f"{w}-{l}" + (f"-{t}" if t else "")


def _move(baseline, key, rank):
    if baseline is None or key not in baseline.index:
        return ""
    return rankmoves.cell(baseline.get(key) - rank)


def _season_section(names: dict) -> str:
    """Every roster's published figure, build by build - the NFL power page's
    chart. One panel per team with the rest of the league in grey: ten lines
    on one axis is a tangle nobody can read against a legend."""
    hist = rankmoves.history(HISTORY_DIR)
    if hist.empty:
        return ""
    hist["team"] = hist["key"].map(lambda k: names.get(k, k))
    rated = hist.dropna(subset=["vs_avg"]) if "vs_avg" in hist.columns else pd.DataFrame()
    if not rated.empty and rated["taken"].nunique() >= 2:
        pivot = rated.pivot_table(index="taken", columns="team", values="vs_avg").sort_index()
        what, base, invert, unit = "lineup points against the league average", 0.0, False, " pts"
    elif hist["taken"].nunique() >= 2:
        pivot = hist.pivot_table(index="taken", columns="team", values="rank").sort_index()
        what, base, invert, unit = "rank", None, True, ""
    else:
        return ("<h3>Through the Season</h3>"
                "<p class='mu-note'>The trend chart appears with the second build.</p>")

    order = pivot.iloc[-1].sort_values(ascending=invert).index.tolist()
    span_days = max(1, (pivot.index[-1] - pivot.index[0]).days + 1)
    cols = 5
    fig_rows = int(np.ceil(len(order) / cols))
    fig, axes = plt.subplots(fig_rows, cols, figsize=(11, 2.5 * fig_rows),
                             sharex=True, sharey=True)
    axes = np.atleast_1d(axes).ravel()
    for ax, team in zip(axes, order):
        for other in pivot.columns:
            ax.plot(pivot.index, pivot[other], color=palette.CONTEXT, linewidth=1.0, zorder=1)
        ax.plot(pivot.index, pivot[team], color=palette.BLUE, linewidth=2.0,
                marker="o", markersize=4, zorder=3)
        if base is not None:
            ax.axhline(base, color=palette.MUTED, linewidth=0.9, linestyle="--", zorder=2)
        # Yahoo team names run long; a panel is 2 inches wide.
        ax.set_title(team if len(team) <= 22 else team[:21] + "\u2026", fontsize=9)
        ax.grid(color=palette.GRIDLINE)
        ax.set_axisbelow(True)
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)
        ax.tick_params(labelsize=8)
        # Whole days, a handful of them: the auto locator falls back to 12-hour
        # ticks on a young archive and prints the same date twice.
        ax.xaxis.set_major_locator(mdates.DayLocator(interval=max(1, span_days // 4)))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %-d"))
        for label in ax.get_xticklabels():
            label.set_rotation(30)
            label.set_horizontalalignment("right")
    if invert:
        axes[0].invert_yaxis()
        axes[0].yaxis.set_major_locator(plt.MaxNLocator(integer=True))
    for ax in axes[len(order):]:
        ax.set_visible(False)
    fig.suptitle(f"Published {what} through the season, one panel per team", y=1.0)
    fig.tight_layout()
    chart = charts.save(_SECTION, "season-trend",
                        alt=f"One small chart per team showing its {what} across every "
                            "build, with the rest of the league in grey behind it")

    first, last = pivot.index[0], pivot.index[-1]
    swing = pivot.iloc[-1] - pivot.iloc[0]
    if invert:
        swing = -swing                 # climbing the table is a smaller rank
    up, down = swing.idxmax(), swing.idxmin()
    fmt = (lambda v: f"{v:+.0f}{unit}") if unit else (lambda v: f"{int(v):+d} places")
    return ("<h3>Through the Season</h3>"
            f"<p class='mu-note'>{what[0].upper() + what[1:]}, every build since "
            f"<strong>{first:%b %-d}</strong>: <strong>{up}</strong> {fmt(swing[up])}, "
            f"<strong>{down}</strong> {fmt(swing[down])}.</p>"
            f"<div class='lg-chart'>{chart}</div>")


def section() -> str:
    """The rankings, the table and the season chart - the dashboard's Power
    Rankings section. Every build archives a snapshot here, so the dashboard
    building it is what keeps the history growing."""
    charts.clear(_SECTION)
    lg = yahoo.league()
    rows = ranked_teams(lg)
    if not rows:
        return ("<p>Nothing to rank yet — the rankings appear on the "
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
            f"<td>{_record(t)}</td>"
            f"<td><b>{r['total']:.0f}</b></td>"
            f"<td>{r['total'] - avg:+.0f}</td>{pos_tds}"
            f"<td>{r['bench']:.0f}</td>"
            f"<td>{(r['playoff'] - 1) * 100:+.0f}%</td>"
            f'<td class="lg-team">{anchor}</td></tr>')

    move_heads = ("<th title='Since the previous build'>Move</th>" if prev is not None else "") \
        + ("<th title='Since a week ago'>7d</th>" if week is not None else "")

    rankmoves.snapshot(
        HISTORY_DIR, pd.Series({r["key"]: i for i, r in enumerate(rows, 1)}),
        extra=pd.DataFrame({"team": [r["team"]["name"] for r in rows],
                            "lineup": [round(r["total"], 1) for r in rows],
                            "vs_avg": [round(r["total"] - avg, 1) for r in rows]},
                           index=[r["key"] for r in rows]))
    season = _season_section({r["key"]: r["team"]["name"] for r in rows})

    return (
        "<p>Each roster's best startable lineup in projected season points under "
        "this league's scoring, with every player's preseason projection updated "
        f"by his real points per game (weighed against {PRIOR_GAMES:.0f} games of "
        "the projection). <b>Bench</b>: value over replacement behind the starters; "
        f"<b>Wks {lg['playoff_start_week']}–{lg['end_week']}</b>: playoff schedule "
        "tilt; <b>Move</b>/<b>7d</b>: places climbed since the last build / a week "
        "ago.</p>"
        '<div class="table-scroll"><table class="lg-table">'
        f"<thead><tr><th>Team</th>{move_heads}<th>Record</th><th>Lineup</th>"
        "<th>±Avg</th><th>QB</th><th>RB</th><th>WR</th><th>TE</th><th>DEF</th>"
        f"<th>Bench</th><th>Wks {lg['playoff_start_week']}–{lg['end_week']}</th>"
        "<th>Anchor</th></tr></thead>"
        f'<tbody>{"".join(cells)}</tbody></table></div>' + season)


def body() -> str:
    return _CSS + section()


def generate():
    """The section as a page of its own - not in build.PAGES; the dashboard
    hosts it now."""
    write_page(OUTPUT, f"CFB League Power Rankings {SEASON}", body())


if __name__ == "__main__":
    generate()
