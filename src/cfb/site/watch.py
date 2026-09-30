"""
The watch guide (/cfb/watch/): every game of the day, grouped by when it
kicks off, the one most worth having on first in each window.

A reader on a Saturday has one question the schedule page answers only after
some sorting: what should be on right now, and what after it. So the day is
cut into windows (early, afternoon, prime time, late night, in Eastern time,
the sport's clock) and each window is ranked by a watch score:

    ESPN's matchup quality     0-100, its own "worth watching" number (team
                               strength and how close it should be), fetched
                               with the game summary (cfb.gameinfo)
    a nudge for a Top 25       both teams ranked
    matchup
    a nudge for playoff        ESPN FPI gives both teams a 10%+ playoff chance,
    stakes                     or one 25%+ in a game its opponent could win

Each nudge closes a quarter of the gap to 100, so the score stays on ESPN's
scale.

Tags say why in words: Top 25 matchup, Toss-up (a line of three points or
fewer), Upset watch (the schedule page's rule: the model or FPI gives the
underdog 35%+), Playoff stakes.

The reader's own part is added in the browser: a starred team's game goes to
the top of its window (gordstats.favorites), and the games with players from
the reader's team in the Yahoo league move up and say who (the team picked on
My Team, `cfbMyTeam`, or here). During the day the page polls the scoreboard
proxy (/api/cfb-scores) and ranks what is on now - a close game late, an
overtime or an underdog ahead in the second half jumping the queue - above
what is still to come, with the finished games folded away at the bottom.

    python -m cfb.site.watch
"""
import json
from datetime import datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

import pandas as pd

from cfb import espn, gameinfo, odds as odds_mod, predict, schools as schools_mod, yahoo
from cfb.config import DATA_DIR, SEASON
from cfb.site import power, write_page
from gordstats import paths, share_button

ET = ZoneInfo("America/New_York")
OUT = paths.DOCS / "cfb" / "watch" / "index.html"
DAYS = 7

# Windows by Eastern kickoff: (key, label, starts before this hour).
SLOTS = [("early", "Early", 14.0), ("afternoon", "Afternoon", 18.0),
         ("prime", "Prime time", 21.5), ("late", "Late night", 99.0)]
TBA = ("tba", "Time TBA")

TOSS_UP = 3.0             # cfb.site.schedule's badge
UPSET_WATCH = 0.35        # and its filter
STAKES_BOTH = 10.0        # FPI playoff chance, percent
STAKES_ONE = 25.0
STAKES_DOG = 0.25


def slot(kick: pd.Timestamp, time_known: bool = True) -> str:
    if not time_known:
        return TBA[0]
    t = kick.tz_convert(ET)
    hour = t.hour + t.minute / 60
    return next(key for key, _label, before in SLOTS if hour < before)


def _num(v, places=1):
    return None if v is None or pd.isna(v) else round(float(v), places)


def judge(g: dict) -> tuple:
    """(watch score, tags, pregame favourite 'h' / 'a' / None) for one game:
    `g` carries mq, the book spread (home), our and FPI's home win chances,
    both ranks and both FPI playoff chances (percent)."""
    spread, ours, fpi = g.get("sp"), g.get("hw"), g.get("fw")
    if spread is None and g.get("margin") is not None:
        spread = -g["margin"]                       # our number when the book has none
    fav = None if spread is None or abs(spread) <= 0.25 else ("h" if spread < 0 else "a")
    known = [p for p in (ours, fpi) if p is not None]
    dog = None
    if known and fav:
        dog = max((p if fav == "a" else 1 - p) for p in known)
    elif known:
        dog = max(min(p, 1 - p) for p in known)

    tags = []
    both_ranked = bool(g.get("hr")) and bool(g.get("ar"))
    if both_ranked:
        tags.append("Top 25 matchup")
    if spread is not None and abs(spread) <= TOSS_UP:
        tags.append("Toss-up")
    elif dog is not None and dog >= UPSET_WATCH:
        tags.append("Upset watch")
    po = [p for p in (g.get("hpo"), g.get("apo")) if p is not None]
    stakes = (len(po) == 2 and min(po) >= STAKES_BOTH) or \
        (po and max(po) >= STAKES_ONE and dog is not None and dog >= STAKES_DOG)
    if stakes:
        tags.append("Playoff stakes")

    mq = g.get("mq")
    if mq is None:
        # ESPN has not rated it (it does for every game inside a few weeks):
        # how close it should be stands in, at half weight.
        mq = 50 * max(0.0, 1 - abs(spread) / 28) if spread is not None else 20.0
    # The two nudges close a quarter of the gap to 100 each, so the score stays
    # on ESPN's 0-100 scale: a 94 matchup cannot be lifted past a perfect one.
    score = mq + (100 - mq) * 0.25 * (both_ranked + bool(stakes))
    return round(score, 1), tags, fav


def _playoff_odds() -> dict:
    """ESPN team id -> FPI playoff chance (percent), from the cached pull."""
    try:
        data = json.loads(power._cache_path().read_text(encoding="utf-8"))
        return {t["id"]: t.get("probmakeplayoffs") for t in power._rows(data)}
    except (OSError, ValueError, KeyError):
        return {}


def games(now: datetime = None) -> list:
    """Every game from the start of today (ET) to a week out, with what the
    browser needs to rank and draw it."""
    now = now or datetime.now(ET)
    start = now.astimezone(ET).replace(hour=0, minute=0, second=0, microsecond=0)
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
            "day": kick.tz_convert(ET).strftime("%Y-%m-%d"), "slot": slot(kick, known),
            "tv": r.get("tv") or "", "note": r.get("note") or "", "n": bool(r.get("neutral")),
            "h": {"id": str(r["home_id"]), "nm": r["home"], "rk": _num(r.get("home_rank"), 0),
                  "sc": _num(r.get("home_score"), 0), "pr": _num(r.get("pred_home"))},
            "a": {"id": str(r["away_id"]), "nm": r["away"], "rk": _num(r.get("away_rank"), 0),
                  "sc": _num(r.get("away_score"), 0), "pr": _num(r.get("pred_away"))},
            "state": r.get("state") or "pre",
            "hw": _num(r.get("home_win_prob"), 3), "fw": _num(e.get("espn_home_wp"), 3),
            "sp": _num(r.get("book_spread")), "mq": _num(e.get("mq"), 0),
        }
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


CSS = """<style>
.wg{--wg-line:#e2e8f0;--wg-card:#fff;--wg-ink:#0f172a;--wg-mute:#475569;--wg-soft:#64748b;
  --wg-acc:#C2410C;--wg-live:#b3382c;--wg-live-bg:#fff5f4;--wg-chip:#eef2f7;--wg-me:#1d4ed8}
@media (prefers-color-scheme: dark){
  .wg{--wg-line:#2b3852;--wg-card:#16203a;--wg-ink:#f1f5f9;--wg-mute:#c3cfdd;--wg-soft:#aab7c9;
    --wg-acc:#fb923c;--wg-live:#ffb4ab;--wg-live-bg:#3a1f22;--wg-chip:#223052;--wg-me:#93c5fd}
}
.wg-days{display:flex;gap:8px;overflow-x:auto;margin:4px 0 10px;padding-bottom:2px}
.wg-days button{flex:none;min-height:40px;padding:0 16px;border-radius:999px;font:inherit;
  font-weight:700;font-size:14px;border:1px solid var(--wg-line);background:var(--wg-card);
  color:var(--wg-ink);cursor:pointer}
.wg-days button[aria-pressed=true]{background:var(--wg-acc);border-color:var(--wg-acc);color:#fff}
.wg-bar{display:flex;flex-wrap:wrap;align-items:center;gap:6px 12px;margin:0 0 12px;
  font-size:13px;color:var(--wg-mute)}
.wg-bar select{min-height:36px;font:inherit;font-size:14px;border-radius:8px;
  border:1px solid var(--wg-line);background:var(--wg-card);color:var(--wg-ink);padding:0 8px;
  max-width:100%}
.wg h3{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--wg-soft);
  margin:18px 0 8px;display:flex;align-items:baseline;gap:8px}
.wg h3 .wg-n{font-weight:600;letter-spacing:0;text-transform:none}
.wg-list{display:grid;gap:8px}
a.wg-g{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:2px 12px;padding:10px 12px;
  border:1px solid var(--wg-line);border-radius:12px;background:var(--wg-card);color:inherit;
  text-decoration:none}
a.wg-g.top{border-left:4px solid var(--wg-acc);padding-left:10px}
a.wg-g.live{border-color:#fca5a5;background:var(--wg-live-bg)}
a.wg-g.done{opacity:.8}
.wg-t{display:flex;align-items:center;gap:8px;min-width:0;font-size:15.5px;font-weight:700;
  color:var(--wg-ink);line-height:1.5}
.wg-t img{width:24px;height:24px;flex:none;object-fit:contain;border:0;padding:0;margin:0;
  box-shadow:none;background:none}
.wg-t .nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.wg-t .rk{font-size:11.5px;font-weight:700;color:var(--wg-soft)}
.wg-t .sc{margin-left:auto;font-variant-numeric:tabular-nums;font-size:16px}
.wg-t.lost{color:var(--wg-mute);font-weight:600}
.wg-when{grid-row:1 / span 2;grid-column:2;text-align:right;font-size:13px;font-weight:700;
  color:var(--wg-ink);white-space:nowrap;align-self:center;line-height:1.35}
.wg-when small{display:block;font-size:12px;font-weight:600;color:var(--wg-soft)}
.wg-when.live{color:var(--wg-live)}
.wg-sub{grid-column:1 / -1;font-size:12.5px;color:var(--wg-mute);line-height:1.45;margin-top:2px}
.wg-sub b{color:var(--wg-ink)}
.wg-tags{grid-column:1 / -1;display:flex;flex-wrap:wrap;gap:5px;margin-top:4px;align-items:center}
.wg-tags span{font-size:11.5px;font-weight:700;padding:2px 8px;border-radius:999px;
  background:var(--wg-chip);color:var(--wg-mute)}
.wg-tags .wg-sc{background:var(--wg-acc);color:#fff}
.wg-tags .hot{background:#fee2e2;color:#991b1b}
.wg-tags .mine{background:#dbeafe;color:#1e3a8a}
.wg-me{grid-column:1 / -1;font-size:12.5px;color:var(--wg-me);font-weight:600;margin-top:2px}
.wg-more{margin-top:8px}
.wg-more summary{cursor:pointer;font-weight:700;font-size:14px;color:var(--wg-acc);
  min-height:40px;display:flex;align-items:center}
.wg-note{font-size:13px;color:var(--wg-mute);line-height:1.5;margin:0 0 8px}
.wg-how summary{cursor:pointer;font-size:13px;color:var(--wg-soft);min-height:36px;
  display:flex;align-items:center}
@media (prefers-color-scheme: dark){
  .wg-t img{background:#e8edf5;border-radius:50%;padding:2px;box-sizing:border-box}
  a.wg-g.live{border-color:#7f1d1d}
  .wg-tags .hot{background:#7f1d1d;color:#fecaca}
  .wg-tags .mine{background:#1e3a8a;color:#dbeafe}
}
</style>"""

JS = """<script>
(function(){
  var D=JSON.parse(document.getElementById('wg-data').textContent);
  var host=document.getElementById('wg-host');
  if(!host) return;
  var LOGO='https://a.espncdn.com/combiner/i?img=/i/teamlogos/ncaa/500/{id}.png&w=80&h=80';
  var GAME_HOURS=4.5, MORE=5, STALE_DAYS=3;
  var live={}, timer=null, day=null;
  function esc(v){
    return String(v==null?'':v).replace(/[&<>"']/g,function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});
  }
  function etDate(t){ return new Date(t).toLocaleDateString('en-CA',{timeZone:'America/New_York'}); }
  function stars(){
    var list=[], set={};
    try{ list=JSON.parse(localStorage.getItem('gs:favorites')||'[]')||[]; }catch(e){}
    list.forEach(function(k){ if(typeof k==='string'&&k.indexOf('cfb:')===0) set[k.slice(4)]=1; });
    return set;
  }
  function myTeam(){
    try{ var k=localStorage.getItem('cfbMyTeam'); if(k&&D.rosters[k]) return k; }catch(e){}
    return '';
  }
  function state(g){ var L=live[g.id]; return (L&&L.state)||g.state; }
  function players(g, team){
    var r=D.rosters[team]; if(!r) return [];
    return r.p.filter(function(p){ return p[2]===g.h.id||p[2]===g.a.id; });
  }
  /** The watch score with the reader's part and the live part added, and why. */
  function watch(g, set, team){
    var s=g.score, why=g.tags.slice(), hot=[], ps=players(g,team);
    var star=!!(set[g.h.id]||set[g.a.id]);
    if(star) s+=100;
    s+=Math.min(20, ps.reduce(function(t,p){ return t+(p[3]?5:2); },0));
    var L=live[g.id];
    if(L&&L.state==='in'){
      var diff=Math.abs((L.home||0)-(L.away||0));
      if(L.period>=5){ s+=40; hot.push('Overtime'); }
      else if(L.period>=4&&diff<=8){ s+=30; hot.push('Close late'); }
      if(L.period>=3&&((g.fav==='h'&&L.away>L.home)||(g.fav==='a'&&L.home>L.away))){ s+=15; hot.push('Upset alert'); }
    }
    return {s:s, why:why, hot:hot, ps:ps, star:star};
  }
  function kick(g){
    var d=new Date(g.ko);
    return g.tk?d.toLocaleTimeString(undefined,{hour:'numeric',minute:'2-digit'}):'TBA';
  }
  function side(g, k, st){
    var t=g[k], L=live[g.id]||{}, o=k==='h'?'a':'h';
    var sc=L[k==='h'?'home':'away'], other=L[k==='h'?'away':'home'];
    if(sc==null&&st!=='pre'){ sc=t.sc; other=g[o].sc; }
    var lost=st==='post'&&sc!=null&&other!=null&&sc<other;
    return '<div class="wg-t'+(lost?' lost':'')+'"><img src="'+LOGO.replace('{id}',encodeURIComponent(t.id))
      +'" alt="" width="24" height="24" loading="lazy">'+(t.rk?'<span class="rk">'+esc(t.rk)+'</span>':'')
      +'<span class="nm">'+esc(t.nm)+'</span>'+(st!=='pre'&&sc!=null?'<span class="sc">'+esc(sc)+'</span>':'')+'</div>';
  }
  function line(g){
    var out='';
    if(g.hw!=null&&g.h.pr!=null&&g.a.pr!=null){
      var hf=g.hw>=0.5, fav=hf?g.h:g.a, p=hf?g.hw:1-g.hw;
      out='GordStats: <b>'+esc(fav.nm)+'</b> by '+Math.abs(g.h.pr-g.a.pr).toFixed(1)+' &middot; '+Math.round(p*100)+'%';
    }
    if(g.sp!=null){
      var bf=g.sp<0?g.h:g.a;
      out+=(out?' &middot; ':'')+'Line: '+esc(bf.nm)+' '+(g.sp===0?'pk':'&minus;'+Math.abs(g.sp));
    }
    if(g.note) out=esc(g.note)+(out?' &middot; '+out:'');
    return out;
  }
  function card(x, top){
    var g=x.g, w=x.w, st=state(g), L=live[g.id]||{};
    var when;
    if(st==='in') when='<div class="wg-when live">Live<small>'+esc(L.detail||'')+'</small></div>';
    else if(st==='post') when='<div class="wg-when">Final<small>'+esc(g.tv)+'</small></div>';
    else when='<div class="wg-when">'+kick(g)+'<small>'+esc(g.tv)+'</small></div>';
    var tags='<span class="wg-sc" title="Watch score, out of 100">Watch '+Math.min(100,Math.round(w.s-(w.star?100:0)))+'</span>'
      +(w.star?'<span class="mine">Your team</span>':'')
      +w.hot.map(function(t){ return '<span class="hot">'+esc(t)+'</span>'; }).join('')
      +w.why.map(function(t){ return '<span>'+esc(t)+'</span>'; }).join('');
    var me=w.ps.length?'<div class="wg-me">Your players: '+w.ps.map(function(p){
      return esc(p[0])+' ('+esc(p[1])+(p[3]?'':', bench')+')'; }).join(', ')+'</div>':'';
    var sub=line(g);
    return '<a class="wg-g'+(top?' top':'')+(st==='in'?' live':'')+(st==='post'?' done':'')
      +'" href="/cfb/schedule/" data-gid="'+esc(g.id)+'">'
      +side(g,'a',st)+side(g,'h',st)+when
      +(sub?'<div class="wg-sub">'+sub+'</div>':'')+me
      +'<div class="wg-tags">'+tags+'</div></a>';
  }
  function list(items, first){
    var head=items.slice(0,MORE), rest=items.slice(MORE);
    return '<div class="wg-list">'+head.map(function(x,i){ return card(x, first&&i===0); }).join('')+'</div>'
      +(rest.length?'<details class="wg-more"><summary>'+rest.length+' more</summary><div class="wg-list">'
        +rest.map(function(x){ return card(x,false); }).join('')+'</div></details>':'');
  }
  function days(){
    var today=etDate(Date.now()), seen={}, out=[];
    D.games.forEach(function(g){ if(g.day>=today&&!seen[g.day]){ seen[g.day]=1; out.push(g.day); } });
    return out.sort();
  }
  function dayLabel(d){
    var t=new Date(d+'T12:00:00Z');
    return (d===etDate(Date.now())?'Today':t.toLocaleDateString(undefined,{weekday:'short',timeZone:'UTC'}))
      +' '+t.getUTCDate();
  }
  function picker(team){
    var keys=Object.keys(D.rosters); if(!keys.length) return '';
    keys.sort(function(a,b){ return D.rosters[a].n.localeCompare(D.rosters[b].n); });
    return '<label>Your fantasy team <select id="wg-team"><option value="">&mdash; pick &mdash;</option>'
      +keys.map(function(k){ return '<option value="'+esc(k)+'"'+(k===team?' selected':'')+'>'+esc(D.rosters[k].n)+'</option>'; }).join('')
      +'</select></label>';
  }
  function draw(){
    var ds=days();
    if(!ds.length){ host.innerHTML='<p class="wg-note">No games in the next week.</p>'; return; }
    if(ds.indexOf(day)<0) day=ds[0];
    var set=stars(), team=myTeam();
    var items=D.games.filter(function(g){ return g.day===day; })
      .map(function(g){ return {g:g, w:watch(g,set,team)}; });
    var by=function(a,b){ return b.w.s-a.w.s; };
    var on=items.filter(function(x){ return state(x.g)==='in'; }).sort(by);
    var done=items.filter(function(x){ return state(x.g)==='post'; }).sort(by);
    var html='<div class="wg-days" role="group" aria-label="Day">'+ds.map(function(d){
      return '<button type="button" data-day="'+d+'" aria-pressed="'+(d===day)+'">'+dayLabel(d)+'</button>'; }).join('')+'</div>'
      +'<div class="wg-bar">'+picker(team)+(Object.keys(set).length?'':'<span>Star teams on the <a href="/cfb/power/">rankings</a> to put their games first.</span>')+'</div>';
    if(on.length) html+='<h3>On now <span class="wg-n">'+on.length+'</span></h3>'+list(on,true);
    D.slots.forEach(function(s){
      var xs=items.filter(function(x){ return x.g.slot===s[0]&&state(x.g)==='pre'; }).sort(by);
      if(xs.length) html+='<h3>'+esc(s[1])+' <span class="wg-n">'+esc(s[2])+'</span></h3>'+list(xs,true);
    });
    if(done.length) html+='<details class="wg-more"><summary>Final &middot; '+done.length+'</summary><div class="wg-list">'
      +done.map(function(x){ return card(x,false); }).join('')+'</div></details>';
    host.innerHTML=html;
  }
  host.addEventListener('click', function(e){
    var b=e.target.closest('button[data-day]'); if(!b) return;
    day=b.getAttribute('data-day'); draw(); poll();
  });
  host.addEventListener('change', function(e){
    if(e.target.id!=='wg-team') return;
    try{ localStorage.setItem('cfbMyTeam', e.target.value); }catch(err){}
    draw();
  });
  function onNow(g){
    var st=state(g), t=Date.parse(g.ko), now=Date.now();
    return st==='in'||(st!=='post'&&now>=t&&now<t+GAME_HOURS*3600e3);
  }
  function poll(){
    clearTimeout(timer);
    var now=D.games.filter(function(g){ return g.day===day&&onNow(g); });
    if(!now.length) return;
    if(document.hidden){ timer=setTimeout(poll,60000); return; }
    var asks={};
    now.forEach(function(g){ asks[g.wk+'|'+g.st]=g; });
    Promise.all(Object.keys(asks).map(function(k){
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
          live[String(e.id)]=o;
        });
      });
      draw();
      timer=setTimeout(poll,60000);
    });
  }
  if(Date.now()-Date.parse(D.generated)>STALE_DAYS*864e5){
    host.innerHTML='<p class="wg-note">This guide has not been rebuilt for a few days; the <a href="/cfb/schedule/">schedule</a> is current.</p>';
    return;
  }
  // Today if there are games today; otherwise the biggest day coming - on a
  // Wednesday that is Saturday, not Thursday's two games.
  var ds=days(), today=etDate(Date.now()), count={};
  D.games.forEach(function(g){ count[g.day]=(count[g.day]||0)+1; });
  day=ds.indexOf(today)>=0?today:ds.slice().sort(function(a,b){ return count[b]-count[a]||(a<b?-1:1); })[0];
  draw(); poll();
  document.addEventListener('gs:favorites', draw);
  document.addEventListener('visibilitychange', function(){ if(!document.hidden) poll(); });
})();
</script>"""


def _slot_hours() -> list:
    """[key, label, "12-2 ET"] for the windows, in order, TBA last."""
    out, start = [], None
    for key, label, before in SLOTS:
        def h(x):
            hh, mm = int(x), int(round((x % 1) * 60))
            return f"{(hh - 1) % 12 + 1}{':%02d' % mm if mm else ''}"
        span = (f"before {h(before)} ET" if start is None else
                f"from {h(start)} ET" if before > 24 else f"{h(start)}-{h(before)} ET")
        out.append([key, label, span])
        start = before
    return out + [[TBA[0], TBA[1], ""]]


def body(data: dict) -> str:
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    how = ("<details class='wg-how'><summary>How games are ranked</summary><p class='wg-note'>"
           "Each window's games, best first, by a watch score: ESPN's matchup quality (0-100, "
           "how good the teams are and how close it should be), nudged up for a Top 25 matchup and "
           "for playoff stakes (ESPN FPI gives both teams a 10%+ playoff chance, or one 25%+ in a "
           "game it could lose). Your starred teams go first, and games with players from your "
           "Yahoo team move up. During the day, a close game late, an overtime or an underdog "
           "ahead in the second half jumps the queue.</p></details>")
    return (CSS + "<div class='wg'>"
            + "<div id='wg-host'><p class='wg-note'>Loading the day's games&hellip;</p></div>"
            + how + share_button.row("/cfb/watch/", "What to watch in college football today")
            + "</div>"
            + f"<script type='application/json' id='wg-data'>{blob}</script>" + JS)


def generate() -> None:
    now = datetime.now(ET)
    try:
        teams = rosters()
    except Exception as exc:                 # the guide stands without the league
        print(f"watch guide: no league rosters ({exc})")
        teams = {}
    data = {"season": SEASON, "generated": now.isoformat(timespec="minutes"),
            "slots": _slot_hours(), "games": games(now), "rosters": teams}
    write_page(OUT, "Watch Guide", body(data), subtitle="What to have on, window by window",
               description="Every college football game of the day, grouped by kickoff and "
                           "ranked by how much it is worth watching - with live scores.")


if __name__ == "__main__":
    generate()
