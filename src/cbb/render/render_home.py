import json
from datetime import date

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
    <h2>College Basketball</h2>
    <a class="home-card-link" href="{href}">{label}</a>
  </div>
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


def _wnba_card() -> str:
    """Compact WNBA card for the CBB-season homepage."""
    return """
<section class="home-card">
  <div class="home-card-head">
    <h2>WNBA Fantasy</h2>
    <a class="home-card-link" href="/wnba/index.html">Full dashboard →</a>
  </div>
  <p>League matchup projections, live win odds, pickups and drops —
     back when the WNBA season resumes.</p>
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
  <p>Draft boards and tiers, ADP versus where players actually went, schedule
     strength, and a full waiver and trade history for the
     <a href="https://sleeper.com/leagues/1257466498994143232">Zelk Team</a> league.</p>
  <p class="home-card-links">
    <a href="/fantasy/adp/">Draft vs ADP</a> ·
    <a href="/fantasy/draft/">Draft</a> ·
    <a href="/fantasy/transactions/">Waivers &amp; Trades</a>
  </p>
</section>
"""


def _wnba_lead() -> str:
    return """
<h1>WNBA Fantasy</h1>
{% include wnba_scoreboard.html %}
<p class="dashboard-cta">
  <a class="dashboard-link" href="/wnba/index.html">
    Full dashboard: player games remaining, pickups &amp; drops →
  </a>
</p>
"""


def _cbb_lead() -> str:
    return """
<h1>College Basketball</h1>
<section class="home-card">
  <div class="home-card-head">
    <h2>March Madness Predictions</h2>
    <a class="home-card-link" href="/men/index.html">Today's Scores →</a>
  </div>
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
{{% include cbb_countdown.html %}}

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

    fm = "---\nlayout: default\ntitle: College Basketball\n---\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(fm + html.lstrip())
    print(f"Wrote CBB home -> {path}")


def render_home():
    """Season-aware homepage: whichever sport is live leads the page."""
    today = date.today()
    cbb_in_season = CBB_TIPOFF <= today <= CBB_SEASON_END

    if cbb_in_season:
        html = _cbb_lead() + _wnba_card() + _fantasy_card()
    else:
        html = _wnba_lead() + _cbb_card(today) + _fantasy_card()

    path = paths.WEB_HOME
    path.parent.mkdir(parents=True, exist_ok=True)

    fm = "---\nlayout: default\ntitle: GordStats Home\n---\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(fm + html.lstrip())
