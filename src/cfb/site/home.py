"""
The college football section landing page (docs/cfb/index.html).

Mirrors the CBB section home: a countdown, one paragraph of what the section
is, then a card per page. League facts (name, draft time, roster shape) come
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

<p>College football, two ways: the real {SEASON} FBS season, and the
   <a href="{lg['url']}">{lg['name']}</a> — a {lg['num_teams']}-team Yahoo
   college fantasy league ({_roster_line(lg)}).{draft_line}</p>

<section class="home-card">
  <div class="home-card-head">
    <h2>Draft Review</h2>
    <a class="home-card-link" href="/cfb/live/">How it went &rarr;</a>
  </div>
  <p>The draft, graded: every pick against Yahoo's ADP and against this
     site's own valuations, team grades, the steal and the reach, and how the
     room actually priced a 2-QB league.</p>
</section>

<section class="home-card">
  <div class="home-card-head">
    <h2>League Power</h2>
    <a class="home-card-link" href="/cfb/league-power/">The rankings &rarr;</a>
  </div>
  <p>Every roster priced as the best lineup it can field, tracked all season —
     waivers and trades move the rankings, and the Move columns remember who
     climbed.</p>
</section>

<section class="home-card">
  <div class="home-card-head">
    <h2>League Dashboard</h2>
    <a class="home-card-link" href="/cfb/league/">Standings &amp; matchups &rarr;</a>
  </div>
  <p>The league itself: standings, the week's matchups, waivers and trades —
     and the draft, graded against the pre-draft board, once it happens.</p>
</section>

<section class="home-card">
  <div class="home-card-head">
    <h2>Scoreboard</h2>
    <a class="home-card-link" href="/cfb/scoreboard/">This week's games &rarr;</a>
  </div>
  <p>Every game of the week on one board &mdash; model projections, betting
     lines, ranks and records before kickoff; live scores, clock and drive
     situation while games are on.</p>
</section>

<section class="home-card">
  <div class="home-card-head">
    <h2>CFB Schedule</h2>
    <a class="home-card-link" href="/cfb/schedule/">Full schedule &rarr;</a>
  </div>
  <p>Every FBS game, week by week: kickoffs, TV, venues, AP ranks, and scores
     once the games go final.</p>
</section>
"""


def generate():
    write_page(WEB_DIR / "index.html", "College Football", body())


if __name__ == "__main__":
    generate()
