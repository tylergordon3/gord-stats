"""
The college football section landing page (docs/cfb/index.html).

A countdown, one line of what the section is, then the numbers - the
reader's starred teams, the day's best games (the watch guide), the week's
bets and the Top 25 - and one card of links. The Yahoo fantasy league's pages
belong to the Fantasy section of the nav, so they share a line at the end. League facts (name, draft time, roster shape) come
from the cached Yahoo pull rather than being retyped here.

    python -m cfb.site.home         # rebuild the page
"""
from datetime import date
from html import escape

from cfb import yahoo
from cfb.config import SEASON, WEB_DIR
from cfb.site import write_page
from cfb.site.draft import _draft_when, _roster_line
from gordstats import my_teams_today
from gordstats.frontmatter import liquid


def _watch() -> str:
    """The day's best games from the watch guide, or nothing between seasons."""
    try:
        from cfb.site import watch
        return watch.teaser(watch.games())
    except Exception as exc:                     # the page stands without it
        print(f"cfb home: no watch teaser ({exc})")
        return ""


def body() -> str:
    """The numbers first - the reader's teams, the day's best games, the
    week's bets and the Top 25 - then one card of links. It was a countdown
    and four cards describing the pages in the nav above them: mid-season the
    site's front page showed more college football than this one did."""
    lg = yahoo.league()
    when = _draft_when(lg)
    draft_line = (f" The draft is <strong>{when}</strong>."
                  if when and lg.get("draft_status") == "predraft" else "")
    watch_card = _watch()
    # The bets and Top 25 includes exist all year but say nothing useful out
    # of season (the site home leaves them off the same way).
    today = date.today()
    in_season = today >= date(today.year, 8, 20) or today <= date(today.year, 1, 31)
    watch_html = (f"""
<section class="home-card">
  <div class="home-card-head">
    <h2>What to watch</h2>
    <a class="home-card-link" href="/cfb/watch/">Watch guide &rarr;</a>
  </div>
  {watch_card}
</section>""" if watch_card else "")
    return f"""
{liquid('{% include cfb_countdown.html %}')}

<p>The {SEASON} FBS season on this site's own game model, ESPN's FPI and the AP poll.{draft_line}</p>

{my_teams_today.section(cfb=True, cbb=False)}
{watch_html}

<section class="home-card"{"" if in_season else " hidden"}>
  <div class="home-card-head">
    <h2>This week's bets</h2>
    <a class="home-card-link" href="/cfb/predictions/">Every game &rarr;</a>
  </div>
  {liquid('{% include cfb_bets.html %}')}
</section>

<section class="home-card"{"" if in_season else " hidden"}>
  <div class="home-card-head">
    <h2>Top 25 Comparison</h2>
    <a class="home-card-link" href="/cfb/power/">All FBS teams &rarr;</a>
  </div>
  {liquid('{% include cfb_top25.html %}')}
</section>

<section class="home-card">
  <div class="home-card-head">
    <h2>Everything else</h2>
  </div>
  <p class="home-card-links">
    <a href="/cfb/predictions/">Predictions</a> ·
    <a href="/cfb/power/">Rankings</a> ·
    <a href="/cfb/watch/">Watch Guide</a> ·
    <a href="/cfb/schedule/">Schedule &amp; Scores</a> ·
    <a href="/cfb/strength/">Strength of Schedule</a>
  </p>
  <p class="home-card-links">
    <a href="{escape(lg['url'], quote=True)}">{escape(lg['name'])}</a> ({lg['num_teams']} teams,
    {_roster_line(lg)}):
    <a href="/cfb/league/">League Home</a> ·
    <a href="/cfb/matchups/">Matchups</a> ·
    <a href="/cfb/roster/">Team</a> ·
    <a href="/cfb/usage/">Usage</a>
  </p>
</section>
"""


def generate():
    write_page(WEB_DIR / "index.html", "CFB", body())


if __name__ == "__main__":
    generate()
