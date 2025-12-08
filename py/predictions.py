import utils
import pandas as pd
import numpy as np
import json
import change
import datetime
from sklearn import preprocessing
import html_builder as htmb
from pytz import timezone

def predict(date):
    randomForest = utils.read_from_pickle('forest')
    decisionTree = utils.read_from_pickle('dt')
    supportVC = utils.read_from_pickle('svc')
    
    randomForest_kenpom = utils.read_from_pickle('kp_forest')
    decisionTree_kenpom = utils.read_from_pickle('kp_dt')
    supportVC_kenpom = utils.read_from_pickle('kp_svc')
    
    [kenpom_path, torvik_path] = utils.get_recent_data(date)
    with open(kenpom_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    kenpom_data = pd.DataFrame(data['rows'], columns=data['headers'])
    
    with open(torvik_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    torvik_data = pd.DataFrame(data['rows'], columns=data['headers'])
    torvik_data['Conf'] = torvik_data['Conf'].replace('Pat', 'PL')
    
    dict = {
            "SIU Edwardsville" : "SIUE",
            "Cal St. Northridge" : "CSUN",
            "McNeese St.": "McNeese",
            "Nicholls St.": "Nicholls",
            "Southeast Missouri" : "SEMO",
            "Southeast Missouri St." : "SEMO",
            "Kansas City" : "UMKC"
        }
    def strip(team):
        for i, char in enumerate(team):
            if char == '(':
                return team[:i]
            if team[i:i+3] == 'vs.':
                return team[:i]
        return team
    
    torvik_data['Team'] = torvik_data['Team'].apply(lambda x: strip(x))
    teams = torvik_data['Team']
    modded = []
    for team in list(teams):
        #mod = team.replace('St.', 'State')
        #mod_space = mod.replace(' ', '_')
        modded.append(team)
        

    utils.save_json_data(modded, utils.get_path('data/team_list.json'))
    torvik_data['Team'] = torvik_data['Team'].replace(dict)
    kenpom_data['Team'] = kenpom_data['Team'].replace(dict)
 
    torvik_teams = torvik_data['Team']
    kenpom_teams = kenpom_data['Team']

   
    torvik_today = torvik_data.drop(columns=['Barthag', 'WAB','Team', 'Conf', 'Rec', 'G', 'Rk', 'FTR', '3PR', '3PRD'])
    kenpom_today = kenpom_data.drop(columns=['Rk','Team', 'Conf', 
                                'W-L', 'Luck_Rk', 'ORtg_Rk', 'DRtg_Rk',
                                'SOS_NetRtg_Rk', 'SOS_ORtg_Rk', 'SOS_DRtg_Rk', 
                                'NCSOS_NetRtg_Rk', "AdjT_Rk", 'AdjT'])
    scaler = preprocessing.StandardScaler()

    x_predict_torvik = scaler.fit_transform(torvik_today)
    x_predict_kenpom = scaler.fit_transform(kenpom_today)

    # Forest
    #   Torvik
    forest_predict_torvik = randomForest.predict(x_predict_torvik)
    torvik_data['RF'] = forest_predict_torvik
    #   Kenpom
    forest_predict_kenpom = randomForest_kenpom.predict(x_predict_kenpom)
    kenpom_data['RF'] = forest_predict_kenpom

    # DT
    #   Torvik
    dt_predict_torvik = decisionTree.predict(x_predict_torvik)
    torvik_data['DT'] = dt_predict_torvik
    #   Kenpom
    dt_predict_kenpom = decisionTree_kenpom.predict(x_predict_kenpom)
    kenpom_data['DT'] = dt_predict_kenpom

    # SVC
    #   Torvik
    svc_predict_torvik = supportVC.predict(x_predict_torvik)
    torvik_data['SVC'] = svc_predict_torvik
    #   Kenpom
    svc_predict_kenpom = supportVC_kenpom.predict(x_predict_kenpom)
    kenpom_data['SVC'] = svc_predict_kenpom

    torvik_data['Sum'] = torvik_data[['RF', 'DT', 'SVC']].sum(1)
    df_torvik = torvik_data[['Rk', 'Team', 'Conf', 'RF', 'DT', 'SVC', 'Sum']].copy()

    kenpom_data['Sum'] = kenpom_data[['RF', 'DT', 'SVC']].sum(1)
    df_kenpom = kenpom_data[['Rk', 'Team', 'Conf', 'RF', 'DT', 'SVC', 'Sum']].copy()
    
  

    # Torvik Clean
    df_torvik_filter = df_torvik.copy()
    df_torvik_filter = df_torvik_filter.drop(columns=['Sum'])
    torvik_teams = df_torvik_filter[['Team', 'Conf', 'Rk']].copy()
    # Kenpom Clean
    df_kenpom_filter = df_kenpom.copy()
    df_kenpom_filter = df_kenpom_filter.drop(columns=['Sum'])
    kenpom_teams = df_kenpom_filter[['Team', 'Conf', 'Rk']].copy()

    # Pull out Top 64
    # Random Forest
    #   Torvik
    rf_filter_torvik = df_torvik_filter[df_torvik_filter['RF'] == 1]
    df_torvik_rf = rf_filter_torvik[['Team', 'Conf', 'Rk', 'RF']].copy()
    #   Kenpom
    rf_filter_kenpom = df_kenpom_filter[df_kenpom_filter['RF'] == 1]
    df_kenpom_rf = rf_filter_kenpom[['Team', 'Conf', 'Rk', 'RF']].copy()

    # Decision Tree
    #   Torvik
    dt_filter_torvik = df_torvik_filter[df_torvik_filter['DT'] == 1]
    df_torvik_dt = dt_filter_torvik[['Team', 'Conf', 'Rk', 'DT']].copy()
    #   Kenpom
    dt_filter_kenpom = df_kenpom_filter[df_kenpom_filter['DT'] == 1]
    df_kenpom_dt = dt_filter_kenpom[['Team', 'Conf', 'Rk', 'DT']].copy()

    # SVC
    #   Torvik
    svc_filter_torvik = df_torvik_filter[df_torvik_filter['SVC'] == 1]
    df_torvik_svc = svc_filter_torvik[['Team', 'Conf', 'Rk', 'SVC']].copy()
    #   Kenpom
    svc_filter_kenpom = df_kenpom_filter[df_kenpom_filter['SVC'] == 1]
    df_kenpom_svc = svc_filter_kenpom[['Team', 'Conf', 'Rk', 'SVC']].copy()

    
    # Torvik Final Clean
    comb1_torvik = pd.merge(torvik_teams, df_torvik_rf, "left", ["Team", 'Conf',  "Rk"])
    comb2_torvik = pd.merge(comb1_torvik, df_torvik_svc, "left", ["Team", 'Conf', "Rk"])
    combined_torvik = pd.merge(comb2_torvik, df_torvik_dt, "left", ["Team", 'Conf', "Rk"])
    
    # Kenpom Final Clean
    comb1_kenpom = pd.merge(kenpom_teams, df_kenpom_rf, "left", ["Team", 'Conf', "Rk"])
    comb2_kenpom = pd.merge(comb1_kenpom, df_kenpom_svc, "left", ["Team", 'Conf', "Rk"])
    combined_kenpom = pd.merge(comb2_kenpom, df_kenpom_dt, "left", ["Team", 'Conf',  "Rk"])
   
    main = pd.merge(combined_kenpom, combined_torvik, on=["Team", 'Conf'], how='outer')
    main['Num KP Models'] = main[['RF_x', 'SVC_x', 'DT_x']].sum(1)
    main['Num TOR Models'] = main[['RF_y', 'SVC_y', 'DT_y']].sum(1)
    main['Rk_y'] = pd.to_numeric(main['Rk_y'])
    main['Rk_x'] = pd.to_numeric(main['Rk_x'])
    
    main['GordScore'] = (((10 * main['Num KP Models']) + (80-main['Rk_x'])) + \
            ((10 * main['Num TOR Models']) + (80-main['Rk_y'])))/2
    main64 = main.sort_values("GordScore", ascending=False)
    main64 =  main64.drop(columns=['RF_x', 'SVC_x', 'DT_x', 'RF_y', 'SVC_y', 'DT_y'])
    main64 = main64.rename(columns={
        'Rk_x' : 'Kenpom Rank', 
        'Rk_y' : 'Torvik Rank',
        'Num KP Models' : '# Models Kenpom',
        'Num TOR Models' : '# Models Torvik'
    })
    
    def seed(x):
        current_team_index = 0
        seed = []
        seed_num = 1
        while current_team_index < len(x):
            if seed_num == 11 or seed_num == 16:
                num_teams_in_seed = 6
            else:
                num_teams_in_seed = 4
            seed += (np.repeat(seed_num, num_teams_in_seed).tolist())
            current_team_index += num_teams_in_seed
            seed_num += 1
        return seed

    bestByConf = main64.loc[main64.groupby(by='Conf')['GordScore'].idxmax()]
    main64 = main64.drop(index=bestByConf.index)
    main64 = main64.head(68-len(bestByConf))
    main64['ConfChamp'] = 0
    bestByConf['ConfChamp'] = 1
    main64 = pd.concat([main64, bestByConf])
    main64 = main64.sort_values(by='GordScore', ascending=False)
    main64['Overall'] = range(1, len(main64)+1)
    last_week = change.change(date)
    main64 = pd.merge(main64, last_week, 'left', 'Team')
 
    main64['vs Last Wk'] = main64['vs Last Wk'].fillna('NR')
    def calcWkDelta(row):
        if row['vs Last Wk'] != 'NR':
            row['vs Last Wk'] = int(row['vs Last Wk']) - row['Overall']
            if row['vs Last Wk'] == 0:
                row['vs Last Wk'] = '-'
        return row['vs Last Wk']
    main64['vs Last Wk'] = main64.apply(lambda row: calcWkDelta(row), axis=1)
 
    main64['Seed'] = seed(main64['Overall'])
    main64['Overall'] = '#' + main64['Overall'].astype(str) +' (Seed ' + main64['Seed'].astype(str) + ')' 
    
    def stars(count, max_count=3):
        filled = '★' * count
        empty = '☆' * (max_count - count)
        return f"({filled}{empty})"
    
    main64['Kenpom Rank'] = main64['Kenpom Rank'].astype(int)
    main64['Torvik Rank'] = main64['Torvik Rank'].astype(int)

    main64['Kenpom'] = main64['Kenpom Rank'].astype(str) + ' ' + main64['# Models Kenpom'].apply(stars)
    main64['Torvik'] = main64['Torvik Rank'].astype(str) + ' ' + main64['# Models Torvik'].apply(stars)
   
    styler = main64[['Kenpom', 'Torvik', 'GordScore', 'Overall', 'vs Last Wk']].style
    conf_champ_dict = pd.Series(main64.ConfChamp.values,index=main64.Team).to_dict()
    df = main64.drop(columns=['Kenpom Rank','# Models Kenpom', 'Torvik Rank', '# Models Torvik', 'Seed', 'ConfChamp'])
    df = df[['Team', 'Conf', 'Kenpom', 'Torvik', 'GordScore', 'Overall', 'vs Last Wk']]
    def _format_arrow(val):
        if (val == 'NR') | (val == '-'):
            return val
        return f"{'↑' if int(val) > 0 else '↓'} {abs(val):.0f}" if int(val) != 0 else f"{val:.0f}"

    def _color_arrow(val):
        if (val == 'NR') | (val == '-'):
            return "color: black"
        return "color: green" if int(val) > 0 else "color: red" if int(val) < 0 else "color: black"
    
    def bold_row(row, conf_champ_dict):
        val = conf_champ_dict[row['Team']]
        if val: 
            ret = [f"font-weight: bold"] * len(row)
            ret[2] = "font-weight: normal" 
            ret[3] = "font-weight: normal"
            return ret
        else:
            return [f"font-weight: normal"] * len(row)
       
    
    styler = (
        df
        .style
        .hide(axis="index") 
        .format({'GordScore' : "{:.1f}"})
        .format(_format_arrow, subset=["vs Last Wk"]).applymap(_color_arrow, subset=["vs Last Wk"])
        .set_table_attributes('class="sticky-table"')
        .background_gradient(
            subset=['Kenpom'],
            cmap='cividis',  # green = better (lower rank)
            gmap=main64['Kenpom Rank'])
        .background_gradient(
            subset=['Torvik'],
            cmap='cividis',
            gmap=main64['Torvik Rank'])
        .apply(lambda x: bold_row(x, conf_champ_dict), axis =1))
    tz = timezone('EST')
    time_obj = datetime.datetime.now(tz)
    time = time_obj.strftime("Last Update: %A %m/%d/%y %I:%M %p")
    df_html = f"<p>{time}</p>"
    df_html += '<div class="table-container">'
    df_html += styler.to_html()
    df_html += '<div>'
    path = utils.get_path(f'docs/predict_{date}.html')
    html = htmb.add_front_matter(df_html, f'Prediction - {date}')
    with open(path, 'w') as f: 
       f.write(html)  
       print(f'Wrote to: {path} for {date}')


    