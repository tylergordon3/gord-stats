'''
Holds Pathing information as constants
'''
from pathlib import Path

def get_project_root() -> Path:
    # Start from the current file's directory
    current_file_dir = Path(__file__).resolve().parent
    # Traverse parents until a marker file (e.g., '.git') is found
    for parent in current_file_dir.parents:
        if (parent / '.git').exists():
            return parent
    # Fallback to current working directory if no marker is found
    return Path.cwd()

# -----
# Bases
# -----
ROOT = get_project_root()
SRC = ROOT / Path("py")
DATA = ROOT / Path("data")
DOCS = ROOT / Path("docs")

# ---------------
# Data Collection
# ---------------
M_DATA = DATA / Path("men")
W_DATA = DATA / Path("women")
OTHER_DATA = DATA / Path("refs")

M_KEN_DIR = M_DATA / Path("kenpom_api")
M_KEN_OLD_DIR = M_DATA / Path("kenpom")
M_ATS_DIR = M_DATA / Path("ats")
M_ESPN_DIR = M_DATA / Path("espn")
M_NET_DIR = M_DATA / Path("net")
M_TOR_DIR = M_DATA / Path("torvik")

W_TOR_DIR = W_DATA / Path("torvik")
W_NET_DIR = W_DATA / Path("net")

# --------------
# Website Assets
# --------------
ASSETS_DIR = DOCS / Path("assets")
CSS = ASSETS_DIR / Path("css")
ASSET_DATA_DIR = ASSETS_DIR / Path("data")
ASSET_IMG_DIR = ASSETS_DIR / Path("images")
ASSET_JS_DIR = ASSETS_DIR / Path("js")

MASTER_DICT = ASSET_DATA_DIR / Path("master.json")
M_RANKS = ASSET_DATA_DIR / Path("ranks.json")
W_RANKS = ASSET_DATA_DIR / Path("wranks.json")

# --------------
# Website HTML
# --------------
WEB_M_DIR = DOCS / Path("men")
WEB_W_DIR = DOCS / Path("women")

WEB_HOME = DOCS / Path("index.html")
WEB_M_HOME = WEB_M_DIR / Path("index.html")
WEB_W_HOME = WEB_W_DIR / Path("index.html")

WEB_M_CONF = WEB_M_DIR / Path("conference.html")
WEB_W_CONF = WEB_W_DIR / Path("conference.html")

# --------------
# ML Training Data
# --------------
M_TRAIN_DIR = ROOT / Path("model_data")
W_TRAIN_DIR = ROOT / Path("model_data_w")

M_KEN_TRAIN_DIR = M_TRAIN_DIR / Path("kenpom_api")
M_KEN_OLD_TRAIN_DIR = M_TRAIN_DIR / Path("kenpom")
M_TOR_TRAIN_DIR = M_TRAIN_DIR / Path("torvik")

W_TOR_TRAIN_DIR = W_TRAIN_DIR / Path("torvik")

M_KEN_TRAIN_ALL = M_KEN_TRAIN_DIR / Path("all.json")
M_KEN_OLD_TRAIN_ALL = M_KEN_OLD_TRAIN_DIR / Path("kenpom_all.json")
M_TOR_TRAIN_ALL = M_TOR_TRAIN_DIR / Path("torvik_all.json")

W_TOR_TRAIN_ALL = W_TOR_TRAIN_DIR / Path("torvik_w_all.json")

# --------------
# ML Models
# --------------
ML_DIR = ROOT / Path("models")
REGISTRY = ML_DIR / Path("registry.json")

ML_2026_DIR = ML_DIR / Path("2026")