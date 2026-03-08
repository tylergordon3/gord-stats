import re

import pandas as pd

from cbb import scraper
from cbb.lib import teams


def _format_arrow(val):
    """
    Format arrow for change since last week

    :param val: Change since previous week
    :type val: int
    :return: Correspondng arrow with value
    :rtype: str
    """
    if (val == "NR") | (val == "-"):
        return val
    elif val == "NaN":
        return "NR"
    return (
        f"{'↑' if int(val) > 0 else '↓'} {abs(val):.0f}"
        if int(val) != 0
        else f"{val:.0f}"
    )


def _color_arrow(val):
    """
    Colors arrow based on direction

    :param val: Change since previous week
    :type val: int
    :return: Color of arrow
    """
    if (val == "NR") | (val == "-"):
        return "color: black"

    return (
        "color: green"
        if int(val) > 0
        else "color: red" if int(val) < 0 else "color: black"
    )


def bold_row(row, conf_champ_dict, bid_dict):
    """
    Bolds row if team is projected conference winner

    :param row: Row of main dataframe
    :type row: Series
    :param conf_champ_dict: Dict with all conference champs
    :type conf_champ_dict: dict
    """
    pattern = r">\s*([^<(]+)"

    matches = re.findall(pattern, row["Team"])

    if matches:
        team = matches[0].strip()
    else:
        # fallback: strip HTML + record
        team = row["Team"].split(">")[-1].split(" (")[0].strip()

    val = conf_champ_dict.get(team, False)
    bid = bid_dict.get(team, False)
    
    if bid:
        ret = ["font-weight: bold; background:#e8f7e8"] * len(row)
        return ret
    elif val:
        ret = ["font-weight: bold"] * len(row)
        ret[2] = "font-weight: normal"
        ret[3] = "font-weight: normal"
        return ret
    else:
        return ["font-weight: normal"] * len(row)


def image_formatter(url):
    """
    Creates html for team logo

    :param url: Path to team logo
    :return: Logo HTML
    :rtype: str
    """
    return f'<img src="{url}" class="team-logo" >'


def getUrl(x, save_df, master, gender="M"):
    """
    Finds path/url for team logo

    :param x: Row for current team
    :type x: Series
    :param save_df: Predictions DataFrame with all D1 teams
    :type save_df: DataFrame
    :param master: Master Team Name DataFrame
    :type master: DataFrame
    :return: Link/Path to logo
    :rtype: str
    """

    if gender == "M":
        saved_index = list(save_df[save_df["Team"] == x["Team"]].index)[0]
    elif gender == "W":
        saved_index = list(save_df[save_df["Team"] == x["Team"]].index)[0]

    link = "/assets/images/" + master.at[saved_index, "path"]

    return link


def strip_team_html(row):
    pattern = r">\s*([^<(]+)"

    matches = re.findall(pattern, row)

    if matches:
        team = matches[0].strip()
    else:
        # fallback: strip HTML + record
        team = row.split(">")[-1].split(" (")[0].strip()
    return team


def style_bracketology(df, gender="M", original=None, conference=None):
    master = scraper.getMasterTeams()
    df = df.copy()
    if gender == "W":
        output_cols = ["Team", "Conf", "Gord", "Ovr", "Δ 1d", "Δ 7d", "Δ 14d", "Δ 1mo"]
        df["Logo"] = df.apply(
            lambda x: "/assets/images/" + scraper.get_image_name(x["Team"]), axis=1
        )
        df["Team"] = df.apply(
            lambda x: f"{image_formatter(x.Logo)} {teams.getTeamNickname(x.Team)} ({x.Record})",
            axis=1,
        )
    else:
        output_cols = ["Team", "Conf", "Pwr", "Ovr", "Δ 1d", "Δ 7d", "Δ 14d", "Δ 1mo"]
        df["Logo"] = df.apply(lambda x: getUrl(x, df, master, "M"), axis=1)
        df["Team"] = df.apply(
            lambda x: f"{image_formatter(x.Logo)} {teams.getTeamNickname(x.Team)} ({x.Record})",
            axis=1,
        )

    team_index = df["Team"].apply(lambda x: strip_team_html(x))

    conf_champ_dict = pd.Series(df.ConfChamp.values, index=team_index).to_dict()
    bids_dict = pd.Series(df.Bid.values, index=team_index).to_dict()
    
    if conference:
        output_cols.insert(2, "Conf Record")
    df = df[output_cols]

    # Build table attributes
    classes = ["sticky-table", "rank-table"]
    attrs = []

    if conference:
        attrs.append(f'data-conference="{conference}"')
        df = df.drop(columns=["Conf"])

    table_attr = f'class="{" ".join(classes)}"'
    if attrs:
        table_attr += " " + " ".join(attrs)

    if gender == "W":
        styler = (
            df.style.hide(axis="index")
            .format(_format_arrow, subset=["Δ 1d", "Δ 7d", "Δ 14d", "Δ 1mo"])
            .map(_color_arrow, subset=["Δ 1d", "Δ 7d", "Δ 14d", "Δ 1mo"])
            .set_table_attributes(table_attr)
            .apply(lambda x: bold_row(x, conf_champ_dict, bids_dict), axis=1)
        )
    else:
        styler = (
            df.style.hide(axis="index")
            .format({"Rtg": "{:.4f}"})
            .format(_format_arrow, subset=["Δ 1d", "Δ 7d", "Δ 14d", "Δ 1mo"])
            .map(_color_arrow, subset=["Δ 1d", "Δ 7d", "Δ 14d", "Δ 1mo"])
            .set_table_attributes(table_attr)
            .apply(lambda x: bold_row(x, conf_champ_dict, bids_dict), axis=1)
        )

    return styler


def add_front_matter(html, title, opt_date=None):
    fm = f"""---
layout: default
title: {title}
---
"""
    header = f"<h1>{title}</h1>"
    if opt_date:
        header += f"<h3>{opt_date} Prediction</h3>"
    new_html = fm + header + html
    return new_html.lstrip()
