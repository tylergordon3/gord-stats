"""
Holds pathing information as constants for the CBB project.

Project layout:
project-root/
    src/cbb/...
    data/
    docs/
    model_data/
    model_data_w/
    models/
"""

from pathlib import Path

# -----------------------
# Project Root Detection
# -----------------------

def get_project_root() -> Path:
    """
    Detect project root by locating pyproject.toml.
    """
    current = Path(__file__).resolve()

    for parent in current.parents:
        if (parent / "pyproject.toml").exists():
            return parent

    raise RuntimeError("Project root not found. Is pyproject.toml missing?")


# -----
# Bases
# -----

ROOT = get_project_root()

SRC = ROOT / "src"
PACKAGE_DIR = SRC / "cbb"

DATA = ROOT / "data"
DOCS = ROOT / "docs"

MODEL_DATA = ROOT / "model_data"
MODEL_DATA_W = ROOT / "model_data_w"

ML_DIR = ROOT / "models"


# ---------------
# Data Collection
# ---------------

M_DATA = DATA / "men"
W_DATA = DATA / "women"
WNBA_DATA = DATA / "wnba"
OTHER_DATA = DATA / "refs"
SCHEDULE_DATA = DATA / "schedule"
LIVE_DATA = DATA / "live"

M_KEN_DIR = M_DATA / "kenpom_api"
M_KEN_OLD_DIR = M_DATA / "kenpom"
M_ATS_DIR = M_DATA / "ats"
M_ESPN_DIR = M_DATA / "espn"
M_NET_DIR = M_DATA / "net"
M_TOR_DIR = M_DATA / "torvik"
M_SCHEDULE = DATA / "schedule" / "men_season.json"
M_LIVE = LIVE_DATA / "live_scores_men.json"

W_TOR_DIR = W_DATA / "torvik"
W_NET_DIR = W_DATA / "net"
W_SCHEDULE = DATA / "schedule" / "women_season.json"
W_LIVE = LIVE_DATA / "live_scores_women.json"

BIDS_FILE = DATA / "teams" / "bids.json"
MARCH_FILE = DATA / "teams" / "march.json"

# --------------
# Website Assets
# --------------

ASSETS_DIR = DOCS / "assets"

CSS = ASSETS_DIR / "css"
ASSET_DATA_DIR = ASSETS_DIR / "data"
ASSET_IMG_DIR = ASSETS_DIR / "images"
ASSET_JS_DIR = ASSETS_DIR / "js"

MASTER_DICT = ASSET_DATA_DIR / "master.json"
M_RANKS = ASSET_DATA_DIR / "ranks.json"
W_RANKS = ASSET_DATA_DIR / "wranks.json"


# --------------
# Website HTML
# --------------

WEB_M_DIR = DOCS / "men"
WEB_W_DIR = DOCS / "women"

WEB_HOME = DOCS / "index.html"
WEB_M_HOME = WEB_M_DIR / "index.html"
WEB_W_HOME = WEB_W_DIR / "index.html"

WEB_M_CONF = WEB_M_DIR / "conference.html"
WEB_W_CONF = WEB_W_DIR / "conference.html"

FINAL_26_BRACKET_M =  WEB_M_DIR / "predict_2026-03-15.html"
FINAL_26_BRACKET_W =  WEB_W_DIR / "predict_2026-03-15.html"

# -------------------
# ML Training Data
# -------------------

M_KEN_TRAIN_DIR = MODEL_DATA / "kenpom_api"
M_KEN_OLD_TRAIN_DIR = MODEL_DATA / "kenpom"
M_TOR_TRAIN_DIR = MODEL_DATA / "torvik"

W_TOR_TRAIN_DIR = MODEL_DATA_W / "torvik"

M_KEN_TRAIN_ALL = M_KEN_TRAIN_DIR / "all.json"
M_KEN_OLD_TRAIN_ALL = M_KEN_OLD_TRAIN_DIR / "kenpom_all.json"
M_TOR_TRAIN_ALL = M_TOR_TRAIN_DIR / "torvik_all.json"

W_TOR_TRAIN_ALL = W_TOR_TRAIN_DIR / "torvik_w_all.json"


# --------------
# ML Models
# --------------

REGISTRY = ML_DIR / "registry.json"
ML_2026_DIR = ML_DIR / "2026"