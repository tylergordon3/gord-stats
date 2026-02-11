'''
Holds Pathing information as constants
'''
from pathlib import Path

# -----
# Bases
# -----
ROOT = Path("cbb-model")
SRC = ROOT / Path("py")
DATA = ROOT / Path("data")
DOCS = ROOT / Path("docs")

# ---------------
# Data Collection
# ---------------
MEN_DATA = DATA / Path("men")
WOMEN_DATA = DATA / Path("women")
OTHER_DATA = DATA / Path("refs")

MEN_KENPOM = MEN_DATA / Path("kenpom_api")
MEN_KENPOM_OLD = MEN_DATA / Path("kenpom")
MEN_ATS = MEN_DATA / Path("ats")
MEN_ESPN = MEN_DATA / Path("espn")
MEN_NET = MEN_DATA / Path("net")
MEN_TORVIK = MEN_DATA / Path("torvik")

WOMEN_TORVIK = WOMEN_DATA / Path("torvik")
WOMEN_NET = WOMEN_DATA / Path("net")

# --------------
# Website Assets
# --------------
ASSETS = DOCS / Path("assets")
CSS = ASSETS / Path("css")
ASSET_DATA = ASSETS / Path("data")

MASTER_DICT = ASSET_DATA / Path("master.json")
MEN_RANK_DICT = ASSET_DATA / Path("ranks.json")
WOMEN_RANK_DICT = ASSET_DATA / Path("wranks.json")