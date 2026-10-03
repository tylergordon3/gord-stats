"""
The CFB watch guide (/cfb/watch/): every game of the day, grouped by when it
kicks off, the one most worth having on first in each window - the shared
engine is gordstats.watch_page (NFL's twin: nfl.site.watch; CBB's:
cbb.render.render_watch). What is college football's own:

    the score           ESPN's matchup quality (cfb.gameinfo), nudged for a
                        Top 25 matchup and for playoff stakes - ESPN FPI gives
                        both teams a 10%+ playoff chance, or one 25%+ in a game
                        its opponent could win
    the reader's part   starred teams (gordstats.favorites, `cfb:<id>`) and
                        players from their Yahoo team (`cfbMyTeam`)
    live                the scoreboard proxy, /api/cfb-scores

    python -m cfb.site.watch
"""
import json
from datetime import datetime, timedelta

import pandas as pd

from cfb import espn, gameinfo, odds as odds_mod, predict, schools as schools_mod, yahoo
from cfb.config import SEASON
from cfb.site import power, write_page
from gordstats import logos, paths, preview_page, watch_page
from gordstats.watch_page import ET, best_day, teaser  # noqa: F401  (cfb.site.home)

OUT = paths.DOCS / "cfb" / "watch" / "index.html"
DAYS = 7

# Windows by Eastern kickoff: (key, label, starts before this hour).
SLOTS = [("early", "Early", 14.0), ("afternoon", "Afternoon", 18.0),
         ("prime", "Prime time", 21.5), ("late", "Late night", 99.0)]

STAKES_BOTH = 10.0        # FPI playoff chance, percent
STAKES_ONE = 25.0
STAKES_DOG = 0.25


def slot(kick: pd.Timestamp, time_known: bool = True) -> str:
    return watch_page.slot(kick, SLOTS, time_known)


def _slot_hours() -> list:
    return watch_page.slot_hours(SLOTS)


def _num(v, places=1):
    return None if v is None or pd.isna(v) else round(float(v), places)


def judge(g: dict) -> tuple:
    """(watch score, tags, pregame favourite) for one game: `g` carries mq, the
    book spread (home), our and FPI's home win chances, both ranks and both
    FPI playoff chances (percent)."""
    spread = g.get("sp")
    if spread is None and g.get("margin") is not None:
        spread = -g["margin"]
    fav = None if spread is None or abs(spread) <= 0.25 else ("h" if spread < 0 else "a")
    probs = [p for p in (g.get("hw"), g.get("fw")) if p is not None]
    dog = (max((p if fav == "a" else 1 - p) for p in probs) if probs and fav else
           max(min(p, 1 - p) for p in probs) if probs else None)
    po = [p for p in (g.get("hpo"), g.get("apo")) if p is not None]
    stakes = bool((len(po) == 2 and min(po) >= STAKES_BOTH)
                  or (po and max(po) >= STAKES_ONE and dog is not None and dog >= STAKES_DOG))
    return watch_page.judge(g.get("mq"), g.get("sp"), probs, margin=g.get("margin"),
                            nudges=[("Top 25 matchup", bool(g.get("hr")) and bool(g.get("ar"))),
                                    ("Playoff stakes", stakes)])


def _playoff_odds() -> dict:
    """ESPN team id -> FPI playoff chance (percent), from the cached pull."""
    try:
        data = json.loads(power._cache_path().read_text(encoding="utf-8"))
        return {t["id"]: t.get("probmakeplayoffs") for t in power._rows(data)}
    except (OSError, ValueError, KeyError):
        return {}


def games(now: datetime = None) -> list:
    """Every game from the start of the guide's day (ET) to a week out, with
    what the browser needs to rank and draw it."""
    now = now or datetime.now(ET)
    # The guide's day runs to NIGHT_ENDS (watch_page.game_day): at 12:30 AM
    # it is still Saturday night, and a start at midnight dropped Saturday's
    # 10:30 kickoffs from the live tick's guide while they were being played.
    start = (now.astimezone(ET) - timedelta(hours=watch_page.NIGHT_ENDS)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    frame, _model, _names = predict.season()
    frame = frame[(frame["date"] >= start) & (frame["date"] < now + timedelta(days=DAYS))]
    if frame.empty:
        return []
    board = odds_mod.latest(SEASON)
    if not board.empty:
        frame = frame.merge(board[odds_mod.KEY + ["spread", "total"]].rename(
            columns={"spread": "book_spread", "total": "book_total"}), on=odds_mod.KEY, how="left")
    info = gameinfo.load(SEASON)
    po = _playoff_odds()
    out = []
    for _, r in frame.sort_values("date").iterrows():
        gid = str(r["game_id"])
        e = info.get(gid) or {}
        known = r.get("time_valid", True)
        known = True if known is None or pd.isna(known) else bool(known)
        q = espn.query(int(r["week"]))
        kick = pd.Timestamp(r["date"])
        g = {
            "id": gid, "wk": q["week"], "st": q["seasontype"],
            "ko": kick.strftime("%Y-%m-%dT%H:%M:%SZ"), "tk": known,
            "day": watch_page.game_day(kick, known), "slot": slot(kick, known),
            "tv": r.get("tv") or "", "note": r.get("note") or "", "n": bool(r.get("neutral")),
            "h": {"id": str(r["home_id"]), "nm": r["home"], "rk": _num(r.get("home_rank"), 0),
                  "lg": logos.url("ncaa", r["home_id"], 80),
                  "sc": _num(r.get("home_score"), 0), "pr": _num(r.get("pred_home"))},
            "a": {"id": str(r["away_id"]), "nm": r["away"], "rk": _num(r.get("away_rank"), 0),
                  "lg": logos.url("ncaa", r["away_id"], 80),
                  "sc": _num(r.get("away_score"), 0), "pr": _num(r.get("pred_away"))},
            "state": r.get("state") or "pre",
            "hw": _num(r.get("home_win_prob"), 3), "fw": _num(e.get("espn_home_wp"), 3),
            "sp": _num(r.get("book_spread")), "mq": _num(e.get("mq"), 0),
        }
        # A card opens the game's preview where one is on disk
        # (cfb.site.previews builds first); the engine's link otherwise.
        preview = preview_page.href("cfb", gid)
        if preview:
            g["href"] = preview
        g["score"], g["tags"], g["fav"] = judge({
            **g, "margin": _num(r.get("pred_margin")), "hr": g["h"]["rk"], "ar": g["a"]["rk"],
            "hpo": _num(po.get(g["h"]["id"])), "apo": _num(po.get(g["a"]["id"]))})
        out.append(g)
    return out


BENCH = {"BN", "IR", "IR+", "NA"}


def rosters() -> dict:
    """{team key: {"n": team name, "p": [[player, pos, ESPN school id, starting]]}}
    from the league's newest archived week - who plays for whom, so the
    browser can find a reader's players in a game."""
    weeks = yahoo.archived_weeks()
    if not weeks:
        return {}
    data = yahoo.week_matchups(weeks[-1])
    names = {t["team_key"]: t["name"] for t in (yahoo.league().get("teams") or [])}
    to_school, espn_ids = schools_mod.yahoo_school(), schools_mod.espn_ids()
    out = {}
    for key, roster in (data.get("rosters") or {}).items():
        players = []
        for p in roster:
            school = espn_ids.get(to_school.get(p.get("team_full") or "", ""))
            if school is None or (p.get("pos") or "") in ("DEF", "K"):
                continue
            players.append([p.get("player") or "", p.get("pos") or "", str(school),
                            (p.get("slot") or "BN") not in BENCH])
        out[key] = {"n": names.get(key, key), "p": players}
    return out


LIVE_JS = """<script>
window.GSWatchLive=window.GSWatchLive||{};
/* One scoreboard call per week on now, through the site's proxy. Shared
   with the all-sports guide (gordstats.watch_all). */
GSWatchLive.cfb=function(games, D){
  var asks={}, out={};
  games.forEach(function(g){ asks[g.wk+'|'+g.st]=g; });
  return Promise.all(Object.keys(asks).map(function(k){
    var g=asks[k];
    return fetch('/api/cfb-scores?week='+g.wk+'&dates='+D.season+'&seasontype='+g.st)
      .then(function(r){ return r.ok?r.json():null; }).catch(function(){ return null; });
  })).then(function(boards){
    boards.forEach(function(b){
      ((b&&b.events)||[]).forEach(function(e){
        var c=(e.competitions||[])[0]; if(!c) return;
        var s=c.status||{}, st=s.type||{};
        var o={state:st.state||'pre', detail:st.shortDetail||'', period:s.period||0};
        (c.competitors||[]).forEach(function(x){ o[x.homeAway]=parseInt(x.score||'0',10); });
        out[String(e.id)]=o;
      });
    });
    return out;
  });
};
</script>"""

ADAPTER_JS = """<script>
(function(){
  var D=JSON.parse(document.getElementById('wg-data').textContent);
  GSWatch(D, {
    myKey:'cfbMyTeam', link:'/cfb/schedule/',
    hint:'Star teams on the <a href="/cfb/power/">rankings</a> to put their games first.',
    staleHtml:'This guide has not been rebuilt for a few days; the <a href="/cfb/schedule/">schedule</a> is current.',
    stars:function(){
      var set={}, list=[];
      try{ list=JSON.parse(localStorage.getItem('gs:favorites')||'[]')||[]; }catch(e){}
      list.forEach(function(k){ if(typeof k==='string'&&k.indexOf('cfb:')===0) set[k.slice(4)]=1; });
      return set;
    },
    live:GSWatchLive.cfb,
    top:'<p class="wg-note"><a href="/watch/">College and pro football together &rarr;</a></p>'
  });
})();
</script>"""



def body(data: dict) -> str:
    return watch_page.body(data, LIVE_JS + ADAPTER_JS, "watch-guide", "/cfb/watch/",
                           "What to watch in college football today")


def generate() -> None:
    now = datetime.now(ET)
    try:
        teams = rosters()
    except Exception as exc:                 # the guide stands without the league
        print(f"watch guide: no league rosters ({exc})")
        teams = {}
    data = {"season": SEASON, "generated": now.isoformat(timespec="minutes"),
            "slots": _slot_hours(), "games": games(now), "rosters": teams}
    # The same games for the all-sports guide, which merges them in the browser.
    watch_page.write_games(OUT.parent / "games.json", data)
    write_page(OUT, "Watch Guide", body(data), subtitle="What to have on, window by window",
               description="Every college football game of the day, grouped by kickoff and "
                           "ranked by how much it is worth watching - with live scores.")


if __name__ == "__main__":
    generate()
