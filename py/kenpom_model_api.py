import json
import warnings
import utils
from io import StringIO
import pandas as pd
from datetime import datetime
from sklearn.metrics import accuracy_score, roc_curve
from sklearn import tree, preprocessing, svm
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split, GridSearchCV
from sklearn.metrics import classification_report
from sklearn.metrics import confusion_matrix
from sklearn.feature_selection import SelectFromModel
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
import statsmodels.api as sm
from sklearn.calibration import calibration_curve
from sklearn.metrics import RocCurveDisplay, roc_auc_score
import matplotlib.pyplot as plt
import numpy as np
from sklearn.metrics import brier_score_loss

warnings.filterwarnings("ignore")

def filter_api_data(df):
    objs = []
    vals = []
    ranks = []
    exceptions = ['Season', 'Seed']
    for col in df.columns:
        if col in exceptions:
            objs.append(col)
        elif df[col].dtype == float or df[col].dtype == bool :
            vals.append(col)
        elif df[col].dtype == int:
            ranks.append(col)
        else:
            objs.append(col)
    to_drop = objs + ranks
    return df.drop(columns=to_drop)

def load_data():
    with open(utils.get_path(f"model_data/kenpom_api/all.json"), 'r') as f:
        data = json.load(f)
    filtered = filter_api_data(pd.read_json(StringIO(data)))
    return filtered

def feature_selection(df):
    X = df.drop('Tourney', axis=1)
    y = df["Tourney"]

    # 1. Scaling is vital for L1 feature selection
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # 2. Use Logistic Regression with L1 penalty
    # Solver 'liblinear' or 'saga' is required for L1
    # C controls sparsity: smaller C = fewer features selected
    selector = SelectFromModel(
        estimator=LogisticRegression(penalty='l1', solver='liblinear', C=0.1),
        threshold=1e-5
    )

    X_new = selector.fit_transform(X_scaled, y)

    # 3. See which features survived
    selected_features = X.columns[selector.get_support()]
    #print(f"Kept {len(selected_features)} (out of {len(X.columns)}) features: {list(selected_features)}")

    return selected_features

def split_data(input_df, features):
    label = input_df['Tourney']
    df = input_df[features]

    X = df.values
    y = label.values
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, stratify=y, random_state=13
    )
    scaler = preprocessing.StandardScaler()
    X_train = scaler.fit_transform(X_train)
    X_test = scaler.fit_transform(X_test)
    return [X_train, X_test, y_train, y_test]

def main():
    start = datetime.now()
    df = load_data()
    selected_features = feature_selection(df)
    selected_features = selected_features[1:]
    # Ensure features match data
    [X_train, X_test, y_train, y_test] = split_data(df, selected_features)
    
    # 1. GRID SEARCH (Find the best hyperparameters)
    log_reg = LogisticRegression(max_iter=1000)
    param_grid = {
        'C': np.logspace(-4, 4, 10),
        'penalty': ['l1', 'l2'],
        'solver': ['liblinear']
    }
    
    grid_search = GridSearchCV(log_reg, param_grid, cv=5, scoring='roc_auc', n_jobs=-1)
    grid_search.fit(X_train, y_train)
    
    print(f"Best Parameters: {grid_search.best_params_}")
    best_clf = grid_search.best_estimator_ # Use this model moving forward
    sk_probs = best_clf.predict_proba(X_test)[:, 1]

    # 2. STATSMODELS (Statistical Insight)
    X_train_sm = sm.add_constant(X_train)
    X_test_sm = sm.add_constant(X_test)
    
    # To match your Grid Search 'l1' and C=0.359
    # alpha in statsmodels is roughly 1 / (N * C)
    # Let's use alpha=1.0 for simplicity as it produced a stable result
    logit_res = sm.Logit(y_train, X_train_sm).fit_regularized(
        method='l1', 
        alpha=1.0, 
        L1_wt=1.0  # Changed to 1.0 to match the 'l1' penalty found by Grid Search
    )
    print(logit_res.summary())
    print("\n--- Statsmodels Coefficients ---")
    print(logit_res.params) # Manual print since .summary() is unavailable
    
    sm_probs = logit_res.predict(X_test_sm)
    brier = brier_score_loss(y_test, sm_probs)
    print(f"Brier Score: {brier:.4f}")
    print(f"Time elapsed: {datetime.now() - start}")

if __name__ == "__main__":
    main()
'''
def runModels(X_train, X_test, y_train, y_test):
    start = datetime.now()
    init_forest = RandomForestClassifier(random_state=13)
    init_forest.fit(X_train, y_train)
    forest = trainForest(init_forest, X_train, y_train, X_test, y_test)
    forest_file = utils.get_path("models/mkp_forest_model.pkl")
    utils.write_to_pickle(forest, forest_file)
    print(
        f"Kenpom Forest Model Training took: {(datetime.now() - start).total_seconds()}"
    )
    init_svc = svm.SVC(random_state=13, kernel="linear")
    init_svc.fit(X_train, y_train)
    svc = trainSVC(init_svc, X_train, y_train, X_test, y_test)
    svc_file = utils.get_path("models/mkp_svc_model.pkl")
    utils.write_to_pickle(svc, svc_file)
    print(f"Kenpom SVC Model Training took: {(datetime.now() - start).total_seconds()}")
    init_dt = tree.DecisionTreeClassifier(random_state=13)
    init_dt.fit(X_train, y_train)
    dt = trainDT(init_dt, X_train, y_train, X_test, y_test)
    dt_file = utils.get_path("models/mkp_dt_model.pkl")
    utils.write_to_pickle(dt, dt_file)
    print(
        f"Kenpom Decision Tree Model Training took: {(datetime.now() - start).total_seconds()}"
    )

def trainDT(init_dt, X_train, y_train, X_test, y_test):
    params = dtParams(init_dt, X_train, y_train)
    dt_model = tree.DecisionTreeClassifier(
        criterion=params["criterion"],
        max_depth=params["max_depth"],
        max_features=params["max_features"],
        ccp_alpha=params["ccp_alpha"],
        random_state=13,
    )
    dt_model.fit(X_train, y_train)
    dt_pred = dt_model.predict(X_test)
    print(classification_report(y_test, dt_pred))
    return dt_model

def dtParams(init_dt, X_train, y_train):
    dt_params = {
        "ccp_alpha": [0.1, 0.01, 0.001],
        "criterion": ["gini", "entropy"],
        "max_depth": [4, 5, 6, 7, 8],
        "max_features": ["auto", "sqrt", "log2"],
    }
    CV_dt = GridSearchCV(estimator=init_dt, param_grid=dt_params)
    CV_dt.fit(X_train, y_train)
    params = CV_dt.best_params_
    return params

def trainSVC(init_svc, X_train, y_train, X_test, y_test):
    params = svcParams(init_svc, X_train, y_train)
    svc_model = svm.SVC(
        C=params["C"], gamma=params["gamma"], kernel="linear", random_state=13
    )
    svc_model.fit(X_train, y_train)
    svc_pred = svc_model.predict(X_test)
    print(classification_report(y_test, svc_pred))
    return svc_model

def svcParams(init_svc, X_train, y_train):
    svc_params = {
        "C": [0.1, 1, 10, 100],
        "gamma": ["scale", "auto"],
    }
    CV_svc = GridSearchCV(estimator=init_svc, param_grid=svc_params)
    CV_svc.fit(X_train, y_train)
    params = CV_svc.best_params_
    return params

def trainForest(init_forest, X_train, y_train, X_test, y_test):
    params = forestParams(init_forest, X_train, y_train)
    forest_model = RandomForestClassifier(
        criterion=params["criterion"],
        max_depth=params["max_depth"],
        max_features=params["max_features"],
        n_estimators=params["n_estimators"],
        random_state=13,
    )
    forest_model.fit(X_train, y_train)
    return forest_model

def forestParams(init_forest, X_train, y_train):
    forest_params = {
        "n_estimators": [100, 300, 500],
        "criterion": ["gini", "entropy"],
        "max_depth": [4, 5, 6, 7, 8],
        "max_features": ["auto", "sqrt", "log2"],
    }
    CV_forest = GridSearchCV(estimator=init_forest, param_grid=forest_params)
    CV_forest.fit(X_train, y_train)
    params = CV_forest.best_params_
    return params
'''