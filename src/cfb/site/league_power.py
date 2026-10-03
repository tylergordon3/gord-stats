"""
League power rankings - the ten fantasy rosters, the Power tab of the college
fantasy league (docs/cfb/league/power/). A section of the league dashboard
from 2026-09-08; its own page again from 2026-09-29, when both leagues' tabs
became Home, Matchups, Team, Power, Usage and the power rankings - read every
week - stopped sharing a tab or a page with the archive. The old
/cfb/league-power/ URL redirects here.

Every roster priced the way the draft board priced the players: the best
starting lineup it can field, in projected season points under this league's
own scoring and slots, with each player's preseason projection updated by
his real scoring so far (cfb.in_season). Follows Yahoo's live rosters, so waivers and trades
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

Under the table, the Playoff Picture (gordstats.clinch, shared with the NFL
league's power page): who has clinched a place or a bye, who is out, and what
the rest need, from the standings and games left the simulation started from.
Then every team's playoff and title odds a week at a time (gordstats.odds_chart,
read back from the same snapshots), above the season chart.

    python -m cfb.site.league_power     # writes docs/cfb/league/power/
"""

import json
import shutil
from datetime import datetime, timedelta
from html import escape

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates                    # noqa: E402
import matplotlib.pyplot as plt                      # noqa: E402
import numpy as np                                   # noqa: E402
import pandas as pd                                  # noqa: E402

from cfb import espn, in_season, league_sim, projections, yahoo  # noqa: E402
from cfb.config import DATA_DIR, LEAGUE_TZ, MY_TEAM, SEASON, WEB_DIR  # noqa: E402
from cfb.site import write_page                      # noqa: E402
from gordstats import (charts, clinch, how, odds_chart, palette, rankmoves,  # noqa: E402
                       share_button, share_card, stakes)

HISTORY_DIR = DATA_DIR / "league_power_history" / str(SEASON)
OUTPUT = WEB_DIR / "league" / "power" / "index.html"
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
/* max-width:none - the site's img{max-width:100%} lets the table size the
   team column as though the logo could shrink to nothing. */
table.lg-table img.lg-logo{width:22px;height:22px;border-radius:50%;
  vertical-align:middle;margin:0 7px 0 0;border:none;padding:0;box-shadow:none;
  max-width:none}
/* Team leads the table, so pinning first-child holds the identity column
   while the rest scrolls on a phone. The cells already carry opaque themed
   backgrounds (zebra and dark) from the rules above. */
table.lg-table td:first-child,table.lg-table th:first-child{
  position:sticky;left:0;z-index:1}
table.lg-table th:first-child{text-align:left}
.lg-nm{display:inline-block;vertical-align:middle;overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap}
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
/* On a phone the longest Yahoo name ("Jackson's Brilliant Team (1 unrated)")
   made the pinned column 264px of a 390px screen, and the odds sat off it.
   The name gives way instead: rank, logo and ~85px of name, the ellipsis
   for the rest, and Record, Playoffs and Title beside it. */
@media (max-width:600px){
  table.lg-table th,table.lg-table td{padding:6px 7px}
  table.lg-table .lg-nm{max-width:86px}
  table.lg-table img.lg-logo{width:18px;height:18px;margin-right:5px}
  table.lg-table .row-rank{min-width:1.4em;font-size:12px}
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
        "starters": list(starters),
    }


def ranked_teams(lg: dict) -> list[dict]:
    """Every team's roster priced, best lineup first."""
    rosters = team_rosters()
    if not any(rosters.values()):
        return []
    # The in-season board: frozen at the draft, then blended with the season.
    board = in_season.board().drop_duplicates("yahoo_id").set_index("yahoo_id")
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
    # The per-week gap since the season simulation arrived (2026-09-28); the
    # season-total gap before it is on another scale, so the two never share
    # a line - with fewer than two builds of the new one, rank carries it.
    rated = (hist.dropna(subset=["wk_vs_avg"]) if "wk_vs_avg" in hist.columns
             else pd.DataFrame())
    if not rated.empty and rated["taken"].nunique() >= 2:
        pivot = rated.pivot_table(index="taken", columns="team", values="wk_vs_avg").sort_index()
        what, base, invert, unit = ("lineup points a week against the league average",
                                    0.0, False, " pts")
    elif hist["taken"].nunique() >= 2:
        pivot = hist.pivot_table(index="taken", columns="team", values="rank").sort_index()
        what, base, invert, unit = "rank", None, True, ""
    else:
        return ("<h3>Through the Season</h3>"
                "<p class='mu-note'>The trend chart appears with the second build.</p>")

    order = pivot.iloc[-1].sort_values(ascending=invert).index.tolist()
    span_days = max(1, (pivot.index[-1] - pivot.index[0]).days + 1)
    def draw(phone: bool = False):
        # Five panels a row on a desktop; two on a phone, drawn for its width
        # with bigger type (fantasy.site.power's chart, the same rule).
        cols = 2 if phone else 5
        fig_rows = int(np.ceil(len(order) / cols))
        size = (4.2, 1.6 * fig_rows + 0.2) if phone else (11, 2.5 * fig_rows)
        fig, axes = plt.subplots(fig_rows, cols, figsize=size, sharex=True, sharey=True)
        axes = np.atleast_1d(axes).ravel()
        longest = 19 if phone else 22
        for ax, team in zip(axes, order):
            for other in pivot.columns:
                ax.plot(pivot.index, pivot[other], color=palette.CONTEXT, linewidth=1.0,
                        zorder=1)
            ax.plot(pivot.index, pivot[team], color=palette.BLUE, linewidth=2.0,
                    marker="o", markersize=4, zorder=3)
            if base is not None:
                ax.axhline(base, color=palette.MUTED, linewidth=0.9, linestyle="--", zorder=2)
            # Yahoo team names run long; a panel is 2 inches wide.
            ax.set_title(team if len(team) <= longest else team[:longest - 1] + "\u2026",
                         fontsize=10.5 if phone else 9)
            ax.grid(color=palette.GRIDLINE)
            ax.set_axisbelow(True)
            for spine in ("top", "right"):
                ax.spines[spine].set_visible(False)
            ax.tick_params(labelsize=9 if phone else 8)
            # Whole days, a handful of them: the auto locator falls back to 12-hour
            # ticks on a young archive and prints the same date twice.
            ax.xaxis.set_major_locator(
                mdates.DayLocator(interval=max(1, span_days // (3 if phone else 4))))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %-d"))
            for label in ax.get_xticklabels():
                label.set_rotation(30)
                label.set_horizontalalignment("right")
        if invert:
            axes[0].invert_yaxis()
            axes[0].yaxis.set_major_locator(plt.MaxNLocator(integer=True))
        for ax in axes[len(order):]:
            ax.set_visible(False)
        # The section's own heading says it on a phone; there the line is room.
        if not phone:
            fig.suptitle(f"Published {what} through the season, one panel per team", y=1.0)
        fig.tight_layout()

    draw()
    chart = charts.save_picture(_SECTION, "season-trend", lambda: draw(phone=True),
                                alt=f"One small chart per team showing its {what} across "
                                    "every build, with the rest of the league in gray "
                                    "behind it")

    first, last = pivot.index[0], pivot.index[-1]
    swing = pivot.iloc[-1] - pivot.iloc[0]
    if invert:
        swing = -swing                 # climbing the table is a smaller rank
    up, down = swing.idxmax(), swing.idxmin()
    fmt = (lambda v: f"{v:+.0f}{unit}") if unit else (lambda v: f"{int(v):+d} places")
    # Name a riser and a faller only when someone moved: on a young archive
    # (or a quiet week) both came out as the same team at +0.
    moved = (f": <strong>{up}</strong> {fmt(swing[up])}, <strong>{down}</strong> "
             f"{fmt(swing[down])}") if up != down and round(swing[up] - swing[down], 1) else ""
    return ("<h3>Through the Season</h3>"
            f"<p class='mu-note'>{what[0].upper() + what[1:]}, every build since "
            f"<strong>{first:%b %-d}</strong>{moved}.</p>"
            f"<div class='lg-chart'>{chart}</div>")


def week_starts() -> list:
    """[(week, first kickoff, last day)] for every league week on record, in
    the snapshots' clock (Eastern, naive).

    The windows are Yahoo's (the week archive's week_start/week_end: week 1
    ran Thursday to Labor Day, week 2 Tuesday to Saturday, then Sunday to
    Saturday); the kickoff is the first FBS game inside one, from the season
    schedule already on disk. A build belongs to the latest week that had
    kicked off: the backfilled snapshots sit at 05:00 on a window's first
    day, before its football, and a Sunday-to-Wednesday build has none of
    the new week in it either. Without the schedule, noon on the window's
    first day stands in."""
    out = []
    try:
        games = espn.schedule(max_age_hours=float("inf"))
        kicks = (pd.to_datetime(games["date_utc"], utc=True).dt.tz_convert(LEAGUE_TZ)
                 .dt.tz_localize(None))
    except Exception as exc:                              # noqa: BLE001
        print(f"  ! odds chart: no schedule ({exc}); week windows alone")
        kicks = pd.Series(dtype="datetime64[ns]")
    for path in sorted(yahoo.MATCHUPS_DIR.glob("week_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            week = int(data.get("week") or path.stem.split("_")[1])
            start = datetime.strptime(data["week_start"], "%Y-%m-%d")
            end = datetime.strptime(data["week_end"], "%Y-%m-%d")
        except (OSError, ValueError, KeyError, TypeError):
            continue
        inside = kicks[(kicks >= start) & (kicks < end + timedelta(days=1))]
        first = inside.min().to_pydatetime() if len(inside) else start + timedelta(hours=12)
        out.append((week, first, end.date()))
    return out


def _odds_section(rows: list, has_odds: bool, now: datetime = None) -> str:
    """Every team's playoff and title odds, a point a week (gordstats.odds_chart):
    the last build before each week's first kickoff - the week before it,
    played out - and, while a week is on, its newest build, provisional.
    This build's odds stand in as the newest: the archive keeps one build in
    twelve hours, and the chart's end must agree with the table."""
    if not has_odds:
        return ""
    now = now or datetime.now(LEAGUE_TZ).replace(tzinfo=None)
    hist = rankmoves.history(HISTORY_DIR)
    cur = pd.DataFrame({"key": [r["key"] for r in rows if r["sim"] is not None],
                        "playoffs": [float(r["sim"]["playoffs"]) for r in rows
                                     if r["sim"] is not None],
                        "title": [float(r["sim"]["title"]) for r in rows
                                  if r["sim"] is not None]}).assign(taken=now)
    cols = ["taken", "key", "playoffs", "title"]
    both = pd.concat([f[cols] for f in (hist, cur) if not f.empty and set(cols) <= set(f.columns)],
                     ignore_index=True)
    starts = week_starts()
    kicks = [(w, k) for w, k, _ in starts]
    both["week"] = both["taken"].map(lambda t: odds_chart.week_of(t, kicks))
    data = odds_chart.by_week(both.rename(columns={"playoffs": "playoff"}))
    current = odds_chart.week_of(now, kicks)
    live = any(w == current and now.date() <= last for w, _, last in starts)
    names = {r["key"]: r["team"].get("name") or r["key"] for r in rows}
    mine = next((k for k, n in names.items() if n == MY_TEAM), "")
    return (f"<h3 id='odds'>Playoff and Title Odds {how.button('fantasy-stakes')}</h3>"
            + odds_chart.section(data, names, mine=mine, storage="cfbMyTeam",
                                 sid="oc-cfb", live=live)
            + odds_chart.JS_TAG)


def _pct(p) -> str:
    """A chance as the table prints it: never a flat 0% or 100% for something
    that is merely very unlikely or very likely."""
    if p is None or pd.isna(p):
        return "\u2014"
    if 0 < p < 0.005:
        return "<1%"
    if 0.995 < p < 1:
        return ">99%"
    return f"{p:.0%}"


_CARD: dict = {}

# This week's stakes, for the matchups page's game of the week (gordstats.stakes).
STAKES_OUT = WEB_DIR / "stakes.json"


def _stakes(sim: pd.DataFrame, names: dict) -> tuple:
    """(week, teams) for the week being played or next, or (None, {}) once
    that week is final."""
    if sim.empty or "playoff_if_win" not in sim:
        return None, {}
    frame = sim.reset_index()
    frame["name"] = frame["team_key"].map(names)
    teams = stakes.teams_from(frame, "team_key", "name")
    if not teams:
        return None, {}
    week = int(frame["stakes_week"].iloc[0])
    try:
        if week in yahoo.archived_weeks() and yahoo.week_final(yahoo.week_matchups(week)):
            return None, {}
    except Exception as exc:                                # noqa: BLE001
        print(f"  ! stakes: week {week} state unknown ({exc})")
    return week, teams


def card(week: int | None = None) -> dict | None:
    """The league dashboard's link-preview card (gordstats.share_card): the top
    five as section() last ranked them."""
    rows = _CARD.get("rows")
    if not rows:
        return None
    return share_card.ranked("cfb-power", "CFB Fantasy" + (f" \u00b7 Week {week}" if week else ""),
                             "Power Rankings", "Best lineup, the rest of the season played out",
                             rows, alt="CFB league power rankings: "
                             + ", ".join(f"{r[0]}. {r[1]}" for r in rows))


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

    # The rest of the season played out (cfb.league_sim): each roster's best
    # lineup every week left, on that week's projections, and the standings,
    # median game and bracket that follow. Ranked by lineup points a week -
    # strength - with what the schedule makes of it beside.
    sim = pd.DataFrame()
    try:
        sim = league_sim.run(lg, team_rosters()).set_index("team_key")
    except Exception as exc:                              # noqa: BLE001
        print(f"  ! season simulation skipped ({exc})")
    for r in rows:
        got = sim.loc[r["key"]] if r["key"] in sim.index else None
        r["per_week"] = float(got["per_week"]) if got is not None else None
        r["sim"] = got
    if not sim.empty:
        rows.sort(key=lambda r: r["per_week"] or 0.0, reverse=True)
    _CARD["stakes"] = _stakes(sim, {r["key"]: r["team"].get("name") or r["key"] for r in rows})
    stakes.write(STAKES_OUT, *_CARD["stakes"])
    avg = (np.mean([r["per_week"] for r in rows if r["per_week"] is not None])
           if not sim.empty else None)
    has_odds = not sim.empty and "title" in sim.columns
    _CARD["rows"] = [
        (str(i), r["team"].get("name") or r["key"],
         f"{r['sim']['playoffs']:.0%} playoffs" if has_odds and r["sim"] is not None
         else (f"{r['per_week'] - avg:+.1f} a week" if r["per_week"] is not None else ""))
        for i, r in enumerate(rows[:5], 1)]

    def pos_pts(r, p):
        if r["sim"] is None:
            return None
        return (r["sim"]["by_pos"] or {}).get(p, 0.0)
    best_pos = {p: max((pos_pts(r, p) or 0.0) for r in rows) for p in projections.POSITIONS}
    moves = rankmoves.movement(HISTORY_DIR)
    prev = moves.get("prev")
    week = (moves.get("prev7")
            if moves.get("prev7_at") != moves.get("prev_at") else None)

    cells = []
    for i, r in enumerate(rows, 1):
        t = r["team"]
        logo = (f'<img class="lg-logo" src="{t["logo"]}" alt="" loading="lazy">'
                if t.get("logo") else "")

        def pos_td(p):
            v = pos_pts(r, p)
            if v is None:
                return "<td>\u2014</td>"
            top = v and v == best_pos[p]
            return f"<td>{'<b>' if top else ''}{v:.0f}{'</b>' if top else ''}</td>"
        pos_tds = "".join(pos_td(p) for p in projections.POSITIONS)
        anchor = (escape(f"{r['anchor']['player']} ({r['anchor']['pos']})")
                  if r["anchor"] is not None else "—")
        move_tds = (f"<td>{_move(prev, r['key'], i)}</td>" if prev is not None else "") \
            + (f"<td>{_move(week, r['key'], i)}</td>" if week is not None else "")
        g = r["sim"]
        proj_rec = (f"{g['wins']:.1f}&ndash;{g['losses']:.1f}" if g is not None else "\u2014")
        odds = (f"<td>{_pct(g['playoffs'])}</td><td><b>{_pct(g['title'])}</b></td>"
                if has_odds and g is not None else ("<td>\u2014</td>" * 2 if has_odds else ""))
        bye = (f"<td>{_pct(g['bye'])}</td>" if has_odds and g is not None
               else ("<td>\u2014</td>" if has_odds else ""))
        per_week = (f"<td><b>{r['per_week']:.1f}</b></td>" if r["per_week"] is not None
                    else "<td>\u2014</td>")
        vs_avg = (f"<td>{r['per_week'] - avg:+.1f}</td>" if r["per_week"] is not None
                  else "<td></td>")
        cells.append(
            f'<tr><td class="lg-team" title="{escape(t["name"], quote=True)}">'
            f'<span class="row-rank">{i}</span>{logo}<span class="lg-nm">{escape(t["name"])}'
            + (f' <span class="mu-note">({r["unrated"]} unrated)</span>'
               if r["unrated"] else "") + "</span></td>"
            # What a phone sees first, beside the name: the record and what
            # the season is worth - playoffs, title - then the strength the
            # rows are ranked by, and the movement and the detail after.
            f"<td>{_record(t)}</td>{odds}{per_week}<td>{proj_rec}</td>{move_tds}"
            f"{bye}{vs_avg}{pos_tds}"
            f"<td>{r['bench']:.0f}</td>"
            f'<td class="lg-team">{anchor}</td></tr>')

    move_heads = ("<th title='Since the previous build'>Move</th>" if prev is not None else "") \
        + ("<th title='Since a week ago'>7d</th>" if week is not None else "")
    odds_heads = ("<th title='Chance of a playoff spot'>Playoffs</th>"
                  "<th title='Chance of winning the title'>Title</th>") if has_odds else ""
    bye_head = "<th title='Chance of a first-round bye'>Bye</th>" if has_odds else ""

    rankmoves.snapshot(
        HISTORY_DIR, pd.Series({r["key"]: i for i, r in enumerate(rows, 1)}),
        extra=pd.DataFrame({"team": [r["team"]["name"] for r in rows],
                            "per_week": [round(r["per_week"], 1) if r["per_week"] is not None
                                         else None for r in rows],
                            "wk_vs_avg": [round(r["per_week"] - avg, 1)
                                          if r["per_week"] is not None else None for r in rows],
                            "playoffs": [round(float(r["sim"]["playoffs"]), 4)
                                         if has_odds and r["sim"] is not None else None
                                         for r in rows],
                            "title": [round(float(r["sim"]["title"]), 4)
                                      if has_odds and r["sim"] is not None else None
                                      for r in rows]},
                           index=[r["key"] for r in rows]))
    season = _season_section({r["key"]: r["team"]["name"] for r in rows})
    playoffs = _playoffs_section(sim, lg, {r["key"]: r["team"].get("name") or r["key"]
                                           for r in rows})
    _leave_picture()
    odds = _odds_section(rows, has_odds)

    # How the season is played out is the cfb-league explainer (gordstats.how),
    # opened from the chip under the lead; the columns say what they are in
    # their headers' tooltips.
    return (
        f"<p>The rest of the season played out {league_sim.SIMS:,} times, ranked by "
        "<b>Pts/wk</b>: each roster's best lineup, projected a week from here on.</p>"
        + how.section_note("cfb-league")
        + '<div class="table-scroll"><table class="lg-table">'
        f"<thead><tr><th>Team</th><th>Record</th>{odds_heads}"
        "<th title='Projected lineup points a week, rest of the regular season'>Pts/wk</th>"
        "<th title='Projected final record'>Proj.</th>"
        f"{move_heads}{bye_head}"
        "<th title='Pts/wk against the league average'>±Avg</th>"
        "<th>QB</th><th>RB</th><th>WR</th><th>TE</th><th>DEF</th>"
        "<th title='Value over a replacement-level player behind the starters'>Bench</th>"
        "<th title='The starter worth the most over a replacement-level player'>Anchor</th>"
        "</tr></thead>"
        f'<tbody>{"".join(cells)}</tbody></table></div>' + playoffs + odds + season)


def _playoffs_section(sim: pd.DataFrame, lg: dict, names: dict) -> str:
    """Who has clinched, who is out, and what the rest need (gordstats.clinch),
    between the rankings and the season chart. The standings and games left
    are the ones the simulation started from (league_sim's now_* and
    games_left, the median game counted), so a team called clinched is in
    every run; the week's head-to-head is offered only while _stakes still
    has it, i.e. before the week is final."""
    _CARD.pop("picture", None)
    field = int(lg.get("num_playoff_teams") or 0)
    if sim.empty or not field or "games_left" not in sim.columns:
        return ""
    week, split = _CARD.get("stakes") or (None, {})
    teams = {}
    for key, g in sim.iterrows():
        s = split.get(key) or {}
        teams[key] = {"name": names.get(key, key), "wins": float(g["now_wins"]),
                      "losses": float(g["now_losses"]), "left": float(g["games_left"]),
                      "pf": float(g["now_pf"]),
                      "odds": float(g["playoffs"]) if "playoffs" in g else None,
                      "opp": s.get("opp"), "win": s.get("win")}
    median = bool(lg.get("uses_median_score"))
    for problem in clinch.check(teams, clinch.picture(teams, field, clinch.byes(field), median)):
        print(f"  ! playoff picture: {problem}")
    _CARD["picture"] = dict(week=week, teams=teams, spots=field, bye_spots=clinch.byes(field),
                            median=median)
    return (f"<h3 id='playoffs'>Playoff Picture {how.button('fantasy-stakes')}</h3>"
            + clinch.section(teams, field, clinch.byes(field), median=median, week=week))


# The playoff picture, for the matchups page's callout (gordstats.clinch).
PICTURE_OUT = WEB_DIR / clinch.FILE


def _leave_picture() -> None:
    """What _playoffs_section drew, left for the matchups page; cleared when
    it drew nothing or the week is over (clinch.write)."""
    clinch.write(PICTURE_OUT, **(_CARD.pop("picture", None) or {}))


def body() -> str:
    # The schedule ahead is the other half of "who is actually good": the
    # matchup strength page, under this tab too.
    html = section()
    week, teams = _CARD.get("stakes") or (None, {})
    if week:
        html += (f"<h2 id='stakes'>This Week's Stakes {how.button('fantasy-stakes')}</h2>"
                 + stakes.table(week, teams))
    top = ", ".join(f"{r[0]}. {r[1]}" for r in (_CARD.get("rows") or [])[:3])
    share = share_button.row("/cfb/league/power/",
                             f"CFB league power rankings: {top}" if top else "")
    return (_CSS + share + "<p class='mu-note'>The schedule ahead - whose helps from here, and "
            "which defenses give up points to each position - is on "
            "<a href='/cfb/strength/'>Matchup Strength</a>.</p>" + html + how.JS_TAG)


def generate():
    html = body()
    week = yahoo.league().get("current_week")
    write_page(OUTPUT, f"CFB League Power Rankings {SEASON}", html,
               description="The college fantasy league's rosters ranked, the rest of the "
                           "season played out.",
               image=card(int(week) if week else None))
    # The pages this replaced, generated on the Pi and never committed: gone,
    # so docs/_redirects is what answers their addresses.
    for old in (WEB_DIR / "analytics", WEB_DIR / "league-power"):
        if old.exists():
            shutil.rmtree(old)
            print(f"Removed {old}; _redirects answers it")


if __name__ == "__main__":
    generate()
