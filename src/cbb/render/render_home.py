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
    <p class="demoTitle">&nbsp;</p>
<p>Fantasy data: 2026-05-23 08:48:58 PM EDT<br />Schedule: fetched 2026-05-23 (332 games)</p>
<p>Week 2: 2026-05-18 &rarr; 2026-05-24<br />Counting: remaining (2 days)</p>
<p>──────────────────────────────────────────────────<br /> Team Max Games<br />──────────────────────────────────────────────────<br /> Kim Mulkey's Rejects 6<br /> Shyanne Sellars pls come back 8<br /> Quarterzip Memorial Team 9<br /> Angel REESE 8<br /> Stud bud enthusiast 7<br /> Brenda Frese Fan Club 8<br /> Tatum Tots Top Team 10<br /> Jake's Scary Team 9<br />──────────────────────────────────────────────────</p>
<p>═══════════════════════════════════════════════════<br /> WEEK 2 MATCHUPS &mdash; LIVE SCOREBOARD<br />═══════════════════════════════════════════════════</p>
<p>───────────────────────────────────────────────────<br /> IN PROGRESS<br /> ───────────────────────────────────────────────────<br /> Stud bud enthusiast 300.0 pts 7 games left<br /> ▲ Shyanne Sellars pls come back 424.0 pts 8 games left</p>
<p>Shyanne Sellars pls come back leads by 124.0 pts (includes live scoring)<br /> Finalized only &rarr; Stud bud enthusiast: 250.0 | Shyanne Sellars pls come back: 323.0</p>
<p>───────────────────────────────────────────────────<br /> IN PROGRESS<br /> ───────────────────────────────────────────────────<br /> ▲ Kim Mulkey's Rejects 397.0 pts 6 games left<br /> Quarterzip Memorial Team 223.0 pts 9 games left</p>
<p>Kim Mulkey's Rejects leads by 174.0 pts (includes live scoring)<br /> Finalized only &rarr; Kim Mulkey's Rejects: 356.0 | Quarterzip Memorial Team: 154.0</p>
<p>───────────────────────────────────────────────────<br /> IN PROGRESS<br /> ───────────────────────────────────────────────────<br /> Tatum Tots Top Team 206.0 pts 10 games left<br /> ▲ Jake's Scary Team 322.0 pts 9 games left</p>
<p>Jake's Scary Team leads by 116.0 pts (includes live scoring)<br /> Finalized only &rarr; Tatum Tots Top Team: 136.0 | Jake's Scary Team: 243.0</p>
<p>──────────────────────────────────────────────────────────<br /> IN PROGRESS<br /> ──────────────────────────────────────────────────────────<br /> Brenda Frese Fan Club 388.0 pts 8 games left<br /> ▲ Angel REESE 434.0 pts 8 games left</p>
<p>Angel REESE leads by 46.0 pts (includes live scoring)<br /> Finalized only &rarr; Brenda Frese Fan Club: 254.0 | Angel REESE: 409.0</p>
<p>══════════════════════════════════════════════════════════</p>
<p><br />════════════════════════════════════════════════════════════<br /> Team 1: Kim Mulkey's Rejects<br /> Week 2 (2026-05-18 &rarr; 2026-05-24)<br /> Today: 2026-05-23 | Days left: 2<br />════════════════════════════════════════════════════════════</p>
<p>(Days already played: 2026-05-18, 2026-05-19, 2026-05-20, 2026-05-21, 2026-05-22)</p>
<p>MAX STARTABLE GAMES REMAINING: 6 (cap: 12)</p>
<p>2026-05-23 ◀ today<br /> [F/C ] Bridget Carleton (POR)<br /> 2026-05-24<br /> [G ] Azzi Fudd (DAL)<br /> [G ] Kahleah Copper (PHX)<br /> [F/C ] Breanna Stewart (NY)<br /> [F/C ] Nneka Ogwumike (LA)<br /> [UTIL] Jewell Loyd (LV)</p>
<p><br />════════════════════════════════════════════════════════════<br /> Team 2: Shyanne Sellars pls come back<br /> Week 2 (2026-05-18 &rarr; 2026-05-24)<br /> Today: 2026-05-23 | Days left: 2<br />════════════════════════════════════════════════════════════</p>
<p>(Days already played: 2026-05-18, 2026-05-19, 2026-05-20, 2026-05-21, 2026-05-22)</p>
<p>MAX STARTABLE GAMES REMAINING: 8 (cap: 12)</p>
<p>2026-05-23 ◀ today<br /> [G ] Skylar Diggins (CHI)<br /> [G ] Kayla McBride (MIN)<br /> [F/C ] Nia Coffey (MIN)<br /> [UTIL] Carla Leite (POR)<br /> 2026-05-24<br /> [G ] Rhyne Howard (ATL)<br /> [G ] Jordin Canada (ATL)<br /> [F/C ] Shakira Austin (WSH)<br /> [UTIL] Natisha Hiedeman (SEA)</p>
<p><br />════════════════════════════════════════════════════════════<br /> Team 3: Quarterzip Memorial Team<br /> Week 2 (2026-05-18 &rarr; 2026-05-24)<br /> Today: 2026-05-23 | Days left: 2<br />════════════════════════════════════════════════════════════</p>
<p>(Days already played: 2026-05-18, 2026-05-19, 2026-05-20, 2026-05-21, 2026-05-22)</p>
<p>MAX STARTABLE GAMES REMAINING: 9 (cap: 12)</p>
<p>2026-05-23 ◀ today<br /> [G ] Olivia Miles (MIN)<br /> [G ] DiJonai Carrington (CHI)<br /> [F/C ] Aneesah Morrow (CON)<br /> [F/C ] Elizabeth Williams (CHI)<br /> 2026-05-24<br /> [G ] Sonia Citron (WSH)<br /> [G ] Chelsea Gray (LV)<br /> [F/C ] Angel Reese (ATL)<br /> [F/C ] Alanna Smith (DAL)<br /> [F/C ] Cameron Brink (LA)</p>
<p><br />════════════════════════════════════════════════════════════<br /> Team 4: Angel REESE<br /> Week 2 (2026-05-18 &rarr; 2026-05-24)<br /> Today: 2026-05-23 | Days left: 2<br />════════════════════════════════════════════════════════════</p>
<p>(Days already played: 2026-05-18, 2026-05-19, 2026-05-20, 2026-05-21, 2026-05-22)</p>
<p>MAX STARTABLE GAMES REMAINING: 8 (cap: 12)</p>
<p>2026-05-23 ◀ today<br /> [G ] Flau'jae Johnson (SEA)<br /> [G ] Brittney Sykes (TOR)<br /> [F/C ] Aaliyah Edwards (CON)<br /> 2026-05-24<br /> [G ] Paige Bueckers (DAL)<br /> [G ] Flau'jae Johnson (SEA)<br /> [F/C ] Jonquel Jones (NY)<br /> [F/C ] DeWanna Bonner (PHX)<br /> [F/C ] NaLyssa Smith (LV)</p>
<p><br />════════════════════════════════════════════════════════════<br /> Team 6: Stud bud enthusiast<br /> Week 2 (2026-05-18 &rarr; 2026-05-24)<br /> Today: 2026-05-23 | Days left: 2<br />════════════════════════════════════════════════════════════</p>
<p>(Days already played: 2026-05-18, 2026-05-19, 2026-05-20, 2026-05-21, 2026-05-22)</p>
<p>MAX STARTABLE GAMES REMAINING: 7 (cap: 12)</p>
<p>2026-05-23 ◀ today<br /> [G ] Courtney Williams (MIN)<br /> [G ] Jacy Sheldon (CHI)<br /> 2026-05-24<br /> [G ] Allisha Gray (ATL)<br /> [F/C ] Lauren Betts (WSH)<br /> [F/C ] Betnijah Laney-Hamilton (NY)<br /> [F/C ] Jessica Shepard (DAL)<br /> [UTIL] Cheyenne Parker-Tyus (LV)</p>
<p><br />════════════════════════════════════════════════════════════<br /> Team 7: Brenda Frese Fan Club<br /> Week 2 (2026-05-18 &rarr; 2026-05-24)<br /> Today: 2026-05-23 | Days left: 2<br />════════════════════════════════════════════════════════════</p>
<p>(Days already played: 2026-05-18, 2026-05-19, 2026-05-20, 2026-05-21, 2026-05-22)</p>
<p>MAX STARTABLE GAMES REMAINING: 8 (cap: 12)</p>
<p>2026-05-23 ◀ today<br /> [G ] Kiki Rice (TOR)<br /> [G ] Gabriela Jaquez (CHI)<br /> [F/C ] Natasha Howard (MIN)<br /> [F/C ] Emily Engstler (POR)<br /> 2026-05-24<br /> [G ] Jackie Young (LV)<br /> [G ] Marine Johannes (NY)<br /> [F/C ] Alyssa Thomas (PHX)<br /> [F/C ] Satou Sabally (NY)</p>
<p><br />════════════════════════════════════════════════════════════<br /> Team 8: Tatum Tots Top Team<br /> Week 2 (2026-05-18 &rarr; 2026-05-24)<br /> Today: 2026-05-23 | Days left: 2<br />════════════════════════════════════════════════════════════</p>
<p>(Days already played: 2026-05-18, 2026-05-19, 2026-05-20, 2026-05-21, 2026-05-22)</p>
<p>MAX STARTABLE GAMES REMAINING: 10 (cap: 12)</p>
<p>2026-05-23 ◀ today<br /> [G ] Marina Mabrey (TOR)<br /> [G ] Natasha Cloud (CHI)<br /> [F/C ] Napheesa Collier (MIN)<br /> [F/C ] Dominique Malonga (SEA)<br /> [UTIL] Julie Allemand (TOR)<br /> 2026-05-24<br /> [G ] Arike Ogunbowale (DAL)<br /> [F/C ] A'ja Wilson (LV)<br /> [F/C ] Dominique Malonga (SEA)<br /> [F/C ] Brionna Jones (ATL)<br /> [UTIL] Leonie Fiebich (NY)</p>
<p><br />════════════════════════════════════════════════════════════<br /> Team 9: Jake's Scary Team<br /> Week 2 (2026-05-18 &rarr; 2026-05-24)<br /> Today: 2026-05-23 | Days left: 2<br />════════════════════════════════════════════════════════════</p>
<p>(Days already played: 2026-05-18, 2026-05-19, 2026-05-20, 2026-05-21, 2026-05-22)</p>
<p>MAX STARTABLE GAMES REMAINING: 9 (cap: 12)</p>
<p>2026-05-23 ◀ today<br /> [G ] Jade Melbourne (SEA)<br /> [F/C ] Kamilla Cardoso (CHI)<br /> [F/C ] Brittney Griner (CON)<br /> 2026-05-24<br /> [G ] Kelsey Plum (LA)<br /> [G ] Jade Melbourne (SEA)<br /> [F/C ] Dearica Hamby (LA)<br /> [F/C ] Kiki Iriafen (WSH)<br /> [F/C ] Natasha Mack (PHX)<br /> [UTIL] Pauline Astier (NY)</p>
    """
    #seeds = compare_bracket.gen()
    #html = html + "<br>" + seeds # + styler.to_html()
    path = paths.WEB_HOME
    path.parent.mkdir(parents=True, exist_ok=True)

    html = html_util.add_front_matter(html, "GordStats Home")

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
        print(f"Wrote to: {path}")
