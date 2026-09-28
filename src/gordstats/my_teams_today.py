"""
"My teams this week" on the home page: the reader's starred college teams,
each with its game - kickoff and TV, the live score, and our pick beside the
book's line - in one place.

The stars already exist (gordstats.favorites, on the CFB rankings and team
pages) and so does everything about the games; what did not was one place to
see them together, which is the question a reader at a tailgate actually has.
Built in the browser: the stars are the reader's own (localStorage, synced to
an account by docs/assets/js/favorites.js), the games come from
/cfb/week-games.json (cfb.site.homecards.week_games, rebuilt with the rest of
the section), and a game on right now polls /api/cfb-scores - the scoreboard
proxy the schedule page already uses - once a minute.

A starred team with no game this week is named on its bye; with nothing
starred the card says where the stars are rather than sitting empty.
"""

CSS = """<style>
.mt-list{display:grid;gap:8px}
.mt-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:4px 12px;align-items:center;
  padding:9px 11px;border:1px solid #e2e8f0;border-radius:10px;background:#fff;
  text-decoration:none;color:inherit}
.mt-row.live{border-color:#fca5a5;background:#fff5f4}
.mt-teams{display:flex;align-items:center;gap:7px;min-width:0;font-size:14.5px;font-weight:700}
.mt-teams img{width:24px;height:24px;flex:none;border:0;padding:0;box-shadow:none;background:none}
.mt-teams .opp{font-weight:600;color:#475569;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mt-teams .rk{font-size:11px;color:#64748b;font-weight:700;margin-right:2px}
.mt-teams .at{font-size:12px;color:#64748b;font-weight:600}
.mt-when{font-size:13px;font-weight:700;text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
.mt-when.live{color:#b3382c}
.mt-when.win{color:#15803d}.mt-when.loss{color:#b91c1c}
.mt-pick{grid-column:1 / -1;font-size:12.5px;color:#475569;line-height:1.45}
.mt-pick b{color:#0f172a}
.mt-none,.mt-bye{font-size:13px;color:#64748b;margin:4px 0 0}
.mt-teams .me{white-space:nowrap}
/* A phone gives the matchup its own line, the kickoff the next. */
@media (max-width:600px){
  .mt-row{grid-template-columns:minmax(0,1fr)}
  .mt-when{text-align:left}
}
@media (prefers-color-scheme: dark){
  .mt-row{background:#16203a;border-color:#2b3852}
  .mt-row.live{background:#3a1f22;border-color:#7f1d1d}
  .mt-teams .opp,.mt-pick{color:#aab7c9}
  .mt-teams .rk,.mt-teams .at,.mt-none,.mt-bye{color:#94a3b8}
  .mt-pick b{color:#e6edf6}
  .mt-when.live{color:#ffb4ab}.mt-when.win{color:#6ee7b7}.mt-when.loss{color:#ff9b91}
  /* The Top 25 card's disc: Ohio State and a dozen others ship a near-black
     mark that is a hole on the dark theme. */
  .mt-teams img{background:#e8edf5;border-radius:50%;padding:2px;box-sizing:border-box;
    box-shadow:0 0 0 1px rgba(255,255,255,.08)}
}
</style>"""

JS = """{% raw %}<script>
(function(){
  var host=document.getElementById('mt-host');
  if(!host) return;
  var LOGO='https://a.espncdn.com/combiner/i?img=/i/teamlogos/ncaa/500/{id}.png&w=80&h=80';
  var GAME_HOURS=4.5, data=null, live={}, timer=null;

  function esc(v){
    return String(v==null?'':v).replace(/[&<>"]/g,function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});
  }
  function starred(){
    var list=[];
    try{ list=JSON.parse(localStorage.getItem('gs:favorites')||'[]')||[]; }catch(e){}
    return list.filter(function(k){ return /^cfb:/.test(k); }).map(function(k){ return k.slice(4); });
  }
  function logo(id){
    return '<img src="'+LOGO.replace('{id}',encodeURIComponent(id))+'" alt="" width="24" height="24" loading="lazy">';
  }
  function kickoff(g){
    var d=new Date(g.kickoff);
    var day=d.toLocaleDateString(undefined,{weekday:'short'});
    if(!g.time_known) return day+' &middot; TBA';
    return day+' '+d.toLocaleTimeString(undefined,{hour:'numeric',minute:'2-digit'});
  }
  function onNow(g){
    var t=Date.parse(g.kickoff), now=Date.now();
    var st=(live[g.id]||{}).state||g.state;
    return st==='in' || (st!=='post' && now>=t && now<t+GAME_HOURS*3600e3);
  }

  /** One game, from the starred side. */
  function row(g, set){
    var side=(set[g.away.id]&&!set[g.home.id])?'away':'home';
    var me=g[side], them=g[side==='home'?'away':'home'];
    var L=live[g.id]||{}, st=L.state||g.state;
    var mine=L[side]!=null?L[side]:me.score, theirs=L[side==='home'?'away':'home']!=null
      ?L[side==='home'?'away':'home']:them.score;
    var when, cls='';
    if(st==='in'){ when='Live '+mine+'&ndash;'+theirs+(L.detail?' &middot; '+esc(L.detail):''); cls='live'; }
    else if(st==='post'){
      var won=mine>theirs;
      when=(won?'W ':mine<theirs?'L ':'T ')+mine+'&ndash;'+theirs; cls=won?'win':'loss';
    } else { when=kickoff(g)+(g.tv?' &middot; '+esc(g.tv):''); }
    var at=g.neutral?'vs':(side==='home'?'vs':'at');
    function rk(t){ return t.rank?'<span class="rk">'+t.rank+'</span>':''; }
    var pick='';
    if(g.home_win!=null && g.home.pred!=null){
      var homeFav=g.home_win>=0.5, fav=homeFav?g.home:g.away;
      var by=Math.abs(g.home.pred-g.away.pred), p=homeFav?g.home_win:1-g.home_win;
      pick='GordStats: <b>'+esc(fav.name)+'</b> by '+by.toFixed(1)+' &middot; '+Math.round(p*100)+'%';
    }
    if(g.book_spread!=null){
      var bf=g.book_spread<0?g.home:g.away;
      pick+=(pick?' &middot; ':'')+'Line: '+esc(bf.name)+' '+(g.book_spread===0?'pk':'&minus;'+Math.abs(g.book_spread));
    }
    if(g.note) pick=esc(g.note)+(pick?' &middot; '+pick:'');
    return '<a class="mt-row'+(st==='in'?' live':'')+'" href="/cfb/schedule/">'
      +'<div class="mt-teams">'+logo(me.id)+rk(me)+'<span class="me">'+esc(me.name)+'</span> <span class="at">'+at+'</span> '
      +'<span class="opp">'+rk(them)+esc(them.name)+'</span></div>'
      +'<div class="mt-when '+cls+'">'+when+'</div>'
      +(pick?'<div class="mt-pick">'+pick+'</div>':'')+'</a>';
  }

  function draw(){
    if(!data) return;
    var ids=starred();
    if(!ids.length){
      host.innerHTML='<p class="mt-none">Star teams (&#9734;) on the '
        +'<a href="/cfb/power/">college football rankings</a> and their games show up here, '
        +'with our pick and the live score.</p>';
      return;
    }
    var set={}; ids.forEach(function(i){ set[i]=1; });
    var games=data.games.filter(function(g){ return set[g.home.id]||set[g.away.id]; });
    var busy={}; games.forEach(function(g){ busy[g.home.id]=1; busy[g.away.id]=1; });
    var byes=ids.filter(function(i){ return !busy[i] && data.teams[i]; })
      .map(function(i){ return esc(data.teams[i]); });
    host.innerHTML=(games.length?'<div class="mt-list">'
        +games.map(function(g){ return row(g,set); }).join('')+'</div>'
        :'<p class="mt-none">None of your teams plays in the next week.</p>')
      +(byes.length&&games.length?'<p class="mt-bye">Off this week: '+byes.join(', ')+'.</p>':'');
  }

  /** Scores for every game of the reader's on right now, from the proxy. */
  function poll(){
    clearTimeout(timer);
    if(!data) return;
    var set={}; starred().forEach(function(i){ set[i]=1; });
    var now=data.games.filter(function(g){ return (set[g.home.id]||set[g.away.id]) && onNow(g); });
    if(!now.length) return;
    if(document.hidden){ timer=setTimeout(poll,60000); return; }
    var asks={};
    now.forEach(function(g){ asks[g.week+'|'+g.seasontype]=g; });
    Promise.all(Object.keys(asks).map(function(k){
      var g=asks[k];
      return fetch('/api/cfb-scores?week='+g.week+'&dates='+data.season+'&seasontype='+g.seasontype)
        .then(function(r){ return r.ok?r.json():null; }).catch(function(){ return null; });
    })).then(function(boards){
      boards.forEach(function(b){
        ((b&&b.events)||[]).forEach(function(e){
          var c=(e.competitions||[])[0]; if(!c) return;
          var st=(c.status||{}).type||{}, o={state:st.state||'pre', detail:st.shortDetail||''};
          (c.competitors||[]).forEach(function(x){ o[x.homeAway]=parseInt(x.score||'0',10); });
          live[String(e.id)]=o;
        });
      });
      draw();
      timer=setTimeout(poll,60000);
    });
  }

  fetch('/cfb/week-games.json').then(function(r){ return r.ok?r.json():null; })
    .then(function(d){
      if(!d||!d.games){ host.closest('section').hidden=true; return; }
      data=d; draw(); poll();
    }).catch(function(){ host.closest('section').hidden=true; });
  // Stars change on this page's other cards, or arrive from the account.
  document.addEventListener('gs:favorites', function(){ draw(); poll(); });
  document.addEventListener('visibilitychange', function(){ if(!document.hidden) poll(); });
})();
</script>{% endraw %}"""


def section() -> str:
    return (CSS + '<section class="home-card" id="my-teams">'
            '<div class="home-card-head"><h2>My teams this week</h2>'
            '<a class="home-card-link" href="/cfb/schedule/">Full schedule &rarr;</a></div>'
            '<div id="mt-host"></div></section>' + JS)
