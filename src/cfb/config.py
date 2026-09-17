"""
College football: season constants and paths.

One league (Yahoo College Fantasy Football, the "B1G West Memorial FFL") and
one real-world schedule feed (ESPN). Everything else in src/cfb reads from
here, the same way fantasy.config anchors the NFL section.
"""
from zoneinfo import ZoneInfo

from gordstats import paths

SEASON = 2026
SEASON_LABEL = "2026"

# Yahoo's game id for College Football changes every season (2026 = 474).
# Verify with:  https://pub-api-ro.fantasysports.yahoo.com/fantasy/v2/game/cfb?format=json
GAME_CODE = "cfb"
GAME_KEY = "474"
LEAGUE_ID = "21318"
LEAGUE_KEY = f"{GAME_KEY}.l.{LEAGUE_ID}"
LEAGUE_URL = f"https://college.fantasysports.yahoo.com/cfb/{LEAGUE_ID}"

LEAGUE_TEAMS = 10
# Whose site this is, by Yahoo team name: the roster "My team" filters and the
# team dashboard open on until a browser picks another (remembered per browser).
MY_TEAM = "Puntaholics"
LEAGUE_TZ = ZoneInfo("America/New_York")

DATA_DIR = paths.DATA / "cfb"
WEB_DIR = paths.DOCS / "cfb"
