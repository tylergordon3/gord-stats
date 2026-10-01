"""
The CBB watch guide (/cbb/watch/): the day's college basketball, men's or
women's, cut into tip-off windows and ranked by what is most worth having on -
the shared engine is gordstats.watch_page (CFB's twin: cfb.site.watch). What
is basketball's own:

    the games       not built here. The live scoreboard Worker already holds
                    both leagues, two days back and a week ahead, with
                    GordStats' call on every game (cbb.live pushes it every ten
                    minutes in playing hours), so the page reads it in the
                    browser: one fetch, and the scores come with it. A 60-game
                    Tuesday built into the page each morning would be stale by
                    the first tip.
    the score       GordStats' ranks and call, where football has ESPN's
                    matchup quality (below)
    the reader's part  starred teams (gordstats.favorites, `cbb-men:<slug>`
                    on the rankings). /cbb/star-teams.json
                    (render_power.star_teams) gives each star key its name on
                    the scoreboard, and its logo - the feed carries neither.
    live            the same feed again, every three minutes while a game is on
    no games        one line: when the next one is (ESPN's calendar, as the
                    /men/ board asks it; the season's first game when that does
                    not answer), and nothing else on the page

The watch score, 0-100, from the two teams' GordStats ranks (`home_model` in
the feed) and our home win chance p:

    grade       100 * 0.5 ** ((rank - 1) / 100) for each team: #1 is 100,
                #101 is 50, #201 is 25 (a team we do not rank counts as #365)
    strength    the harmonic mean of the two grades - a game is only as good
                as its weaker team lets it be
    closeness   100 * (1 - |2p - 1|): 100 for a coin flip, 0 for a sure thing
                (50 when we have no call)
    score       strength * (0.5 + 0.5 * closeness / 100)

so two top-50 teams at 60/40 come to about 66, #1 against #5 near a coin flip
to about 94, a 150th-v-160th coin flip to 34 and #1 against #300 to 11. Then
the engine's nudges (watch_page.judge), each closing a quarter of the gap to
100: a Top 25 matchup (both AP-ranked - but not in the NCAA tournament or the
NIT, where theScore's ranking is the seed) and a tournament game (a conference
tournament, the NIT, the Crown; the NCAA tournament counts twice). Tagged
"Toss-up" at 42-58% and "Upset watch" when the underdog has 35% or more.

    python -m cbb.render.render_watch
"""
import json

from cbb import paths
from gordstats import watch_page
from gordstats.frontmatter import add_front_matter

OUT = paths.DOCS / "cbb" / "watch" / "index.html"
FEED = "https://cbb-live-scores.tmgordon33.workers.dev/scores?league=men"

# Windows by Eastern tip-off: (key, label, starts before this hour). A tip
# after midnight (Hawaii at home, 12:30 ET) is the night before's late game,
# not the next day's early one - the browser moves it back. Not past 3: a
# game in Asia at 5 ET is the morning's.
SLOTS = [("early", "Early", 15.0), ("afternoon", "Afternoon", 18.0),
         ("evening", "Evening", 21.0), ("late", "Late", 99.0)]
AFTER_MIDNIGHT = 3.0

HALF_LIFE = 100            # places of rank that halve a team's grade
UNRANKED = 365             # a team GordStats does not rank (below D-1, new)
NO_CALL = 50.0             # closeness without our win chance
TOSS_UP = (0.42, 0.58)
UPSET_WATCH = watch_page.UPSET_WATCH
CLOSE = 6                  # a margin that is close late
BLOWOUT = 18               # a second-half margin that drops a game down the order
LATE_SECONDS = 300         # "late": the last five minutes, or overtime
EVERY = 180000             # the feed changes once a push, every ten minutes
GAME_HOURS = 2.5           # tip to final, and then some


def config() -> dict:
    """What the browser half needs from here: the windows (as the engine
    draws them and as the tip-off hours that cut them), the score's knobs, so
    the words under "How games are ranked" and the numbers cannot part, and
    the season's first game - the empty line's answer when ESPN's calendar
    does not come (render_home.CBB_TIPOFF, the date the live tick keys on)."""
    from cbb.render.render_home import CBB_TIPOFF
    return {"feed": FEED, "slots": watch_page.slot_hours(SLOTS),
            "cuts": [[key, before] for key, _label, before in SLOTS],
            "midnight": AFTER_MIDNIGHT, "half": HALF_LIFE, "unranked": UNRANKED,
            "nocall": NO_CALL, "toss": list(TOSS_UP), "upset": UPSET_WATCH,
            "close": CLOSE, "blowout": BLOWOUT, "lateSec": LATE_SECONDS, "every": EVERY, "gameHours": GAME_HOURS,
            "tipoff": CBB_TIPOFF.isoformat()}


# The switch between the leagues sits above the engine's host, outside what
# it redraws, so it survives a league with nothing on (the engine's empty line
# has no room for it). Pressed is ink-on-card rather than the day pills'
# orange: a different control, and it reads as one.
CSS = """<style>
.wg-lg{display:inline-flex;border:1px solid var(--wg-line);border-radius:10px;overflow:hidden;
  margin:2px 0 10px}
.wg-lg button{min-height:40px;min-width:92px;padding:0 18px;font:inherit;font-weight:700;
  font-size:14px;border:0;background:var(--wg-card);color:var(--wg-ink);cursor:pointer}
.wg-lg button+button{border-left:1px solid var(--wg-line)}
.wg-lg button[aria-pressed=true]{background:var(--wg-ink);color:var(--wg-card)}
.wg-empty{font-size:17px;color:var(--wg-ink)}
</style>"""

ADAPTER_JS = CSS + """<script>
(function(){
  var C=__CONFIG__;
  var host=document.getElementById('wg-host');
  if(!host||!window.GSWatch) return;
  var feed=null, fetchedAt=0, teams={}, W=null, turn=0, wake=null, lines={};
  var league='men';
  try{ if(localStorage.getItem('league')==='women') league='women'; }catch(e){}

  function etDate(t){ return new Date(t).toLocaleDateString('en-CA',{timeZone:'America/New_York'}); }
  function etHour(t){
    var p={};
    new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',hour:'2-digit',minute:'2-digit',
      hourCycle:'h23'}).formatToParts(new Date(t)).forEach(function(x){ p[x.type]=x.value; });
    return (+p.hour%24)+(+p.minute)/60;
  }
  function dayBefore(d){
    var t=new Date(d+'T12:00:00Z'); t.setUTCDate(t.getUTCDate()-1);
    return t.toISOString().slice(0,10);
  }
  function pushedAt(stamp){
    // Old pushes stamped naive UTC; the live tick stamps an offset.
    var g=String(stamp||''), t=Date.parse(/[zZ]|[+-]\\d\\d:\\d\\d$/.test(g)?g:g+'Z');
    return isNaN(t)?0:t;
  }
  function get(url){
    return fetch(url).then(function(r){ return r.ok?r.json():null; }).catch(function(){ return null; });
  }
  function num(v){ var n=parseFloat(v); return isFinite(n)?n:null; }
  function slug(s){
    return String(s).replace(/['\\u2019\\u02bc`]/g,'').toLowerCase().replace(/[^a-z0-9]+/g,'-')
      .replace(/^-+|-+$/g,'');
  }

  /* theScore's status, as the engine's three states; a game called off is
     no game to watch. */
  function state(s){
    s=String(s||'').toLowerCase();
    if(s==='final'||s==='closed') return 'post';
    if(!s||s==='pre_game'||s==='scheduled') return 'pre';
    if(/postpon|cancel|forfeit/.test(s)) return null;
    return 'in';
  }
  function seconds(clock){
    var c=String(clock||''), m=c.split(':');
    return m.length===2?(+m[0])*60+parseFloat(m[1]):(c?parseFloat(c):NaN);
  }
  /* Where a game is: the feed's period is "1st"/"2nd" for the men's halves,
     "1st"-"4th" for the women's quarters, "OT" (or "2OT") after. */
  function phase(g, women){
    var per=String(g.period||''), n=parseInt(per,10), half=/half/.test(String(g.status).toLowerCase());
    var reg=women?4:2, ot=g.overtime===true||/OT/i.test(per)||n>reg;
    var secs=seconds(g.clock);
    return {detail:half?'Half':[per,g.clock].filter(Boolean).join(' '), period:n||0, ot:!half&&ot,
            second:!half&&(ot||n>=(women?3:2)), late:!half&&(ot||(n>=reg&&secs<=C.lateSec))};
  }
  function liveOf(g, women){
    var p=phase(g, women), st=state(g.status);
    return {state:st, detail:p.detail, period:p.period, home:num(g.home_score), away:num(g.away_score),
            late:p.late, ot:p.ot, second:p.second};
  }

  function grade(rank){ return 100*Math.pow(0.5,((rank||C.unranked)-1)/C.half); }
  /** The watch score before the reader's part: the module docstring's formula. */
  function judge(hm, am, p, top25, tour){
    var a=grade(hm), b=grade(am), strength=2*a*b/(a+b);
    var close=p==null?C.nocall:100*(1-Math.abs(2*p-1));
    var s=strength*(0.5+0.5*close/100), tags=[], lifts=0;
    if(top25){ tags.push('Top 25 matchup'); lifts+=1; }
    if(tour){ tags.push('Tournament'); lifts+=tour; }
    var at=top25?1:0;
    if(p!=null&&p>=C.toss[0]&&p<=C.toss[1]) tags.splice(at,0,'Toss-up');
    else if(p!=null&&Math.min(p,1-p)>=C.upset) tags.splice(at,0,'Upset watch');
    return {score:Math.round((s+(100-s)*0.25*lifts)*10)/10, tags:tags,
            fav:p==null||p===0.5?null:(p>0.5?'h':'a')};
  }

  function team(g, side, women){
    var nm=g[side+'_team']||'TBD', t=teams[nm]||{};
    var rk=num(g[side+'_rank']);
    return {id:nm, nm:nm, lg:t.lg||'', rk:rk&&rk>0?rk:null, rec:g[side+'_record']||'',
            sc:num(g[side+'_score']), pr:num(g['pred_'+side]),
            k:(women?'cbb-women:':'cbb-men:')+(t.slug||slug(nm)),
            gs:num(g[side+'_model'])};
  }
  /** One league's games from the feed, in the engine's shape. */
  function games(lg){
    var src=(feed&&feed.leagues&&feed.leagues[lg])||{}, women=lg==='women', out=[];
    var now=Date.now(), today=etDate(now);
    Object.keys(src).forEach(function(id){
      var g=src[id]||{}, st=state(g.status);
      if(!st) return;
      var ko=g.start_time_utc?Date.parse(g.start_time_utc):NaN, tk=!isNaN(ko);
      var day=g.date||(tk?etDate(ko):''), slot='tba';
      if(tk){
        var h=etHour(ko);
        slot=C.cuts.filter(function(c){ return h<c[1]; })[0][0];
        if(h<C.midnight){ day=dayBefore(etDate(ko)); slot=C.cuts[C.cuts.length-1][0]; }
      }
      // A game not over is never in the past: last night's still going at
      // 12:40, or a tip at 12:30 that is tonight's late game.
      if(day<today&&(st==='in'||(st==='pre'&&tk&&ko>now))) day=today;
      var h2=team(g,'home',women), a2=team(g,'away',women);
      var mm=g.is_mm===true, nit=g.is_nit===true, desc=String(g.game_description||'');
      var tour=mm?2:(nit||/tournament/i.test(desc)||/postseason/i.test(g.game_type||''))?1:0;
      // In the NCAA tournament and the NIT theScore's ranking is the seed.
      var top25=!mm&&!nit&&!!h2.rk&&!!a2.rk;
      var p=num(g.home_win_prob), j=judge(h2.gs, a2.gs, p, top25, tour);
      out.push({id:String(id), day:day, slot:slot, ko:tk?new Date(ko).toISOString():'', tk:tk,
        tv:'', note:tour?desc.replace(/\\s*\\|\\s*/g,' \\u00b7 '):'', n:g.neutral===true, state:st,
        hw:p, sp:null, lt:g.spread_close?String(g.spread_close).replace(/ -(?=\\d)/,' \\u2212'):'',
        score:j.score, tags:j.tags, fav:j.fav, href:'/'+lg+'/', h:h2, a:a2});
    });
    return out;
  }
  function current(lg){
    var today=etDate(Date.now());
    return games(lg).filter(function(g){ return g.day>=today; });
  }

  /* The one line for a league with nothing from today on: what ESPN's
     calendar says about the next date (docs/assets/js/live.js asks the same
     way), once a day a league. */
  function nextLine(lg){
    var today=etDate(Date.now());
    if(lines[lg]&&lines[lg].day===today) return lines[lg].text;
    var url='https://site.api.espn.com/apis/site/v2/sports/basketball/'+(lg==='women'?'womens':'mens')
      +'-college-basketball/scoreboard?dates='+today.replace(/-/g,'')+'&limit=1';
    var text=get(url).then(function(d){
      var days=((d&&d.leagues&&d.leagues[0]&&d.leagues[0].calendar)||[]).map(function(c){
        return String(c&&c.startDate||c).slice(0,10); }).filter(function(x){ return /^\\d{4}-\\d\\d-\\d\\d$/.test(x); }).sort();
      // No calendar (the request failed, or it is still last season's):
      // the first game of the next, if it is still to come.
      var next=days.filter(function(x){ return x>=today; })[0]||(C.tipoff>today?C.tipoff:'');
      if(!next) return 'No games today.';
      if(next===today) return 'Today\\u2019s games aren\\u2019t posted yet.';
      return 'No games until '+new Date(next+'T12:00:00').toLocaleDateString(undefined,
        {weekday:'short',month:'short',day:'numeric'})+'.';
    });
    lines[lg]={day:today, text:text};
    return text;
  }

  /* The league switch, above what the engine redraws. */
  var sw=document.createElement('div');
  sw.className='wg-lg'; sw.setAttribute('role','group'); sw.setAttribute('aria-label','League');
  sw.style.display='none';
  sw.innerHTML='<button type="button" data-lg="men">Men</button><button type="button" data-lg="women">Women</button>';
  host.parentNode.insertBefore(sw, host);
  sw.addEventListener('click', function(e){
    var b=e.target.closest('button[data-lg]'); if(!b) return;
    var lg=b.getAttribute('data-lg'); if(lg===league) return;
    league=lg;
    try{ localStorage.setItem('league', lg); }catch(err){}   // the nav's CBB links follow it
    show();
  });

  /* The page's "Updated" line is the build's; the games are the feed's, so
     it says when the feed was pushed - or goes, with everything else that
     only frames games, when there are none. style.display rather than
     `hidden`: the switch's and the Share row's CSS display would beat it. */
  function shown(el, on){ if(el) el.style.display=on?'':'none'; }
  function stamp(on){
    var up=document.querySelector('.page-updated'), t=feed&&pushedAt(feed.generated);
    if(!up) return;
    shown(up, on&&t);
    if(!(on&&t)) return;
    // updated.js repaints from the attribute every minute; the text is its
    // format, so nothing changes under the reader when it does.
    var min=Math.max(0,Math.round((Date.now()-t)/60000)), hr=Math.round(min/60);
    up.setAttribute('data-updated', new Date(t).toISOString());
    up.textContent='Updated '+(min<1?'just now':min<60?min+' min ago':hr<36?hr+' hr ago':Math.round(hr/24)+' days ago')
      +' \\u00b7 '+new Date(t).toLocaleString(undefined,{weekday:'short',month:'short',day:'numeric',
        hour:'numeric',minute:'2-digit'});
  }
  function chrome(any){
    var wrap=host.parentNode;
    shown(sw, any); shown(wrap.querySelector('.wg-how'), any); shown(wrap.querySelector('.gs-share-row'), any);
    stamp(any);
  }

  /* The engine polls only while a game is on; a page opened at noon has
     none, so it is woken at the next tip. */
  function arm(D){
    clearTimeout(wake);
    var now=Date.now(), today=etDate(now), next=Infinity;
    D.games.forEach(function(g){
      var t=Date.parse(g.ko);
      if(g.day===today&&g.state==='pre'&&t>now&&t<next) next=t;
    });
    if(next<Infinity) wake=setTimeout(function(){
      if(!document.hidden) document.dispatchEvent(new Event('visibilitychange'));
      arm(D);
    }, Math.min(next-now+30e3, 864e5));
  }

  // Only the men's rankings carry stars so far: on the women's games the
  // hint would send the reader somewhere that changes nothing here.
  var HINT='Star teams on the <a href="/cbb/power/">rankings</a> to put their games first.';
  var cfg={
    link:'/men/', close:C.close, blowout:C.blowout, every:C.every, gameHours:C.gameHours,
    staleHtml:'The scoreboard has not been updated for a few days.',
    stars:function(){
      var set={}, list=[];
      try{ list=JSON.parse(localStorage.getItem('gs:favorites')||'[]')||[]; }catch(e){}
      list.forEach(function(k){ if(typeof k==='string'&&/^cbb-(wo)?men:/.test(k)) set[k]=1; });
      return set;
    },
    /* The feed again - unless it was just read (the engine polls as soon as
       it starts) - and every game of the league's state in it. */
    live:function(){
      var fresh=Date.now()-fetchedAt<60e3?Promise.resolve(feed):get(C.feed).then(function(d){
        if(d&&d.leagues){ feed=d; fetchedAt=Date.now(); stamp(true); }
        return feed;
      });
      return fresh.then(function(){
        var src=(feed&&feed.leagues&&feed.leagues[league])||{}, out={};
        Object.keys(src).forEach(function(id){
          var L=liveOf(src[id]||{}, league==='women');
          if(L.state) out[String(id)]=L;
        });
        return out;
      });
    }
  };

  function show(){
    var me=++turn, lg=league;
    Array.prototype.forEach.call(sw.querySelectorAll('button'), function(b){
      b.setAttribute('aria-pressed', String(b.getAttribute('data-lg')===lg)); });
    var list=current(lg), any=list.length>0||current(lg==='men'?'women':'men').length>0;
    chrome(any);
    var D={slots:C.slots, games:list};
    if(list.length&&feed) D.generated=new Date(pushedAt(feed.generated)).toISOString();
    var line=!feed?Promise.resolve('The scoreboard did not load. <a href="/'+lg+'/">Try it here</a>.')
      :list.length?Promise.resolve(''):nextLine(lg);
    line.then(function(text){
      if(me!==turn) return;
      cfg.emptyHtml='<span class="wg-empty">'+text+'</span>';
      cfg.hint=lg==='men'?HINT:'';
      if(W) W.set(D); else W=GSWatch(D, cfg);
      arm(D);
    });
  }

  Promise.all([get(C.feed), get('/cbb/star-teams.json')]).then(function(r){
    if(r[0]&&r[0].leagues){ feed=r[0]; fetchedAt=Date.now(); }
    // {star key: [scoreboard name, logo]}: the other way round, for the feed.
    Object.keys(r[1]||{}).forEach(function(k){
      var v=r[1][k]; if(!v||!v[0]) return;
      teams[v[0]]={slug:k.slice(k.indexOf(':')+1), lg:v[1]?encodeURI(v[1]):''};
    });
    show();
  });
})();
</script>"""


HOW = (f"Each window's games, best first, by a watch score out of 100: how good both teams are "
       f"by GordStats rank (#1 counts 100, #{HALF_LIFE + 1} half that, #{2 * HALF_LIFE + 1} a "
       f"quarter; the weaker team weighs most), all of it for a coin flip by our model and half "
       f"for a sure thing. A Top 25 matchup and a tournament game each close a quarter of the "
       f"gap to 100 (the NCAA tournament twice). Toss-up: {TOSS_UP[0]:.0%}-{TOSS_UP[1]:.0%}. "
       f"Upset watch: the underdog at {UPSET_WATCH:.0%}+. Your starred teams go first; while games "
       f"are on, one within {CLOSE} in the last five minutes, an overtime or an underdog ahead in "
       f"the second half jumps the queue.")


def body(cfg: dict = None) -> str:
    """The page: no games in it (the browser reads them), only the adapter
    with `cfg` (config(), or a test's) where it says __CONFIG__."""
    adapter = ADAPTER_JS.replace("__CONFIG__", json.dumps(cfg or config(), separators=(",", ":")))
    return watch_page.body(None, adapter, HOW, "/cbb/watch/",
                           "What to watch in college basketball today")


def generate() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(add_front_matter(
        body(), "Watch Guide", "What to have on, window by window",
        description="Every college basketball game of the day, men's and women's, grouped by "
                    "tip-off and ranked by how much it is worth watching - with live scores."),
        encoding="utf-8")
    print(f"Wrote CBB watch guide -> {OUT}")


if __name__ == "__main__":
    generate()
