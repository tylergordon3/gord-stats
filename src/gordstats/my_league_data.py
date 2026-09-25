"""
Shared browser-side loading for "your own league": the player index, this
week's projections, and the scoring basis a league actually plays.

Both the matchups view and the team dashboard need the same three things, and
they must agree about them - a lineup recommended on PPR numbers beside a
scoreboard totalled on half-PPR would be its own bug. So it lives here once and
hangs off `window.GSL`.

The scoring basis is the part worth stating. This site plays PPR, and every
projection it publishes is PPR. Sleeper prices each player under PPR, half-PPR
and standard, so those three leagues are exact; `scoring_settings.rec` says
which. Anything further from the default - six-point passing touchdowns,
reception bonuses - is approximated by the nearest of the three, and the page
says so rather than quietly being wrong.
"""

JS = """{% raw %}<script>
window.GSL = (function(){
  var KEY='gsSleeperLeague';
  var cache={};

  function saved(){
    try{ return JSON.parse(localStorage.getItem(KEY)||'null'); }catch(e){ return null; }
  }
  function once(name, url, shape){
    if(cache[name]) return cache[name];
    cache[name]=fetch(url).then(function(r){return r.ok?r.json():shape;})
      .catch(function(){return shape;});
    return cache[name];
  }
  function players(){ return once('players','/fantasy/players-index.json',{}); }
  function week(){ return once('week','/fantasy/week-projections.json',
                               {week:0,kick:{},proj:{}}); }

  function api(id, path){
    return fetch('https://api.sleeper.app/v1/league/'+encodeURIComponent(id)+path)
      .then(function(r){return r.ok?r.json():null;});
  }

  /** Everything about one league: settings, rosters, and who owns what. */
  function league(id){
    return Promise.all([api(id,''), api(id,'/rosters'), api(id,'/users')])
      .then(function(o){
        var info=o[0]||{}, rosters=o[1]||[], users=o[2]||[];
        var byUser={};
        users.forEach(function(u){
          var team=(u.metadata&&u.metadata.team_name)||u.display_name||'Team';
          var mgr=u.display_name||'';
          byUser[u.user_id]=(mgr&&team.indexOf(mgr)<0)?(team+' ('+mgr+')'):team;
        });
        var names={}, held={};
        rosters.forEach(function(r){
          var key=String(r.roster_id);
          names[key]=byUser[r.owner_id]||('Roster '+key);
          (r.players||[]).forEach(function(p){ held[String(p)]=key; });
        });
        return {info:info, rosters:rosters, names:names, held:held,
                basis:basis(info), slots:info.roster_positions||[]};
      });
  }

  /** Which of Sleeper's three published bases this league is closest to. */
  function basis(info){
    var sc=(info&&info.scoring_settings)||{};
    var rec=sc.rec;
    var i = (rec>=0.75)?0 : (rec>=0.25)?1 : 2;          // ppr / half / standard
    // Anything materially off the default is flagged so the page can say the
    // numbers are close rather than exact.
    var custom = (sc.pass_td!=null && Math.abs(sc.pass_td-4)>0.01)
      || (sc.rec_td!=null && Math.abs(sc.rec_td-6)>0.01)
      || Object.keys(sc).some(function(k){return k.indexOf('bonus')===0 && sc[k];});
    return {index:i, name:['PPR','half-PPR','standard'][i], custom:!!custom};
  }

  /** {player_id: points} under one basis. */
  function points(wk, basisIndex){
    var out={};
    for(var pid in wk.proj) out[pid]=wk.proj[pid][basisIndex];
    return out;
  }
  /** {player_id: kickoff ms} from the player's team this week. */
  function kickoffs(wk){
    var out={};
    for(var pid in wk.proj){
      var t=wk.proj[pid][3], k=t&&wk.kick[t];
      if(k){ var ms=Date.parse(k); if(!isNaN(ms)) out[pid]=ms; }
    }
    return out;
  }

  return {saved:saved, players:players, week:week, league:league,
          basis:basis, points:points, kickoffs:kickoffs};
})();
</script>{% endraw %}"""
