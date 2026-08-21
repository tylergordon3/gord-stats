"""
Paths for the fantasy football project.

Re-exports the repo-wide bases from `gordstats.paths` so call sites can keep
saying `paths.X` regardless of which layer X lives in.

`config.py` keeps the league/domain configuration (roster names, league IDs,
scoring); anything that names a location on disk belongs here.
"""

from gordstats.paths import (  # noqa: F401  (re-exported for call sites)
    get_project_root,
    ROOT,
    SRC,
    DATA,
    DOCS,
    ASSETS_DIR,
    CSS,
    ASSET_DATA_DIR,
    ASSET_IMG_DIR,
    ASSET_JS_DIR,
    WEB_HOME,
)

PACKAGE_DIR = SRC / "fantasy"


# ---------------
# Data Collection
# ---------------

DATA_DIR = DATA / "fantasy"

PLAYERS_DIR = DATA_DIR / "players"
SEASON_DIR = DATA_DIR / "season"
ADP_DIR = DATA_DIR / "adp"
INJURIES_DIR = DATA_DIR / "injuries"
TRANSACTIONS_DIR = DATA_DIR / "transactions"
# Weekly league-scored points, one parquet per NFL season: the training data
# for the projection model behind the power rankings.
POINTS_DIR = DATA_DIR / "points"
# Fitted player projections and simulated power rankings, one file per season.
PROJECTIONS_DIR = DATA_DIR / "projections"

# The model's backtest and accuracy scores. Derived, but only from seasons
# that have finished, so it is committed like the other season archives
# rather than recomputed on every build.
VALIDATION_PATH = DATA_DIR / "model_validation.json"

ARCHIVE_PATH = DATA_DIR / "historical.json"
BESTBALL_JSON = DATA_DIR / "bestball.json"


# --------------
# Website HTML
# --------------

WEB_FANTASY_DIR = DOCS / "fantasy"
WEB_FANTASY_HOME = WEB_FANTASY_DIR / "index.html"

# Section pages. Each is a directory with an index.html so the URL stays clean.
WEB_ADP = WEB_FANTASY_DIR / "adp" / "index.html"
WEB_DRAFT = WEB_FANTASY_DIR / "draft" / "index.html"
WEB_DRAFT_DNA = WEB_FANTASY_DIR / "draft-dna" / "index.html"
WEB_DRAFT_RECAP = WEB_FANTASY_DIR / "draft-recap" / "index.html"
WEB_DRAFT_REPORT = WEB_FANTASY_DIR / "draft-report" / "index.html"
WEB_DRAFT_LIVE = WEB_FANTASY_DIR / "live" / "index.html"
WEB_SCHEDULE = WEB_FANTASY_DIR / "schedule" / "index.html"
WEB_POWER = WEB_FANTASY_DIR / "power" / "index.html"
WEB_TRANSACTIONS = WEB_FANTASY_DIR / "transactions" / "index.html"
