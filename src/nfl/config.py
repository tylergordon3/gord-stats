"""
NFL game predictions: season constants and paths.

The real sport, as src/cfb's model half is; the Sleeper fantasy league lives
in src/fantasy and is a different thing.
"""
from zoneinfo import ZoneInfo

from gordstats import paths

SEASON = 2026
TZ = ZoneInfo("America/New_York")

DATA_DIR = paths.DATA / "nfl"
WEB_DIR = paths.DOCS / "nfl"
