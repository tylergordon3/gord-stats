"""
"My teams" on the home page: the reader's starred college teams, each with its
game - kickoff and TV, the live score, and our pick or rank beside the book's
line - in one place. Football's games are the coming week's; basketball's are
the day's.

The stars already exist (gordstats.favorites, on the CFB and CBB rankings and
team pages) and so does everything about the games; what did not was one place
to see them together, which is the question a reader at a tailgate actually
has. Built in the browser: the stars are the reader's own (localStorage, synced
to an account by docs/assets/js/favorites.js).

  Football  /cfb/week-games.json (cfb.site.homecards.week_games, rebuilt with
            the rest of the section); a game on right now polls
            /api/cfb-scores - the scoreboard proxy the schedule page already
            uses - once a minute.
  Basketball  the live scoreboard Worker /men/ reads (cbb.live pushes it every
            ten minutes in playing hours; each game carries GordStats' call,
            cbb.game_model), and /cbb/star-teams.json
            (cbb.render.render_power.star_teams) to find a starred team in it:
            the stars are keyed on T-Rank's names, the scoreboard uses the
            site's. Only fetched for a reader with a basketball star.

A starred football team with no game this week is named on its bye; with
nothing starred the card says where the stars are rather than sitting empty.
"""

CSS = """<style>
.mt-list{display:grid;gap:8px}
.mt-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:4px 12px;align-items:center;
  padding:9px 11px;border:1px solid #e2e8f0;border-radius:10px;background:#fff;
  text-decoration:none;color:inherit}
.mt-row.live{border-color:#fca5a5;background:#fff5f4}
.mt-teams{display:flex;align-items:center;gap:7px;min-width:0;font-size:14.5px;font-weight:700}
.mt-teams img{width:24px;height:24px;flex:none;border:0;padding:0;box-shadow:none;background:none;
  object-fit:contain}
.mt-teams .opp{font-weight:600;color:#475569;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mt-teams .rk{font-size:11px;color:#64748b;font-weight:700;margin-right:2px}
.mt-teams .at{font-size:12px;color:#64748b;font-weight:600}
.mt-when{font-size:13px;font-weight:700;text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
.mt-when.live{color:#b3382c}
.mt-when.win{color:#15803d}.mt-when.loss{color:#b91c1c}
.mt-pick{grid-column:1 / -1;font-size:12.5px;color:#475569;line-height:1.45}
.mt-pick b{color:#0f172a}
/* Which sport, when both are on the card: Duke's football and basketball
   games otherwise read as the same team twice. */
.mt-sp{display:inline-block;font-size:10.5px;font-weight:700;letter-spacing:.04em;color:#475569;
  border:1px solid #cbd5e1;border-radius:4px;padding:0 4px;margin-right:6px;vertical-align:1px}
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
  .mt-sp{color:#aab7c9;border-color:#3b4a66}
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
  var CFB_ON=host.getAttribute('data-cfb')==='1', CBB_ON=host.getAttribute('data-cbb')==='1';
  var LOGO='https://a.espncdn.com/combiner/i?img=/i/teamlogos/ncaa/500/{id}.png&w=80&h=80';
  var HOOPS='https://cbb-live-scores.tmgordon33.workers.dev/scores?league=men';
  // A football file the daily run stopped rebuilding is last season's, not
  // this week's; a scoreboard not pushed for a day and a half is the Pi gone
  // quiet, and its scores are not to be trusted.
  var GAME_HOURS=4.5, HOOP_HOURS=2.5, STALE_DAYS=3, HOOP_STALE_HOURS=36;
  var cfb=null, live={}, timer=null;
  var hoops=null, hoopTeams=null, hoopTimer=null, hoopLoading=false;

  function esc(v){
    return String(v==null?'':v).replace(/[&<>"']/g,function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});
  }
  function starred(prefix){
    var list=[];
    try{ list=JSON.parse(localStorage.getItem('gs:favorites')||'[]')||[]; }catch(e){}
    // A value some other build wrote ('{}', or one key as a bare string) is
    // no list: the card would otherwise throw on it and never draw.
    if(!Array.isArray(list)) list=[];
    return list.filter(function(k){ return typeof k==='string' && k.indexOf(prefix)===0; });
  }
  function cfbStars(){ return CFB_ON?starred('cfb:').map(function(k){ return k.slice(4); }):[]; }
  function cbbStars(){ return CBB_ON?starred('cbb-men:'):[]; }
  function img(src){
    return '<img src="'+esc(src)+'" alt="" width="24" height="24" loading="lazy">';
  }
  function day(t, known){
    if(t==null||t==='') return 'TBA';           // not 1970's Wednesday evening
    var d=new Date(t);
    // A game with no time yet is filed at midnight Eastern of its day: in the
    // reader's own zone, west of Eastern, that midnight is still Friday.
    if(!known) return d.toLocaleDateString('en-US',{weekday:'short',timeZone:'America/New_York'})+' &middot; TBA';
    return d.toLocaleDateString('en-US',{weekday:'short'})+' '
      +d.toLocaleTimeString('en-US',{hour:'numeric',minute:'2-digit'});
  }
  function rk(r){ return r?'<span class="rk">'+esc(r)+'</span>':''; }
  function score(v){ return v==null||v===''?null:(Number(v)||0); }
  function result(mine, theirs, extra){
    var won=mine>theirs;
    return {when:(won?'W ':mine<theirs?'L ':'T ')+mine+'&ndash;'+theirs+(extra||''),
            cls:won?'win':'loss'};
  }
  function shell(o){
    return '<a class="mt-row'+(o.live?' live':'')+'" href="'+o.href+'">'
      +'<div class="mt-teams">'+o.logo+rk(o.rank)+'<span class="me">'+esc(o.me)+'</span> '
      +'<span class="at">'+o.at+'</span> <span class="opp">'+rk(o.theirRank)+esc(o.them)+'</span></div>'
      +'<div class="mt-when '+(o.cls||'')+'">'+o.when+'</div>'
      +(o.pick?'<div class="mt-pick">'+o.pick+'</div>':'')+'</a>';
  }

  /* ---- football ---- */
  function cfbOnNow(g){
    var t=Date.parse(g.kickoff), now=Date.now();
    var st=(live[g.id]||{}).state||g.state;
    return st==='in' || (st!=='post' && now>=t && now<t+GAME_HOURS*3600e3);
  }
  function cfbRow(g, set){
    var side=(set[g.away.id]&&!set[g.home.id])?'away':'home', other=side==='home'?'away':'home';
    var me=g[side], them=g[other];
    var L=live[g.id]||{}, st=L.state||g.state;
    var mine=L[side]!=null?L[side]:me.score, theirs=L[other]!=null?L[other]:them.score;
    var o={href:'/cfb/schedule/', logo:img(LOGO.replace('{id}',encodeURIComponent(me.id))),
           me:me.name, them:them.name, rank:me.rank, theirRank:them.rank,
           at:g.neutral?'vs':(side==='home'?'vs':'at'), live:st==='in', t:Date.parse(g.kickoff)};
    if(st==='in'){ o.when='Live '+mine+'&ndash;'+theirs+(L.detail?' &middot; '+esc(L.detail):''); o.cls='live'; }
    else if(st==='post'){ var r=result(mine,theirs); o.when=r.when; o.cls=r.cls; }
    else { o.when=day(g.kickoff,g.time_known)+(g.tv?' &middot; '+esc(g.tv):''); }
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
    o.pick=pick; o.sport='CFB';
    return o;
  }

  /* ---- basketball ---- */
  function hoopState(g){
    var s=String(g.status||'').toLowerCase();
    if(s==='final') return 'post';
    if(s==='in_progress'||s==='live'||s==='half_over') return 'in';
    return s==='pre_game'||s==='scheduled'||!s?'pre':s;
  }
  function hoopOnNow(g){
    var st=hoopState(g), t=Date.parse(g.start_time_utc), now=Date.now();
    return st==='in' || (st==='pre' && now>=t && now<t+HOOP_HOURS*3600e3);
  }
  function hoopGames(){
    if(!hoops||!hoopTeams) return [];
    var set={}, byName={};
    cbbStars().forEach(function(k){ if(hoopTeams[k]) set[hoopTeams[k][0]]=k; });
    // The scoreboard carries two days back and a week ahead (cbb.live_scraper):
    // the card is the day's - today's games, and last night's, finished or
    // (tipped at 11 and still going past midnight) not.
    var today=etDate(Date.now()), yday=etDate(Date.now()-864e5);
    return Object.keys(hoops).map(function(id){ return hoops[id]; }).filter(function(g){
      var d=g.date||etDate(Date.parse(g.start_time_utc));
      return (set[g.home_team]||set[g.away_team])
        && (d===today || (d===yday && hoopState(g)!=='pre'));
    }).map(function(g){
      return {g:g, side:(set[g.away_team]&&!set[g.home_team])?'away':'home',
              key:set[g.away_team]&&!set[g.home_team]?set[g.away_team]:set[g.home_team]};
    });
  }
  function hoopRow(x){
    var g=x.g, side=x.side, other=side==='home'?'away':'home', st=hoopState(g);
    // Scores reach innerHTML: numbers only, whatever the feed holds.
    var mine=score(g[side+'_score']), theirs=score(g[other+'_score']);
    var o={href:'/men/', logo:img(encodeURI(hoopTeams[x.key][1])), me:g[side+'_team'],
           them:g[other+'_team']||'TBD', rank:g[side+'_rank'], theirRank:g[other+'_rank'],
           at:side==='home'?'vs':'at', live:st==='in', t:Date.parse(g.start_time_utc)};
    if(st==='in'){
      var clock=String(g.status).toLowerCase()==='half_over'?'Half'
        :[g.period,g.clock].filter(Boolean).join(' ');
      o.when='Live '+(mine||0)+'&ndash;'+(theirs||0)+(clock?' &middot; '+esc(clock):''); o.cls='live';
    } else if(st==='post' && mine!=null && theirs!=null){
      var r=result(mine,theirs,g.overtime?' OT':''); o.when=r.when; o.cls=r.cls;
    } else if(st==='pre'){ o.when=day(g.start_time_utc,true); }
    else { o.when=esc(String(g.status).replace(/_/g,' ')); }
    var pick='';
    // GordStats' call (cbb.game_model) like football's; the ranks where there
    // is none yet (no ratings for the season, or an unrated opponent).
    if(g.home_win_prob!=null && g.pred_home!=null && g.pred_away!=null){
      var homeFav=g.home_win_prob>=0.5, fav=homeFav?g.home_team:g.away_team;
      var p=homeFav?g.home_win_prob:1-g.home_win_prob;
      pick='GordStats: <b>'+esc(fav)+'</b> by '+Math.abs(g.pred_home-g.pred_away).toFixed(1)
        +' &middot; '+Math.round(p*100)+'%';
    } else if(g[side+'_model']!==''&&g[side+'_model']!=null)
      pick='GordStats rank: <b>'+esc(o.me)+'</b> #'+esc(g[side+'_model'])
        +(g[other+'_model']!==''&&g[other+'_model']!=null?', '+esc(o.them)+' #'+esc(g[other+'_model']):'');
    if(g.spread_close) pick+=(pick?' &middot; ':'')+'Line: '+esc(g.spread_close).replace(/ -(?=\\d)/,' &minus;');
    if(g.is_mm||g.is_nit||/tournament/i.test(g.game_description||''))
      pick=esc(g.game_description)+(pick?' &middot; '+pick:'');
    o.pick=pick; o.sport='CBB';
    return o;
  }

  function prompt(){
    var where=[];
    if(CFB_ON) where.push('<a href="/cfb/power/">college football</a>');
    if(CBB_ON) where.push('<a href="/cbb/power/">college basketball</a>');
    return '<p class="mt-none">Star teams (&#9734;) on the '+where.join(' or ')
      +' rankings and their games show up here, with '+(CFB_ON?'our pick and ':'')+'the live score.</p>';
  }

  function draw(){
    var fs=cfbStars(), bs=cbbStars();
    if(!fs.length && !bs.length){ host.innerHTML=prompt(); return; }
    var rows=[], byes=[];
    if(cfb && fs.length){
      var set={}; fs.forEach(function(i){ set[i]=1; });
      var games=cfb.games.filter(function(g){ return set[g.home.id]||set[g.away.id]; });
      var busy={}; games.forEach(function(g){ busy[g.home.id]=1; busy[g.away.id]=1; });
      byes=fs.filter(function(i){ return !busy[i] && cfb.teams[i]; })
        .map(function(i){ return esc(cfb.teams[i]); });
      games.forEach(function(g){ rows.push(cfbRow(g,set)); });
    }
    hoopGames().forEach(function(x){ rows.push(hoopRow(x)); });
    rows.sort(function(a,b){ return (a.t||0)-(b.t||0); });
    var both=rows.some(function(o){ return o.sport==='CFB'; }) && rows.some(function(o){ return o.sport==='CBB'; });
    rows.forEach(function(o){ if(both) o.pick='<span class="mt-sp">'+o.sport+'</span>'+(o.pick||''); });
    var kf=!!(cfb&&fs.length), kb=!!(hoops&&hoopTeams&&bs.length), none='';
    if(kf&&kb) none='None of your teams plays today, and your football teams are off this week.';
    else if(kb) none='None of your teams plays today.';
    else if(kf) none='None of your teams plays in the next week.';
    var html=(rows.length?'<div class="mt-list">'+rows.map(shell).join('')+'</div>'
        :(none?'<p class="mt-none">'+none+'</p>':''))
      +(byes.length&&rows.length?'<p class="mt-bye">Off this week: '+byes.join(', ')+'.</p>':'');
    host.innerHTML=html;
    // Stars but nothing loaded for them: no card rather than an empty frame.
    host.closest('section').hidden=!html;
  }
  function etDate(t){ return new Date(t).toLocaleDateString('en-CA',{timeZone:'America/New_York'}); }
  function pushedAt(stamp){
    // The old pusher stamped naive UTC; the live tick stamps an offset.
    var g=String(stamp||''), t=Date.parse(/[zZ]|[+-]\\d\\d:\\d\\d$/.test(g)?g:g+'Z');
    return isNaN(t)?0:t;
  }

  /** A wake-up at the next kickoff of `ts` (ms), within a day: the card was
   *  drawn once and showed "Sat 3:30 PM" through the game. Half a minute in,
   *  so the scoreboard has the game going. */
  function wake(ts, fn){
    var now=Date.now();
    var next=ts.filter(function(t){ return t>now; }).sort(function(a,b){ return a-b; })[0];
    if(next==null || next-now>864e5) return null;
    return setTimeout(fn, next-now+30000);
  }

  /** Football scores for every game of the reader's on right now, from the proxy. */
  function poll(){
    clearTimeout(timer);
    if(!cfb) return;
    var set={}; cfbStars().forEach(function(i){ set[i]=1; });
    var mine=cfb.games.filter(function(g){ return set[g.home.id]||set[g.away.id]; });
    var now=mine.filter(cfbOnNow);
    if(!now.length){
      timer=wake(mine.filter(function(g){ return ((live[g.id]||{}).state||g.state)==='pre'; })
        .map(function(g){ return Date.parse(g.kickoff); }).filter(function(t){ return !isNaN(t); }),
        function(){ draw(); poll(); });
      return;
    }
    if(document.hidden){ timer=setTimeout(poll,60000); return; }
    var asks={};
    now.forEach(function(g){ asks[g.week+'|'+g.seasontype]=g; });
    Promise.all(Object.keys(asks).map(function(k){
      var g=asks[k];
      return fetch('/api/cfb-scores?week='+g.week+'&dates='+cfb.season+'&seasontype='+g.seasontype)
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
    }).catch(function(e){
      if(window.console) console.error('[my-teams]', e);
    }).then(function(){
      clearTimeout(timer);
      timer=setTimeout(poll,60000);
    });
  }

  function json(url){
    return fetch(url).then(function(r){ return r.ok?r.json():null; }).catch(function(){ return null; });
  }
  function hoopScores(){
    return json(HOOPS).then(function(d){
      if(d && d.leagues && Date.now()-pushedAt(d.generated)<HOOP_STALE_HOURS*3600e3)
        hoops=d.leagues.men||{};
    });
  }
  /** The day's basketball, the first time a reader with a basketball star needs it. */
  function loadHoops(){
    if(!CBB_ON || hoopLoading || (hoops&&hoopTeams) || !cbbStars().length) return Promise.resolve();
    hoopLoading=true;
    return Promise.all([hoopTeams?Promise.resolve(hoopTeams):json('/cbb/star-teams.json'),
                        hoopScores()]).then(function(r){
      // A fetch that failed is asked again on the next star or return to the tab.
      hoopTeams=r[0]; hoopLoading=false;
    });
  }
  /** The scoreboard is pushed every ten minutes: a few polls a push is plenty. */
  function pollHoops(){
    clearTimeout(hoopTimer);
    if(!hoops) return;
    var games=hoopGames();
    if(!games.some(function(x){ return hoopOnNow(x.g); })){
      // Nothing on: wake at the next tip-off of the reader's (the scoreboard
      // is fetched on the poll after it, once the feed has the game going).
      hoopTimer=wake(games.filter(function(x){ return hoopState(x.g)==='pre'; })
        .map(function(x){ return Date.parse(x.g.start_time_utc); })
        .filter(function(t){ return !isNaN(t); }),
        function(){ draw(); pollHoops(); });
      return;
    }
    if(document.hidden){ hoopTimer=setTimeout(pollHoops,60000); return; }
    hoopTimer=setTimeout(function(){ hoopScores().then(function(){ draw(); pollHoops(); }); },180000);
  }

  var football=CFB_ON?json('/cfb/week-games.json').then(function(d){
    if(d && d.games && !(Date.now()-Date.parse(d.generated)>STALE_DAYS*864e5)) cfb=d;
  }):Promise.resolve();
  Promise.all([football, loadHoops()]).then(function(){
    draw(); poll(); pollHoops();
  });
  // Stars change on this page's other cards, or arrive from the account.
  document.addEventListener('gs:favorites', function(){
    draw(); poll();
    loadHoops().then(function(){ draw(); pollHoops(); });
  });
  document.addEventListener('visibilitychange', function(){
    if(document.hidden) return;
    poll(); loadHoops().then(function(){ draw(); pollHoops(); });
  });
})();
</script>{% endraw %}"""


def section(cfb: bool = True, cbb: bool = False) -> str:
    """The card, for whichever of the two seasons is on (render_home decides)."""
    title = "My teams" if cbb else "My teams this week"
    link = ('<a class="home-card-link" href="/cfb/schedule/">Full schedule &rarr;</a>' if cfb
            else '<a class="home-card-link" href="/men/">Scoreboard &rarr;</a>')
    # The prompt the script draws for a reader with no stars - most readers -
    # is drawn with the page: drawn by the script, it pushed Home down 32-128px
    # a moment after it painted (the 2026-10-02 layout-shift check).
    where = ((['<a href="/cfb/power/">college football</a>'] if cfb else [])
             + (['<a href="/cbb/power/">college basketball</a>'] if cbb else []))
    prompt = ('<p class="mt-none">Star teams (&#9734;) on the ' + " or ".join(where)
              + " rankings and their games show up here, with "
              + ("our pick and " if cfb else "") + "the live score.</p>")
    return (CSS + '<section class="home-card" id="my-teams">'
            f'<div class="home-card-head"><h2>{title}</h2>{link}</div>'
            f'<div id="mt-host" data-cfb="{int(cfb)}" data-cbb="{int(cbb)}">{prompt}</div></section>' + JS)
