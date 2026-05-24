import json
import pandas as pd

from cbb.lib import html_util
from cbb.lib import paths, teams
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


def render_home():
    # Raw string to preserve formatting

    html = r"""
{% include ff_countdown.html %}
    <p>Using machine learning to predict the NCAA March Madness field.</p>
    <p>
      Data Sources:
      <a href="https://kenpom.com/" target="_blank">KenPom</a> |
      <a href="https://barttorvik.com/#" target="_blank">Torvik</a>
    </p>
    <p>
      Today's scores and schedule from:
      <a href="https://www.thescore.com/" target="_blank">TheScore</a>
    </p>
    <h1>WNBA Fantasy Matchups</h1>
    {% include report.html %}
"""
    #seeds = compare_bracket.gen()
    #html = html + "<br>" + seeds # + styler.to_html()
    path = paths.WEB_HOME
    path.parent.mkdir(parents=True, exist_ok=True)

    html = html_util.add_front_matter(html, "GordStats Home")

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
        print(f"Wrote to: {path}")
