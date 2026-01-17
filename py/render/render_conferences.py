import pandas as pd
import html_util
import utils
import html_builder as htmb

def filter(df, conf):
    if conf not in pd.unique(df['Conf']): return
    return df[df['Conf'] == conf]

def main(df, gender):
    confs = pd.unique(df['Conf'])
    conf_dict = dict.fromkeys(confs)

    for key in conf_dict.keys():
        conf_df = filter(df, key)
        conf_dict[key] = conf_df

    html = '''
    <div class="filter-bar">
    {% include global-toggle.html %}

    <div class="conference-filter">
    <label for="conference-select"><strong>Conference:</strong></label>
    <select id="conference-select">
    <option value="ALL">All Conferences</option>
    </select>
    </div>
    </div>
    '''
    for k, v in conf_dict.items():
        styler = html_util.style_bracketology(
            df=v,
            gender=gender,
            original=df,
            conference=k)
        
        html += '<div class="table-container">'
        html += styler.to_html()
        html += "</div>"
    html += "<script src='/assets/js/rank-toggle.js'></script>"
    html += "<script src='/assets/js/conf-toggle.js'></script>"
    if gender == "M":
        path = utils.get_path(f"docs/men/conference.html")
    elif gender == "W":
        path = utils.get_path(f"docs/women/conference.html")
    html = htmb.add_front_matter(html, f"Conferences")
    
    with open(path, "w") as f:
        f.write(html)
        print(f"Wrote to: {path}")

