import scraper
import os
import utils

def fmt_team(team, rank):
    if rank == "N/A":
        return team
    return f"<strong>#{rank}</strong> {team}"

def meta_class(val):
    val = str(val).lower()

    if ":" in val:
        return "meta meta-upcoming"  # GREEN
    if "," not in val:
        return "meta meta-final"  # GREEN
    return "meta meta-live"  # scheduled


def fmt_team_live(ap_rank, team, score, model_rank):
    if ap_rank == "":
        ap_rank_html = ""
    else:
        ap_rank_html = f" <strong> ({ap_rank})</strong>"

    if model_rank == "":
        model_rank_html = ""
    else:
        model_rank_html = f"<strong> #{model_rank}</strong>"
    html = model_rank_html + ' ' + ap_rank_html + ' ' + team 
    return html

def rank_formatter(model, team, ap):
    if model == "":
        model_html = ""
    else: 
        model_html = f" <strong>#{model}</strong>"

    if ap == "":
        ap_html = ""
    else: 
        ap_html = f" <strong>({ap})</strong> "

    return ap_html + team + model_html

def format_result(res):
    if res:
        return 'winner'
    elif res == False:
        return 'loser'
    else:
        return ''
    
def fmt_team_logo(team):
    # image name -> url -> format
    master = scraper.getMasterTeams()
    url = ''
    try:
        s_exploded = master["names"].explode()
        boolean_mask_exploded = s_exploded == team
        boolean_mask_original = boolean_mask_exploded.groupby(level=0).any()
        df_result = master[boolean_mask_original]
        if df_result.empty:
            print(f'render_teams fmt_team_web :: Could not find match in master teams for: {team}')
            url = '/assets/images/default.png' 
        else:
            names = list(df_result.names)[0]
            img_path = utils.get_path('docs/assets/images')
            files = os.listdir(img_path)
            files_strip = [x[:-4] for x in files]
            master['path'] = ''
            for index, file in enumerate(files_strip):
                if file in names:
                    link = f'/assets/images/{file}' 
                    return f'<img src="{link}" class="team-logo" >'
    except:
        print(f'render_teams fmt_team_web :: Error in function for: {team}')
        url = '/assets/images/default.png' 

    return url