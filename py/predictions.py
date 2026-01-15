import utils
import pandas as pd
import numpy as np
import json
import change
from datetime import datetime, date
from sklearn import preprocessing
import html_builder as htmb
from pytz import timezone
import scraper
import re
from collections import defaultdict
import math
import html_util

def seed_helper(x):
    """
    Calculates would-be seed based on rank

    :param x: DataFrame column containing Ovr rank
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


def calcWkDelta(row, label):
    """
    Calculate rank difference over last week

    :param row: Row with team data
    :type row: Series
    :return: Row with updated vs Last Week
    :rtype: Series
    """
    if row[label] != "NR":
        row[label] = int(row[label]) - row["Ovr"]
        if row[label] == 0:
            row[label] = "-"
    return row[label]


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


def getRecord(x, winloss):
    """
    Gets record and returns formatted with name

    :param x: Row for current team
    :type x: Series
    :param save_df: Predictions DataFrame with all D1 teams
    :type save_df: DataFrame
    :param master: Master Team Name DataFrame
    :type master: DataFrame
    :return: Link/Path to logo
    :rtype: str
    """
  
    idx = list(winloss[winloss["Team"] == x["Team"]].index)[0]
    val = list(winloss.loc[idx])[1]
    text = f"{x['Team']} ({val})"
    return text

def getRecordOnly(x, winloss):
    idx = list(winloss[winloss["Team"] == x["Team"]].index)[0]
    val = list(winloss.loc[idx])[1]
    return val

def getWinPer(record):
    m = re.search(r"(\d+)-(\d+)", record)
    wins, losses = map(int, m.groups())
    total = wins + losses
    return wins / total if total else 0.0

def predByConf():
    return


def predict_w(date):
    master = scraper.getMasterTeams()

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

    #df_torvik = df_torvik.sort_values("GordScore", ascending=False)
    df_torvik = df_torvik.drop(columns=["RF", "SVC", "DT"])
    df_torvik = df_torvik.rename(
        columns={"Rk": "Torvik Rank", "Sum": "# Models Torvik"}
    )
    main64 = df_torvik.copy()

    # Saving to another df for schedule home
    save_df = main64.copy()
    
    save_df["Index"] = save_df.apply(lambda x: scraper.getNameFromCode(x['Team'], master)[0], axis = 1)
    save_df = save_df.sort_values(by="GordScore", ascending=False)
    save_df["Ovr"] = range(1, len(save_df) + 1)

    bestByConf = main64.loc[main64.groupby(by="Conf")["GordScore"].idxmax()]
    main64 = main64.drop(index=bestByConf.index)
    main64 = main64.head(68 - len(bestByConf))
    main64["ConfChamp"] = 0
    bestByConf["ConfChamp"] = 1
    main64 = pd.concat([main64, bestByConf])
    main64 = main64.sort_values(by="GordScore", ascending=False)
    main64["Ovr"] = range(1, len(main64) + 1)
    last_week = change.change_w(date)
    main64 = pd.merge(main64, last_week, "left", "Team")

    main64["Last Wk"] = main64["Last Wk"].fillna("NR")
    main64["Last Wk"] = main64.apply(lambda row: calcWkDelta(row, "Last Wk"), axis=1)

    main64["Seed"] = seed_helper(main64["Ovr"])
    main64["Ovr"] = (
        "#"
        + main64["Ovr"].astype(str)
        + " (Seed "
        + main64["Seed"].astype(str)
        + ")"
    )

    main64["Torvik Rank"] = main64["Torvik Rank"].astype(int)
    main64["Torvik"] = (
        main64["Torvik Rank"].astype(str) + " " + main64["# Models Torvik"].apply(stars)
    )

    styler = main64[["Torvik", "GordScore", "Ovr", "Last Wk"]].style
    conf_champ_dict = pd.Series(main64.ConfChamp.values, index=main64.Team).to_dict()
    df = main64.drop(columns=["Torvik Rank", "# Models Torvik", "Seed", "ConfChamp"])
    df = df[["Team", "Conf", "Torvik", "GordScore", "Ovr", "Last Wk"]]

    conf = (df.groupby("Conf")
                .size()
                .astype(int)
                .to_dict()
    )

    grouped = defaultdict(list)
    for conference, bids in conf.items():
        grouped[bids].append(conference)

    df["img"] = df.apply(lambda x: getUrl(x, save_df, master, 'W'), axis=1)
    df["Team"] = df.apply(lambda x: image_formatter(x.img) + x.Team, axis=1)
    df = df.drop(columns=["img"])

    styler = (
        df.style.hide(axis="index")
        .format({"GordScore": "{:.1f}"})
        .format(_format_arrow, subset=["Last Wk"])
        .applymap(_color_arrow, subset=["Last Wk"])
        .set_table_attributes('class="sticky-table"')
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
    time_obj = datetime.now(tz)
    time = time_obj.strftime("Last Update: %A %m/%d/%y %I:%M %p")
    df_html = f"""<p>{time}</p>
        <div class="table-container">
        {styler.to_html()}
        <div>"""
    df_html += conf_html
    path = utils.get_path(f"docs/women/predict_{date}.html")
    html = htmb.add_front_matter(df_html, f"NCAAW Prediction- {date}")
    
    with open(path, "w") as f:
        f.write(html)
        print(f"Wrote to: {path} for {date}")
    return save_df


def full_prediction(date) -> pd.DataFrame:
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

    winloss = kenpom_data[['Team', "W-L"]]

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

    count = len(main)
    
    def weighted(team, count, weight = 0.55):
        kp_norm_rank = 1 - ((team['Rk_x'] -1) / (count - 1))
        tor_norm_rank = 1 - ((team['Rk_y'] -1) / (count - 1))
        elite_rank = max(kp_norm_rank, tor_norm_rank)
        q = (0.5 * tor_norm_rank) + (0.5 * kp_norm_rank)

        missing = team["Num KP Models"] + team["Num TOR Models"]
        penalty = ((6 - missing) * (1 - elite_rank)) * .03

        v = math.pow(missing / 6, 1)
        calc = ((weight * v) + ((1 - weight) * q)) - penalty
        return calc
       
    main['Rtg'] = main.apply(lambda x: weighted(x, count), axis=1)
    main["Win"] = main.apply(lambda x: getWinPer(getRecordOnly(x, winloss)), axis=1)
    main["Win"] = main["Win"].round(4)

    main_sorted = main.sort_values(by=["Rtg", "Win"], ascending=[False, False])
    main_sorted = main_sorted.drop(columns=["RF_x", "SVC_x", "DT_x", "RF_y", "SVC_y", "DT_y", "Win"])
    main_sorted = main_sorted.rename(
        columns={
            "Rk_x": "Kenpom Rank",
            "Rk_y": "Torvik Rank",
            "Num KP Models": "# Models Kenpom",
            "Num TOR Models": "# Models Torvik",
        }
    )
    return [main_sorted, winloss]

def predict(date):
    [all_sorted, winloss] = full_prediction(date)

    all_sorted = all_sorted.sort_values("Rtg", ascending=False)
    all_sorted["Record"] = all_sorted.apply(lambda x: getRecordOnly(x, winloss), axis=1)
    all_sorted["Win"] = all_sorted.apply(lambda x: getWinPer(getRecordOnly(x, winloss)), axis=1)
    all_sorted["Win"] = all_sorted["Win"].round(4)
    all_sorted = all_sorted.sort_values(by=["Rtg", "Win"], ascending=[False, False])
    all_sorted["Ovr"] = range(1, len(all_sorted) + 1)
    # Saving to another df for schedule home
    save_df = all_sorted.copy()

    conf_winners = all_sorted.loc[all_sorted.groupby(by="Conf")["Rtg"].idxmax()]

    all_sorted['ConfChamp'] = 0
    all_sorted.loc[conf_winners.index, 'ConfChamp'] = 1
   
    delta = change.change(date)
    
    main = pd.merge(all_sorted.reset_index(), delta, "left", "Team").set_index("index")

    main["Δ 7d"] = main["Δ 7d"].fillna("NR")
    main["Δ 14d"] = main["Δ 14d"].fillna("NR")
    main["Δ 1mo"] = main["Δ 1mo"].fillna("NR")

    main["Δ 7d"] = main.apply(lambda row: calcWkDelta(row, "Δ 7d"), axis=1)
    main["Δ 14d"] = main.apply(lambda row: calcWkDelta(row, "Δ 14d"), axis=1)
    main["Δ 1mo"] = main.apply(lambda row: calcWkDelta(row, "Δ 1mo"), axis=1)

    conf_win_idx = main[main['ConfChamp'] == 1].index
    dropped = main.drop(index=conf_win_idx)
    atlarge_idx = dropped.head(68 - len(conf_winners)).index
    tourney_idx = pd.Index.union(conf_win_idx, atlarge_idx)
    mask = main.index.isin(tourney_idx)
    main['Seed'] = None
    main.loc[mask, 'Seed']= seed_helper(main["Ovr"][mask])

    main["Ovr"] = main.apply(lambda x: f'#{x["Ovr"]} (Seed {x["Seed"]})' if x["Seed"] else f'#{x["Ovr"]}', axis=1)
    
    main["Kenpom Rank"] = main["Kenpom Rank"].astype(int)
    main["Torvik Rank"] = main["Torvik Rank"].astype(int)

    main["Kenpom"] = (
        main["Kenpom Rank"].astype(str) + " " + main["# Models Kenpom"].apply(stars)
    )
    main["Torvik"] = (
        main["Torvik Rank"].astype(str) + " " + main["# Models Torvik"].apply(stars)
    )

    conf = (main.groupby("Conf")
                .size()
                .astype(int)
                .to_dict()
    )
    
    grouped = defaultdict(list)
    for conference, bids in conf.items():
        grouped[bids].append(conference)

    march_df = main[main['Ovr'].str.contains(r"\bSeed\b", na=False)]
    first_out = main.drop(march_df.index)[:8]

    march_df = html_util.style_bracketology(march_df)
    first_out = html_util.style_bracketology(first_out)
    
    conf_html =  "<h3>Bid Breakdown by Conference</h3>"
    for bids in sorted(grouped.keys(), reverse=True):
        confs = ", ".join(grouped[bids])
        conf_html += f"<div><strong>{bids}</strong>: {confs}</div>\n"
   
    tz = timezone("EST")
    time_obj = datetime.now(tz)
    time = time_obj.strftime("Last Update: %A %m/%d/%y %I:%M %p")
    df_html = f"<p>{time}</p>"
    df_html +=  f'''
                <div class="change-toggle global-toggle">
                <button data-period="7d">1 Week</button>
                <button data-period="14d" class="active">2 Weeks</button>
                <button data-period="1mo">1 Month</button>
                </div>'''
    df_html += '<div class="table-container">'
    df_html += march_df.to_html()
    df_html += "</div>"
    df_html += "<h3>First Four Out & Next 4 Out</h3>"
    df_html += '<div class="table-container">'
    df_html += first_out.to_html()
    df_html += "</div>"
    df_html += "<script src='/assets/js/rank-toggle.js'></script>"
    
    # MAIN -> DF with Conf col data
    path = utils.get_path(f"docs/men/predict_{date}.html")
    html = htmb.add_front_matter(df_html, f"NCAAM Prediction - {date}")
    with open(path, "w") as f:
        f.write(html)
        print(f"Wrote to: {path} for {date}")

    return [save_df, main]