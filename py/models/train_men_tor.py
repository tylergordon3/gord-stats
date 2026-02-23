from sklearn.ensemble import GradientBoostingClassifier, HistGradientBoostingClassifier
from sklearn.ensemble import AdaBoostClassifier, RandomForestClassifier
from sklearn.svm import SVC
from sklearn.linear_model import LogisticRegression
from sklearn.feature_selection import RFECV, SelectFromModel
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import roc_auc_score, brier_score_loss
from sklearn.tree import DecisionTreeClassifier
from sklearn.model_selection import (
    train_test_split,
    StratifiedKFold,
    GridSearchCV,
)


'''
Hist GB
GB
SVC
Log Reg
Ada
'''
import joblib
import json
from pathlib import Path
from datetime import datetime
import pandas as pd
import numpy as np
from ..lib import paths, help

DROP = [
        "TEAM",
        "CONF",
        "YEAR",
        "SEED",
        "POSTSEASON",
        "G",
        "W"
    ]

CV = StratifiedKFold(n_splits=5, shuffle=True, random_state=13)

def load():
    filename = paths.M_TOR_TRAIN_ALL
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            data = json.loads(json.load(f))
            df = pd.DataFrame(data)
            print(f"Data successfully loaded from {filename}")
    except FileNotFoundError:
            print(f"Error: File '{filename}' not found.")
    except json.JSONDecodeError as e:
            print(f"Error decoding JSON from {filename}: {e}")
    except IOError as e:
            print(f"Error loading data from {filename}: {e}")

    return df

def save_ensemble_model(ensemble_package, version):

    models_dir = paths.ML_2026_DIR
    models_dir.mkdir(parents=True, exist_ok=True)

    filename = f"men_tor_{version}.pkl"
    filepath = models_dir / filename

    ensemble_package["saved_at"] = datetime.utcnow().isoformat()

    joblib.dump(ensemble_package, filepath)

    print(f"\nModel saved to: {filepath}")

def filter_cols(df):
    df = df.copy()
    df = df.drop(columns=DROP, errors="ignore")

    #df["TOURNEY"] = df["TOURNEY"].map({"True": 1, "False": 0})
    #print(pd.unique(df["TOURNEY"]))
    #if "WAB" in df.columns:
    #    df["WAB"] = df["WAB"].str.replace("+", "", regex=False)
    #for col in df.columns:
    #    if col != "TOURNEY":
    #        df[col] = pd.to_numeric(df[col], errors="coerce")
    #df = df.dropna()

    return df


def train_logistic(X, y):
    # ---------------------------
    # 1. Train/Test Split
    # ---------------------------
    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.25,
        stratify=y,
        random_state=13,
    )

    # ---------------------------
    # 2. Feature Selection (RFECV)
    # ---------------------------
    base_pipeline = Pipeline(
        [
            ("scaler", StandardScaler()),
            ("model", LogisticRegression(max_iter=5000, class_weight="balanced")),
        ]
    )

    rfecv = RFECV(
        estimator=base_pipeline,
        step=1,
        cv=StratifiedKFold(5, shuffle=True, random_state=13),
        scoring="roc_auc",
        importance_getter="named_steps.model.coef_",
        n_jobs=-1,
    )

    rfecv.fit(X_train, y_train)

    selected_features = X.columns[rfecv.support_]

    # ---------------------------
    # 3. Hyperparameter Tuning
    # ---------------------------
    tuned_pipeline = Pipeline(
        [
            ("scaler", StandardScaler()),
            ("model", LogisticRegression(max_iter=5000, class_weight="balanced")),
        ]
    )

    param_grid = {
        "model__C": np.logspace(-3, 2, 8),
        "model__solver": ["liblinear"],
    }

    grid = GridSearchCV(
        tuned_pipeline,
        param_grid,
        scoring="roc_auc",
        cv=StratifiedKFold(5, shuffle=True, random_state=13),
        n_jobs=-1,
    )

    grid.fit(X_train[selected_features], y_train)

    best_model = grid.best_estimator_

    # ---------------------------
    # 4. Evaluate on Test Set
    # ---------------------------
    test_probs = best_model.predict_proba(X_test[selected_features])[:, 1]

    test_auc = roc_auc_score(y_test, test_probs)
    test_brier = brier_score_loss(y_test, test_probs)

    return {
        "model": best_model,
        "features": selected_features,
        "test_auc": test_auc,
        "test_brier": test_brier,
    }

def train_svc(X, y):
    # 1. Train/Test Split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, stratify=y, random_state=13
    )

    # 2. Feature Selection (RFECV)
    # SVC with a linear kernel is required to get 'coef_' for RFECV
    # Using a smaller C to speed up the selection process
    selector_model = SVC(kernel="linear", C=0.1, random_state=13, class_weight="balanced")

    rfecv = RFECV(
        estimator=selector_model,
        step=1,
        cv=StratifiedKFold(5, shuffle=True, random_state=13),
        scoring="roc_auc",
        n_jobs=-1,
    )

    # Scaling is mandatory for SVM
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    
    rfecv.fit(X_train_scaled, y_train)
    selected_features = X.columns[rfecv.support_]

    # 3. Hyperparameter Tuning
    # We use a Pipeline to ensure scaling is done correctly within CV folds
    pipe = Pipeline([
        ('scaler', StandardScaler()),
        ('svc', SVC(probability=True, random_state=13, class_weight="balanced"))
    ])

    # Smaller, high-impact grid for SVC
    param_grid = {
        "svc__C": [0.1, 1, 10],
        "svc__gamma": ["scale", "auto"],
        "svc__kernel": ["rbf", "linear"]
    }

    grid = GridSearchCV(
        pipe,
        param_grid,
        scoring="roc_auc",
        cv=StratifiedKFold(5, shuffle=True, random_state=13),
        n_jobs=-1,
    )

    grid.fit(X_train[selected_features], y_train)
    best_model = grid.best_estimator_

    # 4. Evaluate on Test Set
    test_probs = best_model.predict_proba(X_test[selected_features])[:, 1]
    test_auc = roc_auc_score(y_test, test_probs)
    test_brier = brier_score_loss(y_test, test_probs)

    return {
        "model": best_model,
        "features": selected_features,
        "test_auc": test_auc,
        "test_brier": test_brier,
    }

def train_adaboost(X, y):

    # ---------------------------
    # 1. Train/Test Split
    # ---------------------------
    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.25,
        stratify=y,
        random_state=13,
    )

    # ---------------------------
    # 2. Feature Selection (RFECV)
    # ---------------------------
    base_model = AdaBoostClassifier(
        estimator=DecisionTreeClassifier(max_depth=2),
        n_estimators=300,
        learning_rate=0.1,
        random_state=13,
    )

    rfecv = RFECV(
        estimator=base_model,
        step=1,
        cv=StratifiedKFold(5, shuffle=True, random_state=13),
        scoring="roc_auc",
        n_jobs=-1,
    )

    rfecv.fit(X_train, y_train)

    selected_features = X.columns[rfecv.support_]

    # ---------------------------
    # 3. Hyperparameter Tuning
    # ---------------------------
    param_grid = {
        "n_estimators": [200, 300, 500],
        "learning_rate": [0.01, 0.05, 0.1, 0.2],
        "estimator__max_depth": [1, 2, 3],
    }

    grid = GridSearchCV(
        AdaBoostClassifier(estimator=DecisionTreeClassifier(), random_state=13),
        param_grid,
        scoring="roc_auc",
        cv=StratifiedKFold(5, shuffle=True, random_state=13),
        n_jobs=-1,
    )

    grid.fit(X_train[selected_features], y_train)

    best_model = grid.best_estimator_

    # ---------------------------
    # 4. Evaluate on Test Set
    # ---------------------------
    test_probs = best_model.predict_proba(X_test[selected_features])[:, 1]

    test_auc = roc_auc_score(y_test, test_probs)
    test_brier = brier_score_loss(y_test, test_probs)

    return {
        "model": best_model,
        "features": selected_features,
        "test_auc": test_auc,
        "test_brier": test_brier,
    }


def train_gradient_boost(X, y):

    # ---------------------------
    # 1. Train/Test Split
    # ---------------------------
    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.25,
        stratify=y,
        random_state=13,
    )

    # ---------------------------
    # 2. Feature Selection (RFECV)
    # ---------------------------
    base_model = GradientBoostingClassifier(
        n_estimators=300,
        learning_rate=0.05,
        max_depth=3,
        random_state=13,
    )

    rfecv = RFECV(
        estimator=base_model,
        step=1,
        cv=StratifiedKFold(5, shuffle=True, random_state=13),
        scoring="roc_auc",
        n_jobs=-1,
    )

    rfecv.fit(X_train, y_train)

    selected_features = X.columns[rfecv.support_]

    # ---------------------------
    # 3. Hyperparameter Tuning
    # ---------------------------
    param_grid = {
        "n_estimators": [200, 300, 500],
        "learning_rate": [0.01, 0.05, 0.1],
        "max_depth": [2, 3, 4],
        "min_samples_leaf": [1, 5, 10],
        "subsample": [0.6, 0.8, 1.0],
    }

    grid = GridSearchCV(
        GradientBoostingClassifier(random_state=13),
        param_grid,
        scoring="roc_auc",
        cv=StratifiedKFold(5, shuffle=True, random_state=13),
        n_jobs=-1,
    )

    grid.fit(X_train[selected_features], y_train)

    best_model = grid.best_estimator_

    # ---------------------------
    # 4. Evaluate on Test Set
    # ---------------------------
    test_probs = best_model.predict_proba(X_test[selected_features])[:, 1]

    test_auc = roc_auc_score(y_test, test_probs)
    test_brier = brier_score_loss(y_test, test_probs)

    return {
        "model": best_model,
        "features": selected_features,
        "test_auc": test_auc,
        "test_brier": test_brier,
    }


def train_hist_gradient_boost(X, y):

    # ---------------------------
    # 1. Train/Test Split
    # ---------------------------
    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.25,
        stratify=y,
        random_state=13,
    )

    # ---------------------------
    # 2. Feature Selection
    #    (Using RandomForest importance)
    # ---------------------------
    selector_model = RandomForestClassifier(
        n_estimators=500, random_state=13, class_weight="balanced"
    )

    selector_model.fit(X_train, y_train)

    selector = SelectFromModel(selector_model, threshold="median")  # keep top 50%

    selector.fit(X_train, y_train)

    selected_features = X.columns[selector.get_support()]

    # ---------------------------
    # 3. Hyperparameter Tuning
    # ---------------------------
    param_grid = {
        "learning_rate": [0.01, 0.03, 0.05, 0.1],
        "max_iter": [200, 300, 500],
        "max_depth": [None, 3, 5],
        "min_samples_leaf": [20, 40, 80],
        "l2_regularization": [0.0, 0.1, 1.0],
    }

    grid = GridSearchCV(
        HistGradientBoostingClassifier(random_state=13),
        param_grid,
        scoring="roc_auc",
        cv=StratifiedKFold(5, shuffle=True, random_state=13),
        n_jobs=-1,
    )

    grid.fit(X_train[selected_features], y_train)

    best_model = grid.best_estimator_

    # ---------------------------
    # 4. Evaluate on Test Set
    # ---------------------------
    test_probs = best_model.predict_proba(X_test[selected_features])[:, 1]

    test_auc = roc_auc_score(y_test, test_probs)
    test_brier = brier_score_loss(y_test, test_probs)

    return {
        "model": best_model,
        "features": selected_features,
        "test_auc": test_auc,
        "test_brier": test_brier,
    }


def generate_oof_predictions(model_fn, X, y, n_splits=5):
    """
    model_fn: function that trains and returns {"model", "features"}
    """
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=13)

    oof_preds = np.zeros(len(y))

    for train_idx, val_idx in skf.split(X, y):

        X_train, X_val = X.iloc[train_idx], X.iloc[val_idx]
        y_train, y_val = y[train_idx], y[val_idx]

        result = model_fn(X_train, y_train)

        model = result["model"]
        features = result["features"]

        preds = model.predict_proba(X_val[features])[:, 1]

        oof_preds[val_idx] = preds

    return oof_preds


def train_stacked_ensemble(X, y):

    # ---------------------------
    # 1. Train/Test Split
    # ---------------------------
    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.25,
        stratify=y,
        random_state=13,
    )

    print("\nGenerating OOF predictions...")

    log_oof = generate_oof_predictions(train_logistic, X_train, y_train)
    svc_oof = generate_oof_predictions(train_svc, X_train, y_train)
    ada_oof = generate_oof_predictions(train_adaboost, X_train, y_train)
    gb_oof = generate_oof_predictions(train_gradient_boost, X_train, y_train)
    hgb_oof = generate_oof_predictions(train_hist_gradient_boost, X_train, y_train)

    # ---------------------------
    # 2. Train Meta Model
    # ---------------------------
    meta_X_train = np.column_stack([log_oof, svc_oof, ada_oof, gb_oof, hgb_oof])

    meta_model = LogisticRegression(max_iter=5000)
    meta_model.fit(meta_X_train, y_train)

    print("\nMeta-model trained.")

    # ---------------------------
    # 3. Fit Base Models on FULL training set
    # ---------------------------
    log_full = train_logistic(X_train, y_train)
    svc_full = train_svc(X_train, y_train)
    ada_full = train_adaboost(X_train, y_train)
    gb_full = train_gradient_boost(X_train, y_train)
    hgb_full = train_hist_gradient_boost(X_train, y_train)

    # ---------------------------
    # 4. Generate Test Predictions
    # ---------------------------
    log_test = log_full["model"].predict_proba(X_test[log_full["features"]])[:, 1]

    svc_test = svc_full["model"].predict_proba(X_test[svc_full["features"]])[:, 1]

    ada_test = ada_full["model"].predict_proba(X_test[ada_full["features"]])[:, 1]

    gb_test = gb_full["model"].predict_proba(X_test[gb_full["features"]])[:, 1]

    hgb_test = hgb_full["model"].predict_proba(X_test[hgb_full["features"]])[:, 1]

    meta_X_test = np.column_stack([log_test, svc_test, ada_test, gb_test, hgb_test])

    ensemble_probs = meta_model.predict_proba(meta_X_test)[:, 1]

    # ---------------------------
    # 5. Evaluate
    # ---------------------------
    test_auc = roc_auc_score(y_test, ensemble_probs)
    test_brier = brier_score_loss(y_test, ensemble_probs)

    print("\nSTACKED MODEL RESULTS")
    print("Test ROC AUC:", test_auc)
    print("Test Brier:", test_brier)

    ensemble_package = {
        "version": "2-23-2026",
        "meta_model": meta_model,
        "base_models": {
            "logistic": log_full,
            "svc": svc_full,
            "ada": ada_full,
            "gb": gb_full,
            "hgb": hgb_full,
        },
        "test_auc": test_auc,
    }
    
    save_ensemble_model(ensemble_package, version="2-23-2026")

    return ensemble_package

def main():
    # ----- Setup -----
    df = filter_cols(load())
    X = df.drop(columns=["TOURNEY"])
    y = df["TOURNEY"].values

    results = train_stacked_ensemble(X, y)


main()
