/* "This week" at the top of League Home.
   Source file, loaded by gordstats.week_strip (JS_TAG); see gordstats.js_assets. */
(function(){
  var host=document.getElementById('ws-host');
  function settle(){ if(host) host.classList.remove('ws-wait'); }
  if(!host||!window.GSL){ settle(); return; }
  // The league on screen: the reader's, or this site's own.
  var have=GSL.saved();
  var ID=String((have&&have.id)||(window.GSCFG||{}).siteLeague||'');
  var AVATAR='https://sleepercdn.com/avatars/thumbs/';
  var GAME_HOURS=3.75;
  var timer=null, ctx=null, fails=0, over=false;

  function get(p){
    return GSAPI.get(p)
      .catch(function(){return null;});
  }
  function esc(v){
    return String(v==null?'':v).replace(/[&<>"']/g,function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});
  }
  function fmt(v){ return (Math.round(v*10)/10).toFixed(1); }

  /** A matchup's state by its starters' kickoffs: 'pre' before the first,
   *  'live' while any of their games is on, 'mid' between them (Sunday night,
   *  with a starter still to play on Monday), 'post' once the last is over. */
  function stateOf(starters){
    var now=Date.now(), span=GAME_HOURS*3600e3, first=Infinity, last=-Infinity, on=false;
    starters.forEach(function(pid){
      var row=ctx.wk.proj[pid], k=row&&ctx.wk.kick[row[3]];
      var ms=k?Date.parse(k):NaN;
      if(isNaN(ms)) return;
      first=Math.min(first,ms); last=Math.max(last,ms);
      if(now>=ms && now<ms+span) on=true;
    });
    if(first===Infinity || now<first) return 'pre';
    if(on) return 'live';
    return now>last+span?'post':'mid';
  }

  function side(r){
    var ro=ctx.byRoster[r.roster_id]||{}, u=ctx.byUser[ro.owner_id]||{};
    var starters=(r.starters||[]).filter(function(p){ return p && p!=='0'; });
    var proj=starters.reduce(function(t,p){ return t+(ctx.proj[p]||0); },0);
    return {key:String(r.roster_id), name:u.team||('Team '+r.roster_id), avatar:u.avatar,
            pts:Number(r.points||0), proj:proj, starters:starters};
  }

  /** The next kickoff among these starters still to come (ms), or null. */
  function nextKick(starters){
    var now=Date.now(), next=null;
    starters.forEach(function(pid){
      var row=ctx.wk.proj[pid], k=row&&ctx.wk.kick[row[3]];
      var ms=k?Date.parse(k):NaN;
      if(!isNaN(ms) && ms>now && (next===null || ms<next)) next=ms;
    });
    return next;
  }

  function drawWeek(rows){
    var by={}, next=null, done=true;
    (rows||[]).forEach(function(r){
      if(r.matchup_id==null) return;
      (by[r.matchup_id]=by[r.matchup_id]||[]).push(r);
    });
    var live=false;
    var pairs=Object.keys(by).map(function(m){
      var p=by[m]; if(p.length!==2) return null;
      var a=side(p[0]), b=side(p[1]);
      if(ctx.mine && b.key===ctx.mine){ var t=a; a=b; b=t; }
      var both=a.starters.concat(b.starters), st=stateOf(both);
      if(st==='pre' && (a.pts||b.pts)) st='mid';
      if(st==='live') live=true;
      if(st!=='post') done=false;
      var k=nextKick(both);
      if(k!==null && (next===null || k<next)) next=k;
      return {a:a, b:b, st:st, mine:!!ctx.mine&&(a.key===ctx.mine||b.key===ctx.mine), id:m};
    }).filter(Boolean).sort(function(x,y){ return (y.mine?1:0)-(x.mine?1:0) || x.id-y.id; });
    if(!pairs.length) return {html:'<p class="ws-load">No matchups this week.</p>', live:false,
                              next:null, done:true};
    var html=pairs.map(function(p){
      function one(s, cls){
        return '<div class="ws-side '+cls+'">'
          +(s.avatar?'<img src="'+esc(s.avatar)+'" alt="" loading="lazy">':'')
          +'<span class="ws-nm">'+esc(s.name)+'</span></div>';
      }
      var pre=p.st==='pre';
      function num(s, o, cls){
        var v=pre?s.proj:s.pts;
        return '<b class="'+cls+(pre?' proj':(s.pts>o.pts?' lead':''))+'">'+fmt(v)+'</b>';
      }
      var label=pre?'projected':({live:'live', mid:'in progress', post:'final'}[p.st]);
      return '<a class="ws-mu'+(p.mine?' me':'')+'" href="/fantasy/matchups/">'
        +one(p.a,'a')+num(p.a,p.b,'pa')+'<span class="dash">&ndash;</span>'+num(p.b,p.a,'pb')
        +one(p.b,'b r')+'<small class="st'+(p.st==='live'?' live':'')+'">'+label+'</small></a>';
    }).join('');
    return {html:html, live:live, next:next, done:done};
  }

  function drawStandings(){
    var rows=ctx.rosters.map(function(r){
      var s=r.settings||{}, u=ctx.byUser[r.owner_id]||{};
      return {key:String(r.roster_id), name:u.team||('Team '+r.roster_id),
              w:s.wins||0, l:s.losses||0, t:s.ties||0,
              pf:(s.fpts||0)+((s.fpts_decimal||0)/100)};
    }).sort(function(a,b){ return (b.w-a.w)||(a.l-b.l)||(b.pf-a.pf); });
    return '<table class="ws-st"><thead><tr><th>#</th><th>Team</th><th>W-L</th><th>PF</th></tr></thead><tbody>'
      + rows.map(function(r,i){
          return '<tr'+(r.key===ctx.mine?' class="me"':'')+'><td class="rk">'+(i+1)+'</td>'
            +'<td class="t">'+esc(r.name)+'</td><td>'+r.w+'-'+r.l+(r.t?'-'+r.t:'')+'</td>'
            +'<td>'+r.pf.toFixed(1)+'</td></tr>';
        }).join('')+'</tbody></table>';
  }

  function render(rows){
    // Priced again on the points so far: GSL.points spends a Questionable
    // player's play chance once Sleeper has him scoring.
    var seen={};
    (rows||[]).forEach(function(r){
      var pp=r.players_points||{};
      for(var k in pp) seen[k]=pp[k];
    });
    ctx.proj=GSL.points(ctx.wk, ctx.basis, seen);
    var week=drawWeek(rows);
    var median=!!((ctx.info.settings||{}).league_average_match);
    settle();
    host.innerHTML='<div class="ws">'
      +'<div class="ws-card"><div class="ws-head"><h2>This week</h2>'
      +'<span class="ws-sub">Week '+ctx.week+'</span>'
      +'<a href="/fantasy/matchups/">Matchups &rarr;</a></div>'+week.html+'</div>'
      +'<div class="ws-card"><div class="ws-head"><h2>Standings</h2>'
      +'<span class="ws-sub">'+(median?'median games included':'')+'</span>'
      +'<a href="/fantasy/power/">Power &rarr;</a></div>'+drawStandings()+'</div></div>';
    // Live: every minute. Not yet: at the next kickoff, so a page opened on
    // Sunday morning goes live at one without a reload (it used to poll only
    // if something was already on when it was drawn). Over: nothing to wait for.
    over=week.done && !week.live;
    if(week.live) later(60000);
    else if(week.next!==null) later(Math.min(week.next-Date.now()+30000, 6*3600e3));
    else { clearTimeout(timer); timer=null; }
  }

  function later(ms){ clearTimeout(timer); timer=setTimeout(refresh, Math.max(ms, 1000)); }

  function refresh(){
    clearTimeout(timer); timer=null;
    if(document.hidden){ later(60000); return; }
    get('/league/'+ID+'/matchups/'+ctx.week).then(function(rows){
      if(rows){ fails=0; render(rows); return; }
      // Sleeper did not answer: try again, backing off - a failed fetch used
      // to end the live updates for good.
      fails++;
      later(Math.min(60000*Math.pow(2, fails-1), 15*60000));
    }).catch(function(e){
      if(window.console) console.error('[week-strip]', e);
      later(120000);
    });
  }
  // Back to the tab: read the week again at once, unless it is all over.
  document.addEventListener('visibilitychange', function(){
    if(!document.hidden && ctx && !over) refresh(); });

  function boot(tries){
  Promise.all([get('/state/nfl'), get('/league/'+ID), get('/league/'+ID+'/rosters'),
               get('/league/'+ID+'/users'), GSL.week()]).then(function(o){
    // Sleeper's clock did not answer: that is the network, not the offseason,
    // so it is asked again a little later rather than leaving the card off.
    if(!o[0] && tries<3){ setTimeout(function(){ boot(tries+1); }, 30000*(tries+1)); return; }
    var state=o[0]||{}, info=o[1], rosters=o[2]||[], users=o[3]||[], wk=o[4]||{proj:{},kick:{}};
    var week=parseInt(state.display_week||state.week||wk.week||0,10);
    if(!info||!rosters.length||!week||String(info.season)!==String(state.season)){
      settle(); host.innerHTML=''; return;       // offseason, or a league Sleeper cannot find
    }
    // The site's week file trails Sleeper for a few hours at a rollover: last
    // week's kickoffs drew the new week's games as "0.0-0.0 final". Another
    // week's file is no file.
    if(wk.week && +wk.week!==week) wk={proj:{},kick:{}};
    var byUser={}, byRoster={};
    users.forEach(function(u){
      byUser[u.user_id]={team:(u.metadata&&u.metadata.team_name)||u.display_name||'Team',
                         avatar:(u.metadata&&String(u.metadata.avatar).indexOf('https://sleepercdn.com/')===0&&u.metadata.avatar)||(u.avatar?AVATAR+u.avatar:'')};
    });
    rosters.forEach(function(r){ byRoster[r.roster_id]=r; });
    var mine=GSL.myRoster({rosters:rosters, names:{}}, ID);
    ctx={info:info, rosters:rosters, byUser:byUser, byRoster:byRoster, wk:wk, week:week,
         basis:GSL.basis(info).index,
         proj:GSL.points(wk, GSL.basis(info).index), mine:mine?String(mine):null};
    return get('/league/'+ID+'/matchups/'+week).then(function(rows){
      if(rows) render(rows);
      else { fails++; settle(); later(60000); }    // asked again, as a poll is
    });
  }).catch(function(e){
    if(window.console) console.error('[week-strip]', e);
    settle(); host.innerHTML='';
  });
  }
  boot(0);
})();
