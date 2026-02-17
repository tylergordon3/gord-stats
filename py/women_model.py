from lib import paths, url
import requests

BASE = "https://site.web.api.espn.com/apis/site/v2/sports/basketball/womens-college-basketball/scoreboard/conferences?groups=50"

season = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/womens-college-basketball/seasons?region=us&lang=en&contentorigin=espn&onlyWithStats=true&startingseason=2010"
by_team = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/womens-college-basketball/statistics/byteam?region=us&lang=en&contentorigin=espn&sort=differential.offensive.avgPoints%3Adesc&limit=50&conference=50&season=2026"
conf = "https://site.web.api.espn.com/apis/site/v2/sports/basketball/womens-college-basketball/scoreboard/conferences?groups=50&seasontype=2&season=2026"
params = {
    "groups": 50,
    "limit": 50,
    "lang": "en",
    "region": "us"
}

r = requests.get(BASE, params={**params, "page": 1})
data = r.text
print(data)