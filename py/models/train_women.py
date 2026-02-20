from sklearn.ensemble import GradientBoostingClassifier, HistGradientBoostingClassifier
from sklearn.ensemble import RandomForestClassifier, AdaBoostClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.feature_selection import RFECV
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.model_selection import train_test_split,  StratifiedKFold

import pandas as pd
import numpy as np

from ..lib import paths, help

"""
    Random Forest,
    Gradient Boost,
    Hist Gradient Boost,
    Logistic Regression,
    AdaBoost
"""

HEADERS = [
    "Rk",
    "Team",
    "Seed",
    "Finish",
    "Tourney",
    "Year",
    "Conf",
    "G",
    "Rec",
    "AdjOE",
    "AdjDE",
    "Barthag",
    "EFG%",
    "EFGD%",
    "TOR",
    "TORD",
    "ORB",
    "DRB",
    "FTR",
    "FTRD",
    "2P%",
    "2P%D",
    "3P%",
    "3P%D",
    "3PR",
    "3PRD",
    "Adj T.",
    "WAB",
]

DROP = ["Rk", "Team", "Conf", "Year", "Seed", "Finish", "Rec", "G"]


def load():
    raw_data = help.load_json_data(paths.W_TOR_TRAIN_ALL)
    df = pd.DataFrame(raw_data, columns=HEADERS)
    return df

def filter_cols(df):
    df = df.copy()

    df = df.drop(columns=DROP, errors="ignore")

    df["Tourney"] = df["Tourney"].map({"True": 1, "False": 0})

    if "WAB" in df.columns:
        df["WAB"] = df["WAB"].str.replace("+", "", regex=False)

    for col in df.columns:
        if col != "Tourney":
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna()
    return df

def logistic_features(X, y):
    pipeline = Pipeline([
        ("scalar", StandardScaler()),
        ("model", LogisticRegression(max_iter=5000))
    ])
    
    rfecv = RFECV(
        estimator=pipeline,
        step=1,
        cv=StratifiedKFold(5),
        scoring="roc_auc",
        importance_getter="model.coef_",
        n_jobs=-1
    )
    
    rfecv.fit(X, y)
    
    selected = X.columns[rfecv.support_]
    
    return rfecv, selected

def randforest_features(X, y):
    model = RandomForestClassifier(n_estimators=500, random_state=13)
    
    rfecv = RFECV(
        estimator=model,
        step=1,
        cv=5,
        scoring="roc_auc",
        importance_getter="model.coef_",
        n_jobs=-1
    )
    
    rfecv.fit(X, y)
    
    selected = X.columns[rfecv.support_]
    
    return rfecv, selected

def main():
    # ----- Setup -----
    df = filter_cols(load())
    X = df.drop(columns=["Tourney"])
    y = df["Tourney"].values
    
     # ----- Feature Selection -----
    log_model, log_features = logistic_features(X, y)
    rf_model, rf_features = randforest_features(X, y)
    
     # ----- Logistic Regression -----

    

main()
