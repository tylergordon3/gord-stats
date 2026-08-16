"""
Paths for the WNBA fantasy project.

Re-exports the repo-wide bases from `gordstats.paths` so call sites can keep
saying `paths.X` regardless of which layer X lives in.
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

PACKAGE_DIR = SRC / "wnba"

WNBA_DATA = DATA / "wnba"

WEB_WNBA_DIR = DOCS / "wnba"
WEB_WNBA_HOME = WEB_WNBA_DIR / "index.html"
