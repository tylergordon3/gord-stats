"""
The real college football schedule (docs/cfb/schedule/).

Every FBS game of the season (cfb.espn.schedule), one tab per week. Inside a
tab, games still to play come first (grouped by day) and finished ones sink
into a Final section below, so mid-week the top of the page is what's next,
not what already happened. Each game is a stacked scorebox - away over home,
ESPN logos, AP ranks, names linked to their team page, the winner in bold -
with kickoff (ET), TV and venue alongside. A "Ranked only" toggle cuts the
slate down to games with a top-25 team in them, hiding any day that empties
out.

The tab that opens first is the current week, computed at build time - the
page is rebuilt daily, so "current" stays current.

    python -m cfb.site.schedule     # rebuild the page
"""
from datetime import datetime, timezone
from functools import lru_cache
from html import escape

import pandas as pd

from cfb import espn
from cfb.config import LEAGUE_TZ, SEASON, WEB_DIR
from cfb.site import write_page
from cfb.site.teams import LOGO, team_slug

_CSS = """<style>
table.cfb-sched{width:100%;border-collapse:collapse;font-size:14px}
table.cfb-sched th{background:#eef2f7;color:#334155;padding:7px 10px;text-align:left;
  font-size:12px;text-transform:uppercase;letter-spacing:.03em;white-space:nowrap;
  border:1px solid #e2e8f0}
table.cfb-sched td{padding:6px 10px;border:1px solid #eef2f7;color:#0f172a;background:#fff}
table.cfb-sched tbody tr:nth-child(even) td{background:#f8fafc}
table.cfb-sched td.t{white-space:nowrap;color:#4a5a68}
table.cfb-sched .rk{font-weight:700;color:#8a6d00;font-size:11.5px}
table.cfb-sched td.tv{white-space:nowrap}
table.cfb-sched td.venue{color:#4a5a68;font-size:13px}
/* The stacked scorebox in the matchup cell: away over home, logos, ranks,
   the winner's line in bold. Same bones as the predictions page's .pg-row. */
.sc-mu{display:flex;flex-direction:column;gap:3px;min-width:200px}
.sc-row{display:flex;align-items:center;gap:8px}
/* The Slate remote theme frames every <img>; reset or each logo becomes a
   boxed figure and the row grows (same reset the power/predictions pages carry). */
table.cfb-sched .sc-row img{width:20px;height:20px;object-fit:contain;flex:none;
  border:none;padding:0;box-shadow:none;background:none;border-radius:0;margin:0}
.sc-name{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  color:#334155;font-size:14px}
.sc-name a{color:inherit;text-decoration:none}
.sc-name a:hover{text-decoration:underline}
.sc-joiner{color:#94a3b8;font-size:12px}
.sc-pts{min-width:24px;text-align:right;font-variant-numeric:tabular-nums;
  font-size:15px;font-weight:600;color:#94a3b8}
.sc-row.sc-win .sc-name{font-weight:700;color:#0f172a}
.sc-row.sc-win .sc-pts{color:#0f172a;font-weight:700}
.t-live{color:#0a7d33;font-weight:700}
.cfb-sec{margin:26px 0 0;font-size:12.5px;text-transform:uppercase;
  letter-spacing:.06em;color:#64748b}
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
  .sc-name{color:#c3cfdd}
  .sc-joiner,.sc-pts{color:#7f8ea3}
  .sc-row.sc-win .sc-name,.sc-row.sc-win .sc-pts{color:#ffffff}
  .t-live{color:#4ade80}
  .cfb-sec{color:#aab7c9}
  .wk-note{color:#aab7c9}
}
</style>"""


@lru_cache(maxsize=1)
def _team_pages() -> frozenset:
    """Slugs with a built team page - the only names worth linking.

    cfb.build runs teams before schedule, so on a full build every FBS page is
    on disk by now; FCS visitors have no page and stay plain text.
    """
    d = WEB_DIR / "teams"
    return frozenset(p.name for p in d.iterdir() if p.is_dir()) if d.exists() else frozenset()


def _abandoned(g) -> bool:
    """Cancelled/postponed games arrive as state=post with hollow 0-0 scores."""
    return any(w in (g.detail or "") for w in ("Cancel", "Postpon"))


def _side_row(g, side: str) -> str:
    """One team's line in the scorebox: logo, rank, linked name, score."""
    name = str(getattr(g, side))
    rank = getattr(g, f"{side}_rank")
    badge = "" if pd.isna(rank) else f'<span class="rk">#{int(rank)}</span> '
    joiner = ("" if side == "away"
              else f'<span class="sc-joiner">{"vs" if g.neutral else "at"}</span> ')
    slug = team_slug(name)
    a, a_close = ((f'<a href="/cfb/teams/{slug}/">', "</a>")
                  if slug in _team_pages() else ("", ""))
    logo = LOGO.format(team_id=escape(str(getattr(g, f"{side}_id"))))

    score = getattr(g, f"{side}_score")
    other = getattr(g, "home_score" if side == "away" else "away_score")
    scored = g.state in ("in", "post") and not pd.isna(score) and not _abandoned(g)
    won = g.state == "post" and scored and score > other
    pts = f'<span class="sc-pts">{score:.0f}</span>' if scored else ""
    return (f'<div class="sc-row{" sc-win" if won else ""}">'
            f'{a}<img src="{logo}" alt="" loading="lazy">{a_close}'
            f'<span class="sc-name">{joiner}{badge}{a}{escape(name)}{a_close}</span>'
            f"{pts}</div>")


def _scorebox(g) -> str:
    return f'<div class="sc-mu">{_side_row(g, "away")}{_side_row(g, "home")}</div>'


def _time(g, local) -> str:
    if _abandoned(g):
        return g.detail
    if g.state == "post":
        return g.detail if "Final" in (g.detail or "") else "Final"
    if g.state == "in":
        return f'<span class="t-live">{g.detail or "Live"}</span>'
    return local.strftime("%-I:%M %p")


def _day_table(games: pd.DataFrame) -> str:
    rows = []
    for g in games.itertuples():
        ranked = not (pd.isna(g.home_rank) and pd.isna(g.away_rank))
        venue = g.venue + (f" — {g.place}" if g.place else "")
        rows.append(
            f'<tr class="{"ranked" if ranked else "unranked"}">'
            f'<td class="t">{_time(g, g.local)}</td>'
            f"<td>{_scorebox(g)}</td>"
            f'<td class="tv">{g.tv or "—"}</td>'
            f'<td class="venue">{venue}</td></tr>')
    return ('<table class="cfb-sched"><thead><tr><th>ET</th><th>Matchup</th>'
            '<th>TV</th><th class="venue">Venue</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>')


def _days(games: pd.DataFrame) -> list[str]:
    out = []
    for day, grp in games.groupby(games["local"].dt.date, sort=True):
        all_unranked = bool((grp["home_rank"].isna() & grp["away_rank"].isna()).all())
        cls = "cfb-empty-day" if all_unranked else ""
        stamp = pd.Timestamp(day).strftime("%A, %B %-d")
        out.append(f'<div class="{cls}"><h3 class="cfb-day">{stamp}</h3>'
                   f'<div class="table-scroll">{_day_table(grp)}</div></div>')
    return out


def _week_view(games: pd.DataFrame) -> str:
    ranked = int((games["home_rank"].notna() | games["away_rank"].notna()).sum())
    out = [f'<p class="wk-note">{len(games)} games, {ranked} with a ranked team.</p>']
    # What's next on top: finished games sink into a Final section below the
    # still-to-play days (live games count as still-on). Headers only when the
    # week is actually split - a week untouched or fully played reads straight
    # through.
    done = games["state"] == "post"
    if done.any() and not done.all():
        out += ['<h2 class="cfb-sec">Still to play</h2>'] + _days(games[~done])
        out += ['<h2 class="cfb-sec">Final</h2>'] + _days(games[done])
    else:
        out += _days(games)
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
