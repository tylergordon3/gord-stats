import json
import warnings
import utils
import pandas as pd
import numpy as np
from io import StringIO
from datetime import datetime

from sklearn import tree, preprocessing, svm
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split, GridSearchCV
from sklearn.metrics import classification_report, roc_auc_score, brier_score_loss
from sklearn.feature_selection import SelectFromModel, RFE
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

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

def feature_selection(df, n_features=12):
    X = df.drop('Tourney', axis=1)
    y = df["Tourney"]
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Method 1: Lasso (Your current method)
    lasso = SelectFromModel(LogisticRegression(penalty='l1', solver='liblinear', C=0.1))
    lasso.fit(X_scaled, y)
    
    # Method 2: RFE (Recursive Elimination)
    rfe = RFE(estimator=LogisticRegression(max_iter=1000), n_features_to_select=n_features)
    rfe.fit(X_scaled, y)

    # Method 3: Random Forest Importance
    rf = SelectFromModel(RandomForestClassifier(n_estimators=100), max_features=n_features)
    rf.fit(X_scaled, y)

    # Create a "Voting" mask (Feature must be picked by at least 2 methods)
    votes = lasso.get_support().astype(int) + rfe.support_.astype(int) + rf.get_support().astype(int)
    consensus_mask = votes >= 2
    
    return X.columns[consensus_mask]

def split_data(input_df, features):
    y = input_df['Tourney'].values
    X = input_df[features].values

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, stratify=y, random_state=13
    )

    scaler = StandardScaler()
    X_train = scaler.fit_transform(X_train)
    X_test = scaler.transform(X_test)

    return [X_train, X_test, y_train, y_test]

def automate_refinement(X, y, feature_names, threshold=4.0):
    if isinstance(X, np.ndarray):
        X = pd.DataFrame(X, columns=feature_names)
    
    current_features = list(X.columns)
    
    while True:
        print(f"\nEvaluating model with {len(current_features)} features...")
        X_train_curr = X[current_features]
        
        param_grid = {'C': np.logspace(-3, 2, 6), 'penalty': ['l1', 'l2'], 'solver': ['liblinear']}
        grid = GridSearchCV(LogisticRegression(max_iter=2000), param_grid, cv=5, scoring='roc_auc')
        grid.fit(X_train_curr, y)
        
        best_model = grid.best_estimator_
        coeffs = pd.Series(best_model.coef_[0], index=current_features)

        max_coef = coeffs.abs().max()
        top_feature = coeffs.abs().idxmax()
    
        if max_coef > threshold:
            print(f"DROPPING '{top_feature}': Likely data leakage or causing separation.")
            current_features.remove(top_feature)
        else:
            print("Model is stable. No features exceed the leakage threshold.")
            return best_model, current_features

def main():
    start = datetime.now()
    df = load_data()
    selected_features = feature_selection(df)
    [X_train, X_test, y_train, y_test] = split_data(df, selected_features)
    best_clf, final_features = automate_refinement(X_train, y_train, selected_features, threshold=4.0)
    
    X_test_df = pd.DataFrame(X_test, columns=selected_features)
    X_test_final = X_test_df[final_features]
    
    # 4. Final Evaluation
    y_pred = best_clf.predict(X_test_final)
    y_probs = best_clf.predict_proba(X_test_final)[:, 1]
    n_tourney_teams = sum(y_test)
    # Sort probabilities and pick the top 'n'
    thresh = np.sort(y_probs)[-n_tourney_teams]
    y_pred_adj = (y_probs >= thresh).astype(int)
    print("\n" + "="*30)
    print("FINAL MODEL PERFORMANCE")
    print("="*30)
    print(f"Final Features: {final_features}")
    print(classification_report(y_test, y_pred_adj))
    print(f"ROC-AUC Score: {roc_auc_score(y_test, y_probs):.4f}")
    print(f"Brier Score:   {brier_score_loss(y_test, y_probs):.4f}")
    
    # 5. Output Odds Ratios for Interpretation
    coeffs = pd.Series(best_clf.coef_[0], index=final_features)
    odds_ratios = np.exp(coeffs).sort_values(ascending=False)
    print("\nTop Odds Ratios (Impact per 1-SD increase):")
    print(odds_ratios.head(5))
    # After your existing code in main():
    test_results = pd.DataFrame({
        'Actual': y_test,
        'Probability': y_probs,
        'Predicted': y_pred
    })

    # Identify the "Snubs" (Model said IN, Committee said OUT)
    false_positives = test_results[(test_results['Actual'] == 0) & (test_results['Predicted'] == 1)]
    print(f"\nModel's 'False Alarms' (Bubble teams that missed): {len(false_positives)}")
    print(f"\nExecution Time: {datetime.now() - start}")

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