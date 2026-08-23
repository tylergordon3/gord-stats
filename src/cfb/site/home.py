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
{{% include countdown.html key="cfb" %}}

<p>College football, two ways: the real {SEASON} FBS season, and the
   <a href="{lg['url']}">{lg['name']}</a> — a {lg['num_teams']}-team Yahoo
   college fantasy league ({_roster_line(lg)}).{draft_line}</p>

<section class="home-card">
  <div class="home-card-head">
    <h2>Draft Board</h2>
    <a class="home-card-link" href="/cfb/draft/">Full board &rarr;</a>
  </div>
  <p>The pre-draft preview: Yahoo's college ADP board, sortable and filterable,
     with the league's roster and scoring shape beside it. Two starting QBs —
     plan accordingly.</p>
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
