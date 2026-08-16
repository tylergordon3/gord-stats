"""
Paths shared by every project in this repo.

Each project keeps its own `paths` module (cbb.paths, wnba.paths,
fantasy.paths) that re-exports these and adds its own constants, so call
sites can keep saying `paths.X` without caring which layer X came from.

Project layout:
project-root/
    src/gordstats/...      shared site + path helpers
    src/cbb/...            college basketball
    src/wnba/...           WNBA fantasy
    src/fantasy/...        fantasy football
    data/<project>/
    docs/                  one Jekyll site, one section per project
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

DATA = ROOT / "data"
DOCS = ROOT / "docs"


# --------------
# Website Assets
# --------------
# Shared by every section: one stylesheet, one image pool, one JS bundle.

ASSETS_DIR = DOCS / "assets"

CSS = ASSETS_DIR / "css"
ASSET_DATA_DIR = ASSETS_DIR / "data"
ASSET_IMG_DIR = ASSETS_DIR / "images"
ASSET_JS_DIR = ASSETS_DIR / "js"


# --------------
# Website HTML
# --------------

# The GordStats hub page. Section landing pages live in each project's paths.
WEB_HOME = DOCS / "index.html"
