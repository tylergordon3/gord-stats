import pandas as pd

from cbb import html_util, utils
from cbb.lib import paths


def filter(df, conf):
    if conf not in pd.unique(df["Conf"]):
        return
    return df[df["Conf"] == conf]


def main(df, gender):
    confs = pd.unique(df["Conf"])
    conf_dict = dict.fromkeys(confs)

    for key in conf_dict.keys():
        conf_df = filter(df, key)
        conf_dict[key] = conf_df

    html = """
    <div class="filter-bar">
    {% include global-toggle.html %}

    <div class="conference-filter">
    <label for="conference-select"><strong>Conference:</strong></label>
    <select id="conference-select">
    <option value="ALL">All Conferences</option>
    </select>
    </div>
    </div>
    """

    for k, v in conf_dict.items():
        styler = html_util.style_bracketology(
            df=v,
            gender=gender,
            original=df,
            conference=k,
        )

        html += '<div class="table-container">'
        html += styler.to_html()
        html += "</div>"

    html += "<script src='/assets/js/rank-toggle.js'></script>"
    html += "<script src='/assets/js/conf-toggle.js'></script>"

    # -------------------
    # Corrected Path Logic
    # -------------------

    if gender == "M":
        path = paths.WEB_M_CONF
    elif gender == "W":
        path = paths.WEB_W_CONF
    else:
        raise ValueError("Invalid gender. Must be 'M' or 'W'.")

    path.parent.mkdir(parents=True, exist_ok=True)

    html = html_util.add_front_matter(html, "Conferences")

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
        print(f"Wrote to: {path}")