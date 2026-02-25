import utils
import pandas as pd
import numpy as np
import json
import change
from datetime import datetime
from pytz import timezone
import scraper
import re
from collections import defaultdict
import html_util
import joblib
from lib import paths, teams


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
        saved_index = list(save_df[save_df["Team"] == x["Team"]]["Index"])[0]
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


def get_recent_file(path):
    # Today's filename
    today_str = datetime.now().strftime("%Y-%m-%d")
    today_file = path / f"{today_str}.json"

    # If today's file exists, return it
    if today_file.exists():
        target_file = today_file

    # Otherwise get most recent file
    files = sorted(
        path.glob("*.json"),
        key=lambda f: f.name,  # filenames are YYYY-MM-DD.json so this works
        reverse=True,
    )

    if not files:
        return None

    target_file = files[0]

    # Load JSON
    with open(target_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data


def predict_womens(date):
    ensemble = joblib.load("models/2026/womens_2-20-2026.pkl")

    data_path = utils.get_recent_data(date, 1)
    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    df = pd.DataFrame(data["rows"], columns=data["headers"])
    df = clean_teams(df)

    record = df[["Team", "Rec"]].copy()

    base_models = ensemble["base_models"]
    meta_model = ensemble["meta_model"]

    log = base_models["logistic"]
    rf = base_models["rf"]
    ada = base_models["ada"]
    gb = base_models["gb"]
    hgb = base_models["hgb"]

    log_probs = log["model"].predict_proba(df[log["features"]])[:, 1]
    rf_probs = rf["model"].predict_proba(df[rf["features"]])[:, 1]
    ada_probs = ada["model"].predict_proba(df[ada["features"]])[:, 1]
    gb_probs = gb["model"].predict_proba(df[gb["features"]])[:, 1]
    hgb_probs = hgb["model"].predict_proba(df[hgb["features"]])[:, 1]

    meta_input = np.column_stack(
        [
            log_probs,
            rf_probs,
            ada_probs,
            gb_probs,
            hgb_probs,
        ]
    )

    final_probs = meta_model.predict_proba(meta_input)[:, 1]

    df["Gord"] = final_probs
    df = df.sort_values("Gord", ascending=False)
    df = df.rename(columns={"Rk": "Torvik", "Rec": "Record"})

    n = len(df)
    df["Torvik"] = df["Torvik"].astype(float)
    df["Torvik"] = 1 - (df["Torvik"] - 1) / (n - 1)

    net_json = get_recent_file(paths.W_NET_DIR)
    net_df = pd.DataFrame(net_json["rows"], columns=net_json["headers"])
    net_df = net_df[["Rank", "School"]].copy()
    net_df["Team"] = net_df.apply(
        lambda x: teams.getTeamOfficialName(x["School"]), axis=1
    )
    net_df = net_df.rename(columns={"Rank": "Net"})
    df = pd.merge(df, net_df[["Net", "Team"]].copy(), "inner", "Team")

    df["Net"] = df["Net"].astype(float)
    df["Net"] = 1 - (df["Net"] - 1) / (n - 1)

    df["Rank"] = df.apply(
        lambda x: (0.3 * x["Torvik"] + 0.5 * x["Gord"] + 0.2 * x["Net"]),
        axis=1,
    )

    df = df.drop(columns=["Torvik", "Net"])
    df = df.sort_values("Rank", ascending=False)
    df["Ovr"] = range(1, len(df) + 1)

    save_ranks = scraper.getWTeamRanks()
    date_key = date.isoformat()
    team_map = df.set_index("Team")[["Record", "Ovr"]].to_dict(orient="index")
    save_ranks[date_key] = team_map
    scraper.saveWTeamRanks(save_ranks)
    save_df = df.copy()

    conf_winners = df.groupby(by="Conf")["Ovr"].transform("min")
    df["ConfChamp"] = df["Ovr"] == conf_winners

    delta = change.change(date, "W")

    df = pd.merge(df.reset_index(), delta, "left", "Team").set_index("index")

    df["Δ 1d"] = df["Δ 1d"].replace(to_replace=0, value="-")
    df["Δ 7d"] = df["Δ 7d"].replace(to_replace=0, value="-")
    df["Δ 14d"] = df["Δ 14d"].replace(to_replace=0, value="-")
    df["Δ 1mo"] = df["Δ 1mo"].replace(to_replace=0, value="-")

    conf_win_idx = df[df["ConfChamp"] == 1].index
    dropped = df.drop(index=conf_win_idx)
    atlarge_idx = dropped.head(68 - len(conf_winners)).index
    tourney_idx = pd.Index.union(conf_win_idx, atlarge_idx)
    mask = df.index.isin(tourney_idx)
    df["Seed"] = None
    df.loc[mask, "Seed"] = seed_helper(df["Ovr"][mask])

    df["Ovr"] = df.apply(
        lambda x: f'#{x["Ovr"]} (Seed {x["Seed"]})' if x["Seed"] else f'#{x["Ovr"]}',
        axis=1,
    )

    conf = df.groupby("Conf").size().astype(int).to_dict()

    grouped = defaultdict(list)
    for conference, bids in conf.items():
        grouped[bids].append(conference)

    march_df = df[df["Ovr"].str.contains(r"\bSeed\b", na=False)]
    first_out = df.drop(march_df.index)[:8]

    march_df = html_util.style_bracketology(march_df, gender="W")
    first_out = html_util.style_bracketology(first_out, gender="W")

    conf_html = "<h3>Bid Breakdown by Conference</h3>"
    for bids in sorted(grouped.keys(), reverse=True):
        confs = ", ".join(grouped[bids])
        conf_html += f"<div><strong>{bids}</strong>: {confs}</div>\n"

    tz = timezone("EST")
    time_obj = datetime.now(tz)
    time = time_obj.strftime("Last Update: %A %m/%d/%y %I:%M %p")
    df_html = f"<p>{time}</p>"
    df_html += '<div class="filter-bar">'
    df_html += """{% include global-toggle.html %} """
    df_html += "</div>"
    df_html += '<div class="table-container">'
    df_html += march_df.to_html()
    df_html += "</div>"
    df_html += "<h3>First Four Out & Next 4 Out</h3>"
    df_html += '<div class="table-container">'
    df_html += first_out.to_html()
    df_html += "</div>"
    df_html += "<script src='/assets/js/rank-toggle.js'></script>"

    # MAIN -> DF with Conf col data
    path = utils.get_path(f"docs/women/predict_{date}.html")
    html = html_util.add_front_matter(df_html, f"NCAAW Bracketology", date)
    with open(path, "w") as f:
        f.write(html)
        print(f"Wrote to: {path} for {date}")

    return [save_df, df]

def predict_tor(date):
    ensemble = joblib.load("models/2026/men_tor_2-23-2026.pkl")
    [_, torvik_path] = utils.get_recent_data(date)

    # Torvik Load/Clean
    with open(torvik_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    torvik_data = pd.DataFrame(data["rows"], columns=data["headers"])
    df = clean_teams(torvik_data)

    df.columns = df.columns.str.upper()
    df = df.rename(columns={
      "RK" : "Torvik",
      "EFG%" : "EFG_O",
      "EFGD%" : "EFG_D",
      "2P%" : "2P_O",
      "2P%D" : "2P_D",
      "3P%" : "3P_O",
      "3P%D" : "3P_D",
      "ADJ T." : "ADJ_T",
      "TEAM" : "Team",
      "CONF" : "Conf"
    })
    
    base_models = ensemble["base_models"]
    meta_model = ensemble["meta_model"]

    log = base_models["logistic"]
    svc = base_models["svc"]
    ada = base_models["ada"]
    gb = base_models["gb"]
    hgb = base_models["hgb"]

    log_probs = log["model"].predict_proba(df[log["features"]])[:, 1]
    svc_probs = svc["model"].predict_proba(df[svc["features"]])[:, 1]
    ada_probs = ada["model"].predict_proba(df[ada["features"]])[:, 1]
    gb_probs = gb["model"].predict_proba(df[gb["features"]])[:, 1]
    hgb_probs = hgb["model"].predict_proba(df[hgb["features"]])[:, 1]

    meta_input = np.column_stack(
        [
            log_probs,
            svc_probs,
            ada_probs,
            gb_probs,
            hgb_probs,
        ]
    )

    final_probs = meta_model.predict_proba(meta_input)[:, 1]

    df["GordTor"] = final_probs
    df = df.sort_values("GordTor", ascending=False)
    
    return df

def predict_ken(date):
    ensemble = joblib.load("models/2026/men_ken_2-24-2026.pkl")
    [kenpom_path, _] = utils.get_recent_data(date)

    # Kenpom Load/Clean
    with open(kenpom_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    kenpom_data = pd.DataFrame(data["rows"], columns=data["headers"])
    kenpom_data = kenpom_data.rename(columns={
      "TeamName" : "Team",
      "ConfShort" : "Conf",
    })
    
    df = clean_teams(kenpom_data, True)

    df["Kenpom"] = df["RankAdjEM"]
    
    base_models = ensemble["base_models"]
    meta_model = ensemble["meta_model"]

    log = base_models["logistic"]
    svc = base_models["svc"]
    ada = base_models["ada"]
    gb = base_models["gb"]
    hgb = base_models["hgb"]

    log_probs = log["model"].predict_proba(df[log["features"]])[:, 1]
    svc_probs = svc["model"].predict_proba(df[svc["features"]])[:, 1]
    ada_probs = ada["model"].predict_proba(df[ada["features"]])[:, 1]
    gb_probs = gb["model"].predict_proba(df[gb["features"]])[:, 1]
    hgb_probs = hgb["model"].predict_proba(df[hgb["features"]])[:, 1]

    meta_input = np.column_stack(
        [
            log_probs,
            svc_probs,
            ada_probs,
            gb_probs,
            hgb_probs,
        ]
    )

    final_probs = meta_model.predict_proba(meta_input)[:, 1]

    df["GordKen"] = final_probs
    df = df.sort_values("GordKen", ascending=False)

    df["Record"] = df.apply(
        lambda x: f"{x['Wins']}-{x['Losses']}", axis=1
    )
    return df

def full_prediction(date) -> pd.DataFrame:

    torvik_full = predict_tor(date)
    torvik = torvik_full[['Torvik', 'Team', 'Conf', 'GordTor']].copy()

    kenpom_full = predict_ken(date)
    kenpom = kenpom_full[['Team', 'Conf', 'Record', 'Kenpom', 'GordKen']].copy()

    df = pd.merge(kenpom, torvik, on=["Team", "Conf"], how="outer")

    net_json = get_recent_file(paths.M_NET_DIR)
    net_df = pd.DataFrame(net_json["rows"], columns=net_json["headers"])
    net_df = net_df[["Rank", "School"]].copy()
    net_df["Team"] = net_df.apply(
        lambda x: teams.getTeamOfficialName(x["School"]), axis=1
    )
    net_df = net_df.rename(columns={"Rank": "Net"})
    df = pd.merge(df, net_df[["Net", "Team"]].copy(), "inner", "Team")

    n = len(df)
    df["Net"] = df["Net"].astype(float)
    df["Net"] = 1 - (df["Net"] - 1) / (n - 1)
    
    bpi_json = get_recent_file(paths.M_ESPN_DIR)
    bpi_df = pd.DataFrame(bpi_json["rows"], columns=bpi_json["headers"])
    bpi_df = bpi_df[["team", "rank"]].copy()
    bpi_df["Team"] = bpi_df.apply(
        lambda x: teams.getTeamOfficialName(x["team"]), axis=1
    )
    bpi_df = bpi_df.rename(columns={"rank": "BPI"})
    df = pd.merge(df, bpi_df[["BPI", "Team"]].copy(), "inner", "Team")
    
    df["BPI"] = df["BPI"].astype(float)
    df["BPI"] = 1 - (df["BPI"] - 1) / (n - 1)
    
    df["Torvik"] = df["Torvik"].astype(float)
    df["Torvik"] = 1 - (df["Torvik"] - 1) / (n - 1)
    
    df["Kenpom"] = df["Kenpom"].astype(float)
    df["Kenpom"] = 1 - (df["Kenpom"] - 1) / (n - 1)
    
    model_cons = 0.4
    ranks_cons = 0.05
    df["Pwr"] = df.apply(
        lambda x: (ranks_cons * x["Torvik"] + model_cons * x["GordTor"] + model_cons * x["GordKen"] + ranks_cons * x["Net"] + ranks_cons * x["Kenpom"] + ranks_cons* x["BPI"]),
        axis=1,
    )
    df = df.sort_values("Pwr", ascending=False)
    df["Ovr"] = range(1, len(df) + 1)
    
    
    save_ranks = scraper.getTeamRanks()
    date_key = date.isoformat()
    team_map = df.set_index("Team")[["Record", "Ovr"]].to_dict(orient="index")
    save_ranks[date_key] = team_map
    scraper.saveTeamRanks(save_ranks)
    save_df = df.copy()
    return df, save_df


def predict(date):
    [df, save_df] = full_prediction(date)


    conf_winners = df.loc[df.groupby(by="Conf")["Pwr"].idxmax()]

    df["ConfChamp"] = 0
    df.loc[conf_winners.index, "ConfChamp"] = 1

    delta = change.change(date)

    main = pd.merge(df.reset_index(), delta, "left", "Team").set_index("index")

    main["Δ 1d"] = main["Δ 1d"].replace(to_replace=0, value="-")
    main["Δ 7d"] = main["Δ 7d"].replace(to_replace=0, value="-")
    main["Δ 14d"] = main["Δ 14d"].replace(to_replace=0, value="-")
    main["Δ 1mo"] = main["Δ 1mo"].replace(to_replace=0, value="-")

    conf_win_idx = main[main["ConfChamp"] == 1].index
    dropped = main.drop(index=conf_win_idx)
    atlarge_idx = dropped.head(68 - len(conf_winners)).index
    tourney_idx = pd.Index.union(conf_win_idx, atlarge_idx)
    mask = main.index.isin(tourney_idx)
    main["Seed"] = None
    main.loc[mask, "Seed"] = seed_helper(main["Ovr"][mask])

    main["Ovr"] = main.apply(
        lambda x: f'#{x["Ovr"]} (Seed {x["Seed"]})' if x["Seed"] else f'#{x["Ovr"]}',
        axis=1,
    )

    conf = main.groupby("Conf").size().astype(int).to_dict()

    grouped = defaultdict(list)
    for conference, bids in conf.items():
        grouped[bids].append(conference)

    march_df = main[main["Ovr"].str.contains(r"\bSeed\b", na=False)]
    first_out = main.drop(march_df.index)[:8]

    march_df = html_util.style_bracketology(march_df)
    first_out = html_util.style_bracketology(first_out)

    conf_html = "<h3>Bid Breakdown by Conference</h3>"
    for bids in sorted(grouped.keys(), reverse=True):
        confs = ", ".join(grouped[bids])
        conf_html += f"<div><strong>{bids}</strong>: {confs}</div>\n"

    tz = timezone("EST")
    time_obj = datetime.now(tz)
    time = time_obj.strftime("Last Update: %A %m/%d/%y %I:%M %p")
    df_html = f"<p>{time}</p>"
    df_html += f"<p>Pwr is derived from using machine learning models on Kenpom & Torvik data in aggregate to calculate tournament probabilties.</p>"
    df_html += f"<p>This value is then balanced by rankings from ESPN BPI, NCAA Net, Kenpom and Torvik to help rank/seed teams.</p>"
    df_html += f"<p>Future plans include using machine learning to specifically rank teams seperately from tournament projections.</p>"
    df_html += '<div class="filter-bar">'
    df_html += """{% include global-toggle.html %} """
    df_html += "</div>"
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
    html = html_util.add_front_matter(df_html, f"NCAAM Bracketology", date)
    with open(path, "w") as f:
        f.write(html)
        print(f"Wrote to: {path} for {date}")

    return [save_df, main]
