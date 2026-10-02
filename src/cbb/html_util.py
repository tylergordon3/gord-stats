import re

import pandas as pd

from cbb import teams

DAYTON_SLOTS = {42, 43, 44, 45, 64, 65, 66, 67}
FF_BADGE = '<span class="ff-badge" title="First Four (Dayton)">FF</span>'


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


#: The rank-movement columns, named once.
MOVE_COLS = ["Δ 1d", "Δ 7d", "Δ 14d", "Δ 1mo"]


def _arrow_class(val) -> str:
    """Which way a team moved, as a class rather than a colour.

    Named `rk-*` rather than `mv-*`: gordstats.rankmoves already owns those
    for the small arrow spans it puts inside a cell, at 12px and bold, and
    reusing them here would resize every cell in the column.

    It used to return `color: green` / `color: red` / `color: black` inline.
    Inline means one colour for both themes, and these cells have no fill of
    their own - they sit on the table's own background, which is white by day
    and navy at night, so black was about to become invisible. The classes are
    styled per theme in custom.css (`.rk-up`, `.rk-down`, `.rk-flat`).
    """
    if val == "NR" or val == "-":
        return "rk-flat"
    try:
        moved = int(val)
    except (TypeError, ValueError):
        return "rk-flat"
    return "rk-up" if moved > 0 else "rk-down" if moved < 0 else "rk-flat"


def _arrow_classes(df, columns) -> pd.DataFrame:
    """A class per cell for `Styler.set_td_classes`, empty outside `columns`."""
    out = pd.DataFrame("", index=df.index, columns=df.columns)
    for col in columns:
        if col in df.columns:
            out[col] = df[col].map(_arrow_class)
    return out


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


def image_formatter(url, alt=""):
    """
    Creates html for team logo - the one tag every CBB table uses.

    Lazy and sized: a conference page lists all 365 teams, and loaded eagerly
    with no size every logo was fetched up front and the rows jumped as they
    landed. `alt` is empty by default because the logo sits beside the team's
    name - a screen reader should read the name once, not a filename first.

    :param url: Path to team logo
    :param alt: Text for the image when it is the only label
    :return: Logo HTML
    :rtype: str
    """
    if not url:
        return ""
    alt = str(alt).replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")
    return (f'<img src="{url}" class="team-logo" loading="lazy" decoding="async" '
            f'width="40" height="40" alt="{alt}">')


def logo_urls() -> dict:
    """Every name master.json knows a team by -> that team's logo URL.

    Names more than one school answers to ("Wildcats", "Cougars") are left
    out rather than handed to whichever school came first.
    """
    master = teams.getTeams()
    urls, clash = {}, set()
    for names, path in zip(master["names"], master["path"]):
        for name in names:
            url = "/assets/images/" + path
            if urls.setdefault(name, url) != url:
                clash.add(name)
    for name in clash:
        del urls[name]
    return urls


def strip_team_html(row):
    pattern = r">\s*([^<(]+)"

    matches = re.findall(pattern, row)

    if matches:
        team = matches[0].strip()
    else:
        # fallback: strip HTML + record
        team = row.split(">")[-1].split(" (")[0].strip()
    return team


def format_team_cell(x, dayton_set):
    badge = FF_BADGE if x.BracketRank in dayton_set else ""
    return f"{image_formatter(x.Logo)} {teams.getTeamNickname(x.Team)} ({x.Record}) {badge}"


def style_bracketology(df, gender="M", original=None, conference=None):
    df = df.copy()
    df["BracketRank"] = range(len(df))
    # By name, for both leagues. The men's side used to take each row's index
    # label as a row number into master.json, which is right only while the
    # field is exactly master's 365 teams in master's order: one school leaving
    # D1 shifted 108 logos onto the wrong teams. The women's side looked up by
    # name but crashed on a team it could not find.
    logos = logo_urls()
    df["Logo"] = df["Team"].map(logos).fillna("")
    if gender == "W":
        output_cols = ["Team", "Conf", "Gord", "Ovr", "Δ 1d", "Δ 7d", "Δ 14d", "Δ 1mo"]
    else:
        output_cols = ["Team", "Conf", "Pwr", "Ovr", "Δ 1d", "Δ 7d", "Δ 14d", "Δ 1mo"]
    df["Team"] = df.apply(lambda x: format_team_cell(x, DAYTON_SLOTS), axis=1)

    team_index = df["Team"].apply(lambda x: strip_team_html(x))

    conf_champ_dict = pd.Series(df.ConfChamp.values, index=team_index).to_dict()
    bids_dict = pd.Series(df.Bid.values, index=team_index).to_dict()

    if conference and "Conf Record" in df.columns:
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
            # The rating column is "Gord" here ("Pwr" on the men's side); an
            # earlier formatter targeted "Rtg", a column that never existed,
            # so the rating rendered as a raw 6-decimal float.
            .format({"Gord": "{:.3f}"})
            .format(_format_arrow, subset=MOVE_COLS)
            .set_td_classes(_arrow_classes(df, MOVE_COLS))
            .set_table_attributes(table_attr)
            .apply(lambda x: bold_row(x, conf_champ_dict, bids_dict), axis=1)
        )
    else:
        styler = (
            df.style.hide(axis="index")
            .format({"Pwr": "{:.3f}"})  # was "Rtg", a column that never existed
            .format(_format_arrow, subset=MOVE_COLS)
            .set_td_classes(_arrow_classes(df, MOVE_COLS))
            .set_table_attributes(table_attr)
            .apply(lambda x: bold_row(x, conf_champ_dict, bids_dict), axis=1)
        )

    return styler
