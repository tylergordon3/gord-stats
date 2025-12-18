import numpy as np
import utils
import pandas as pd
from datetime import datetime
from scipy.stats import chi2_contingency
from kagglehub import KaggleDatasetAdapter
from sklearn import tree, preprocessing, svm
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split, GridSearchCV
import matplotlib.pyplot as plt
import base64
from io import BytesIO
from sklearn.metrics import classification_report, confusion_matrix
import warnings

warnings.filterwarnings("ignore")

def trainModelsAndSave(df): 
    start = datetime.now()
    [cbb, ind] = chiSquared(df)
    [X_train, X_test, y_train, y_test] = splitData(cbb, ind)
    print(f'Kenpom data set split took: {(datetime.now() - start).total_seconds()}')
    #[svc, forest, tree, html] = runModels(X_train, X_test, y_train, y_test)
    runModels(X_train, X_test, y_train, y_test)

def splitData(cbb, ind):
    cbb = cbb.drop(columns=ind)
    cbb_features = cbb.iloc[:,1:]
    cbb_label = cbb['Tourney']

    X = cbb_features.values
    y = cbb_label.values  
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=.25, stratify=y, random_state=13)
    scaler = preprocessing.StandardScaler()
    X_train = scaler.fit_transform(X_train)
    X_test = scaler.fit_transform(X_test)
    return [X_train, X_test, y_train, y_test]

def chiSquared(df):
    cbb = df.drop(columns=['Rk','Team', 'Seed', 'Conf', 'Year', 
                           'W-L', 'Luck_Rk', 'ORtg_Rk', 'DRtg_Rk',
                           'SOS_NetRtg_Rk', 'SOS_ORtg_Rk', 'SOS_DRtg_Rk', 
                           'NCSOS_NetRtg_Rk', "AdjT_Rk"])
    cbb_features = cbb.iloc[:,:-1]
    
    ind = []
    dep = []
    pval = []
    for col in cbb_features:
        csq = chi2_contingency(pd.crosstab(cbb[col], cbb['Tourney']))
        pval.append(csq[1])
        if csq[1] > .05:
            ind.append(col)
        else:
            dep.append(col)
    return [cbb, ind]


def runModels(X_train, X_test, y_train, y_test):
    start = datetime.now()
    init_forest = RandomForestClassifier(random_state=13)
    init_forest.fit(X_train, y_train)
    forest = trainForest(init_forest, X_train, y_train, X_test, y_test)
    forest_file = utils.get_path('models/mkp_forest_model.pkl')
    utils.write_to_pickle(forest, forest_file)
    print(f'Kenpom Forest Model Training took: {(datetime.now() - start).total_seconds()}')
    init_svc = svm.SVC(random_state=13, kernel='linear')
    init_svc.fit(X_train, y_train)
    svc = trainSVC(init_svc, X_train, y_train, X_test, y_test)
    svc_file = utils.get_path('models/mkp_svc_model.pkl')
    utils.write_to_pickle(svc, svc_file)
    print(f'Kenpom SVC Model Training took: {(datetime.now() - start).total_seconds()}')
    init_dt = tree.DecisionTreeClassifier(random_state=13)
    init_dt.fit(X_train, y_train)
    dt = trainDT(init_dt, X_train, y_train, X_test, y_test)
    dt_file = utils.get_path('models/mkp_dt_model.pkl')
    utils.write_to_pickle(dt, dt_file)
    print(f'Kenpom Decision Tree Model Training took: {(datetime.now() - start).total_seconds()}')

def trainDT(init_dt, X_train, y_train, X_test, y_test):
    params = dtParams(init_dt, X_train, y_train)
    dt_model = tree.DecisionTreeClassifier(criterion=params['criterion'], max_depth=params['max_depth'],
        max_features=params['max_features'], ccp_alpha=params['ccp_alpha'], random_state=13)
    dt_model.fit(X_train, y_train)
    dt_pred = dt_model.predict(X_test)
    print(classification_report(y_test, dt_pred))
    return dt_model

def dtParams(init_dt, X_train, y_train):
    dt_params = {
    'ccp_alpha' : [0.1, .01, .001],
    'criterion' : ['gini', 'entropy'],
    'max_depth' : [4, 5, 6, 7, 8],
    'max_features' : ['auto', 'sqrt', 'log2']
    }
    CV_dt = GridSearchCV(estimator=init_dt, param_grid=dt_params)
    CV_dt.fit(X_train, y_train)
    params = CV_dt.best_params_
    return params

def trainSVC(init_svc, X_train, y_train, X_test, y_test):
    params = svcParams(init_svc, X_train, y_train)
    svc_model = svm.SVC(C=params['C'], gamma=params['gamma'], kernel='linear', random_state=13)
    svc_model.fit(X_train, y_train)
    svc_pred = svc_model.predict(X_test)
    print(classification_report(y_test, svc_pred))
    return svc_model

def svcParams(init_svc, X_train, y_train):
    svc_params = {
        'C' : [0.1, 1, 10, 100],
        'gamma' : ['scale', 'auto'],
    }
    CV_svc = GridSearchCV(estimator=init_svc, param_grid=svc_params)
    CV_svc.fit(X_train, y_train)
    params = CV_svc.best_params_
    return params

def trainForest(init_forest, X_train, y_train, X_test, y_test):
    params = forestParams(init_forest, X_train, y_train)
    forest_model = RandomForestClassifier(criterion=params['criterion'], max_depth=params['max_depth'],
        max_features=params['max_features'], n_estimators=params['n_estimators'], random_state=13)
    forest_model.fit(X_train, y_train)
    return forest_model

def forestParams(init_forest, X_train, y_train):
    forest_params = {
    'n_estimators' : [100, 300, 500],
    'criterion' : ['gini', 'entropy'],
    'max_depth' : [4, 5, 6, 7, 8],
    'max_features' : ['auto', 'sqrt', 'log2']
    }   
    CV_forest = GridSearchCV(estimator=init_forest, param_grid=forest_params)
    CV_forest.fit(X_train, y_train)
    params = CV_forest.best_params_
    return params