import json
import warnings
import utils
from io import StringIO
import pandas as pd
from datetime import datetime
from sklearn.metrics import accuracy_score
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
import os
import webbrowser

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
    [X_train, X_test, y_train, y_test] = split_data(df, selected_features)
    clf = LogisticRegression(penalty='l2', C=1.0, solver='liblinear')
    clf.fit(X_train, y_train)
    # ... inside your main() ...

    # 1. PREPARE STATSMODELS DATA
    X_train_sm = sm.add_constant(X_train)
    X_test_sm = sm.add_constant(X_test)

    # 2. FIT STATSMODELS LOGIT (Regularized for your quasi-separation)
    logit_model = sm.Logit(y_train, X_train_sm).fit_regularized(method='l1', alpha=1.0, L1_wt=0.0)
    print(logit_model.summary())
    sm_probs = logit_model.predict(X_test_sm)
    feature_names = ['const'] + list(selected_features)
    
    # 3. COMBINED CALIBRATION PLOT
    plt.figure(figsize=(10, 7))
    # Sklearn Curve
    sk_prob_true, sk_prob_pred = calibration_curve(y_test, sm_probs, n_bins=10)
    plt.plot(sk_prob_pred, sk_prob_true, marker='o', label='Sklearn (L2)')
    # Statsmodels Curve
    sm_prob_true, sm_prob_pred = calibration_curve(y_test, sm_probs, n_bins=10)
    plt.plot(sm_prob_pred, sm_prob_true, marker='s', label='Statsmodels (L1/L2)')

    plt.plot([0, 1], [0, 1], linestyle='--', color='gray', label='Perfectly Calibrated')
    plt.title('Calibration Curve: Sklearn vs Statsmodels')
    plt.legend()
    plt.savefig('calibration_comparison.png')
    plt.close()

    # 4. COMBINED ROC PLOT
    plt.figure(figsize=(10, 7))
    # Use sklearn display for the first one
    ax = plt.gca()
    RocCurveDisplay.from_estimator(clf, X_test, y_test, ax=ax, name='Sklearn')

    # Add Statsmodels manually
    from sklearn.metrics import roc_curve
    fpr, tpr, _ = roc_curve(y_test, sm_probs)
    auc_sm = roc_auc_score(y_test, sm_probs)
    plt.plot(fpr, tpr, label=f'Statsmodels (AUC = {auc_sm:.3f})')

    plt.plot([0, 1], [0, 1], color='navy', linestyle='--')
    plt.title('ROC Curve Comparison')
    plt.legend()
    plt.savefig('roc_comparison.png')
    plt.close()

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