import json
from datetime import datetime
from io import StringIO

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import (AdaBoostClassifier, GradientBoostingClassifier,
                              HistGradientBoostingClassifier)
from sklearn.feature_selection import RFECV
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.model_selection import (GridSearchCV, StratifiedKFold,
                                     train_test_split)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC
from sklearn.tree import DecisionTreeClassifier

from cbb.lib import paths

DROP = [
    "DataThrough",
    "TeamName",
    "ConfShort",
    "Coach",
    "Seed",
    "Season",
    "Wins",
    "Losses",
    "Event",
    "ConfOnly",
]

CV = StratifiedKFold(n_splits=5, shuffle=True, random_state=13)


def load():
    with open(paths.M_KEN_TRAIN_ALL, "r") as f:
        data = json.load(f)
    df = pd.read_json(StringIO(data))

    return df


def save_ensemble_model(ensemble_package, version):

    models_dir = paths.ML_2026_DIR
    models_dir.mkdir(parents=True, exist_ok=True)

    filename = f"men_ken_{version}.pkl"
    filepath = models_dir / filename

    ensemble_package["saved_at"] = datetime.utcnow().isoformat()

    joblib.dump(ensemble_package, filepath)

    print(f"\nModel saved to: {filepath}")


def filter_cols(df):
    df = df.copy()
    df = df.drop(columns=DROP, errors="ignore")

    for col in df.columns:
        if col != "Tourney":
            df[col] = pd.to_numeric(df[col], errors="coerce")

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
    selector_model = SVC(
        kernel="linear", C=0.1, random_state=13, class_weight="balanced"
    )

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
    pipe = Pipeline(
        [
            ("scaler", StandardScaler()),
            ("svc", SVC(probability=True, random_state=13, class_weight="balanced")),
        ]
    )

    # Smaller, high-impact grid for SVC
    param_grid = {
        "svc__C": [0.1, 1, 10],
        "svc__gamma": ["scale", "auto"],
        "svc__kernel": ["rbf", "linear"],
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
    # 2. Hyperparameter Tuning
    # ---------------------------
    param_grid = {
        "n_estimators": [200, 400],
        "learning_rate": [0.05, 0.1],
        "estimator__max_depth": [1, 2],
    }

    grid = GridSearchCV(
        AdaBoostClassifier(
            estimator=DecisionTreeClassifier(),
            random_state=13
        ),
        param_grid,
        scoring="roc_auc",
        cv=StratifiedKFold(5, shuffle=True, random_state=13),
        n_jobs=-1,
    )

    grid.fit(X_train, y_train)

    best_model = grid.best_estimator_

    # ---------------------------
    # 3. Evaluate on Test Set
    # ---------------------------
    test_probs = best_model.predict_proba(X_test)[:, 1]

    test_auc = roc_auc_score(y_test, test_probs)
    test_brier = brier_score_loss(y_test, test_probs)

    return {
        "model": best_model,
        "features": X.columns,  # all features used
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
    # 2. Hyperparameter Tuning
    # ---------------------------
    param_grid = {
        "n_estimators": [200, 400],
        "learning_rate": [0.03, 0.05],
        "max_depth": [2, 3],
        "min_samples_leaf": [5, 10],
        "subsample": [0.8, 1.0],
    }

    grid = GridSearchCV(
        GradientBoostingClassifier(random_state=13),
        param_grid,
        scoring="roc_auc",
        cv=StratifiedKFold(5, shuffle=True, random_state=13),
        n_jobs=-1,
    )

    grid.fit(X_train, y_train)

    best_model = grid.best_estimator_

    # ---------------------------
    # 3. Evaluate on Test Set
    # ---------------------------
    test_probs = best_model.predict_proba(X_test)[:, 1]

    test_auc = roc_auc_score(y_test, test_probs)
    test_brier = brier_score_loss(y_test, test_probs)

    return {
        "model": best_model,
        "features": X.columns,
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
    # 2. Hyperparameter Tuning
    # ---------------------------
    param_grid = {
        "learning_rate": [0.03, 0.05],
        "max_iter": [300, 500],
        "max_depth": [None, 3],
        "min_samples_leaf": [20, 40],
        "l2_regularization": [0.0, 0.1],
    }

    grid = GridSearchCV(
        HistGradientBoostingClassifier(
            random_state=13,
            early_stopping=True,   # big speed boost
            validation_fraction=0.1,
            n_iter_no_change=10,
        ),
        param_grid,
        scoring="roc_auc",
        cv=StratifiedKFold(5, shuffle=True, random_state=13),
        n_jobs=-1,
    )

    grid.fit(X_train, y_train)

    best_model = grid.best_estimator_

    # ---------------------------
    # 3. Evaluate on Test Set
    # ---------------------------
    test_probs = best_model.predict_proba(X_test)[:, 1]

    test_auc = roc_auc_score(y_test, test_probs)
    test_brier = brier_score_loss(y_test, test_probs)

    return {
        "model": best_model,
        "features": X.columns,
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
    start = datetime.now()
    log_oof = generate_oof_predictions(train_logistic, X_train, y_train)
    print(f"Log OOF took: {(datetime.now() - start).total_seconds()}")
    start = datetime.now()
    svc_oof = generate_oof_predictions(train_svc, X_train, y_train)
    print(f"SVC OOF took: {(datetime.now() - start).total_seconds()}")
    start = datetime.now()
    ada_oof = generate_oof_predictions(train_adaboost, X_train, y_train)
    print(f"ADA OOF took: {(datetime.now() - start).total_seconds()}")
    start = datetime.now()
    gb_oof = generate_oof_predictions(train_gradient_boost, X_train, y_train)
    print(f"GB OOF took: {(datetime.now() - start).total_seconds()}")
    start = datetime.now()
    hgb_oof = generate_oof_predictions(train_hist_gradient_boost, X_train, y_train)
    print(f"HGB OOF took: {(datetime.now() - start).total_seconds()}")
    start = datetime.now()

    # ---------------------------
    # 2. Train Meta Model
    # ---------------------------
    meta_X_train = np.column_stack([log_oof, svc_oof, ada_oof, gb_oof, hgb_oof])

    meta_model = LogisticRegression(max_iter=5000)
    meta_model.fit(meta_X_train, y_train)

    print(f"\nMeta-model trained and took: {(datetime.now() - start).total_seconds()}")
    start = datetime.now()
    # ---------------------------
    # 3. Fit Base Models on FULL training set
    # ---------------------------
    log_full = train_logistic(X_train, y_train)
    svc_full = train_svc(X_train, y_train)
    ada_full = train_adaboost(X_train, y_train)
    gb_full = train_gradient_boost(X_train, y_train)
    hgb_full = train_hist_gradient_boost(X_train, y_train)
    print(f"\nIndividual models trained and took: {(datetime.now() - start).total_seconds()}")

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
        "version": "2-24-2026",
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

    save_ensemble_model(ensemble_package, version="2-24-2026")

    return ensemble_package


def main():
    # ----- Setup -----
    df = filter_cols(load())
    X = df.drop(columns=["Tourney"])
    y = df["Tourney"].values

    results = train_stacked_ensemble(X, y)


main()
