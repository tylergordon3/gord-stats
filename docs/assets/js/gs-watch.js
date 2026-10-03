/* window.GSWatch: the watch guide's engine, every sport.
   Source file, loaded by gordstats.watch_page (ENGINE_JS_TAG); see gordstats.js_assets. */
window.GSWatch=function(D, cfg){
  var host=document.getElementById('wg-host');
  if(!host) return null;
  cfg=cfg||{};
  var GAME_HOURS=cfg.gameHours||4.5, MORE=5, STALE_DAYS=3, CLOSE=cfg.close||8;
  var BLOWOUT=(typeof cfg.blowout==='number'&&cfg.blowout)||21, SWAP=15, FRESH_MS=5*60e3;
  var live={}, timer=null, day=null, view='list', onBox=[], fresh={};
  // A day on the guide runs to NIGHT_ENDS the next morning (game_day, in
  // Python): Saturday's 10:30 PM kickoff is Saturday's game at 12:30 AM, and
  // the day it is on stays on the guide until then.
  // An adapter may say (CBB's calendar does); otherwise watch_page.NIGHT_ENDS,
  // which the page sets (GSCFG).
  var NIGHT=(typeof cfg.nightEnds==='number')?cfg.nightEnds:(window.GSCFG||{}).nightEnds;
  var stale=false, drawnDay=null;
  try{ if(localStorage.getItem('gsWatchView')==='quad') view='quad'; }catch(e){}
  function esc(v){
    return String(v==null?'':v).replace(/[&<>"']/g,function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});
  }
  function etDate(t){ return new Date(t).toLocaleDateString('en-CA',{timeZone:'America/New_York'}); }
  function today(){ return etDate(Date.now()-NIGHT*3600e3); }
  /** A failed fetch says nothing; anything else is a bug, and an empty catch
   *  is how a feature disappears without a trace. */
  function report(e){
    var net=e&&e.name==='TypeError'&&/fetch|network|load failed/i.test(String(e.message||''));
    if(!net&&window.console) console.error('[watch]', e);
  }
  function rosters(){ return D.rosters||{}; }
  function stars(){ try{ return cfg.stars?cfg.stars()||{}:{}; }catch(e){ return {}; } }
  function myTeam(){
    if(cfg.team){ var t=cfg.team(); return t&&rosters()[t]?t:''; }
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
    var s=g.score, why=(g.tags||[]).slice(), hot=[], ps=players(g,team), blow=false;
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
      // A second half that is decided is the first thing to turn off.
      var bl=typeof cfg.blowout==='function'?cfg.blowout(g):BLOWOUT;
      if(second&&!ot&&diff>=bl){ s-=30; why.unshift('Blowout'); blow=true; }
    }
    return {s:s, why:why, hot:hot, ps:ps, theirs:theirs, opp:opp, star:star, blow:blow};
  }
  function kick(g){
    var d=new Date(g.ko);
    return g.tk?d.toLocaleTimeString('en-US',{hour:'numeric',minute:'2-digit'}):'TBA';
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
    var them=w.theirs.length?'<div class="wg-them">'+esc(rosters()[String(w.opp)].n)+'\u2019s: '+names(w.theirs)+'</div>':'';
    var sub=line(g);
    return '<a class="wg-g'+(top?' top':'')+(st==='in'?' live':'')+(st==='post'?' done':'')
      +'" href="'+esc(g.href||cfg.link||'#')+'" data-gid="'+esc(g.id)+'">'
      +side(g,'a',st)+side(g,'h',st)+when
      +(sub?'<div class="wg-sub">'+sub+'</div>':'')+me+them
      +'<div class="wg-tags">'+tags+'</div></a>';
  }
  // `k` names the "N more" fold, so a redraw can open again what was open.
  function list(items, first, k){
    var head=items.slice(0,MORE), rest=items.slice(MORE);
    return '<div class="wg-list">'+head.map(function(x,i){ return card(x, first&&i===0); }).join('')+'</div>'
      +(rest.length?'<details class="wg-more" data-k="'+esc(k||'')+'"><summary>'+rest.length+' more</summary><div class="wg-list">'
        +rest.map(function(x){ return card(x,false); }).join('')+'</div></details>':'');
  }
  // ----- the quadbox ------------------------------------------------------ //

  // Streaming services show any number of games at once; a broadcast channel
  // shows one (ABC's regional 3:30 games are the usual trap).
  var STREAM=/\+|peacock|prime|netflix|youtube|paramount|apple|stream|\bmax\b|flo|espn3|app\b/i;
  function channels(g){
    var shared=typeof cfg.quadShared==='function'?cfg.quadShared(g):cfg.quadShared;
    if(shared||!g.tv) return [];
    var parts=String(g.tv).split(/\s*[\/,&]\s*/).filter(Boolean);
    if(parts.some(function(p){ return STREAM.test(p); })) return [];
    return parts.map(function(p){ return p.toUpperCase(); });
  }
  /** Up to four games, best first, never two on one channel; `keep` go in
   *  first. The rest, in order, are the bench. */
  function pickFour(items, keep){
    var used={}, box=[], bench=[];
    function free(x){ return channels(x.g).every(function(c){ return !used[c]; }); }
    function take(x){ channels(x.g).forEach(function(c){ used[c]=1; }); box.push(x); }
    (keep||[]).forEach(function(x){ if(box.length<4&&free(x)) take(x); });
    items.forEach(function(x){
      if(box.indexOf(x)>=0) return;
      if(box.length<4&&free(x)) take(x); else bench.push(x);
    });
    return {box:box, bench:bench};
  }
  /** The games on now, in four boxes that stay put: a game keeps its box
   *  until it ends, turns into a blowout, or something better by SWAP points
   *  is on - nobody wants the screens reshuffled every minute. */
  function nowFour(on){
    var byId={};
    on.forEach(function(x){ byId[x.g.id]=x; });
    var kept=onBox.map(function(id){ return byId[id]; })
      .filter(function(x){ return x&&!x.w.blow; });
    var pick=pickFour(on, kept);
    for(var n=0;n<4&&pick.bench.length;n++){
      var best=pick.bench[0], weakest=pick.box.slice().sort(function(a,b){ return a.w.s-b.w.s; })[0];
      if(!weakest||best.w.s-weakest.w.s<SWAP) break;
      kept=pick.box.filter(function(x){ return x!==weakest; });
      var next=pickFour([best].concat(on), kept);
      if(next.box.indexOf(best)<0) break;
      pick=next;
    }
    var pos=[null,null,null,null], had={};
    onBox.forEach(function(id, i){
      if(pick.box.some(function(x){ return x.g.id===id; })){ pos[i]=byId[id]; had[id]=1; }
    });
    pick.box.slice().sort(function(a,b){ return b.w.s-a.w.s; }).forEach(function(x){
      if(had[x.g.id]) return;
      if(onBox.length) fresh[x.g.id]=Date.now();
      pos[pos.indexOf(null)]=x;
    });
    onBox=pos.map(function(x){ return x?x.g.id:null; });
    return {box:pos.filter(Boolean), bench:pick.bench};
  }
  function qside(g, k, st){
    var t=g[k], L=live[g.id]||{};
    var sc=L[k==='h'?'home':'away'];
    if(sc==null&&st!=='pre') sc=t.sc;
    return '<div class="tm">'
      +(t.lg?'<img src="'+esc(t.lg)+'" alt="" width="18" height="18" loading="lazy">':'')
      +(t.rk?'<span class="rk">'+esc(t.rk)+'</span>':'')
      +'<span class="nm">'+(k==='h'&&!g.n?'<span class="rk">at</span> ':'')+esc(t.nm)+'</span>'
      +(st!=='pre'&&sc!=null?'<span class="sc">'+esc(sc)+'</span>':'')+'</div>';
  }
  function tile(x, audio){
    var g=x.g, st=state(g), L=live[g.id]||{};
    var when=st==='in'?esc(L.detail||'Live'):st==='post'?'Final':kick(g);
    var isNew=fresh[g.id]&&Date.now()-fresh[g.id]<FRESH_MS;
    var why=x.w.hot.length?' &middot; <span class="hot">'+esc(x.w.hot[0])+'</span>'
      :(x.w.blow?' &middot; Blowout':'');
    return '<a class="wg-q'+(audio?' audio':'')+(st==='in'?' live':'')+'" href="'
      +esc(g.href||cfg.link||'#')+'" data-gid="'+esc(g.id)+'">'
      +'<div class="ch">'+(g.badge?'<span class="sp">'+esc(g.badge)+'</span>':'')
      +'<b>'+esc(g.tv||'TV TBA')+'</b>'
      +(isNew?'<span class="new">New</span>':'')
      +(audio?'<span class="aud">&#x1F50A;<span class="aud-w"> Sound</span></span>':'')+'</div>'
      +qside(g,'a',st)+qside(g,'h',st)
      +'<div class="st">'+when+' &middot; Watch '+Math.min(100,Math.round(g.score))+why+'</div></a>';
  }
  function benchLine(xs, lead){
    if(!xs.length) return '';
    return '<p class="wg-bench">'+lead+' '+xs.slice(0,2).map(function(x){
      return '<b>'+esc(x.g.a.nm)+(x.g.n?' v ':' at ')+esc(x.g.h.nm)+'</b> ('+esc(x.g.tv||'TBA')+')';
    }).join(', ')+'.</p>';
  }
  function quad(items, now, k){
    if(items.length<2) return list(items,true,k);
    var pick=now?nowFour(items):pickFour(items);
    // Every game but one on a single channel: a list says more than a grid.
    if(pick.box.length<2) return list(items,true,k);
    var top=pick.box.reduce(function(a,x){ return !a||x.w.s>a.w.s?x:a; }, null);
    return '<div class="wg-quad">'+pick.box.map(function(x){ return tile(x, x===top); }).join('')
      +'</div>'+benchLine(pick.bench.filter(function(x){ return !x.w.blow&&state(x.g)!=='post'; }),
                          now?'If one gets out of hand:':'Next in line:');
  }

  function days(){
    // From the guide's today (NIGHT hours into the calendar's), and any
    // earlier day with a game still being played: a late game is not dropped
    // at midnight while it is on.
    var t=today(), seen={}, out=[];
    D.games.forEach(function(g){
      if((g.day>=t||state(g)==='in')&&!seen[g.day]){ seen[g.day]=1; out.push(g.day); } });
    return out.sort();
  }
  function dayLabel(d){
    var t=new Date(d+'T12:00:00Z');
    return (d===today()?'Today':t.toLocaleDateString('en-US',{weekday:'short',timeZone:'UTC'}))
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
    var ds=days(), t=today(), count={};
    D.games.forEach(function(g){ count[g.day]=(count[g.day]||0)+1; });
    day=ds.indexOf(t)>=0?t:ds.slice().sort(function(a,b){ return count[b]-count[a]||(a<b?-1:1); })[0];
  }
  function staleNote(){
    return '<p class="wg-note">'+(cfg.staleHtml||'This guide has not been rebuilt for a few days.')+'</p>';
  }
  function draw(){
    // A guide not rebuilt for days says so, and keeps saying so: a later
    // redraw (a star, the CBB feed, a return to the tab) used to paint the
    // stale games over the notice.
    if(stale){ host.innerHTML=staleNote(); return; }
    // Drawn again whole every live poll: what the reader had opened ("N
    // more", "Final") stays open, and the page stays where it was.
    var opened={}, y=window.pageYOffset;
    Array.prototype.forEach.call(host.querySelectorAll('details[data-k]'), function(d){
      if(d.open) opened[d.getAttribute('data-k')]=1; });
    var ds=days();
    if(!ds.length){ drawnDay=null; host.innerHTML=(cfg.top||'')+'<p class="wg-note wg-empty">'+(cfg.emptyHtml||'No games in the next week.')+'</p>'; return; }
    if(ds.indexOf(day)<0) day=ds[0];
    var set=stars(), team=myTeam();
    var items=D.games.filter(function(g){ return g.day===day; })
      .map(function(g){ return {g:g, w:watch(g,set,team)}; });
    var by=function(a,b){ return b.w.s-a.w.s; };
    var on=items.filter(function(x){ return state(x.g)==='in'; }).sort(by);
    var done=items.filter(function(x){ return state(x.g)==='post'; }).sort(by);
    var hint=(Object.keys(set).length||team||!cfg.hint)?'':'<span>'+cfg.hint+'</span>';
    var quadView=view==='quad';
    var switcher='<div class="wg-view" role="group" aria-label="View">'
      +'<button type="button" data-view="list" aria-pressed="'+!quadView+'">List</button>'
      +'<button type="button" data-view="quad" aria-pressed="'+quadView+'">Quadbox</button></div>';
    var html=(cfg.top||'')+'<div class="wg-days" role="group" aria-label="Day">'+ds.map(function(d){
      return '<button type="button" data-day="'+esc(d)+'" aria-pressed="'+(d===day)+'">'+dayLabel(d)+'</button>'; }).join('')+'</div>'
      +'<div class="wg-bar">'+switcher+picker(team)+hint+'</div>'
      +(quadView?'<p class="wg-note">Four games for one screen, each window: the best top left with '
        +'the sound'+(cfg.quadShared?'.':', never two on one broadcast channel.')
        +(cfg.quadNote?' '+cfg.quadNote:'')+'</p>':'');
    if(on.length) html+='<h3>On now <span class="wg-n">'+on.length+'</span></h3>'
      +(quadView?quad(on,true,'on'):list(on,true,'on'));
    D.slots.forEach(function(s){
      var xs=items.filter(function(x){ return x.g.slot===s[0]&&state(x.g)==='pre'; }).sort(by);
      if(xs.length) html+='<h3>'+esc(s[1])+' <span class="wg-n">'+esc(s[2])+'</span></h3>'
        +(quadView?quad(xs,false,s[0]):list(xs,true,s[0]));
    });
    if(done.length) html+='<details class="wg-more" data-k="final"><summary>Final &middot; '+done.length+'</summary><div class="wg-list">'
      +done.map(function(x){ return card(x,false); }).join('')+'</div></details>';
    host.innerHTML=html;
    if(day===drawnDay){
      Array.prototype.forEach.call(host.querySelectorAll('details[data-k]'), function(d){
        if(opened[d.getAttribute('data-k')]) d.open=true; });
      if(Math.abs(window.pageYOffset-y)>1) window.scrollTo(window.pageXOffset, y);
    }
    drawnDay=day;
  }
  function onNow(g){
    var st=state(g), t=Date.parse(g.ko), now=Date.now();
    return st==='in'||(st!=='post'&&now>=t&&now<t+GAME_HOURS*3600e3);
  }
  function poll(){
    clearTimeout(timer);
    if(stale) return;
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
    Promise.resolve().then(function(){ return cfg.live(now, D); }).then(function(map){
      Object.keys(map||{}).forEach(function(k){ live[k]=map[k]; });
    }).catch(report).then(function(){
      draw();
    }).catch(report).then(function(){
      // Whatever went wrong this time, the next poll still comes.
      timer=setTimeout(poll,cfg.every||60000);
    });
  }
  host.addEventListener('click', function(e){
    var v=e.target.closest('button[data-view]');
    if(v){
      view=v.getAttribute('data-view');
      try{ localStorage.setItem('gsWatchView', view); }catch(err){}
      draw(); return;
    }
    var b=e.target.closest('button[data-day]'); if(!b) return;
    day=b.getAttribute('data-day'); onBox=[]; fresh={}; draw(); poll();
  });
  host.addEventListener('change', function(e){
    if(e.target.id!=='wg-team') return;
    try{ localStorage.setItem(cfg.myKey, e.target.value); }catch(err){}
    draw();
  });
  document.addEventListener('gs:favorites', function(){ draw(); });
  document.addEventListener('visibilitychange', function(){ if(!document.hidden) poll(); });
  function isStale(){
    return !!(D.generated&&Date.now()-Date.parse(D.generated)>STALE_DAYS*864e5);
  }
  function start(){
    stale=isStale();
    if(stale){ clearTimeout(timer); host.innerHTML=staleNote(); return; }
    live={}; onBox=[]; fresh={}; drawnDay=null; pickDay(); draw(); poll();
  }
  start();
  // set: another set of games altogether (CBB's men's/women's switch) - the
  // day and the live scores start over. update: the same games refreshed -
  // the reader's day and what is live stay.
  return {set:function(next){ D=next; start(); },
          update:function(next){
            D=next;
            if(stale!==isStale()){ start(); return; }
            draw(); poll();
          }, redraw:draw};
};
