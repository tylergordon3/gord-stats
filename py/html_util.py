import re
import scraper
import pandas as pd

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


def bold_row(row, conf_champ_dict):
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

    if val:
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


def getUrl(x, save_df, master, gender='M'):
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
    if gender == 'M':
        saved_index = list(save_df[save_df["Team"] == x["Team"]].index)[0]
    elif gender == 'W':
        saved_index = list(save_df[save_df["Team"] == x["Team"]]['Index'])[0]
    link = "/assets/images/" + master.at[saved_index, "path"]
    return link

def style_bracketology(df, original=None):
    master = scraper.getMasterTeams()

    output_cols = ['Team', 'Conf', 'Kenpom', 'Torvik', 'Rtg', 'Ovr', 'Δ 7d', 'Δ 14d', 'Δ 1mo']
    # need_cols = ['Team', 'Conf', 'Kenpom', 'Torvik', 'Rtg', 'Ovr', 'Δ 7d', 'Δ 14d', 'Δ 1mo', 'Kenpom Rank', 'Torvik Rank', 'ConfChamp']

    df["Logo"] = df.apply(lambda x: getUrl(x, df, master, 'M'), axis=1)
    df["Team"] = df.apply(lambda x: image_formatter(x.Logo) + x.Team, axis=1)

    if original is not None:
        copy = original.copy()
    else:
        copy = df.copy()

    conf_champ_dict = pd.Series(df.ConfChamp.values, index=df.Team).to_dict()

    df = df[output_cols]
    
    styler = (
        df.style.hide(axis="index")
        .format({"Rtg": "{:.4f}"})
        .format(_format_arrow, subset=["Δ 7d", "Δ 14d", "Δ 1mo"])
        .map(_color_arrow, subset=["Δ 7d", "Δ 14d", "Δ 1mo"])
        .set_table_attributes('class="sticky-table rank-table"')
        .background_gradient(
            subset=["Kenpom"],
            cmap="cividis", 
            gmap=copy['Kenpom Rank'],
        )
        .background_gradient(
            subset=["Torvik"], cmap="cividis", gmap=copy['Torvik Rank']
        )
        .apply(lambda x: bold_row(x, conf_champ_dict), axis=1)
    )

    return styler

