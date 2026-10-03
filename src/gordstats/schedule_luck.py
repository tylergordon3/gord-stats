"""
Schedule difficulty: what the schedule has done to each team's record, in
wins, split into how good its opponents are and when they happened to play
well.

Every head-to-head game is scored three ways:

    all-play     the share of the league the team outscored that week - its
                 chance of winning against an opponent drawn at random
    vs normal    its chance of beating *this* opponent on one of the
                 opponent's other weeks: the share of the opponent's scores
                 in its other weeks the team's points beat, all-play again
                 but against that one team - with one more "week" at the
                 all-play share, so a week-2 figure is not a coin with one
                 face. (A normal curve about each opponent's average was
                 tried first; with the league's small week-to-week spread
                 and averages shrunk toward the league's, one team far above
                 the rest made every other team's opponents look stronger
                 than they were.)
    actual       won, lost or tied

Summed over the season:

    Opp. strength = vs normal - all-play   the opponents' quality: negative
                                           when the teams faced are better
                                           than the league
    Opp. timing   = actual - vs normal     the luck: negative when opponents
                                           scored above their normal against
                                           this team, positive when below
    Schedule      = actual - all-play      the two together: wins the
                                           schedule cost (-) or gave (+)

Schedule is the "Luck" the NFL power table already shows (record minus the
all-play expectation, head-to-head part); this says why. Points against,
opponents' normal and how far they beat it (per game) sit beside it. The
median game is left out throughout: no schedule changes it.

    frame = schedule_luck.table(rows)   # rows: week, team, opp, pts, opp_pts
    html  = schedule_luck.html(frame, names)
"""
from html import escape

import pandas as pd

CSS = """<style>
table.sl{width:100%;border-collapse:collapse;font-size:14px}
table.sl th{font-size:11.5px;text-transform:uppercase;letter-spacing:.03em;color:#334155;
  background:#eef2f7;padding:6px 8px;border-bottom:1px solid #e2e8f0;text-align:center;
  white-space:nowrap}
table.sl td{padding:6px 8px;border-bottom:1px solid #eef2f7;text-align:center;white-space:nowrap}
table.sl td.t{text-align:left;font-weight:700}
table.sl td.big{font-weight:800}
table.sl .neg{color:#b91c1c}
table.sl .pos{color:#15803d}
.sl-note{font-size:13px;color:#475569;line-height:1.55;margin:6px 0 10px}
/* A phone sees the name and the three win figures without scrolling: the
   bold team column was 157px of a 390px screen. */
@media (max-width:600px){
  table.sl td.t{max-width:120px;overflow:hidden;text-overflow:ellipsis}
  table.sl th{font-size:12px}
  table.sl th,table.sl td{padding:6px 6px}
}
@media (prefers-color-scheme: dark){
  table.sl th{color:#dde5ef;background:#223052;border-color:#2b3852}
  table.sl td{border-color:#2b3852}
  table.sl .neg{color:#f87171}
  table.sl .pos{color:#4ade80}
  .sl-note{color:#aab7c9}
}
</style>"""


def table(rows) -> pd.DataFrame:
    """One row per team: games, wins, PF/PA per game, the opponents' normal
    and how far above it they scored, and the three win figures. `rows` is
    one row per team per head-to-head game (both sides of each game), with
    week, team, opp, pts, opp_pts."""
    g = pd.DataFrame(rows, columns=["week", "team", "opp", "pts", "opp_pts"])
    if g.empty:
        return pd.DataFrame()
    g = g.astype({"pts": float, "opp_pts": float})
    scores = g[["week", "team", "pts"]].drop_duplicates(["week", "team"])
    league_mean = scores["pts"].mean()

    by_team = {t: s.set_index("week")["pts"] for t, s in scores.groupby("team")}
    by_week = {w: s["pts"].tolist() for w, s in scores.groupby("week")}

    def normal(team, week):
        other = by_team[team].drop(index=week, errors="ignore")
        return (other.sum() + league_mean) / (len(other) + 1)

    out = []
    for team, games in g.groupby("team"):
        allplay = quality = wins = pa_norm = 0.0
        for r in games.itertuples(index=False):
            week_scores = [p for p in by_week[r.week]]
            others = len(week_scores) - 1
            beaten = sum(p < r.pts for p in week_scores) + 0.5 * (sum(p == r.pts for p in week_scores) - 1)
            share = beaten / others if others else 0.5
            allplay += share
            pa_norm += normal(r.opp, r.week)
            theirs = by_team[r.opp].drop(index=r.week, errors="ignore")
            quality += ((share + (theirs < r.pts).sum() + 0.5 * (theirs == r.pts).sum())
                        / (len(theirs) + 1))
            wins += 1.0 if r.pts > r.opp_pts else 0.5 if r.pts == r.opp_pts else 0.0
        n = len(games)
        out.append({
            "team": team, "games": n, "wins": wins,
            "pf_g": games["pts"].mean(), "pa_g": games["opp_pts"].mean(),
            "opp_normal": pa_norm / n, "opp_over": games["opp_pts"].mean() - pa_norm / n,
            "allplay_w": allplay, "normal_w": quality,
            "strength": quality - allplay, "timing": wins - quality, "schedule": wins - allplay,
        })
    frame = pd.DataFrame(out)
    # Strength is measured against the league: the normal-week estimate runs a
    # little under all-play across a whole league (2025-26: -0.59 wins over
    # ten teams), so it is centred, and what it moves goes to timing - each
    # team's Schedule total is untouched, and all three sum to zero.
    shift = frame["strength"].mean()
    frame["strength"] -= shift
    frame["timing"] += shift
    return frame.sort_values("schedule").reset_index(drop=True)


def _w(v: float) -> str:
    """Wins, signed, a dash for nothing to speak of."""
    if abs(v) < 0.05:
        return "0.0"
    cls = "neg" if v < 0 else "pos"
    return f"<span class='{cls}'>{v:+.1f}</span>"


def html(frame: pd.DataFrame, names: dict, season_label: str = "") -> str:
    """The table and what it says, hardest schedule first."""
    if frame.empty:
        return "<p class='sl-note'>Nothing to measure until the first week is final.</p>"
    rows = "".join(
        f"<tr><td class='t'>{escape(str(names.get(r.team, r.team)))}</td>"
        f"<td class='big'>{_w(r.schedule)}</td><td>{_w(r.strength)}</td><td>{_w(r.timing)}</td>"
        f"<td>{r.wins:g}-{r.games - r.wins:g}</td><td>{r.allplay_w:.1f}</td>"
        f"<td>{r.pa_g:.1f}</td><td>{r.opp_normal:.1f}</td><td>{r.opp_over:+.1f}</td></tr>"
        for r in frame.itertuples(index=False))
    worst = frame.iloc[0]
    games = int(frame["games"].max())
    lead = ""
    if worst["schedule"] <= -0.3:
        why = (f"opponents scored {worst['opp_over']:.1f} a game above their normal against it"
               if worst["timing"] <= worst["strength"]
               else "the strongest opponents of anyone")
        lead = (f"<p class='sl-note'><b>Hardest: {escape(str(names.get(worst.team, worst.team)))}"
                f"</b>, {-worst['schedule']:.1f} wins lost - {why}.</p>")
    # How it is worked out is the schedule-strength explainer (gordstats.how),
    # opened from a chip the page puts by this section's heading; each column
    # says what it is in its header's tooltip.
    legend = (f"<p class='sl-note'>{season_label + '. ' if season_label else ''}"
              f"Wins the schedule has cost (&minus;) or given (+) over {games} "
              f"game{'s' if games != 1 else ''}, split into the opponents' strength and "
              "their timing.</p>")
    head = "".join((f"<th title='{escape(tip, quote=True)}'>" if tip else "<th>") + f"{label}</th>"
                   for label, tip in (
        ("Team", ""),
        ("Schedule", "Wins the schedule has cost or given: record minus all-play wins"),
        ("Opp. strength", "Wins from how good the opponents normally are"),
        ("Opp. timing", "Wins from opponents scoring above or below their normal against this team"),
        ("Record", "Head-to-head wins and losses"),
        ("All-play W", "Wins these scores would have earned against the whole league"),
        ("PA", "Points against, a game"),
        ("Opp. normal", "What those opponents score in their other weeks, a game"),
        ("Over", "Points against minus the opponents' normal, a game")))
    return (CSS + lead + legend + "<div class='table-scroll'><table class='sl'><thead><tr>"
            f"{head}</tr></thead><tbody>{rows}</tbody></table></div>")


def finding(frame: pd.DataFrame, names: dict, when: str = "") -> str:
    """One line for a records card: whom the schedule has cost most, and
    which half did it."""
    if frame.empty:
        return ""
    worst = frame.iloc[0]
    if worst["schedule"] > -0.3:
        return ""
    name = names.get(worst.team, worst.team)
    part = ("opponents' big weeks" if worst["timing"] <= worst["strength"]
            else "strong opponents")
    return (f"Toughest schedule{when}: {name}, {-worst['schedule']:.1f} wins lost, "
            f"mostly to {part}")
