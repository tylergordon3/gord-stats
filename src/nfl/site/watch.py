"""
The NFL watch guide (/nfl/watch/): every game of the week's days, grouped by
kickoff window, the one most worth having on first in each - the twin of
/cfb/watch/, on the shared engine (gordstats.watch_page). What is the NFL's
own:

    the score           ESPN's matchup quality (its predictor endpoint, one
                        call a game, fetched at build), nudged when both teams
                        have winning records; our closeness stands in where
                        ESPN has not rated a game
    the reader's part   their Sleeper team in the site's league (`nflMyTeam`,
                        the key My Team uses): their starters in each game,
                        and their opponent's this week - the other half of
                        what they are watching for
    live                ESPN's NFL scoreboard, read straight from the browser
                        (it allows any origin), one call a day on now

Windows are Eastern: a London morning, the 1 o'clock games, the late
afternoon, and prime time - Thursday, Sunday and Monday nights land there.

    python -m nfl.site.watch
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pandas as pd
import requests

from gordstats import logos, paths, preview_page, watch_page
from gordstats.frontmatter import add_front_matter
from gordstats.watch_page import ET
from nfl import games as games_mod, predict
from nfl.config import SEASON

OUT = paths.DOCS / "nfl" / "watch" / "index.html"
DAYS = 7
_PREDICTOR = ("https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/"
              "events/{id}/competitions/{id}/predictor")
_TIMEOUT = 15

SLOTS = [("morning", "Morning", 12.0), ("early", "Early", 15.0),
         ("late", "Late afternoon", 18.5), ("prime", "Prime time", 99.0)]

# ESPN and Sleeper spell one team differently; the roster key is Sleeper's.
_SLEEPER_ABBR = {"WSH": "WAS"}


def slot(kick: pd.Timestamp, time_known: bool = True) -> str:
    return watch_page.slot(kick, SLOTS, time_known)


def _num(v, places=1):
    return None if v is None or pd.isna(v) else round(float(v), places)


def _winning(record) -> bool:
    """A winning record, two games or more in: "3-1" yes, "1-0" not yet."""
    try:
        w, l, *t = (int(x) for x in str(record).split("-"))
    except ValueError:
        return False
    return w + l >= 2 and w > l


def _espn(game_id: str) -> dict:
    """{mq, fw}: ESPN's matchup quality and its home win chance, or {}."""
    try:
        r = requests.get(_PREDICTOR.format(id=game_id), timeout=_TIMEOUT,
                         headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        stats = {s.get("name"): s.get("value")
                 for s in (r.json().get("homeTeam") or {}).get("statistics", [])}
    except (requests.RequestException, ValueError):
        return {}
    fw = stats.get("gameProjection")
    return {"mq": _num(stats.get("matchupQuality"), 0),
            "fw": None if fw is None else round(float(fw) / 100, 3)}


def quality(game_ids: list) -> dict:
    """{game id: {mq, fw}} for the games coming, fetched side by side."""
    with ThreadPoolExecutor(max_workers=6) as pool:
        return dict(zip(game_ids, pool.map(_espn, game_ids)))


def judge(g: dict) -> tuple:
    return watch_page.judge(g.get("mq"), g.get("sp"), [g.get("hw"), g.get("fw")],
                            margin=g.get("margin"),
                            nudges=[("Winning teams", _winning(g.get("hrec")) and
                                     _winning(g.get("arec")))])


def games(now: datetime = None, espn: dict = None) -> list:
    """Every game from the start of the guide's today (ET) to a week out, in
    the engine's shape. `espn` is quality()'s answer; fetched here when not
    given.

    The guide's today, not the calendar's: its day runs to NIGHT_ENDS
    (watch_page.game_day), and a build at 00:30 ET started the window at
    that midnight and dropped Monday night's game while it was still on."""
    now = now or datetime.now(ET)
    start = pd.Timestamp(watch_page.game_day(pd.Timestamp(now))).tz_localize(ET)
    frame, _model, _names = predict.season()
    frame = frame[(frame["date"] >= start) & (frame["date"] < now + timedelta(days=DAYS))
                  & (frame["home_abbr"] != "TBD") & (frame["away_abbr"] != "TBD")]
    if frame.empty:
        return []
    if espn is None:
        espn = quality([str(g) for g in frame.loc[frame["state"] != "post", "game_id"]])

    def team(r, side):
        abbr = str(r[f"{side}_abbr"])
        return {"id": str(r[f"{side}_id"]), "nm": r[side], "k": _SLEEPER_ABBR.get(abbr, abbr),
                "lg": logos.url("nfl", abbr.lower(), 80), "rec": r.get(f"{side}_record") or "",
                "sc": _num(r.get(f"{side}_score"), 0), "pr": _num(r.get(f"pred_{side}"))}

    out = []
    for _, r in frame.sort_values("date").iterrows():
        gid = str(r["game_id"])
        e = espn.get(gid) or {}
        kick = pd.Timestamp(r["date"])
        # ESPN files a kickoff it does not know yet (week 18's) at midnight
        # Eastern and says TBD. Taken as real, the small-hours rule moved
        # those games to Saturday under prime time at 12:00 AM; they are on
        # their own day, in the TBA window.
        known = games_mod.time_known(r)
        g = {
            "id": gid, "ko": kick.strftime("%Y-%m-%dT%H:%M:%SZ"), "tk": known,
            "day": watch_page.game_day(kick, known), "slot": slot(kick, known),
            "tv": r.get("tv") or "", "n": bool(r.get("neutral")),
            "note": (f"at {r['venue']}" if r.get("neutral") and r.get("venue") else ""),
            "h": team(r, "home"), "a": team(r, "away"),
            "state": r.get("state") or "pre",
            "hw": _num(r.get("home_win_prob"), 3), "fw": e.get("fw"),
            "sp": _num(r.get("book_spread")), "mq": e.get("mq"),
        }
        # A card opens the game's preview where one is on disk
        # (nfl.site.previews builds first); the engine's link otherwise.
        preview = preview_page.href("nfl", gid)
        if preview:
            g["href"] = preview
        g["score"], g["tags"], g["fav"] = judge({
            **g, "margin": _num(r.get("pred_margin")),
            "hrec": g["h"]["rec"], "arec": g["a"]["rec"]})
        out.append(g)
    return out


def rosters() -> dict:
    """{roster id: {"n": manager, "p": [[player, pos, team, starting]], "opp":
    this week's opponent}} for the site's Sleeper league, from Sleeper's own
    rows for the week being played - so the starters are the ones set now."""
    from fantasy import paths as fpaths
    from fantasy.league import matchups as mdata

    week = mdata.current_week()
    rows = mdata.sleeper_matchups(week)
    teams = mdata.teams()
    names = pd.read_parquet(fpaths.PLAYERS_DIR / "sleeper.parquet").drop_duplicates("sleeper_id")
    info = {str(r.sleeper_id): (r.full_name, r.position, r.team)
            for r in names.itertuples(index=False)}
    pairs = {}
    for r in rows:
        pairs.setdefault(r["matchup_id"], []).append(str(r["roster_id"]))
    out = {}
    for r in rows:
        rid = str(r["roster_id"])
        starting = set(r["starters"])
        players = []
        for pid in r["players"]:
            name, pos, nfl_team = info.get(pid, (None, None, None))
            if pid.isalpha() and len(pid) <= 3:          # a team defence is keyed by its team
                name, pos, nfl_team = f"{pid} D/ST", "DEF", pid
            if not nfl_team or pd.isna(nfl_team):
                continue
            players.append([name or pid, pos or "", str(nfl_team), pid in starting])
        t = teams.get(int(r["roster_id"])) or teams.get(rid) or {}
        opp = [k for k in pairs.get(r["matchup_id"], []) if k != rid]
        out[rid] = {"n": t.get("manager") or t.get("name") or f"Team {rid}", "p": players,
                    "opp": opp[0] if opp else None}
    return out


LIVE_JS = """<script>
window.GSWatchLive=window.GSWatchLive||{};
/* ESPN's scoreboard answers any origin: one call per day on now. Shared
   with the all-sports guide (gordstats.watch_all). */
GSWatchLive.nfl=(function(){
  var BOARD='https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates=';
  return function(games){
    var dates={}, out={};
    games.forEach(function(g){ dates[g.day.replace(/-/g,'')]=1; });
    return Promise.all(Object.keys(dates).map(function(d){
      return fetch(BOARD+d).then(function(r){ return r.ok?r.json():null; }).catch(function(){ return null; });
    })).then(function(boards){
      boards.forEach(function(b){
        ((b&&b.events)||[]).forEach(function(e){
          var c=(e.competitions||[])[0]; if(!c) return;
          // The clock and quarter are on the competition's status, not its type.
          var s=c.status||e.status||{}, st=s.type||{};
          var o={state:st.state||'pre', detail:st.shortDetail||'', period:s.period||0};
          (c.competitors||[]).forEach(function(x){ o[x.homeAway]=parseInt(x.score||'0',10); });
          out[String(e.id)]=o;
        });
      });
      return out;
    });
  };
})();
</script>"""

ADAPTER_JS = """<script>
(function(){
  var D=JSON.parse(document.getElementById('wg-data').textContent);
  GSWatch(D, {
    myKey:'nflMyTeam', link:'/nfl/', pickLabel:'Your team', blowout:17,
    /* Sunday afternoons are all CBS and FOX: a quadbox only works with
       every game available, so the guide assumes it and says so. */
    quadShared:true,
    quadNote:'Every game counted as available, as with NFL Sunday Ticket; without it the '
      +'afternoon windows are your local CBS and FOX games.',
    hint:'Star teams on the <a href="/nfl/power/">rankings</a> to put their games first, or pick your team to see your starters.',
    staleHtml:'This guide has not been rebuilt for a few days; the <a href="/nfl/">predictions page</a> is current.',
    /* A star is stored by ESPN id (nfl:<id>, as /nfl/power/ writes it); the
       engine knows a team by k, the Sleeper abbreviation the rosters use, so
       each starred id is turned into its k through this guide's own games. */
    stars:function(){
      var ids={}, set={}, list=[];
      try{ list=JSON.parse(localStorage.getItem('gs:favorites')||'[]')||[]; }catch(e){}
      list.forEach(function(k){ if(typeof k==='string'&&k.indexOf('nfl:')===0) ids[k.slice(4)]=1; });
      (D.games||[]).forEach(function(g){
        [g.h,g.a].forEach(function(t){ if(t&&ids[t.id]) set[t.k!=null?t.k:t.id]=1; });
      });
      return set;
    },
    live:GSWatchLive.nfl,
    top:'<p class="wg-note"><a href="/watch/">College and pro football together &rarr;</a></p>'
  });
})();
</script>"""

HOW = ("Each window's games, best first, by a watch score: ESPN's matchup quality (0-100, how "
       "good the teams are and how close it should be), nudged up when both teams have winning "
       "records. Pick your team and the games with your starters move up and name them, with "
       "your opponent's this week beside them. During the day, a close game in the fourth, an "
       "overtime or an underdog ahead in the second half jumps the queue.")


def body(data: dict) -> str:
    return watch_page.body(data, LIVE_JS + ADAPTER_JS, HOW, "/nfl/watch/",
                           "What to watch in the NFL today")


def generate() -> None:
    now = datetime.now(ET)
    try:
        teams = rosters()
    except Exception as exc:                 # the guide stands without the league
        print(f"NFL watch guide: no league rosters ({exc})")
        teams = {}
    data = {"season": SEASON, "generated": now.isoformat(timespec="minutes"),
            "slots": watch_page.slot_hours(SLOTS), "games": games(now), "rosters": teams}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    # The same games for the all-sports guide, which merges them in the browser.
    watch_page.write_games(OUT.parent / "games.json", data)
    OUT.write_text(add_front_matter(
        body(data), "Watch Guide", "What to have on, window by window",
        description="Every NFL game of the week, grouped by kickoff and ranked by how much it "
                    "is worth watching - with your fantasy starters and live scores."),
        encoding="utf-8")
    print(f"Wrote NFL watch guide -> {OUT}")


if __name__ == "__main__":
    generate()
