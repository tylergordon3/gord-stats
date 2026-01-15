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

    html = ''
    for k, v in conf_dict.items():
        styler = html_util.style_bracketology(v, df)
        html += f'<h3>{k}</h3>'
        html += styler.to_html()

    path = utils.get_path(f"docs/conference.html")
    html = htmb.add_front_matter(html, f"Conferences")
    with open(path, "w") as f:
        f.write(html)
        print(f"Wrote to: {path}")

    return

