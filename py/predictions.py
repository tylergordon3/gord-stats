import utils
import pandas as pd
import numpy as np
from sklearn import preprocessing
import html_builder as htmb
from pretty_html_table import build_table

def predict(date):
    randomForest = utils.read_from_pickle('forest')
    decisionTree = utils.read_from_pickle('dt')
    supportVC = utils.read_from_pickle('svc')
    
    [kenpom_path, torvik_path] = utils.get_recent_data(date)
    kenpom_data = utils.load_json_data(kenpom_path)
    torvik_data = utils.load_json_data(torvik_path)

    teams = torvik_data['Team']
   
    cbb_now = torvik_data.drop(columns=['Barthag', 'WAB','Team', 'Conf', 'Rec', 'G', 'Rk', 'FTR', '3PR', '3PRD'])
    scaler = preprocessing.StandardScaler()
    x_predict = scaler.fit_transform(cbb_now)
    forest_predict = randomForest.predict(x_predict)
    torvik_data['RF'] = forest_predict

    dt_predict = decisionTree.predict(x_predict)
    torvik_data['DT'] = dt_predict

    svc_predict = supportVC.predict(x_predict)
    torvik_data['SVC'] = svc_predict
    torvik_data['Sum'] = torvik_data[['RF', 'DT', 'SVC']].sum(1)
    df = torvik_data[['Rk', 'Team', 'RF', 'DT', 'SVC', 'Sum']].copy()

    def strip(team):
        for i, char in enumerate(team):
            if char == '(':
                return team[:i]
            if team[i:i+3] == 'vs.':
                return team[:i]
        return team

    df_filter = df[df['Sum'] > 0].copy()
    df_filter['Team'] = df_filter['Team'].apply(lambda x: strip(x))
    df_filter = df_filter.drop(columns=['Sum'])
    teams = df_filter[['Team', 'Rk']].copy()

    rf_filter = df_filter[df_filter['RF'] == 1].head(64)
    df_rf = rf_filter[['Team', 'Rk', 'RF']].copy()
    
    dt_filter = df_filter[df_filter['DT'] == 1].head(64)
    df_dt = dt_filter[['Team', 'Rk', 'DT']].copy()

    svc_filter = df_filter[df_filter['SVC'] == 1].head(64)
    df_svc = svc_filter[['Team', 'Rk', 'SVC']].copy()

    comb1 = pd.merge(teams, df_rf, "left", ["Team", "Rk"])
    comb2 = pd.merge(comb1, df_svc, "left", ["Team", "Rk"])
    combined = pd.merge(comb2, df_dt, "left", ["Team", "Rk"])
    df_clean = combined.dropna(subset=['RF', 'DT', 'SVC'], how= 'all')
    df_clean.replace(np.nan, False, inplace=True)
    df_clean['Num Models Made'] = df_clean[['RF', 'DT', 'SVC']].sum(1)
    df_clean['Rk'] = pd.to_numeric(df_clean['Rk'])
    df_clean['WeightedScore'] = (10 * df_clean['Num Models Made']) + (80-df_clean['Rk'])
    df_clean = df_clean.rename(columns={'Rk' : 'Torvik Rank'})
    df_final = df_clean.drop(columns=['Num Models Made'])
    top64 = df_final.sort_values("WeightedScore", ascending=False).head(64)
    top64['MM Rank'] = range(1, 65)
    top64['Est. Seed'] = np.repeat(range(1,17), 4)
    top64 = top64[[
        'MM Rank',
        'Torvik Rank',
        'Est. Seed',
        'Team',
        'RF',
        'DT',
        'SVC',
        'WeightedScore'
    ]]
    
    tab = build_table(top64, 'green_dark')
    html = htmb.add_front_matter(tab,f'Prediction - {date}')
    path = utils.get_path(f'docs/predict_{date}.html')
    with open(path, 'w') as f: 
       f.write(html)  
