"""
The real college football schedule (docs/cfb/schedule/).

Every FBS game of the season (cfb.espn.schedule), one tab per week, grouped by
day inside the tab. Rows carry kickoff (ET), the matchup with AP ranks, TV and
venue; once a game has been played the matchup cell shows the score instead of
a kickoff time. A "Ranked only" toggle cuts the slate down to games with a
top-25 team in them, hiding any day that empties out.

The tab that opens first is the current week, computed at build time - the
page is rebuilt daily, so "current" stays current.

    python -m cfb.site.schedule     # rebuild the page
"""
from datetime import datetime, timezone

import pandas as pd

from cfb import espn
from cfb.config import LEAGUE_TZ, SEASON, WEB_DIR
from cfb.site import write_page

_CSS = """<style>
table.cfb-sched{width:100%;border-collapse:collapse;font-size:14px}
table.cfb-sched th{background:#eef2f7;color:#334155;padding:7px 10px;text-align:left;
  font-size:12px;text-transform:uppercase;letter-spacing:.03em;white-space:nowrap;
  border:1px solid #e2e8f0}
table.cfb-sched td{padding:6px 10px;border:1px solid #eef2f7;color:#0f172a;background:#fff}
table.cfb-sched tbody tr:nth-child(even) td{background:#f8fafc}
table.cfb-sched td.t{white-space:nowrap;color:#4a5a68}
table.cfb-sched .rk{font-weight:700;color:#8a6d00;font-size:12px}
table.cfb-sched .win{font-weight:700}
table.cfb-sched td.tv{white-space:nowrap}
table.cfb-sched td.venue{color:#4a5a68;font-size:13px}
.cfb-day{margin:16px 0 6px;font-size:15px}
.wk-note{font-size:13px;color:#4a5a68;margin:4px 0 10px}
.ranked-only .cfb-sched tr.unranked{display:none}
.ranked-only .cfb-empty-day{display:none}
@media (max-width:600px){
  table.cfb-sched td.venue{display:none}
  table.cfb-sched th.venue{display:none}
}
@media (prefers-color-scheme: dark){
  table.cfb-sched th{background:#223052;color:#dde5ef;border-color:#2b3852}
  table.cfb-sched td{background:#16203a;border-color:#2b3852;color:#dde5ef}
  table.cfb-sched tbody tr:nth-child(even) td{background:#1b2540}
  table.cfb-sched td.t,table.cfb-sched td.venue{color:#aab7c9}
  table.cfb-sched .rk{color:#f2cc60}
  .wk-note{color:#aab7c9}
}
</style>"""


def _team(name, rank) -> str:
    tag = "" if pd.isna(rank) else f'<span class="rk">#{int(rank)}</span> '
    return f"{tag}{name}"


def _matchup(g) -> str:
    joiner = "vs" if g.neutral else "at"
    if g.state == "post" and not pd.isna(g.home_score):
        aw = "win" if g.away_score > g.home_score else ""
        hw = "win" if g.home_score > g.away_score else ""
        return (f'<span class="{aw}">{_team(g.away, g.away_rank)} '
                f"{g.away_score:.0f}</span> {joiner} "
                f'<span class="{hw}">{_team(g.home, g.home_rank)} '
                f"{g.home_score:.0f}</span>")
    return f"{_team(g.away, g.away_rank)} {joiner} {_team(g.home, g.home_rank)}"


def _time(g, local) -> str:
    if g.state == "post":
        return g.detail if "Final" in (g.detail or "") else "Final"
    if g.state == "in":
        return g.detail or "Live"
    return local.strftime("%-I:%M %p")


def _day_table(games: pd.DataFrame) -> str:
    rows = []
    for g in games.itertuples():
        ranked = not (pd.isna(g.home_rank) and pd.isna(g.away_rank))
        venue = g.venue + (f" — {g.place}" if g.place else "")
        rows.append(
            f'<tr class="{"ranked" if ranked else "unranked"}">'
            f'<td class="t">{_time(g, g.local)}</td>'
            f"<td>{_matchup(g)}</td>"
            f'<td class="tv">{g.tv or "—"}</td>'
            f'<td class="venue">{venue}</td></tr>')
    return ('<table class="cfb-sched"><thead><tr><th>ET</th><th>Matchup</th>'
            '<th>TV</th><th class="venue">Venue</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>')


def _week_view(games: pd.DataFrame) -> str:
    ranked = int((games["home_rank"].notna() | games["away_rank"].notna()).sum())
    out = [f'<p class="wk-note">{len(games)} games, {ranked} with a ranked team.</p>']
    for day, grp in games.groupby(games["local"].dt.date, sort=True):
        all_unranked = bool((grp["home_rank"].isna() & grp["away_rank"].isna()).all())
        cls = "cfb-empty-day" if all_unranked else ""
        stamp = pd.Timestamp(day).strftime("%A, %B %-d")
        out.append(f'<div class="{cls}"><h3 class="cfb-day">{stamp}</h3>'
                   f'<div class="table-scroll">{_day_table(grp)}</div></div>')
    return "".join(out)


def _current_week(df: pd.DataFrame) -> int:
    """The first week with games still to play, else the last week."""
    now = datetime.now(timezone.utc).isoformat()
    pending = df[df["date_utc"] >= now]
    return int(pending["week"].min()) if len(pending) else int(df["week"].max())


def _switcher(week_ids: list[int], current: int, views: dict[int, str]) -> str:
    buttons = "".join(
        f'<button class="wk-btn{" active" if w == current else ""}" '
        f"onclick=\"show_wk('{w}')\" id=\"wk-tab-{w}\">{w}</button>"
        for w in week_ids)
    divs = "".join(
        f'<div id="wk-view-{w}" class="wk-view"'
        f'{"" if w == current else " style=\'display:none\'"}>{views[w]}</div>'
        for w in week_ids)
    js = """<script>
function show_wk(w){
  document.querySelectorAll('.wk-view').forEach(function(e){e.style.display='none';});
  document.getElementById('wk-view-'+w).style.display='';
  document.querySelectorAll('.wk-btn').forEach(function(b){b.classList.remove('active');});
  document.getElementById('wk-tab-'+w).classList.add('active');
}
var rankedBtn=document.getElementById('cfb-ranked');
rankedBtn.addEventListener('click',function(){
  var on=document.getElementById('cfb-weeks').classList.toggle('ranked-only');
  rankedBtn.classList.toggle('active',on);
});
</script>"""
    return (f'<div class="view-switch"><span class="switch-label">Week:</span>{buttons}</div>'
            '<div class="adp-controls">'
            '<button id="cfb-ranked" class="adp-toggle">Ranked matchups only</button>'
            "</div>"
            f'<div id="cfb-weeks">{divs}</div>' + js)


def body() -> str:
    df = espn.schedule().copy()
    df["local"] = (pd.to_datetime(df["date_utc"], utc=True)
                   .dt.tz_convert(str(LEAGUE_TZ)))
    week_ids = sorted(df["week"].unique().tolist())
    views = {int(w): _week_view(grp.sort_values("local"))
             for w, grp in df.groupby("week")}
    current = _current_week(df)

    built = datetime.now(LEAGUE_TZ).strftime("%b %-d, %-I:%M %p %Z")
    return (
        _CSS
        + f"<p>Every FBS game of the {SEASON} season, from ESPN — kickoffs in "
        "Eastern time, TV where it has been announced, scores once games go "
        f"final. Ranks are the AP top 25. Rebuilt daily (last: {built}).</p>"
        + _switcher([int(w) for w in week_ids], current, views)
    )


def generate():
    write_page(WEB_DIR / "schedule" / "index.html", f"CFB Schedule {SEASON}", body())


if __name__ == "__main__":
    generate()
