"""
The watch guide, for any sport: the day cut into kickoff windows, each ranked
by a watch score, with the reader's own teams and fantasy players and the live
state of the games added in the browser.

A reader on a game day has one question the schedule answers only after some
sorting: what should be on right now, and what after it. This is the page for
it, shared by the three sports (the pattern of gordstats.matchup_page): each
sport's adapter builds the day's games in one shape and says how its live
scores are read, and everything else - the windows, the ranking, the cards,
the reader's part, the live queue - lives here once.

    cfb.site.watch      /cfb/watch/   ESPN matchup quality, Yahoo rosters, stars
    nfl.site.watch      /nfl/watch/   ESPN matchup quality, Sleeper rosters and
                                      the reader's opponent this week
    cbb.render.render_watch  /cbb/watch/  built in the browser from the live
                                      scoreboard feed, men's and women's

A game, as the adapters build it (JSON, short keys - a Saturday is 60 of them):

    id, day (ET date), slot, ko (kickoff, UTC), tk (time known), tv, note,
    n (neutral), state, hw (our home win chance), sp (book spread, home),
    score (the watch score), tags, fav ('h' / 'a' / None, the pregame favourite)
    h / a: id, nm, lg (logo URL), rk (rank), rec (record), sc (score),
           pr (our projected points), k (the key rosters use for the team)

Rosters, when the sport has a fantasy league here: {key: {n: team name,
p: [[player, pos, team key, starting]], opp: this week's opponent's key}}.

The watch score starts from ESPN's matchup quality (0-100: how good the teams
are and how close it should be) where the sport has one, nudged for the
things it misses; the reader's part (+100 for a starred team, up to +20 for
their fantasy players, +12 for their opponent's) and the live part (a close
game late, overtime, an underdog ahead in the second half) are added in the
browser, where they are known.
"""
import json
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

import pandas as pd

from gordstats import share_button

ET = ZoneInfo("America/New_York")
TBA = ("tba", "Time TBA")
TOSS_UP = 3.0             # a line this small is a coin flip (cfb.site.schedule's badge)
UPSET_WATCH = 0.35        # an underdog somebody gives this much is worth a look


# A kickoff before this Eastern hour belongs to the night before: Hawaii's
# 12:30 AM football and the Pacific's late tips are the end of a day, not the
# start of the next one's early window.
NIGHT_ENDS = 4


def slot(kick: pd.Timestamp, slots: list, time_known: bool = True) -> str:
    """The window a kickoff falls in: `slots` is [(key, label, starts before
    this Eastern hour)], the last one open-ended."""
    if not time_known:
        return TBA[0]
    t = pd.Timestamp(kick).tz_convert(ET)
    hour = t.hour + t.minute / 60
    if hour < NIGHT_ENDS:
        return slots[-1][0]
    return next(key for key, _label, before in slots if hour < before)


def game_day(kick: pd.Timestamp) -> str:
    """The Eastern date a game is on the guide's day tabs, the small hours
    counted to the night before (NIGHT_ENDS)."""
    t = pd.Timestamp(kick).tz_convert(ET)
    if t.hour < NIGHT_ENDS:
        t -= pd.Timedelta(days=1)
    return t.strftime("%Y-%m-%d")


def slot_hours(slots: list) -> list:
    """[key, label, "2-6 ET"] for the windows, in order, TBA last."""
    def h(x):
        hh, mm = int(x), int(round((x % 1) * 60))
        return f"{(hh - 1) % 12 + 1}{':%02d' % mm if mm else ''}"
    out, start = [], None
    for key, label, before in slots:
        span = (f"before {h(before)} ET" if start is None else
                f"from {h(start)} ET" if before > 24 else f"{h(start)}-{h(before)} ET")
        out.append([key, label, span])
        start = before
    return out + [[TBA[0], TBA[1], ""]]


def judge(quality, spread, probs, margin=None, nudges=(), toss_up: float = TOSS_UP,
          span: float = 28.0) -> tuple:
    """(watch score, tags, pregame favourite 'h' / 'a' / None).

    `quality` is ESPN's matchup quality (0-100) or None; `spread` the book's
    home line (our `margin`, home points, stands in when there is none);
    `probs` the home win chances there are (ours, ESPN's). `nudges` are
    (tag, applies) pairs - a Top 25 matchup, playoff stakes - and each that
    applies is tagged and closes a quarter of the gap to 100, so the score
    stays on the 0-100 scale. With no quality the closeness of the game stands
    in, at half weight."""
    if spread is None and margin is not None:
        spread = -margin
    fav = None if spread is None or abs(spread) <= 0.25 else ("h" if spread < 0 else "a")
    probs = [p for p in probs if p is not None]
    dog = None
    if probs and fav:
        dog = max((p if fav == "a" else 1 - p) for p in probs)
    elif probs:
        dog = max(min(p, 1 - p) for p in probs)
    tags = [tag for tag, on in nudges if on and tag]
    if spread is not None and abs(spread) <= toss_up:
        tags.insert(1 if tags and tags[0] == "Top 25 matchup" else 0, "Toss-up")
    elif dog is not None and dog >= UPSET_WATCH:
        tags.insert(1 if tags and tags[0] == "Top 25 matchup" else 0, "Upset watch")
    if quality is None:
        quality = 50 * max(0.0, 1 - abs(spread) / span) if spread is not None else 20.0
    lifted = sum(1 for _tag, on in nudges if on)
    return round(quality + (100 - quality) * 0.25 * lifted, 1), tags, fav


def best_day(games: list, today: str) -> str:
    """The day the guide opens on: today if there are games today, otherwise
    the biggest day coming (on a Wednesday, Saturday rather than Thursday's
    two games). The browser makes the same choice (JS)."""
    days = {}
    for g in games:
        if g["day"] >= today:
            days[g["day"]] = days.get(g["day"], 0) + 1
    if not days:
        return ""
    return today if today in days else min(days, key=lambda d: (-days[d], d))


def teaser(games: list, now: datetime = None, n: int = 3) -> str:
    """The day's best few, for a section's home page: the guide's own ranking
    without the reader's part, which only the guide itself can add."""
    now = now or datetime.now(ET)
    today = now.astimezone(ET).strftime("%Y-%m-%d")
    day = best_day(games, today)
    todo = sorted((g for g in games if g["day"] == day and g["state"] != "post"),
                  key=lambda g: -g["score"])[:n]
    if not todo:
        return ""
    when = "Today" if day == today else datetime.strptime(day, "%Y-%m-%d").strftime("%A")

    def team(t):
        return (f"{'<span class=wt-rk>' + str(int(t['rk'])) + '</span> ' if t.get('rk') else ''}"
                f"{escape(t['nm'])}")
    rows = "".join(
        f"<li><span class='wt-g'>{team(g['a'])} <span class='wt-at'>{'vs' if g['n'] else 'at'}</span> "
        f"{team(g['h'])}</span><span class='wt-w'>"
        + (pd.Timestamp(g["ko"]).tz_convert(ET).strftime("%-I:%M %p ET") if g["tk"] else "TBA")
        + (f" &middot; {escape(g['tv'])}" if g["tv"] else "")
        + f" &middot; <b>Watch {min(100, round(g['score']))}</b></span></li>"
        for g in todo)
    return ("<style>.wt{list-style:none;margin:0;padding:0}.wt li{padding:8px 0;"
            "border-top:1px solid var(--gs-line,#e2e8f0);display:flex;flex-direction:column;gap:2px}"
            ".wt li:first-child{border-top:0}.wt-g{font-weight:700;font-size:15px}"
            ".wt-at{font-weight:500;color:var(--gs-muted,#5d6b7e);font-size:13px}"
            ".wt-rk{font-size:12px;color:var(--gs-muted,#5d6b7e)}"
            ".wt-w{font-size:13px;color:var(--gs-muted,#5d6b7e)}"
            "@media (prefers-color-scheme: dark){.wt li{border-color:#2b3852}}</style>"
            f"<p class='wt-day'><b>{when}</b>, best first:</p><ul class='wt'>{rows}</ul>")


def body(data: dict, adapter_js: str, how: str, share_url: str, share_text: str) -> str:
    """The page: the host the engine draws into, how it ranks, the Share
    button, the day's games as JSON (when the sport builds them here), then
    the engine and the sport's adapter, which starts it."""
    blob = ("" if data is None else
            "<script type='application/json' id='wg-data'>"
            + json.dumps(data, separators=(",", ":")).replace("</", "<\\/") + "</script>")
    return (CSS + "<div class='wg'>"
            + "<div id='wg-host'><p class='wg-note'>Loading the day's games&hellip;</p></div>"
            + "<details class='wg-how'><summary>How games are ranked</summary>"
            + f"<p class='wg-note'>{how}</p></details>"
            + share_button.row(share_url, share_text) + "</div>"
            + blob + ENGINE_JS + adapter_js)


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
.wg-t .rec{font-size:12px;font-weight:600;color:var(--wg-soft)}
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
.wg-them{grid-column:1 / -1;font-size:12.5px;color:var(--wg-mute);font-weight:600}
.wg-more{margin-top:8px}
.wg-more summary{cursor:pointer;font-weight:700;font-size:14px;color:var(--wg-acc);
  min-height:40px;display:flex;align-items:center}
.wg-note{font-size:13px;color:var(--wg-mute);line-height:1.5;margin:0 0 8px}
.wg-note.wg-empty{font-size:17px;color:var(--wg-ink);margin:8px 0 16px}
.wg-how summary{cursor:pointer;font-size:13px;color:var(--wg-soft);min-height:36px;
  display:flex;align-items:center}
@media (prefers-color-scheme: dark){
  .wg-t img{background:#e8edf5;border-radius:50%;padding:2px;box-sizing:border-box}
  a.wg-g.live{border-color:#7f1d1d}
  .wg-tags .hot{background:#7f1d1d;color:#fecaca}
  .wg-tags .mine{background:#1e3a8a;color:#dbeafe}
}
</style>"""



# The engine. A sport's adapter calls GSWatch(data, cfg) - cfg says what only
# the sport knows:
#
#   live(games, D)  -> Promise of {game id: {state, detail, period, home, away,
#                      late, ot, second}} for the games on now (the phase flags
#                      optional: football reads them off the quarter, the
#                      adapter sets them where it cannot)
#   stars()         -> {team key: 1} for the reader's starred teams
#   myKey           the localStorage key of the reader's fantasy team
#   link            where a card goes; a game's own `href` wins
#   hint            a line for a reader with no stars and no team picked
#   close           a margin that counts as close late (football 8, basketball 6)
#   every           milliseconds between live polls (default a minute)
#
# cfg is read each time the guide draws, so an adapter may change its hint or
# empty line between draws (CBB does, per league). It returns {set(D),
# update(D), redraw()}: set swaps in another set of games, update refreshes
# the same ones keeping the reader's day.
ENGINE_JS = """<script>
window.GSWatch=function(D, cfg){
  var host=document.getElementById('wg-host');
  if(!host) return null;
  cfg=cfg||{};
  var GAME_HOURS=cfg.gameHours||4.5, MORE=5, STALE_DAYS=3, CLOSE=cfg.close||8;
  var live={}, timer=null, day=null;
  function esc(v){
    return String(v==null?'':v).replace(/[&<>"']/g,function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});
  }
  function etDate(t){ return new Date(t).toLocaleDateString('en-CA',{timeZone:'America/New_York'}); }
  function rosters(){ return D.rosters||{}; }
  function stars(){ try{ return cfg.stars?cfg.stars()||{}:{}; }catch(e){ return {}; } }
  function myTeam(){
    if(!cfg.myKey) return '';
    try{ var k=localStorage.getItem(cfg.myKey); if(k&&rosters()[k]) return k; }catch(e){}
    return '';
  }
  function key(t){ return String(t.k!=null?t.k:t.id); }
  function state(g){ var L=live[g.id]; return (L&&L.state)||g.state; }
  function players(g, team){
    var r=rosters()[team]; if(!r) return [];
    var hk=key(g.h), ak=key(g.a);
    return r.p.filter(function(p){ return String(p[2])===hk||String(p[2])===ak; });
  }
  /** The watch score with the reader's part and the live part added, and why. */
  function watch(g, set, team){
    var s=g.score, why=(g.tags||[]).slice(), hot=[], ps=players(g,team);
    var opp=team&&rosters()[team]&&rosters()[team].opp;
    var theirs=opp!=null&&rosters()[String(opp)]?players(g,String(opp)):[];
    var star=!!(set[key(g.h)]||set[key(g.a)]);
    if(star) s+=100;
    s+=Math.min(20, ps.reduce(function(t,p){ return t+(p[3]?5:2); },0));
    s+=Math.min(12, theirs.reduce(function(t,p){ return t+(p[3]?3:0); },0));
    var L=live[g.id];
    if(L&&L.state==='in'){
      var diff=Math.abs((L.home||0)-(L.away||0));
      var late=L.late!=null?L.late:L.period>=4, ot=L.ot!=null?L.ot:L.period>=5;
      var second=L.second!=null?L.second:L.period>=3;
      if(ot){ s+=40; hot.push('Overtime'); }
      else if(late&&diff<=CLOSE){ s+=30; hot.push('Close late'); }
      if(second&&((g.fav==='h'&&L.away>L.home)||(g.fav==='a'&&L.home>L.away))){ s+=15; hot.push('Upset alert'); }
    }
    return {s:s, why:why, hot:hot, ps:ps, theirs:theirs, opp:opp, star:star};
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
    return '<div class="wg-t'+(lost?' lost':'')+'">'
      +(t.lg?'<img src="'+esc(t.lg)+'" alt="" width="24" height="24" loading="lazy">':'')
      +(t.rk?'<span class="rk">'+esc(t.rk)+'</span>':'')
      +'<span class="nm">'+esc(t.nm)+'</span>'+(t.rec&&st==='pre'?'<span class="rec">'+esc(t.rec)+'</span>':'')
      +(st!=='pre'&&sc!=null?'<span class="sc">'+esc(sc)+'</span>':'')+'</div>';
  }
  function line(g){
    var out='';
    if(g.hw!=null&&g.h.pr!=null&&g.a.pr!=null){
      var hf=g.hw>=0.5, fav=hf?g.h:g.a, p=hf?g.hw:1-g.hw;
      out='GordStats: <b>'+esc(fav.nm)+'</b> by '+Math.abs(g.h.pr-g.a.pr).toFixed(1)+' &middot; '+Math.round(p*100)+'%';
    } else if(g.hw!=null){
      var hf2=g.hw>=0.5;
      out='GordStats: <b>'+esc((hf2?g.h:g.a).nm)+'</b> '+Math.round((hf2?g.hw:1-g.hw)*100)+'%';
    }
    if(g.lt) out+=(out?' &middot; ':'')+'Line: '+esc(g.lt);
    else if(g.sp!=null){
      var bf=g.sp<0?g.h:g.a;
      out+=(out?' &middot; ':'')+'Line: '+esc(bf.nm)+' '+(g.sp===0?'pk':'&minus;'+Math.abs(g.sp));
    }
    if(g.note) out=esc(g.note)+(out?' &middot; '+out:'');
    return out;
  }
  function names(ps){
    return ps.map(function(p){ return esc(p[0])+' ('+esc(p[1])+(p[3]?'':', bench')+')'; }).join(', ');
  }
  function card(x, top){
    var g=x.g, w=x.w, st=state(g), L=live[g.id]||{};
    var when;
    if(st==='in') when='<div class="wg-when live">Live<small>'+esc(L.detail||'')+'</small></div>';
    else if(st==='post') when='<div class="wg-when">Final<small>'+esc(g.tv)+'</small></div>';
    else when='<div class="wg-when">'+kick(g)+'<small>'+esc(g.tv)+'</small></div>';
    var tags='<span class="wg-sc" title="Watch score, out of 100">Watch '+Math.min(100,Math.round(g.score))+'</span>'
      +(w.star?'<span class="mine">Your team</span>':'')
      +w.hot.map(function(t){ return '<span class="hot">'+esc(t)+'</span>'; }).join('')
      +w.why.map(function(t){ return '<span>'+esc(t)+'</span>'; }).join('');
    var me=w.ps.length?'<div class="wg-me">Your players: '+names(w.ps)+'</div>':'';
    var them=w.theirs.length?'<div class="wg-them">'+esc(rosters()[String(w.opp)].n)+'\\u2019s: '+names(w.theirs)+'</div>':'';
    var sub=line(g);
    return '<a class="wg-g'+(top?' top':'')+(st==='in'?' live':'')+(st==='post'?' done':'')
      +'" href="'+esc(g.href||cfg.link||'#')+'" data-gid="'+esc(g.id)+'">'
      +side(g,'a',st)+side(g,'h',st)+when
      +(sub?'<div class="wg-sub">'+sub+'</div>':'')+me+them
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
    var R=rosters(), keys=Object.keys(R); if(!keys.length||!cfg.myKey) return '';
    keys.sort(function(a,b){ return R[a].n.localeCompare(R[b].n); });
    return '<label>'+esc(cfg.pickLabel||'Your fantasy team')+' <select id="wg-team"><option value="">&mdash; pick &mdash;</option>'
      +keys.map(function(k){ return '<option value="'+esc(k)+'"'+(k===team?' selected':'')+'>'+esc(R[k].n)+'</option>'; }).join('')
      +'</select></label>';
  }
  function pickDay(){
    // Today if there are games today; otherwise the biggest day coming - on a
    // Wednesday that is Saturday, not Thursday's two games (best_day, in Python).
    var ds=days(), today=etDate(Date.now()), count={};
    D.games.forEach(function(g){ count[g.day]=(count[g.day]||0)+1; });
    day=ds.indexOf(today)>=0?today:ds.slice().sort(function(a,b){ return count[b]-count[a]||(a<b?-1:1); })[0];
  }
  function draw(){
    var ds=days();
    if(!ds.length){ host.innerHTML=(cfg.top||'')+'<p class="wg-note wg-empty">'+(cfg.emptyHtml||'No games in the next week.')+'</p>'; return; }
    if(ds.indexOf(day)<0) day=ds[0];
    var set=stars(), team=myTeam();
    var items=D.games.filter(function(g){ return g.day===day; })
      .map(function(g){ return {g:g, w:watch(g,set,team)}; });
    var by=function(a,b){ return b.w.s-a.w.s; };
    var on=items.filter(function(x){ return state(x.g)==='in'; }).sort(by);
    var done=items.filter(function(x){ return state(x.g)==='post'; }).sort(by);
    var hint=(Object.keys(set).length||team||!cfg.hint)?'':'<span>'+cfg.hint+'</span>';
    var html=(cfg.top||'')+'<div class="wg-days" role="group" aria-label="Day">'+ds.map(function(d){
      return '<button type="button" data-day="'+d+'" aria-pressed="'+(d===day)+'">'+dayLabel(d)+'</button>'; }).join('')+'</div>'
      +'<div class="wg-bar">'+picker(team)+hint+'</div>';
    if(on.length) html+='<h3>On now <span class="wg-n">'+on.length+'</span></h3>'+list(on,true);
    D.slots.forEach(function(s){
      var xs=items.filter(function(x){ return x.g.slot===s[0]&&state(x.g)==='pre'; }).sort(by);
      if(xs.length) html+='<h3>'+esc(s[1])+' <span class="wg-n">'+esc(s[2])+'</span></h3>'+list(xs,true);
    });
    if(done.length) html+='<details class="wg-more"><summary>Final &middot; '+done.length+'</summary><div class="wg-list">'
      +done.map(function(x){ return card(x,false); }).join('')+'</div></details>';
    host.innerHTML=html;
  }
  function onNow(g){
    var st=state(g), t=Date.parse(g.ko), now=Date.now();
    return st==='in'||(st!=='post'&&now>=t&&now<t+GAME_HOURS*3600e3);
  }
  function poll(){
    clearTimeout(timer);
    var now=D.games.filter(function(g){ return g.day===day&&onNow(g); });
    if(!cfg.live) return;
    if(!now.length){
      // Nothing on yet: wake at the next kickoff of the day on screen, so a
      // page opened at noon goes live at one without a reload.
      var next=D.games.filter(function(g){ return g.day===day&&state(g)==='pre'&&g.tk&&Date.parse(g.ko)>Date.now(); })
        .map(function(g){ return Date.parse(g.ko); }).sort()[0];
      if(next&&next-Date.now()<864e5) timer=setTimeout(poll, next-Date.now()+30000);
      return;
    }
    if(document.hidden){ timer=setTimeout(poll,60000); return; }
    Promise.resolve(cfg.live(now, D)).then(function(map){
      Object.keys(map||{}).forEach(function(k){ live[k]=map[k]; });
    }).catch(function(){}).then(function(){
      draw();
      timer=setTimeout(poll,cfg.every||60000);
    });
  }
  host.addEventListener('click', function(e){
    var b=e.target.closest('button[data-day]'); if(!b) return;
    day=b.getAttribute('data-day'); draw(); poll();
  });
  host.addEventListener('change', function(e){
    if(e.target.id!=='wg-team') return;
    try{ localStorage.setItem(cfg.myKey, e.target.value); }catch(err){}
    draw();
  });
  document.addEventListener('gs:favorites', function(){ draw(); });
  document.addEventListener('visibilitychange', function(){ if(!document.hidden) poll(); });
  function start(){
    if(D.generated&&Date.now()-Date.parse(D.generated)>STALE_DAYS*864e5){
      host.innerHTML='<p class="wg-note">'+(cfg.staleHtml||'This guide has not been rebuilt for a few days.')+'</p>';
      return;
    }
    live={}; pickDay(); draw(); poll();
  }
  start();
  // set: another set of games altogether (CBB's men's/women's switch) - the
  // day and the live scores start over. update: the same games refreshed -
  // the reader's day and what is live stay.
  return {set:function(next){ D=next; start(); },
          update:function(next){ D=next; draw(); poll(); }, redraw:draw};
};
</script>"""
