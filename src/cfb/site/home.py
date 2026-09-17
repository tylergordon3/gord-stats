"""
The college football section landing page (docs/cfb/index.html).

Mirrors the CBB section home: a countdown, one paragraph of what the section
is, then a card per page. The Yahoo fantasy league's pages belong to the
Fantasy section of the nav now, so they share one card at the end. League facts (name, draft time, roster shape) come
from the cached Yahoo pull rather than being retyped here.

    python -m cfb.site.home         # rebuild the page
"""
from cfb import yahoo
from cfb.config import SEASON, WEB_DIR
from cfb.site import write_page
from cfb.site.draft import _draft_when, _roster_line


def body() -> str:
    lg = yahoo.league()
    when = _draft_when(lg)
    draft_line = (f" The draft is <strong>{when}</strong>."
                  if when and lg.get("draft_status") == "predraft" else "")
    return f"""
{{% include cfb_countdown.html %}}

<p>The {SEASON} FBS season: this site's own game model, ESPN's FPI and the AP
   poll, and every game on the schedule. The
   <a href="{lg['url']}">{lg['name']}</a> Yahoo fantasy league
   ({lg['num_teams']} teams, {_roster_line(lg)}) is under
   <a href="/cfb/matchups/">Fantasy &rsaquo; CFB</a>.{draft_line}</p>

<section class="home-card">
  <div class="home-card-head">
    <h2>Predictions</h2>
    <a class="home-card-link" href="/cfb/predictions/">This week's picks &rarr;</a>
  </div>
  <p>A score, a margin and a win chance for every FBS game from this site's
     own model, set against the DraftKings line, and how the model has done.</p>
</section>

<section class="home-card">
  <div class="home-card-head">
    <h2>Rankings</h2>
    <a class="home-card-link" href="/cfb/power/">All FBS teams &rarr;</a>
  </div>
  <p>Every FBS team on ESPN's FPI, the AP poll and the GordStats rating, with
     playoff and conference odds, and how far each has moved since any week.
     Each team links to its own page: schedule, projected results and
     projected record.</p>
</section>

<section class="home-card">
  <div class="home-card-head">
    <h2>Schedule &amp; Scores</h2>
    <a class="home-card-link" href="/cfb/schedule/">This week's games &rarr;</a>
  </div>
  <p>Every FBS game, week by week &mdash; kickoffs, TV, ranks, the GordStats and
     DraftKings lines, FPI and the forecast, with sorting and filters; live
     scores, clock and drive situation while games are on.</p>
</section>

<section class="home-card">
  <div class="home-card-head">
    <h2>Fantasy League</h2>
    <a class="home-card-link" href="/cfb/matchups/">This week's matchups &rarr;</a>
  </div>
  <p>The Yahoo college league: every matchup with both rosters and live
     scoring, standings and power, and the draft graded.</p>
  <p class="home-card-links">
    <a href="/cfb/matchups/">Matchups</a> ·
    <a href="/cfb/roster/">Team Dashboard</a> ·
    <a href="/cfb/usage/">Usage</a> ·
    <a href="/cfb/league/">League Dashboard</a> ·
    <a href="/cfb/live/">Draft Review</a>
  </p>
</section>
"""


def generate():
    write_page(WEB_DIR / "index.html", "CFB", body())


if __name__ == "__main__":
    generate()
