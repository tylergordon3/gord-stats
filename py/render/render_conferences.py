import pandas as pd
import html_util
import utils
import html_builder as htmb

def filter(df, conf):
    if conf not in pd.unique(df['Conf']): return
    return df[df['Conf'] == conf]

def main(df):
    confs = pd.unique(df['Conf'])
    conf_dict = dict.fromkeys(confs)

    for key in conf_dict.keys():
        conf_df = filter(df, key)
        conf_dict[key] = conf_df

    html = '''
    <div class="change-toggle global-toggle">
    <button data-period="7d">1 Week</button>
    <button data-period="14d" class="active">2 Weeks</button>
    <button data-period="1mo">1 Month</button>
    </div>
    '''
    for k, v in conf_dict.items():
        styler = html_util.style_bracketology(v, df)
        html += f'<h3>{k}</h3>'
        html += '<div class="table-container">'
        html += styler.to_html()
        html += "</div>"
    html += "<script src='/assets/js/rank-toggle.js'></script>"
    path = utils.get_path(f"docs/men/conference.html")
    html = htmb.add_front_matter(html, f"Conferences")
    
    with open(path, "w") as f:
        f.write(html)
        print(f"Wrote to: {path}")
        
    path = utils.get_path(f"docs/women/conference.html")
    html_w = 'Not available yet.'
    html_w = htmb.add_front_matter(html_w, f"Conferences")
    with open(path, "w") as f:
        f.write(html_w)
        print(f"Wrote to: {path}")

    return

