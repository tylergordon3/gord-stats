import utils
import pandas as pd
import numpy as np
import json
import constants
from sklearn import preprocessing
import html_builder as htmb
from pretty_html_table import build_table

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
    df_torvik = torvik_data[['Rk', 'Team', 'RF', 'DT', 'SVC', 'Sum']].copy()

    kenpom_data['Sum'] = kenpom_data[['RF', 'DT', 'SVC']].sum(1)
    df_kenpom = kenpom_data[['Rk', 'Team', 'RF', 'DT', 'SVC', 'Sum']].copy()
    
    def strip(team):
        for i, char in enumerate(team):
            if char == '(':
                return team[:i]
            if team[i:i+3] == 'vs.':
                return team[:i]
        return team

    # Torvik Clean
    df_torvik_filter = df_torvik[df_torvik['Sum'] > 0].copy()
    df_torvik_filter['Team'] = df_torvik_filter['Team'].apply(lambda x: strip(x))
    df_torvik_filter = df_torvik_filter.drop(columns=['Sum'])
    torvik_teams = df_torvik_filter[['Team', 'Rk']].copy()
    # Kenpom Clean
    df_kenpom_filter = df_kenpom[df_kenpom['Sum'] > 0].copy()
    df_kenpom_filter = df_kenpom_filter.drop(columns=['Sum'])
    kenpom_teams = df_kenpom_filter[['Team', 'Rk']].copy()

    # Pull out Top 64
    # Random Forest
    #   Torvik
    rf_filter_torvik = df_torvik_filter[df_torvik_filter['RF'] == 1].head(64)
    df_torvik_rf = rf_filter_torvik[['Team', 'Rk', 'RF']].copy()
    #   Kenpom
    rf_filter_kenpom = df_kenpom_filter[df_kenpom_filter['RF'] == 1].head(64)
    df_kenpom_rf = rf_filter_kenpom[['Team', 'Rk', 'RF']].copy()

    # Decision Tree
    #   Torvik
    dt_filter_torvik = df_torvik_filter[df_torvik_filter['DT'] == 1].head(64)
    df_torvik_dt = dt_filter_torvik[['Team', 'Rk', 'DT']].copy()
    #   Kenpom
    dt_filter_kenpom = df_kenpom_filter[df_kenpom_filter['DT'] == 1].head(64)
    df_kenpom_dt = dt_filter_kenpom[['Team', 'Rk', 'DT']].copy()

    # SVC
    #   Torvik
    svc_filter_torvik = df_torvik_filter[df_torvik_filter['SVC'] == 1].head(64)
    df_torvik_svc = svc_filter_torvik[['Team', 'Rk', 'SVC']].copy()
    #   Kenpom
    svc_filter_kenpom = df_kenpom_filter[df_kenpom_filter['SVC'] == 1].head(64)
    df_kenpom_svc = svc_filter_kenpom[['Team', 'Rk', 'SVC']].copy()

    
    # Torvik Final Clean
    comb1_torvik = pd.merge(torvik_teams, df_torvik_rf, "left", ["Team", "Rk"])
    comb2_torvik = pd.merge(comb1_torvik, df_torvik_svc, "left", ["Team", "Rk"])
    combined_torvik = pd.merge(comb2_torvik, df_torvik_dt, "left", ["Team", "Rk"])
    df_torvik_clean = combined_torvik.dropna(subset=['RF', 'DT', 'SVC'], how= 'all')
    df_torvik_clean.replace(np.nan, False, inplace=True)
    df_torvik_clean['Num Models Made'] = df_torvik_clean[['RF', 'DT', 'SVC']].sum(1)
    df_torvik_clean['Rk'] = pd.to_numeric(df_torvik_clean['Rk'])
    df_torvik_clean['WeightedScore'] = (10 * df_torvik_clean['Num Models Made']) + (80-df_torvik_clean['Rk'])
    df_torvik_clean = df_torvik_clean.rename(columns={'Rk' : 'Torvik Rank'})
    df_torvik_final = df_torvik_clean.drop(columns=['Num Models Made'])

    top64_torvik = df_torvik_final.sort_values("WeightedScore", ascending=False).head(64)
    top64_torvik['MM Rank'] = range(1, 65)
    top64_torvik['Est. Seed'] = np.repeat(range(1,17), 4)
    top64_torvik = top64_torvik[[
        'MM Rank',
        'Torvik Rank',
        'Est. Seed',
        'Team',
        'RF',
        'DT',
        'SVC',
        'WeightedScore'
    ]]

    # Kenpom Final Clean
    comb1_kenpom = pd.merge(kenpom_teams, df_kenpom_rf, "left", ["Team", "Rk"])
    comb2_kenpom = pd.merge(comb1_kenpom, df_kenpom_svc, "left", ["Team", "Rk"])
    combined_kenpom = pd.merge(comb2_kenpom, df_kenpom_dt, "left", ["Team", "Rk"])
    df_kenpom_clean = combined_kenpom.dropna(subset=['RF', 'DT', 'SVC'], how= 'all')
    df_kenpom_clean.replace(np.nan, False, inplace=True)
    df_kenpom_clean['Num Models Made'] = df_kenpom_clean[['RF', 'DT', 'SVC']].sum(1)
    df_kenpom_clean['Rk'] = pd.to_numeric(df_kenpom_clean['Rk'])
    df_kenpom_clean['WeightedScore'] = (10 * df_kenpom_clean['Num Models Made']) + (80-df_kenpom_clean['Rk'])
    df_kenpom_clean = df_kenpom_clean.rename(columns={'Rk' : 'Kenpom Rank'})
    df_kenpom_final = df_kenpom_clean.drop(columns=['Num Models Made'])
    
    main = pd.merge(combined_kenpom, combined_torvik, "left", "Team")
    main['Rk_y'].replace(np.nan, 0, inplace=True)
    main['Rk_x'].replace(np.nan, 0, inplace=True)
    main.replace(np.nan, False, inplace=True)
    
    main['Num KP Models'] = main[['RF_x', 'SVC_x', 'DT_x']].sum(1)
    main['Num TOR Models'] = main[['RF_y', 'SVC_y', 'DT_y']].sum(1)
    main['Rk_y'] = pd.to_numeric(main['Rk_y'])
    main['Rk_x'] = pd.to_numeric(main['Rk_x'])
    main['WeightedScore'] = (((10 * main['Num KP Models']) + (80-main['Rk_x'])) + \
            ((10 * main['Num TOR Models']) + (80-main['Rk_y'])))/2

    main64 = main.sort_values("WeightedScore", ascending=False).head(64)
    main64 =  main64.drop(columns=['RF_x', 'SVC_x', 'DT_x', 'RF_y', 'SVC_y', 'DT_y'])
    main64['Overall Rank'] = range(1, 65)
    main64 = main64.rename(columns={
        'Rk_x' : 'Kenpom Rank', 
        'Rk_y' : 'Torvik Rank',
        'Num KP Models' : '# Models Kenpom',
        'Num TOR Models' : '# Models Torvik'
    })
        
    tab = build_table(main64, 'green_dark')
    html = htmb.add_front_matter(tab, f'Prediction - {date}')
    path = utils.get_path(f'docs/current_model.html')
    with open(path, 'w') as f: 
       f.write(html)  
       print(f'Wrote to: {path} for {date}')
