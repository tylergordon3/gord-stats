import json
import warnings
import utils
import joblib
from pathlib import Path
import pandas as pd
import numpy as np
from io import StringIO
from datetime import datetime

from sklearn import tree, preprocessing, svm
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.model_selection import cross_val_score, train_test_split, GridSearchCV, RepeatedStratifiedKFold
from sklearn.metrics import classification_report, roc_auc_score, brier_score_loss
from sklearn.feature_selection import SelectFromModel, RFE
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.calibration import CalibratedClassifierCV

warnings.filterwarnings("ignore")

CURRENT_SEASON = 2026
MODEL_VERSION = "1.0"

MODEL_DIR = Path(utils.get_path("models"))
MODEL_DIR.mkdir(parents=True, exist_ok=True)

MODEL_LIMITS = {
    "logistic": 8,
    "svc": 10,
    "gb": 9,
}

LOGISTIC_GRID = {
    "C": np.logspace(-3, 2, 8),
    "penalty": ["l2"],
    "solver": ["liblinear"],
}

SVC_GRID = {
    "C": [0.1, 0.5, 1, 2, 5, 10],
    "gamma": ["scale", 0.01, 0.05, 0.1],
    "kernel": ["rbf"],
}

GB_GRID = {
    "n_estimators": [200, 300, 400],
    "learning_rate": [0.03, 0.05, 0.08],
    "max_depth": [2, 3],
    "min_samples_leaf": [10, 20],
}

def update_registry(payload, path):
    registry_path = MODEL_DIR / "registry.json"

    if registry_path.exists():
        with open(registry_path) as f:
            registry = json.load(f)
    else:
        registry = {}

    key = payload["model_type"]
    entry = {
        "season": payload["season"],
        "version": payload["version"],
        "path": str(path.relative_to(MODEL_DIR)),
        "metrics": payload.get("metrics", {}),
        "trained_at": payload["trained_at"],
        "notes": payload.get("notes"),
        "features":payload.get("features"),
    }

    registry.setdefault(key, {"versions": []})
    registry[key]["versions"].append(entry)
    registry[key]["latest"] = entry["path"]

    with open(registry_path, "w") as f:
        json.dump(registry, f, indent=2)

def load_latest(model_type):
    with open(MODEL_DIR / "registry.json") as f:
        registry = json.load(f)

    rel_path = registry[model_type]["latest"]
    payload = joblib.load(MODEL_DIR / rel_path)
    return payload

def load_version(model_type, season, version):
    path = MODEL_DIR / str(season) / f"{model_type}_v{version}.pkl"
    return joblib.load(path)

def save_model(
    model_type,
    season,
    version,
    model,
    features,
    scaler=None,
    metrics=None,
    notes=None,
):
    path = MODEL_DIR / str(season)
    path.mkdir(parents=True, exist_ok=True)

    payload = {
        "model": model,
        "features": features,
        "scaler": scaler,
        "model_type": model_type,
        "season": season,
        "version": version,
        "trained_at": datetime.utcnow().isoformat(),
        "metrics": metrics or {},
        "notes": notes,
    }

    fname = f"{model_type}_v{version}_model.pkl"
    full_path = path / fname

    utils.write_to_pickle(model, full_path)
    #joblib.dump(payload, full_path)
    #print(f"Saved {full_path}")

    update_registry(payload, full_path)

def load_model(name):
    path = MODEL_DIR / f"{name}.pkl"
    payload = joblib.load(path)
    return payload["model"], payload["features"], payload["scaler"]

def clip_extremes(X, q=0.01):
    return X.clip(
        lower=X.quantile(q),
        upper=X.quantile(1 - q),
        axis=1
    )
    
def filter_api_data(df):
    exceptions = ['Season', 'Seed']
    keep = []

    for col in df.columns:
        if col in exceptions:
            continue
        if df[col].dtype in [float, bool]:
            keep.append(col)

    return df[keep]

def load_data():
    with open(utils.get_path("model_data/kenpom_api/all.json"), "r") as f:
        data = json.load(f)

    df = pd.read_json(StringIO(data))
    return filter_api_data(df)

def evaluate_model(name, model, scaler, X_test, y_test):
    if scaler is not None:
        X_test = scaler.transform(X_test)

    probs = model.predict_proba(X_test)[:, 1]

    auc = roc_auc_score(y_test, probs)
    brier = brier_score_loss(y_test, probs)

    print(f"\n{name} PERFORMANCE")
    print("-" * 30)
    print(f"AUC:   {auc:.4f}")
    print(f"Brier:{brier:.4f}")

    # Force tournament-size selection
    n_in = y_test.sum()
    thresh = np.sort(probs)[-n_in]
    preds = (probs >= thresh).astype(int)

    print(classification_report(y_test, preds))

    # Bubble-only diagnostics
    bubble = (probs > 0.25) & (probs < 0.75)
    if bubble.sum() > 20:
        bubble_auc = roc_auc_score(y_test[bubble], probs[bubble])
        print(f"Bubble AUC: {bubble_auc:.4f}")

    return probs

def calibrate(model, X, y, scaler=None):
    if scaler is not None:
        X = scaler.transform(X)

    calib = CalibratedClassifierCV(
        model,
        method="isotonic",
        cv=5,
    )
    calib.fit(X, y)
    return calib

def rank_features(X, y, model_type):
    X = clip_extremes(X)
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    if model_type == 'logistic':
        model = LogisticRegression(
            penalty='l1',
            solver="liblinear",
            C=0.1,
            class_weight="balanced",
            max_iter=3000,
        )
        model.fit(X_scaled, y)
        importance = np.abs(model.coef_[0])
    
    elif model_type == "svc":
        svc = svm.SVC(kernel='linear', class_weight='balanced')
        svc.fit(X_scaled, y)
        importance = np.abs(svc.coef_[0])
    
    elif model_type == "gb":
        gb = GradientBoostingClassifier(
            n_estimators=300,
            learning_rate=0.05,
            max_depth=3,
        )
        gb.fit(X,y)
        importance = gb.feature_importances_
    
    return (
        pd.Series(importance, index=X.columns)
        .sort_values(ascending=False)
        .index.to_list()
    )

def auto_feature_select(
    X, y, model_type, min_features=5, patience=3, eps=0.002
):
    ranked = rank_features(X, y, model_type)
    
    best_auc = 0
    no_improve = 0
    selected = []
    
    for i, feat in enumerate(ranked):
        selected.append(feat)
        
        if len(selected) < min_features:
            continue
        
        if len(selected) >= MODEL_LIMITS[model_type]:
            print(f"Reached {model_type} feature cap")
            break
        
        X_sub = clip_extremes(X[selected])
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X_sub)
        
        if model_type == "logistic":
            model = LogisticRegression(
                max_iter=3000,
                class_weight="balanced",
            )
        elif model_type == "svc":
            model = svm.SVC(
                kernel="rbf",
                probability=True,
                class_weight="balanced",
            )
        elif model_type == "gb":
            model = GradientBoostingClassifier(
                n_estimators=300,
                max_depth=3,
                learning_rate=0.05,
            )
            
        cv = RepeatedStratifiedKFold(
            n_splits=5,
            n_repeats=3,
            random_state=13
        )

        scores = cross_val_score(
            model,
            X_scaled,
            y,
            cv=cv,
            scoring="roc_auc",
            n_jobs=-1,
        )
        
        mean_auc = scores.mean()
        
        print(f"{model_type}: {len(selected)} feats → AUC={mean_auc:.4f}")
        if model_type == "svc" and len(selected) == 7:
            print("🚨 SVC jump feature:", feat)
        if mean_auc > best_auc + eps:
            best_auc = mean_auc
            no_improve = 0
        else:
            no_improve += 1

        if no_improve >= patience and len(selected) >= min_features + 2:
            print(f"Stopping at {len(selected)} features")
            break
    return selected

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

def tune_logistic(X, y):
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    model = LogisticRegression(
        max_iter=5000,
        class_weight="balanced",
    )

    cv = RepeatedStratifiedKFold(
        n_splits=5,
        n_repeats=3,
        random_state=13,
    )

    grid = GridSearchCV(
        model,
        LOGISTIC_GRID,
        scoring="roc_auc",
        cv=cv,
        n_jobs=-1,
    )

    grid.fit(X_scaled, y)
    return grid.best_estimator_, scaler

def tune_svc(X, y):
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    model = svm.SVC(
        probability=True,
        class_weight="balanced",
    )

    cv = RepeatedStratifiedKFold(
        n_splits=5,
        n_repeats=3,
        random_state=13,
    )

    grid = GridSearchCV(
        model,
        SVC_GRID,
        scoring="roc_auc",
        cv=cv,
        n_jobs=-1,
    )

    grid.fit(X_scaled, y)
    return grid.best_estimator_, scaler

def tune_gb(X, y):
    model = GradientBoostingClassifier()

    cv = RepeatedStratifiedKFold(
        n_splits=5,
        n_repeats=3,
        random_state=13,
    )

    grid = GridSearchCV(
        model,
        GB_GRID,
        scoring="roc_auc",
        cv=cv,
        n_jobs=-1,
    )

    grid.fit(X, y)
    return grid.best_estimator_

def main():
    start = datetime.now()

    df = load_data()
    y = np.asarray(df["Tourney"]).ravel()

    # -------- SVC --------
    svc_features = auto_feature_select(df.drop(columns="Tourney"), y, "svc")
    X_svc = df[svc_features]

    X_train, X_test, y_train, y_test = train_test_split(
        X_svc, y, test_size=0.25, stratify=y, random_state=13
    )

    svc_model, svc_scaler = tune_svc(X_train, y_train)
    svc_model = calibrate(svc_model, X_train, y_train, svc_scaler)

    svc_probs = evaluate_model(
        "SVC",
        svc_model,
        svc_scaler,
        X_test.values,
        y_test,
    )

    # -------- LOGISTIC --------
    logistic_features = auto_feature_select(df.drop(columns="Tourney"), y, "logistic")
    X_log = df[logistic_features]

    X_train, X_test, y_train, y_test = train_test_split(
        X_log, y, test_size=0.25, stratify=y, random_state=13
    )

    log_model, log_scaler = tune_logistic(X_train, y_train)

    log_probs = evaluate_model(
        "Logistic",
        log_model,
        log_scaler,
        X_test.values,
        y_test,
    )

    # -------- GRADIENT BOOSTING --------
    gb_features = auto_feature_select(df.drop(columns="Tourney"), y, "gb")
    X_gb = df[gb_features]

    X_train, X_test, y_train, y_test = train_test_split(
        X_gb, y, test_size=0.25, stratify=y, random_state=13
    )

    gb_model = tune_gb(X_train, y_train)
    gb_model = calibrate(gb_model, X_train, y_train)

    gb_probs = evaluate_model(
        "Gradient Boosting",
        gb_model,
        None,
        X_test.values,
        y_test,
    )

    # -------- ENSEMBLE --------
    ens_probs = (svc_probs + log_probs + gb_probs) / 3

    print("\nENSEMBLE PERFORMANCE")
    print("-" * 30)
    print(f"AUC: {roc_auc_score(y_test, ens_probs):.4f}")
    print(f"Brier: {brier_score_loss(y_test, ens_probs):.4f}")

    print(f"\nExecution Time: {datetime.now() - start}")
    

    # -------- SAVE VERSIONED MODELS --------
    save_model(
        model_type="svc",
        season=CURRENT_SEASON,
        version=MODEL_VERSION,
        model=svc_model,
        features=svc_features,
        scaler=svc_scaler,
        metrics={
            "auc": roc_auc_score(y_test, svc_probs),
            "brier": brier_score_loss(y_test, svc_probs),
        },
        notes="SVC classifier with Luck; lock detector",
    )

    save_model(
        model_type="logistic",
        season=CURRENT_SEASON,
        version=MODEL_VERSION,
        model=log_model,
        features=logistic_features,
        scaler=log_scaler,
        metrics={
            "auc": roc_auc_score(y_test, log_probs),
            "brier": brier_score_loss(y_test, log_probs),
        },
        notes="Logistic regression calibration anchor",
    )

    save_model(
        model_type="gb",
        season=CURRENT_SEASON,
        version=MODEL_VERSION,
        model=gb_model,
        features=gb_features,
        scaler=None,  # GB not scaled
        metrics={
            "auc": roc_auc_score(y_test, gb_probs),
            "brier": brier_score_loss(y_test, gb_probs),
        },
        notes="Primary tournament selection model",
    )


    
if __name__ == "__main__":
    main()