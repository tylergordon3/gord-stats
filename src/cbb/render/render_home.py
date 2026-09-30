import json
import re
from datetime import date, datetime, timedelta
from html import escape


from cbb import html_util
from cbb import paths, teams, utils

def team_logos(df):
    if teams.getTeamOfficialName(df['Men'], debug=False) != None:
      logo = teams.getTeamLogo(df["Men"], debug=False)
      df["Men"] = f'{html_util.image_formatter(logo)} {teams.getTeamNickname(df.Men)}'
    
    if teams.getTeamOfficialName(df['Women'], debug=False) != None:
      logo = teams.getTeamLogo(df["Women"], debug=False)
      df["Women"] = f'{html_util.image_formatter(logo)} {teams.getTeamNickname(df.Women)}'

    return df


# CBB regular season window: the homepage leads with college basketball
# inside it. Update yearly - from the first game on the schedule, not the
# usual Monday: 2026-27 opens Sunday Nov 1 (Notre Dame-Villanova in Rome, men
# and women), and a Nov 2 tipoff left the live scoreboard off for it. This is
# a switch - the live tick (cbb.live), the daily run (gordstats.daily) and the
# homepage layout all key on it - so it stays the first game. The date the
# words give is opening day, from the countdown: see _tipoff_shown.
CBB_TIPOFF     = date(2026, 11, 1)
CBB_SEASON_END = date(2027, 4, 10)


def _tipoff_shown() -> date:
    """The opening day the words name: the countdown's own date.

    The clock in countdowns.yml counts to opening day, the Monday all of
    Division I starts, while CBB_TIPOFF is the first game on the schedule -
    this season a day earlier. The line under the clock used to print
    CBB_TIPOFF - "tips off November 1" under a card reading "Monday,
    November 2" (the 2026-09-29 phone audit). Reading the clock's date means
    the two cannot disagree. A clock that is missing, or plainly another
    season's (not within the week after CBB_TIPOFF), falls back to the
    switch date.
    """
    target = _countdown_targets().get("cbb")
    if target and CBB_TIPOFF <= target.date() <= CBB_TIPOFF + timedelta(days=7):
        return target.date()
    return CBB_TIPOFF


def _season_status(today: date, ndash: str) -> str:
    """One line on where the season stands, for the homepage and /cbb/ cards.

    The dash comes in as an argument because the two cards spell it
    differently (a literal character on one, an entity on the other).
    """
    label = f"{CBB_TIPOFF.year}{ndash}{str(CBB_TIPOFF.year + 1)[2:]}"
    if today < CBB_TIPOFF:
        # No "N days away": both cards carry the live clock right above this,
        # and a count fixed at build time read "34 days" under "33 DAYS"
        # for most of every day.
        return f"The {label} season tips off <strong>{_tipoff_shown():%B %-d}</strong>."
    if today <= CBB_SEASON_END:
        return "The season is underway."
    return f"The {label} season is over."


def _latest_predict_link() -> tuple[str, str]:
    """(href, label) for the newest men's bracketology page on disk."""
    dates = sorted(
        f.name.removeprefix("predict_").removesuffix(".html")
        for f in paths.WEB_M_DIR.glob("predict_*.html")
    )
    if not dates:
        return "/men/history", "Prediction Archive →"
    latest = dates[-1]
    season = utils.season_year(latest)
    # "Final" only once that season's bracket can no longer change - the page
    # is rewritten daily in season, and the link used to call it final anyway.
    today = date.today()
    final = season < utils.season_year(today) or today > CBB_SEASON_END
    return f"/men/predict_{latest}", f"{'Final ' if final else ''}{season} Bracketology →"


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
    """Compact college-basketball card for the homepage outside the season."""
    when = _season_status(today, "–")
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
    <a href="/men/conference">Conference Rankings</a> ·
    <a href="/men/history">Prediction History</a>
  </p>
</section>
"""


# No WNBA card (2026-09-29). With the season over it was a whole card of phone
# promising pages that come "back when the WNBA season resumes", and the
# section is out of the switcher in docs/_data/nav.yml already. The /wnba/
# pages are still built; when the season resumes, the card comes back from
# git history (it lived here as _wnba_card) alongside the nav entry.


def _fantasy_card() -> str:
    """Compact fantasy football card. Shown in both season layouts."""
    return """
<section class="home-card">
  <div class="home-card-head">
    <h2>Fantasy Football</h2>
    <a class="home-card-link" href="/fantasy/">League dashboard →</a>
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
    <a class="home-card-link" href="/cfb/">CFB home →</a>
  </div>
  {% include cfb_countdown.html %}
  <p>The Yahoo college fantasy league, and every FBS game of the season —
     model predictions, live scores, kickoffs, TV, and ranks.</p>
  <p class="home-card-links">
    <a href="/cfb/watch/">Watch Guide</a> ·
    <a href="/cfb/schedule/">CFB Schedule</a> ·
    <a href="/cfb/league/">League Dashboard</a>
  </p>
</section>
"""


def _cbb_lead() -> str:
    return """
<h1>CBB</h1>
<section class="home-card">
  <div class="home-card-head">
    <h2>March Madness Predictions</h2>
    <a class="home-card-link" href="/men/">Today's Scores →</a>
  </div>
  {% include countdown.html key="cbb" %}
  <p>Machine-learning predictions of the NCAA tournament field, updated daily.
     Built on <a href="https://kenpom.com/" target="_blank">KenPom</a> and
     <a href="https://barttorvik.com/#" target="_blank">Torvik</a>, with scores
     from <a href="https://www.thescore.com/" target="_blank">TheScore</a>.</p>
  <p class="home-card-links">
    <a href="/men/conference">Conference Rankings</a> ·
    <a href="/men/history">Prediction History</a>
  </p>
</section>
"""


def _stale_note(days: int, what: str = "") -> str:
    """That a page is last season's, said plainly.

    Out of season the daily task refuses to run - the feeds keep serving last
    season's numbers, so rebuilding would republish March as if it were now -
    which means these pages are frozen at whatever they last had. A reader has
    no way to know that from the page, and a bracket with no date on it reads
    as current.

    `what` is the date where one is actually known; the file's own timestamp
    is not it, because any edit to the file moves it and a fresh checkout on
    the Pi resets it to the checkout.
    """
    if days <= 0:
        return ""
    when = f"{what} &mdash; " if what else "Last season&rsquo;s &mdash; "
    return (f'<p class="home-card-stale">{when}this fills in again when the '
            "season starts.</p>")


def _latest_predict_date() -> str:
    """The date the newest bracketology page was predicted for, from its own
    name - which is the real prediction date, not a file timestamp."""
    dates = sorted(
        f.name.removeprefix("predict_").removesuffix(".html")
        for f in paths.WEB_M_DIR.glob("predict_*.html"))
    if not dates:
        return ""
    try:
        return f"{date.fromisoformat(dates[-1]):%B %-d, %Y}"
    except ValueError:
        return ""


def _cbb_home_body(today: date) -> str:
    """The college basketball section landing page.

    Deliberately league-agnostic: it sits above the men's/women's split so the
    section has somewhere to land that isn't already a scores page. The
    countdown include is the same one the season banner uses.

    Out of season the page leads with what is actually live. The power
    rankings are built from Torvik's preseason projections and rebuild every
    day of the year; the bracket, the conference table and the scoreboard all
    need games, and say when they last had any.
    """
    from gordstats import my_teams_today
    days = (CBB_TIPOFF - today).days
    when = _season_status(today, "&ndash;")
    href, label = _latest_predict_link()
    preseason = days > 0

    # The numbers first, as on /cfb/: this page was a countdown, two
    # paragraphs and four cards describing the nav above them. The top ten is
    # live all year (Torvik's preseason projections rebuild daily), so it
    # leads preseason; in season the bracket does.
    power = f"""
<section class="home-card">
  <div class="home-card-head">
    <h2>Power Rankings</h2>
    <a class="home-card-link" href="/cbb/power/">All teams &rarr;</a>
  </div>
  {_top_ten()}
</section>
"""
    bracket = f"""
<section class="home-card">
  <div class="home-card-head">
    <h2>Bracketology</h2>
    <a class="home-card-link" href="{href}">{label}</a>
  </div>
  <p>The projected tournament field: seeds, bubble, and the teams on the wrong
     side of the cut.</p>
  {_stale_note(days, _latest_predict_date())}
</section>
"""
    return f"""
{{% include countdown.html key="cbb" %}}

<p>{when} Power rankings, bracketology and live scores, men's and women's.</p>
{my_teams_today.section(cfb=False, cbb=True) if not preseason else ""}
{power + bracket if preseason else bracket + power}
<section class="home-card">
  <div class="home-card-head">
    <h2>Everything else</h2>
  </div>
  <p class="home-card-links">
    <a href="/men/">Today's Scores</a> ·
    <a href="/men/conference">Conference Rankings</a> ·
    <a href="/men/history">Prediction History</a>
  </p>
  {_stale_note(days) if preseason else ""}
</section>
"""


def _top_ten() -> str:
    """The power rankings' first ten, in the page's own order
    (render_power.ranked), or nothing if the table cannot be read."""
    try:
        from cbb.render import render_power
        rows = render_power.top(10)
    except Exception as exc:                     # the page stands without it
        print(f"  ! CBB home: no top ten ({exc})")
        return ""
    body = "".join(
        f"<tr><td class='tt-rk'>{int(r.rk)}</td><td class='tt-t'>{escape(str(r.team))}</td>"
        f"<td>{r.pw:.0f}&ndash;{r.pl:.0f}</td><td class='tt-c'>{escape(str(r.conf))}</td></tr>"
        for r in rows.itertuples(index=False))
    return ("<style>table.tt{width:100%;border-collapse:collapse;font-size:15px;border:0;"
            "margin:0;box-shadow:none}"
            "table.tt td{padding:7px 6px;border:0;border-bottom:1px solid var(--gs-line,#e2e8f0);"
            "background:transparent}"
            "table.tt tr:last-child td{border-bottom:0}"
            "table.tt td.tt-rk{width:28px;color:var(--gs-muted,#5d6b7e);font-weight:700}"
            "table.tt td.tt-t{font-weight:700}"
            "table.tt td.tt-c{color:var(--gs-muted,#5d6b7e);text-align:right}"
            "@media (prefers-color-scheme: dark){table.tt td{border-color:#2b3852}}</style>"
            "<table class='tt'><tbody>" + body + "</tbody></table>")


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
    <h2>Top 25 Comparison</h2>
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


def _my_teams(today: date) -> str:
    """The reader's own teams (gordstats.my_teams_today), ahead of everything:
    football's week from late August through the playoff final, basketball's
    day from tipoff to the last game."""
    # Through January: the CFP final is Jan 25, 2027, and ESPN's postseason
    # window runs to the 28th.
    cfb = today >= date(today.year, 8, 20) or today <= date(today.year, 1, 31)
    cbb = CBB_TIPOFF <= today <= CBB_SEASON_END
    if not (cfb or cbb):
        return ""
    from gordstats import my_teams_today
    return my_teams_today.section(cfb=cfb, cbb=cbb)


def render_home():
    """Season-aware homepage: every sport is a preview card, closest clock first.

    The WNBA scoreboard used to lead the page outside the college basketball
    season; it moved to /wnba/ only (2026-08-31), so the homepage is now cards
    all the way down in both layouts — in CBB season the basketball lead
    stays on top. The WNBA's own card went too, with its season (2026-09-29).
    """
    today = date.today()
    cbb_in_season = CBB_TIPOFF <= today <= CBB_SEASON_END

    # Preview boxes run closest clock first: the thing happening soonest is
    # the thing the page should lead with, and the order corrects itself as
    # each date passes rather than being re-argued by hand.
    if cbb_in_season:
        html = _cbb_lead() + _by_next_clock(
            [("fantasy", _fantasy_card()), ("cfb", _cfb_card())])
    else:
        html = _by_next_clock(
            [("cbb", _cbb_card(today)), ("fantasy", _fantasy_card()),
             ("cfb", _cfb_card())])
    # The graphics lead: they are the thing worth looking at today, and the
    # preview cards are navigation, which can sit under them.
    html = _my_teams(today) + _cfb_graphics(today) + html

    path = paths.WEB_HOME
    path.parent.mkdir(parents=True, exist_ok=True)

    # No page title: jekyll-seo-tag then renders the site title and tagline,
    # which is a better tab than "GordStats Home | GordStats".
    fm = "---\nlayout: default\n---\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(fm + html.lstrip())
