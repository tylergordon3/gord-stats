import json
import re
from datetime import date, datetime

import pandas as pd

from cbb import html_util
from cbb import paths, teams
from cbb.tools import compare_bracket

def team_logos(df):
    if teams.getTeamOfficialName(df['Men'], debug=False) != None:
      logo = teams.getTeamLogo(df["Men"], debug=False)
      df["Men"] = f'{html_util.image_formatter(logo)} {teams.getTeamNickname(df.Men)}'
    
    if teams.getTeamOfficialName(df['Women'], debug=False) != None:
      logo = teams.getTeamLogo(df["Women"], debug=False)
      df["Women"] = f'{html_util.image_formatter(logo)} {teams.getTeamNickname(df.Women)}'

    return df

def bids():
    with open(paths.BIDS_FILE, "r") as f:
        bid_json = json.load(f)
    
    men = bid_json["Men"]["2026"]
    women = bid_json["Women"]["2026"]
    
    men_df = pd.DataFrame.from_dict(men, orient="index")
    women_df = pd.DataFrame.from_dict(women, orient="index")
    combo = pd.merge(men_df, women_df, "inner", left_index=True, right_index=True)
    combo['Conf'] = combo.index
    combo = combo.reset_index(drop=True)
    combo = combo.rename(columns={
        "0_x" : "Men",
        "0_y" : "Women"
    })
    combo = combo[["Men", "Conf", "Women"]].copy()

    combo = combo.apply(lambda x: team_logos(x), axis=1)
    classes = ["sticky-table", "bids-table"]
    table_attr = f'class="{" ".join(classes)}"'
    
    def highlight(row):
      ret = ["", "", ""]

      if "team-logo" in row.Women:
        ret[2] = "font-weight: bold; background:#e8f7e8 !important;"
      
      if "team-logo" in row.Men:
        ret[0] = "font-weight: bold; background:#e8f7e8 !important;"
      return ret
      
    styler = (
        combo.style
        .hide(axis="index")
        .set_table_attributes(table_attr)
        .apply(lambda x: highlight(x), axis=1)
    )
    
    return styler


# CBB regular season window: the homepage leads with college basketball
# inside it, and with WNBA fantasy outside it. Update yearly.
CBB_TIPOFF     = date(2026, 11, 2)
CBB_SEASON_END = date(2027, 4, 10)


def _latest_predict_link() -> tuple[str, str]:
    """(href, label) for the newest men's bracketology page on disk."""
    dates = sorted(
        f.name.removeprefix("predict_").removesuffix(".html")
        for f in paths.WEB_M_DIR.glob("predict_*.html")
    )
    if not dates:
        return "/men/history.html", "Prediction Archive →"
    latest = dates[-1]
    season = int(latest[:4]) + 1 if int(latest[5:7]) >= 7 else int(latest[:4])
    return f"/men/predict_{latest}.html", f"Final {season} Bracketology →"


def _countdown_targets() -> dict:
    """{key: target datetime} from docs/_data/countdowns.yml.

    Parsed with a regex rather than a YAML library on purpose: the Pi's
    runtime does not carry pyyaml, and the file is two fields per block by
    construction. The include itself stays the authority on rendering; this
    only answers "when does each clock fire", for ordering the preview boxes.
    """
    text = (paths.DOCS / "_data" / "countdowns.yml").read_text(encoding="utf-8")
    out = {}
    for match in re.finditer(
            r"^(\w+):.*?^\s*target:\s*\"([^\"]+)\"", text, re.S | re.M):
        try:
            out[match.group(1)] = datetime.fromisoformat(match.group(2))
        except ValueError:
            continue
    # The CFB clock left countdowns.yml for the build-generated game clock
    # (cfb.site.countdown). Its target is a real UTC instant; the yml ones are
    # naive local times, so fold it to naive local for the same comparison.
    try:
        clock = json.loads((paths.DOCS / "_data" / "cfb_countdown.json")
                           .read_text(encoding="utf-8"))
        if clock.get("mode") == "countdown":
            out["cfb"] = (datetime.fromisoformat(
                clock["target"].replace("Z", "+00:00"))
                .astimezone().replace(tzinfo=None))
    except (OSError, ValueError, KeyError):
        pass
    return out


def _by_next_clock(cards) -> str:
    """Join preview cards ordered by how soon their countdown fires.

    `cards`: (countdown key or None, html). The card whose clock fires next
    goes first; a card whose clock has passed - or that has no clock at all -
    renders nothing where the countdown would be, so it drops behind every
    live one, keeping its position among the clockless (the sort is stable).
    """
    targets = _countdown_targets()
    now = datetime.now()

    def fires(item):
        target = targets.get(item[0])
        return target if target and target > now else datetime.max
    return "".join(html for _, html in sorted(cards, key=fires))


# Each clock is included by its own sport's preview box below, directly under
# that box's heading.
#
# They spent a while as a strip across the top of the page instead, because
# sitting at the *bottom* of a box — under a paragraph and two rows of links —
# put them below the fold on a phone. Under the heading is what makes the box
# work as a home for them: the clock is the second thing in the box, and it is
# attached to the sport it counts down to rather than floating above a page
# that is mostly about something else.
#
# A card renders nothing at all once its date has passed (see the include), so
# out of season a box simply has no clock in it — there is no empty frame left
# behind to clear up.


def _cbb_card(today: date) -> str:
    """Compact college-basketball card for the WNBA-season homepage."""
    days = (CBB_TIPOFF - today).days
    if days > 0:
        when = (f"The 2026–27 season tips off <strong>{CBB_TIPOFF:%B %-d}</strong> "
                f"— {days} days away.")
    else:
        when = "The season is underway."
    href, label = _latest_predict_link()
    return f"""
<section class="home-card">
  <div class="home-card-head">
    <h2>CBB</h2>
    <a class="home-card-link" href="{href}">{label}</a>
  </div>
  {{% include countdown.html key="cbb" %}}
  <p>{when} Machine-learning March Madness field predictions,
     built on <a href="https://kenpom.com/" target="_blank">KenPom</a> and
     <a href="https://barttorvik.com/#" target="_blank">Torvik</a>, with scores
     from <a href="https://www.thescore.com/" target="_blank">TheScore</a>.</p>
  <p class="home-card-links">
    <a href="/men/conference.html">Conference Rankings</a> ·
    <a href="/men/history.html">Prediction History</a>
  </p>
</section>
"""


def _wnba_card(in_season: bool) -> str:
    """Compact WNBA card. The full scoreboard lives only on /wnba/ now."""
    what = ("Live fantasy scoreboard, player games remaining, and suggested\n"
            "     pickups &amp; drops for the WNBA fantasy league."
            if in_season else
            "League matchup projections, live win odds, pickups and drops —\n"
            "     back when the WNBA season resumes.")
    return f"""
<section class="home-card">
  <div class="home-card-head">
    <h2>WNBA Fantasy</h2>
    <a class="home-card-link" href="/wnba/index.html">Full dashboard →</a>
  </div>
  <p>{what}</p>
</section>
"""


def _fantasy_card() -> str:
    """Compact fantasy football card. Shown in both season layouts."""
    return """
<section class="home-card">
  <div class="home-card-head">
    <h2>Fantasy Football</h2>
    <a class="home-card-link" href="/fantasy/index.html">League dashboard →</a>
  </div>
  {% include countdown.html key="fantasy" %}
  <p>Draft boards, values and busts, simulated power rankings, schedule
     strength, and a full waiver and trade history for the
     <a href="https://sleeper.com/leagues/1257466498994143232">Zelk Team</a> league.</p>
  <p class="home-card-links">
    <a href="/fantasy/draft/">Draft Analytics</a> ·
    <a href="/fantasy/power/">Power Rankings</a> ·
    <a href="/fantasy/transactions/">Waivers &amp; Trades</a>
  </p>
</section>
"""


def _cfb_card() -> str:
    """Compact college football card. Shown in both season layouts.

    The clock is the build-generated game clock (cfb_countdown.html /
    _data/cfb_countdown.json), not a countdowns.yml entry — it counts to the
    next kickoff and shows a notice while games are on.
    """
    return """
<section class="home-card">
  <div class="home-card-head">
    <h2>CFB</h2>
    <a class="home-card-link" href="/cfb/index.html">CFB home →</a>
  </div>
  {% include cfb_countdown.html %}
  <p>The Yahoo college fantasy league, and every FBS game of the season —
     model predictions, live scores, kickoffs, TV, and ranks.</p>
  <p class="home-card-links">
    <a href="/cfb/scoreboard/">Scoreboard</a> ·
    <a href="/cfb/league/">League Dashboard</a> ·
    <a href="/cfb/schedule/">CFB Schedule</a>
  </p>
</section>
"""


def _cbb_lead() -> str:
    return """
<h1>CBB</h1>
<section class="home-card">
  <div class="home-card-head">
    <h2>March Madness Predictions</h2>
    <a class="home-card-link" href="/men/index.html">Today's Scores →</a>
  </div>
  {% include countdown.html key="cbb" %}
  <p>Machine-learning predictions of the NCAA tournament field, updated daily.
     Built on <a href="https://kenpom.com/" target="_blank">KenPom</a> and
     <a href="https://barttorvik.com/#" target="_blank">Torvik</a>, with scores
     from <a href="https://www.thescore.com/" target="_blank">TheScore</a>.</p>
  <p class="home-card-links">
    <a href="/men/conference.html">Conference Rankings</a> ·
    <a href="/men/history.html">Prediction History</a>
  </p>
</section>
"""


def _cbb_home_body(today: date) -> str:
    """The college basketball section landing page.

    Deliberately league-agnostic: it sits above the men's/women's split so the
    section has somewhere to land that isn't already a scores page. The
    countdown include is the same one the season banner uses.
    """
    days = (CBB_TIPOFF - today).days
    if days > 0:
        when = (f"The 2026&ndash;27 season tips off <strong>{CBB_TIPOFF:%B %-d}</strong>"
                f" &mdash; {days} days away.")
    else:
        when = "The season is underway."
    href, label = _latest_predict_link()

    return f"""
{{% include countdown.html key="cbb" %}}

<p>{when} Machine-learning predictions of the NCAA tournament field, rebuilt daily
   through the season and scored against what actually happened. Built on
   <a href="https://kenpom.com/" target="_blank">KenPom</a> and
   <a href="https://barttorvik.com/#" target="_blank">Torvik</a>, with scores from
   <a href="https://www.thescore.com/" target="_blank">TheScore</a>.</p>

<p>Every page below carries a men's/women's toggle in the header &mdash; it
   remembers which league you last looked at.</p>

<section class="home-card">
  <div class="home-card-head">
    <h2>Bracketology</h2>
    <a class="home-card-link" href="{href}">{label}</a>
  </div>
  <p>The projected tournament field: seeds, bubble, and the teams on the wrong
     side of the cut.</p>
  <p class="home-card-links">
    <a href="/men/history.html">Prediction History</a>
  </p>
</section>

<section class="home-card">
  <div class="home-card-head">
    <h2>Today's Scores</h2>
    <a class="home-card-link" href="/men/index.html">Scoreboard &rarr;</a>
  </div>
  <p>Live scores and the day's slate.</p>
</section>

<section class="home-card">
  <div class="home-card-head">
    <h2>Conference Rankings</h2>
    <a class="home-card-link" href="/men/conference.html">Standings &rarr;</a>
  </div>
  <p>Conference-by-conference strength, and how many bids each is projected to get.</p>
</section>
"""


def render_cbb_home():
    """Write the college basketball section landing page."""
    html = _cbb_home_body(date.today())

    path = paths.DOCS / "cbb" / "index.html"
    path.parent.mkdir(parents=True, exist_ok=True)

    fm = "---\nlayout: default\ntitle: CBB\n---\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(fm + html.lstrip())
    print(f"Wrote CBB home -> {path}")


# The two football graphics. Both are written by cfb.site.homecards as
# includes, because the homepage has no business importing the football model;
# they are placed here, in season, under the preview cards.
def _cfb_graphics(today: date) -> str:
    """The Top 25 comparison and the week's bets, if the season is on.

    Out of season the includes still exist but say nothing useful, so the
    whole block is left off rather than rendering two empty frames.
    """
    if not (date(today.year, 8, 20) <= today <= date(today.year, 12, 20)):
        return ""
    return """
<section class="home-card">
  <div class="home-card-head">
    <h2>Top 25: three opinions</h2>
    <a class="home-card-link" href="/cfb/power/">All 138 teams &rarr;</a>
  </div>
  {% include cfb_top25.html %}
</section>

<section class="home-card">
  <div class="home-card-head">
    <h2>This week's bets</h2>
    <a class="home-card-link" href="/cfb/predictions/">Every game &rarr;</a>
  </div>
  {% include cfb_bets.html %}
</section>
"""


def render_home():
    """Season-aware homepage: every sport is a preview card, closest clock first.

    The WNBA scoreboard used to lead the page outside the college basketball
    season; it moved to /wnba/ only (2026-08-31), so the homepage is now cards
    all the way down in both layouts — in CBB season the basketball lead
    stays on top.
    """
    today = date.today()
    cbb_in_season = CBB_TIPOFF <= today <= CBB_SEASON_END

    # Preview boxes run closest clock first: the thing happening soonest is
    # the thing the page should lead with, and the order corrects itself as
    # each date passes rather than being re-argued by hand.
    if cbb_in_season:
        html = _cbb_lead() + _by_next_clock(
            [(None, _wnba_card(in_season=False)), ("fantasy", _fantasy_card()),
             ("cfb", _cfb_card())])
    else:
        html = _by_next_clock(
            [("cbb", _cbb_card(today)), ("fantasy", _fantasy_card()),
             ("cfb", _cfb_card()), (None, _wnba_card(in_season=True))])
    # The graphics lead: they are the thing worth looking at today, and the
    # preview cards are navigation, which can sit under them.
    html = _cfb_graphics(today) + html

    path = paths.WEB_HOME
    path.parent.mkdir(parents=True, exist_ok=True)

    # No page title: jekyll-seo-tag then renders the site title and tagline,
    # which is a better tab than "GordStats Home | GordStats".
    fm = "---\nlayout: default\n---\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(fm + html.lstrip())
