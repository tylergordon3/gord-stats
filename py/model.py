import kagglehub
import numpy as np
import utils
import pandas as pd

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

HEADERS = {
    'G':'Games',
    'W':'Wins',
    'ADJOE':'Adjusted Offensive Efficiency',
    'ADJDE':'Adjusted Defensive Efficiency',
    'BARTHAG':'Chance of Beating an Average DI Team',
    'EFG_O':'Effective Field Goal Percentage Shot',
    'EFG_D':'Effective Field Goal Percentage Allowed',
    'TOR':'Turnover Rate',
    'TORD':'Steal Rate',
    'ORB':'Offensive Rebound Rate',
    'DRB':'Offensive Rebound Rate Allowed',
    'FTR':'Free Throw Rate',
    'FTRD':'Free Throw Rate Allowed',
    '2P_O':'Two-Point Shooting Percentage',
    '2P_D':'Two-Point Shooting Percentage Allowed',
    '3P_O':'Three-Point Shooting Percentage',
    '3P_D':'Three-Point Shooting Percentage Allowed',
    'ADJ_T':'Adjusted Tempo',
    'WAB':'Wins Above Bubble'
}

def initDataset():
    # Load cbb dataset containing data from 2013-2025
    cbb_full = kagglehub.dataset_load(
        KaggleDatasetAdapter.PANDAS,
        "andrewsundberg/college-basketball-dataset",
        "cbb.csv",
    )
    cbb_full['TOURNEY'] = np.where(cbb_full['POSTSEASON'].notnull(), True, False)
    path = utils.get_path( "/model_data/cbb_data.json")
    utils.save_json_data(cbb_full.to_json(), path)

def trainModelsAndSave(df, update_about):
    
    [cbb, ind, dep] = chiSquared(df)
    [X_train, X_test, y_train, y_test, features] = splitData(cbb, ind)

    if update_about: updateAbout(ind, dep, features, X_train, y_train)

    #[svc, forest, tree, html] = runModels(X_train, X_test, y_train, y_test)
    runModels(X_train, X_test, y_train, y_test)

def splitData(cbb, ind):
    cbb = cbb.drop(columns=ind)
    cbb_features = cbb.iloc[:,:-1]
    cbb_label = cbb['TOURNEY']

    X = cbb_features.values
    y = cbb_label.values  
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=.25, stratify=y, random_state=13)
    scaler = preprocessing.StandardScaler()
    X_train = scaler.fit_transform(X_train)
    X_test = scaler.fit_transform(X_test)
    return [X_train, X_test, y_train, y_test, cbb_features]

def chiSquared(df):
    cbb = df.drop(columns=['TEAM', 'CONF', 'POSTSEASON', 'SEED', 'YEAR', 
                           'G', 'W', 'BARTHAG', 'WAB'])
    cbb_features = cbb.iloc[:,:-1]
    ind = []
    dep = []
    pval = []
    for col in cbb_features:
        csq = chi2_contingency(pd.crosstab(cbb[col], cbb['TOURNEY']))
        pval.append(csq[1])
        if csq[1] > .05:
            ind.append(col)
        else:
            dep.append(col)
    return [cbb, ind, dep]


def runModels(X_train, X_test, y_train, y_test):
    init_forest = RandomForestClassifier(random_state=13)
    init_forest.fit(X_train, y_train)
    forest = trainForest(init_forest, X_train, y_train, X_test, y_test)
    forest_file = utils.get_path('models/forest_model.pkl')
    utils.write_to_pickle(forest, forest_file)

    init_svc = svm.SVC(random_state=13, kernel='linear')
    init_svc.fit(X_train, y_train)
    svc = trainSVC(init_svc, X_train, y_train, X_test, y_test)
    svc_file = utils.get_path('models/svc_model.pkl')
    utils.write_to_pickle(svc, svc_file)

    init_dt = tree.DecisionTreeClassifier(random_state=13)
    init_dt.fit(X_train, y_train)
    dt = trainDT(init_dt, X_train, y_train, X_test, y_test)
    dt_file = utils.get_path('models/dt_model.pkl')
    utils.write_to_pickle(dt, dt_file)

    print('Done with run models.')

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

# *** Updating About Section Functions ***

def updateAbout(ind, dep, features, X_train, y_train):
    html = ''
    html += f'<p><strong>Independent Features:</strong></p>'
    for feature in ind:
        descrip = HEADERS[feature]
        html += f'<p>{feature} - {descrip}</p>'
    html += f'<p><strong>Dependent Features:</strong></p>'
    for feature in dep:
        descrip = HEADERS[feature]
        html += f'<p>{feature} - {descrip}</p>'
    html += aboutSVC(features, X_train, y_train)
    html += aboutForest(features, X_train, y_train)
    html += aboutDecisionTree(features, X_train, y_train)
    utils.save_to_html('/docs/about.html', html)

def aboutSVC(features, X_train, y_train):
    # Train SVC
    svc = svm.SVC(random_state=13, kernel='linear')
    svc.fit(X_train, y_train)
    svc_sort = abs(svc.coef_[0]).argsort()
    fig, ax = plt.subplots()
    ax.barh(features.columns[svc_sort], abs(svc.coef_[0])[svc_sort], color=['green'])
    ax.set_xlabel("Model Coefficients")
    ax.set_title("Model Coefficients for SVC Model")
    tmpfile = BytesIO()
    fig.savefig(tmpfile, format='png')
    encoded = base64.b64encode(tmpfile.getvalue()).decode('utf-8')
    return '<img src=\'data:image/png;base64,{}\'>'.format(encoded)

def aboutForest(features, X_train, y_train):
    init_forest = RandomForestClassifier(random_state=13)
    init_forest.fit(X_train, y_train)
   # Finds feature importance for index/background page
    forest_sort = init_forest.feature_importances_.argsort()
    fig, ax = plt.subplots()
    ax.barh(features.columns[forest_sort], init_forest.feature_importances_[forest_sort], color=['blue'])
    ax.set_xlabel("Feature Importance")
    ax.set_title("Feature Importance for Random Forest")
    tmpfile = BytesIO()
    fig.savefig(tmpfile, format='png')
    encoded = base64.b64encode(tmpfile.getvalue()).decode('utf-8')
    return '<img src=\'data:image/png;base64,{}\'>'.format(encoded)

def aboutDecisionTree(features, X_train, y_train):
    dt = tree.DecisionTreeClassifier(random_state=13)
    dt.fit(X_train, y_train)
    dt_sort = dt.feature_importances_.argsort()
    fig, ax = plt.subplots()
    ax.barh(features.columns[dt_sort], dt.feature_importances_[dt_sort], color=['red'])
    ax.set_xlabel("Feature Importance")
    ax.set_title("Feature Importance for Decision Tree Model")
    tmpfile = BytesIO()
    fig.savefig(tmpfile, format='png')
    encoded = base64.b64encode(tmpfile.getvalue()).decode('utf-8')
    return '<img src=\'data:image/png;base64,{}\'>'.format(encoded)