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
    <p>Fantasy data: 2026-05-24 12:14:59 PM EDT<br />Schedule: fetched 2026-05-24 (332 games)</p>
<p>Week 2: 2026-05-18 &rarr; 2026-05-24<br />Counting: remaining (1 days)</p>
<p>──────────────────────────────────────────────────<br /> Team Max Games<br />──────────────────────────────────────────────────<br /> Kim Mulkey's Rejects 5<br /> Shyanne Sellars pls come back 4<br /> Quarterzip Memorial Team 5<br /> Angel REESE 5<br /> Stud bud enthusiast 5<br /> Brenda Frese Fan Club 5<br /> Tatum Tots Top Team 5<br /> Jake's Scary Team 6<br />──────────────────────────────────────────────────</p>
<p>══════════════════════════════════════════════════════════════<br /> WEEK 2 MATCHUPS &mdash; LIVE SCOREBOARD<br />══════════════════════════════════════════════════════════════</p>
<p>──────────────────────────────────────────────────────────<br /> IN PROGRESS<br /> ──────────────────────────────────────────────────────────<br /> Stud bud enthusiast 300.0 pts 5 games left<br /> ▲ Shyanne Sellars pls come back 424.0 pts 4 games left</p>
<p>Shyanne Sellars pls come back leads by 124.0 pts</p>
<p>──────────────────────────────────────────────────────────<br /> IN PROGRESS<br /> ──────────────────────────────────────────────────────────<br /> ▲ Kim Mulkey's Rejects 399.0 pts 5 games left<br /> Quarterzip Memorial Team 253.0 pts 5 games left</p>
<p>Kim Mulkey's Rejects leads by 146.0 pts</p>
<p>──────────────────────────────────────────────────────────<br /> IN PROGRESS<br /> ──────────────────────────────────────────────────────────<br /> Tatum Tots Top Team 243.0 pts 5 games left<br /> ▲ Jake's Scary Team 393.0 pts 6 games left</p>
<p>Jake's Scary Team leads by 150.0 pts</p>
<p>──────────────────────────────────────────────────────────<br /> IN PROGRESS<br /> ──────────────────────────────────────────────────────────<br /> Brenda Frese Fan Club 391.0 pts 5 games left<br /> ▲ Angel REESE 465.0 pts 5 games left</p>
<p>Angel REESE leads by 74.0 pts</p>
<p>══════════════════════════════════════════════════════════</p>
<p><br />════════════════════════════════════════════════════════════<br /> Team 1: Kim Mulkey's Rejects<br /> Week 2 (2026-05-18 &rarr; 2026-05-24)<br /> Today: 2026-05-24 | Days left: 1<br />════════════════════════════════════════════════════════════</p>
<p>(Days already played: 2026-05-18, 2026-05-19, 2026-05-20, 2026-05-21, 2026-05-22, 2026-05-23)</p>
<p>MAX STARTABLE GAMES REMAINING: 5 (cap: 6)</p>
<p>2026-05-24 ◀ today<br /> [G ] Azzi Fudd (DAL)<br /> [G ] Kahleah Copper (PHX)<br /> [F/C ] Breanna Stewart (NY)<br /> [F/C ] Naz Hillmon (ATL)<br /> [UTIL] Jewell Loyd (LV)</p>
<p><br />════════════════════════════════════════════════════════════<br /> Team 2: Shyanne Sellars pls come back<br /> Week 2 (2026-05-18 &rarr; 2026-05-24)<br /> Today: 2026-05-24 | Days left: 1<br />════════════════════════════════════════════════════════════</p>
<p>(Days already played: 2026-05-18, 2026-05-19, 2026-05-20, 2026-05-21, 2026-05-22, 2026-05-23)</p>
<p>MAX STARTABLE GAMES REMAINING: 4 (cap: 6)</p>
<p>2026-05-24 ◀ today<br /> [G ] Rhyne Howard (ATL)<br /> [G ] Jordin Canada (ATL)<br /> [F/C ] Shakira Austin (WSH)<br /> [UTIL] Natisha Hiedeman (SEA)</p>
<p><br />════════════════════════════════════════════════════════════<br /> Team 3: Quarterzip Memorial Team<br /> Week 2 (2026-05-18 &rarr; 2026-05-24)<br /> Today: 2026-05-24 | Days left: 1<br />════════════════════════════════════════════════════════════</p>
<p>(Days already played: 2026-05-18, 2026-05-19, 2026-05-20, 2026-05-21, 2026-05-22, 2026-05-23)</p>
<p>MAX STARTABLE GAMES REMAINING: 5 (cap: 6)</p>
<p>2026-05-24 ◀ today<br /> [G ] Sonia Citron (WSH)<br /> [G ] Chelsea Gray (LV)<br /> [F/C ] Angel Reese (ATL)<br /> [F/C ] Alanna Smith (DAL)<br /> [F/C ] Cameron Brink (LA)</p>
<p><br />════════════════════════════════════════════════════════════<br /> Team 4: Angel REESE<br /> Week 2 (2026-05-18 &rarr; 2026-05-24)<br /> Today: 2026-05-24 | Days left: 1<br />════════════════════════════════════════════════════════════</p>
<p>(Days already played: 2026-05-18, 2026-05-19, 2026-05-20, 2026-05-21, 2026-05-22, 2026-05-23)</p>
<p>MAX STARTABLE GAMES REMAINING: 5 (cap: 6)</p>
<p>2026-05-24 ◀ today<br /> [G ] Paige Bueckers (DAL)<br /> [G ] Flau'jae Johnson (SEA)<br /> [F/C ] Jonquel Jones (NY)<br /> [F/C ] DeWanna Bonner (PHX)<br /> [F/C ] NaLyssa Smith (LV)</p>
<p><br />════════════════════════════════════════════════════════════<br /> Team 6: Stud bud enthusiast<br /> Week 2 (2026-05-18 &rarr; 2026-05-24)<br /> Today: 2026-05-24 | Days left: 1<br />════════════════════════════════════════════════════════════</p>
<p>(Days already played: 2026-05-18, 2026-05-19, 2026-05-20, 2026-05-21, 2026-05-22, 2026-05-23)</p>
<p>MAX STARTABLE GAMES REMAINING: 5 (cap: 6)</p>
<p>2026-05-24 ◀ today<br /> [G ] Allisha Gray (ATL)<br /> [F/C ] Lauren Betts (WSH)<br /> [F/C ] Betnijah Laney-Hamilton (NY)<br /> [F/C ] Jessica Shepard (DAL)<br /> [UTIL] Cheyenne Parker-Tyus (LV)</p>
<p><br />════════════════════════════════════════════════════════════<br /> Team 7: Brenda Frese Fan Club<br /> Week 2 (2026-05-18 &rarr; 2026-05-24)<br /> Today: 2026-05-24 | Days left: 1<br />════════════════════════════════════════════════════════════</p>
<p>(Days already played: 2026-05-18, 2026-05-19, 2026-05-20, 2026-05-21, 2026-05-22, 2026-05-23)</p>
<p>MAX STARTABLE GAMES REMAINING: 5 (cap: 6)</p>
<p>2026-05-24 ◀ today<br /> [G ] Jackie Young (LV)<br /> [G ] Sabrina Ionescu (NY)<br /> [F/C ] Alyssa Thomas (PHX)<br /> [F/C ] Satou Sabally (NY)<br /> [UTIL] Jovana Nogic (PHX)</p>
<p><br />════════════════════════════════════════════════════════════<br /> Team 8: Tatum Tots Top Team<br /> Week 2 (2026-05-18 &rarr; 2026-05-24)<br /> Today: 2026-05-24 | Days left: 1<br />════════════════════════════════════════════════════════════</p>
<p>(Days already played: 2026-05-18, 2026-05-19, 2026-05-20, 2026-05-21, 2026-05-22, 2026-05-23)</p>
<p>MAX STARTABLE GAMES REMAINING: 5 (cap: 6)</p>
<p>2026-05-24 ◀ today<br /> [G ] Arike Ogunbowale (DAL)<br /> [F/C ] A'ja Wilson (LV)<br /> [F/C ] Dominique Malonga (SEA)<br /> [F/C ] Brionna Jones (ATL)<br /> [UTIL] Leonie Fiebich (NY)</p>
<p><br />════════════════════════════════════════════════════════════<br /> Team 9: Jake's Scary Team<br /> Week 2 (2026-05-18 &rarr; 2026-05-24)<br /> Today: 2026-05-24 | Days left: 1<br />════════════════════════════════════════════════════════════</p>
<p>(Days already played: 2026-05-18, 2026-05-19, 2026-05-20, 2026-05-21, 2026-05-22, 2026-05-23)</p>
<p>MAX STARTABLE GAMES REMAINING: 6 (cap: 6)</p>
<p>2026-05-24 ◀ today<br /> [G ] Kelsey Plum (LA)<br /> [G ] Jade Melbourne (SEA)<br /> [F/C ] Dearica Hamby (LA)<br /> [F/C ] Kiki Iriafen (WSH)<br /> [F/C ] Natasha Mack (PHX)<br /> [UTIL] Pauline Astier (NY)</p>
 """
    #seeds = compare_bracket.gen()
    #html = html + "<br>" + seeds # + styler.to_html()
    path = paths.WEB_HOME
    path.parent.mkdir(parents=True, exist_ok=True)

    html = html_util.add_front_matter(html, "GordStats Home")

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
        print(f"Wrote to: {path}")
