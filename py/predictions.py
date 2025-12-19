import utils
import pandas as pd
import numpy as np
import json
import change
import datetime
from sklearn import preprocessing
import html_builder as htmb
from pytz import timezone
import scraper
import re
import matplotlib.pyplot as plt
import plotly.express as px
from collections import defaultdict

def seed_helper(x):
    """
    Calculates would-be seed based on rank

    :param x: DataFrame column containing overall rank
    :type x: Series
    :return: List with seed for each team
    :rtype: List[int]
    """
    current_team_index = 0
    seed = []
    seed_num = 1
    while current_team_index < len(x):
        if seed_num == 11 or seed_num == 16:
            num_teams_in_seed = 6
        else:
            num_teams_in_seed = 4
        seed += np.repeat(seed_num, num_teams_in_seed).tolist()
        current_team_index += num_teams_in_seed
        seed_num += 1
    return seed


def clean_teams(df, kenpom_bool=False):
    """
    Cleans Torvik team names

    :param df: Torvik data
    :type df: DataFrame
    :param kenpom_bool: Bool for if Kenpom
    :type kenpom_bool: bool
    :return: Torvik data with clean names
    :rtype: DataFrame
    """
    dict = {
        "SIU Edwardsville": "SIUE",
        "Cal St. Northridge": "CSUN",
        "McNeese St.": "McNeese",
        "Nicholls St.": "Nicholls",
        "Southeast Missouri": "SEMO",
        "Southeast Missouri St.": "SEMO",
        "Kansas City": "UMKC",
    }

    def strip(team):
        for i, char in enumerate(team):
            if char == "(":
                return team[:i]
            if team[i : i + 3] == "vs.":
                return team[:i]
        return team

    if kenpom_bool:
        df["Team"] = df["Team"].replace(dict)
        return df

    df["Conf"] = df["Conf"].replace("Pat", "PL")
    df["Team"] = df["Team"].apply(lambda x: strip(x))
    df["Team"] = df["Team"].replace(dict)
    return df


def calcWkDelta(row):
    """
    Calculate rank difference over last week

    :param row: Row with team data
    :type row: Series
    :return: Row with updated vs Last Week
    :rtype: Series
    """
    if row["vs Last Wk"] != "NR":
        row["vs Last Wk"] = int(row["vs Last Wk"]) - row["Overall"]
        if row["vs Last Wk"] == 0:
            row["vs Last Wk"] = "-"
    return row["vs Last Wk"]


def stars(count, max_count=3):
    """
    Docstring for stars

    :param count: Number of models team is in
    :type count: int
    :param max_count: Max number of models possible
    :type max_count: int
    :return: Formatted string with stars to represent # of models
    :rtype: str
    """
    filled = "★" * count
    empty = "☆" * (max_count - count)
    return f"({filled}{empty})"


def predict_model(model, fitted_data):
    """
    Predict on data

    :param model: Model read from pkl
    :param fitted_data: Data set fitted
    :return: Predictions
    """
    return model.predict(fitted_data)


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
    try:
        pattern = r"(?:[^>]+?>)(.*)"
        check = re.findall(pattern, row["Team"])
        val = conf_champ_dict[check[0]]
    except:
        val = conf_champ_dict[row["Team"]]
    if val:
        ret = [f"font-weight: bold"] * len(row)
        ret[2] = "font-weight: normal"
        ret[3] = "font-weight: normal"
        return ret
    else:
        return [f"font-weight: normal"] * len(row)


def image_formatter(url):
    """
    Creates html for team logo

    :param url: Path to team logo
    :return: Logo HTML
    :rtype: str
    """
    return f'<img src="{url}" class="team-logo" >'


def getUrl(x, save_df, master):
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
    save = list(save_df[save_df["Team"] == x["Team"]].index)[0]
    link = "/assets/images/" + master.at[save, "path"]
    return link


def predByConf(df):
    print(df)


def predict_w(date):
    randomForest = utils.read_from_pickle("wtor_forest")
    decisionTree = utils.read_from_pickle("wtor_dt")
    supportVC = utils.read_from_pickle("wtor_svc")

    torvik_path = utils.get_recent_data(date, 1)
    with open(torvik_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    torvik_data = pd.DataFrame(data["rows"], columns=data["headers"])
    torvik_data = clean_teams(torvik_data)

    torvik_today = torvik_data.drop(
        columns=[
            "Barthag",
            "WAB",
            "Team",
            "Conf",
            "Rec",
            "G",
            "Rk",
            "FTR",
            "3PR",
            "3PRD",
            "AdjOE",
            "AdjDE",
            "TORD",
            "FTR",
            "FTRD",
            "3P%D",
            "Adj T.",
        ]
    )

    scaler = preprocessing.StandardScaler()
    x_predict_torvik = scaler.fit_transform(torvik_today)

    # Torvik Model Predictions
    torvik_data["RF"] = predict_model(randomForest, x_predict_torvik)
    torvik_data["DT"] = predict_model(decisionTree, x_predict_torvik)
    torvik_data["SVC"] = predict_model(supportVC, x_predict_torvik)

    torvik_data["Sum"] = torvik_data[["RF", "DT", "SVC"]].sum(1)
    df_torvik = torvik_data[["Rk", "Team", "Conf", "RF", "DT", "SVC", "Sum"]].copy()

    df_torvik_filter = df_torvik.copy()
    df_torvik_filter = df_torvik_filter.drop(columns=["Sum"])
    df_torvik["Rk"] = pd.to_numeric(df_torvik["Rk"])
    df_torvik["GordScore"] = (10 * df_torvik["Sum"]) + (80 - df_torvik["Rk"])

    df_torvik = df_torvik.sort_values("GordScore", ascending=False)
    df_torvik = df_torvik.drop(columns=["RF", "SVC", "DT"])
    df_torvik = df_torvik.rename(
        columns={"Rk": "Torvik Rank", "Sum": "# Models Torvik"}
    )

    main64 = df_torvik.copy()
    # Saving to another df for schedule home
    save_df = df_torvik.copy()
    save_df = save_df.sort_values(by="GordScore", ascending=False)
    save_df["Overall"] = range(1, len(save_df) + 1)

    bestByConf = main64.loc[main64.groupby(by="Conf")["GordScore"].idxmax()]
    main64 = main64.drop(index=bestByConf.index)
    main64 = main64.head(68 - len(bestByConf))
    main64["ConfChamp"] = 0
    bestByConf["ConfChamp"] = 1
    main64 = pd.concat([main64, bestByConf])
    main64 = main64.sort_values(by="GordScore", ascending=False)
    main64["Overall"] = range(1, len(main64) + 1)
    last_week = change.change_w(date)
    main64 = pd.merge(main64, last_week, "left", "Team")

    main64["vs Last Wk"] = main64["vs Last Wk"].fillna("NR")
    main64["vs Last Wk"] = main64.apply(lambda row: calcWkDelta(row), axis=1)

    main64["Seed"] = seed_helper(main64["Overall"])
    main64["Overall"] = (
        "#"
        + main64["Overall"].astype(str)
        + " (Seed "
        + main64["Seed"].astype(str)
        + ")"
    )

    main64["Torvik Rank"] = main64["Torvik Rank"].astype(int)
    main64["Torvik"] = (
        main64["Torvik Rank"].astype(str) + " " + main64["# Models Torvik"].apply(stars)
    )

    styler = main64[["Torvik", "GordScore", "Overall", "vs Last Wk"]].style
    conf_champ_dict = pd.Series(main64.ConfChamp.values, index=main64.Team).to_dict()
    df = main64.drop(columns=["Torvik Rank", "# Models Torvik", "Seed", "ConfChamp"])
    df = df[["Team", "Conf", "Torvik", "GordScore", "Overall", "vs Last Wk"]]

    styler = (
        df.style.hide(axis="index")
        .format({"GordScore": "{:.1f}"})
        .format(_format_arrow, subset=["vs Last Wk"])
        .applymap(_color_arrow, subset=["vs Last Wk"])
        .set_table_attributes('class="sticky-table"')
        .background_gradient(
            subset=["Torvik"], cmap="cividis", gmap=main64["Torvik Rank"]
        )
        .apply(lambda x: bold_row(x, conf_champ_dict), axis=1)
    )
    tz = timezone("EST")
    time_obj = datetime.datetime.now(tz)
    time = time_obj.strftime("Last Update: %A %m/%d/%y %I:%M %p")
    df_html = f"""<p>{time}</p>
        <div class="table-container">
        {styler.to_html()}
        <div>"""
    path = utils.get_path(f"docs/women/predict_{date}.html")
    html = htmb.add_front_matter(df_html, f"NCAAW Prediction- {date}")
    with open(path, "w") as f:
        f.write(html)
        print(f"Wrote to: {path} for {date}")
    return save_df


def predict(date):
    randomForest = utils.read_from_pickle("mtor_forest")
    decisionTree = utils.read_from_pickle("mtor_dt")
    supportVC = utils.read_from_pickle("mtor_svc")

    randomForest_kenpom = utils.read_from_pickle("mkp_forest")
    decisionTree_kenpom = utils.read_from_pickle("mkp_dt")
    supportVC_kenpom = utils.read_from_pickle("mkp_svc")

    [kenpom_path, torvik_path] = utils.get_recent_data(date)
    with open(kenpom_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    kenpom_data = pd.DataFrame(data["rows"], columns=data["headers"])

    with open(torvik_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    torvik_data = pd.DataFrame(data["rows"], columns=data["headers"])

    torvik_data = clean_teams(torvik_data)
    kenpom_data = clean_teams(kenpom_data, True)

    torvik_teams = torvik_data["Team"]
    kenpom_teams = kenpom_data["Team"]

    torvik_today = torvik_data.drop(
        columns=[
            "Barthag",
            "WAB",
            "Team",
            "Conf",
            "Rec",
            "G",
            "Rk",
            "FTR",
            "3PR",
            "3PRD",
        ]
    )
    kenpom_today = kenpom_data.drop(
        columns=[
            "Rk",
            "Team",
            "Conf",
            "W-L",
            "Luck_Rk",
            "ORtg_Rk",
            "DRtg_Rk",
            "SOS_NetRtg_Rk",
            "SOS_ORtg_Rk",
            "SOS_DRtg_Rk",
            "NCSOS_NetRtg_Rk",
            "AdjT_Rk",
            "AdjT",
        ]
    )
    scaler = preprocessing.StandardScaler()

    x_predict_torvik = scaler.fit_transform(torvik_today)
    x_predict_kenpom = scaler.fit_transform(kenpom_today)

    # Torvik Model Predictions
    torvik_data["RF"] = predict_model(randomForest, x_predict_torvik)
    torvik_data["DT"] = predict_model(decisionTree, x_predict_torvik)
    torvik_data["SVC"] = predict_model(supportVC, x_predict_torvik)

    # Kenpom Model Predictions
    kenpom_data["RF"] = predict_model(randomForest_kenpom, x_predict_kenpom)
    kenpom_data["DT"] = predict_model(decisionTree_kenpom, x_predict_kenpom)
    kenpom_data["SVC"] = predict_model(supportVC_kenpom, x_predict_kenpom)

    # Sum Models and drop not needed cols
    torvik_data["Sum"] = torvik_data[["RF", "DT", "SVC"]].sum(1)
    df_torvik = torvik_data[["Rk", "Team", "Conf", "RF", "DT", "SVC", "Sum"]].copy()
    kenpom_data["Sum"] = kenpom_data[["RF", "DT", "SVC"]].sum(1)
    df_kenpom = kenpom_data[["Rk", "Team", "Conf", "RF", "DT", "SVC", "Sum"]].copy()

    # Torvik Clean
    df_torvik_filter = df_torvik.copy()
    df_torvik_filter = df_torvik_filter.drop(columns=["Sum"])
    torvik_teams = df_torvik_filter[["Team", "Conf", "Rk"]].copy()
    # Kenpom Clean
    df_kenpom_filter = df_kenpom.copy()
    df_kenpom_filter = df_kenpom_filter.drop(columns=["Sum"])
    kenpom_teams = df_kenpom_filter[["Team", "Conf", "Rk"]].copy()

    # Prep to merge into one DF
    # Random Forest - Torvik
    rf_filter_torvik = df_torvik_filter[df_torvik_filter["RF"] == 1]
    df_torvik_rf = rf_filter_torvik[["Team", "Conf", "Rk", "RF"]].copy()
    # Random Forest - Kenpom
    rf_filter_kenpom = df_kenpom_filter[df_kenpom_filter["RF"] == 1]
    df_kenpom_rf = rf_filter_kenpom[["Team", "Conf", "Rk", "RF"]].copy()

    # Decision Tree - Torvik
    dt_filter_torvik = df_torvik_filter[df_torvik_filter["DT"] == 1]
    df_torvik_dt = dt_filter_torvik[["Team", "Conf", "Rk", "DT"]].copy()
    # Decision Tree - Kenpom
    dt_filter_kenpom = df_kenpom_filter[df_kenpom_filter["DT"] == 1]
    df_kenpom_dt = dt_filter_kenpom[["Team", "Conf", "Rk", "DT"]].copy()

    # SVC - Torvik
    svc_filter_torvik = df_torvik_filter[df_torvik_filter["SVC"] == 1]
    df_torvik_svc = svc_filter_torvik[["Team", "Conf", "Rk", "SVC"]].copy()
    # SVC - Kenpom
    svc_filter_kenpom = df_kenpom_filter[df_kenpom_filter["SVC"] == 1]
    df_kenpom_svc = svc_filter_kenpom[["Team", "Conf", "Rk", "SVC"]].copy()

    # Torvik Final Clean
    comb1_torvik = pd.merge(torvik_teams, df_torvik_rf, "left", ["Team", "Conf", "Rk"])
    comb2_torvik = pd.merge(comb1_torvik, df_torvik_svc, "left", ["Team", "Conf", "Rk"])
    combined_torvik = pd.merge(
        comb2_torvik, df_torvik_dt, "left", ["Team", "Conf", "Rk"]
    )

    # Kenpom Final Clean
    comb1_kenpom = pd.merge(kenpom_teams, df_kenpom_rf, "left", ["Team", "Conf", "Rk"])
    comb2_kenpom = pd.merge(comb1_kenpom, df_kenpom_svc, "left", ["Team", "Conf", "Rk"])
    combined_kenpom = pd.merge(
        comb2_kenpom, df_kenpom_dt, "left", ["Team", "Conf", "Rk"]
    )

    # Merge models into one DF
    main = pd.merge(combined_kenpom, combined_torvik, on=["Team", "Conf"], how="outer")
    main["Num KP Models"] = main[["RF_x", "SVC_x", "DT_x"]].sum(1)
    main["Num TOR Models"] = main[["RF_y", "SVC_y", "DT_y"]].sum(1)
    main["Rk_y"] = pd.to_numeric(main["Rk_y"])
    main["Rk_x"] = pd.to_numeric(main["Rk_x"])

    main["GordScore"] = (
        ((10 * main["Num KP Models"]) + (80 - main["Rk_x"]))
        + ((10 * main["Num TOR Models"]) + (80 - main["Rk_y"]))
    ) / 2
    main64 = main.sort_values("GordScore", ascending=False)
    main64 = main64.drop(columns=["RF_x", "SVC_x", "DT_x", "RF_y", "SVC_y", "DT_y"])
    main64 = main64.rename(
        columns={
            "Rk_x": "Kenpom Rank",
            "Rk_y": "Torvik Rank",
            "Num KP Models": "# Models Kenpom",
            "Num TOR Models": "# Models Torvik",
        }
    )

    # Saving to another df for schedule home
    save_df = main64.copy()
    save_df = save_df.sort_values(by="GordScore", ascending=False)
    save_df["Overall"] = range(1, len(save_df) + 1)

    bestByConf = main64.loc[main64.groupby(by="Conf")["GordScore"].idxmax()]
    main64 = main64.drop(index=bestByConf.index)
    main64 = main64.head(68 - len(bestByConf))
    main64["ConfChamp"] = 0
    bestByConf["ConfChamp"] = 1
    main64 = pd.concat([main64, bestByConf])
    main64 = main64.sort_values(by="GordScore", ascending=False)
    main64["Overall"] = range(1, len(main64) + 1)
    last_week = change.change(date)
    main64 = pd.merge(main64, last_week, "left", "Team")

    main64["vs Last Wk"] = main64["vs Last Wk"].fillna("NR")
    main64["vs Last Wk"] = main64.apply(lambda row: calcWkDelta(row), axis=1)

    main64["Seed"] = seed_helper(main64["Overall"])
    main64["Overall"] = (
        "#"
        + main64["Overall"].astype(str)
        + " (Seed "
        + main64["Seed"].astype(str)
        + ")"
    )

    main64["Kenpom Rank"] = main64["Kenpom Rank"].astype(int)
    main64["Torvik Rank"] = main64["Torvik Rank"].astype(int)

    main64["Kenpom"] = (
        main64["Kenpom Rank"].astype(str) + " " + main64["# Models Kenpom"].apply(stars)
    )
    main64["Torvik"] = (
        main64["Torvik Rank"].astype(str) + " " + main64["# Models Torvik"].apply(stars)
    )

    styler = main64[["Kenpom", "Torvik", "GordScore", "Overall", "vs Last Wk"]].style
    conf_champ_dict = pd.Series(main64.ConfChamp.values, index=main64.Team).to_dict()
    df = main64.drop(
        columns=[
            "Kenpom Rank",
            "# Models Kenpom",
            "Torvik Rank",
            "# Models Torvik",
            "Seed",
            "ConfChamp",
        ]
    )
    df = df[["Team", "Conf", "Kenpom", "Torvik", "GordScore", "Overall", "vs Last Wk"]]
    conf = (df.groupby("Conf")
                .size()
                .astype(int)
                .to_dict()
    )

    grouped = defaultdict(list)
    for conference, bids in conf.items():
        grouped[bids].append(conference)

    master = scraper.getMasterTeams()
    df["img"] = df.apply(lambda x: getUrl(x, save_df, master), axis=1)
    df["Team"] = df.apply(lambda x: image_formatter(x.img) + x.Team, axis=1)
    df = df.drop(columns=["img"])
    styler = (
        df.style.hide(axis="index")
        .format({"GordScore": "{:.1f}"})
        .format(_format_arrow, subset=["vs Last Wk"])
        .applymap(_color_arrow, subset=["vs Last Wk"])
        .set_table_attributes('class="sticky-table"')
        .background_gradient(
            subset=["Kenpom"],
            cmap="cividis",  # green = better (lower rank)
            gmap=main64["Kenpom Rank"],
        )
        .background_gradient(
            subset=["Torvik"], cmap="cividis", gmap=main64["Torvik Rank"]
        )
        .apply(lambda x: bold_row(x, conf_champ_dict), axis=1)
    )
    conf_html =  "<h3>Bid Breakdown by Conference</h3>"
    for bids in sorted(grouped.keys(), reverse=True):
        confs = ", ".join(grouped[bids])
        conf_html += f"<div><strong>{bids}</strong>: {confs}</div>\n"
   
    tz = timezone("EST")
    time_obj = datetime.datetime.now(tz)
    time = time_obj.strftime("Last Update: %A %m/%d/%y %I:%M %p")
    df_html = f"<p>{time}</p>"
    df_html += '<div class="table-container">'
    df_html += styler.to_html()
    df_html += "</div>"
    df_html += conf_html
    path = utils.get_path(f"docs/men/predict_{date}.html")
    html = htmb.add_front_matter(df_html, f"NCAAM Prediction - {date}")
    with open(path, "w") as f:
        f.write(html)
        print(f"Wrote to: {path} for {date}")

    return save_df
