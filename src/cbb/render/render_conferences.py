import pandas as pd

from gordstats import frontmatter
from cbb import paths
from cbb import html_util
from cbb.scrape import bpi


def filter(df, conf):
    if conf not in pd.unique(df["Conf"]):
        return
    return df[df["Conf"] == conf]


def main(df, gender):
    confs = pd.unique(df["Conf"])
    conf_dict = dict.fromkeys(confs)

    for key in conf_dict.keys():
        conf_df = filter(df, key).copy()
        conf_dict[key] = conf_df

    html = """
    <div class="filter-bar">
    """ + frontmatter.liquid("{% include global-toggle.html %}") + """

    <div class="conference-filter">
    <label for="conference-select"><strong>Conference:</strong></label>
    <select id="conference-select">
    <option value="ALL">All Conferences</option>
    </select>
    </div>
    </div>
    """

    # The tables shipped with no key: Pwr/Gord, Ovr and the Δ arrows were
    # unexplained everywhere on the site. Column name differs by gender.
    rating = "Pwr" if gender == "M" else "Gord"
    # Conference records come from ESPN's men's BPI table, and the women's page
    # was reading it too: UConn's women (34-0) showed the men's 17-3. There is
    # no women's source wired in yet, so their page goes without the column.
    # And none until ESPN publishes this season's table: last season's
    # records read as this season's until December otherwise.
    conf_record_dict = bpi.get_conf_records() if gender == "M" else {}
    records = bool(conf_record_dict)
    html += (
        "<p class='week-meta'>"
        + ("<strong>Conf Record</strong> is the record in conference play; " if records else "")
        + f"<strong>{rating}</strong> is the model's power rating (0&ndash;1, higher "
        f"is better); <strong>Ovr</strong> is overall rank with projected tournament seed; "
        f"<strong>&Delta;</strong> is movement in overall rank over the selected window "
        f"(&uarr;/&darr; places, <strong>NR</strong> = newly ranked, "
        f"<strong>-</strong> = no change).</p>"
    )

    for k, v in conf_dict.items():
        if records:
            # .get: a team BPI does not list (a school new to D1) is a blank,
            # not a KeyError that stops the whole page.
            v['Conf Record'] = v["Team"].map(lambda t: conf_record_dict.get(t, ""))
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

    html = frontmatter.add_front_matter(html, "Conferences")

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
        print(f"Wrote to: {path}")