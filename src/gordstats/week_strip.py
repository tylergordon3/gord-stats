"""
"This week" at the top of League Home: every matchup with its score, and the
standings.

League Home was all history - all-time metrics and the team profiles - so the
page a manager opens on a Sunday said nothing about the Sunday. This puts the
week first. It is drawn in the browser from Sleeper for whichever league is on
screen - this site's own is a Sleeper league too - so the built page and a
reader's league get the same strip, from the same code, with live points:

  * every matchup of the week, the reader's own first; Sleeper's projected
    totals before kickoff (the league's scoring basis, from the week's
    projection file), points once games are on, marked live or final by the
    kickoffs of the starters involved;
  * the standings - Sleeper's records, which in a league playing the median
    count two results a week - with points for, the reader's team marked.

It polls once a minute only while a game is on, and never on a hidden tab.
"""

CSS = """<style>
.ws{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(0,1fr);gap:14px;margin:12px 0 22px}
@media (max-width:760px){.ws{grid-template-columns:minmax(0,1fr)}}
.ws-card{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:12px 14px;min-width:0}
.ws-head{display:flex;align-items:baseline;justify-content:space-between;gap:8px;margin:0 0 8px}
.ws-head h2{margin:0;font-size:17px;border:0;padding:0}
.ws-head a{font-size:13px;font-weight:700;white-space:nowrap}
.ws-sub{font-size:12px;color:#64748b}
/* A matchup: side by side on a wide screen (name, score - score, name,
   the state under the scores); on a phone one team a line, so the names
   keep their width, with the state on the right. */
.ws-mu{display:grid;grid-template-columns:minmax(0,1fr) auto auto auto minmax(0,1fr);
  grid-template-areas:"a pa dash pb b" ". st st st .";align-items:center;column-gap:8px;
  padding:7px 6px;border-top:1px solid #eef2f7;text-decoration:none;color:inherit;border-radius:8px}
.ws-mu .a{grid-area:a}.ws-mu .b{grid-area:b}.ws-mu .pa{grid-area:pa;text-align:right}
.ws-mu .pb{grid-area:pb}.ws-mu .dash{grid-area:dash;color:#64748b}.ws-mu .st{grid-area:st;text-align:center}
@media (max-width:600px){
  .ws-mu{grid-template-columns:minmax(0,1fr) auto auto;grid-template-areas:"a pa st" "b pb st";
    row-gap:4px}
  .ws-mu .dash{display:none}
  .ws-mu .pb{text-align:right}
  .ws-mu .ws-side.r{flex-direction:row;text-align:left}
  .ws-mu .st{text-align:right;min-width:62px}
}
.ws-mu:first-of-type{border-top:0}
.ws-mu.me{background:#f0fdf4;box-shadow:inset 3px 0 0 #1a7f4b}
.ws-side{display:flex;align-items:center;gap:7px;min-width:0}
.ws-side.r{flex-direction:row-reverse;text-align:right}
.ws-side img{width:24px;height:24px;border-radius:50%;flex:none;border:0;padding:0;box-shadow:none;
  background:none;object-fit:cover}
.ws-nm{font-size:13.5px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ws-mu b{font-size:15px;font-variant-numeric:tabular-nums;white-space:nowrap}
.ws-mu b.lead{color:#1a7f4b}
.ws-mu b.proj{color:#64748b;font-weight:600;font-style:italic}
.ws-mu small{font-size:10.5px;color:#64748b;text-transform:uppercase;letter-spacing:.04em;white-space:nowrap}
.ws-mu small.live{color:#b3382c;font-weight:700}
table.ws-st{width:100%;border-collapse:collapse;font-size:13px}
table.ws-st th{font-size:11px;text-transform:uppercase;letter-spacing:.03em;color:#64748b;
  text-align:right;padding:4px 6px;border-bottom:1px solid #e2e8f0;background:transparent}
table.ws-st th:nth-child(2){text-align:left}
table.ws-st td{padding:5px 6px;border-bottom:1px solid #eef2f7;text-align:right;
  font-variant-numeric:tabular-nums;background:transparent;color:inherit}
table.ws-st td.t{text-align:left;max-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  font-weight:600;width:60%}
table.ws-st td.rk{color:#64748b;width:1%}
table.ws-st tr.me td{background:#f0fdf4}
.ws-load{font-size:13px;color:#64748b}
@media (prefers-color-scheme: dark){
  .ws-card{background:#16203a;border-color:#2b3852}
  .ws-sub,.ws-mu small,.ws-mu .dash,.ws-load,table.ws-st th,table.ws-st td.rk{color:#aab7c9}
  .ws-mu{border-top-color:#2b3852}
  .ws-mu.me{background:#123c2e;box-shadow:inset 3px 0 0 #6ee7b7}
  .ws-mu b.lead{color:#8ff0bd}
  .ws-mu b.proj{color:#aab7c9}
  .ws-mu small.live{color:#ffb4ab}
  table.ws-st th{border-bottom-color:#2b3852}
  table.ws-st td{border-bottom-color:#2b3852}
  table.ws-st tr.me td{background:#123c2e}
}
</style>"""

JS = """{% raw %}<script>
(function(){
  var host=document.getElementById('ws-host');
  if(!host||!window.GSL) return;
  // The league on screen: the reader's, or this site's own.
  var have=GSL.saved();
  var ID=String((have&&have.id)||'__SITE_LEAGUE__');
  var AVATAR='https://sleepercdn.com/avatars/thumbs/';
  var GAME_HOURS=3.75;
  var timer=null, ctx=null;

  function get(p){
    return GSAPI.get(p)
      .catch(function(){return null;});
  }
  function esc(v){
    return String(v==null?'':v).replace(/[&<>"]/g,function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});
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

  function drawWeek(rows){
    var by={};
    (rows||[]).forEach(function(r){
      if(r.matchup_id==null) return;
      (by[r.matchup_id]=by[r.matchup_id]||[]).push(r);
    });
    var live=false;
    var pairs=Object.keys(by).map(function(m){
      var p=by[m]; if(p.length!==2) return null;
      var a=side(p[0]), b=side(p[1]);
      if(ctx.mine && b.key===ctx.mine){ var t=a; a=b; b=t; }
      var st=stateOf(a.starters.concat(b.starters));
      if(st==='pre' && (a.pts||b.pts)) st='mid';
      if(st==='live') live=true;
      return {a:a, b:b, st:st, mine:!!ctx.mine&&(a.key===ctx.mine||b.key===ctx.mine), id:m};
    }).filter(Boolean).sort(function(x,y){ return (y.mine?1:0)-(x.mine?1:0) || x.id-y.id; });
    if(!pairs.length) return {html:'<p class="ws-load">No matchups this week.</p>', live:false};
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
    return {html:html, live:live};
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
    var week=drawWeek(rows);
    var median=!!((ctx.info.settings||{}).league_average_match);
    host.innerHTML='<div class="ws">'
      +'<div class="ws-card"><div class="ws-head"><h2>This week</h2>'
      +'<span class="ws-sub">Week '+ctx.week+'</span>'
      +'<a href="/fantasy/matchups/">Matchups &rarr;</a></div>'+week.html+'</div>'
      +'<div class="ws-card"><div class="ws-head"><h2>Standings</h2>'
      +'<span class="ws-sub">'+(median?'median games included':'')+'</span>'
      +'<a href="/fantasy/power/">Power &rarr;</a></div>'+drawStandings()+'</div></div>';
    clearTimeout(timer);
    if(week.live) timer=setTimeout(refresh, 60000);
  }

  function refresh(){
    if(document.hidden){ timer=setTimeout(refresh, 60000); return; }
    get('/league/'+ID+'/matchups/'+ctx.week).then(function(rows){ if(rows) render(rows); });
  }
  document.addEventListener('visibilitychange', function(){
    if(!document.hidden && ctx && timer){ clearTimeout(timer); refresh(); } });

  Promise.all([get('/state/nfl'), get('/league/'+ID), get('/league/'+ID+'/rosters'),
               get('/league/'+ID+'/users'), GSL.week()]).then(function(o){
    var state=o[0]||{}, info=o[1], rosters=o[2]||[], users=o[3]||[], wk=o[4]||{proj:{},kick:{}};
    var week=parseInt(state.display_week||state.week||wk.week||0,10);
    if(!info||!rosters.length||!week||String(info.season)!==String(state.season)){
      host.innerHTML=''; return;                 // offseason, or a league Sleeper cannot find
    }
    // The site's week file trails Sleeper for a few hours at a rollover: last
    // week's kickoffs drew the new week's games as "0.0-0.0 final". Another
    // week's file is no file.
    if(wk.week && +wk.week!==week) wk={proj:{},kick:{}};
    var byUser={}, byRoster={};
    users.forEach(function(u){
      byUser[u.user_id]={team:(u.metadata&&u.metadata.team_name)||u.display_name||'Team',
                         avatar:(u.metadata&&u.metadata.avatar)||(u.avatar?AVATAR+u.avatar:'')};
    });
    rosters.forEach(function(r){ byRoster[r.roster_id]=r; });
    var mine=GSL.myRoster({rosters:rosters, names:{}}, ID);
    ctx={info:info, rosters:rosters, byUser:byUser, byRoster:byRoster, wk:wk, week:week,
         proj:GSL.points(wk, GSL.basis(info).index), mine:mine?String(mine):null};
    return get('/league/'+ID+'/matchups/'+week).then(render);
  }).catch(function(){ host.innerHTML=''; });
})();
</script>{% endraw %}"""


def _site_league() -> str:
    from fantasy.config import UPCOMING_LEAGUE_ID
    return str(UPCOMING_LEAGUE_ID)


JS = JS.replace("__SITE_LEAGUE__", _site_league())


def section() -> str:
    """The container the script fills; empty in the offseason."""
    return CSS + "<div id='ws-host'></div>"
