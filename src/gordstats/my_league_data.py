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
  // One copy of the index, shared with GSAPI: an ESPN league adds the
  // players it cannot map to Sleeper to it, by name, so they can be shown.
  function players(){ return GSAPI.players(); }
  function week(){ return once('week','/fantasy/week-projections.json',
                               {week:0,kick:{},proj:{}}); }

  // Every league this browser knows about, as /api/leagues answered - the
  // list gordstats.my_league caches. Read here rather than re-requested.
  var LIST='gsSleeperLeagues';

  /** What the account knows about the reader in one league: their own Sleeper
   *  user id, and their team's name as a fallback for a row synced before the
   *  id was stored.
   *
   *  A page showing somebody's league has twelve rosters and, without this,
   *  no idea which is theirs - so "My Team" opened on whoever happened to
   *  hold roster 1.
   */
  function mine(leagueId){
    var rows=[];
    try{ rows=JSON.parse(localStorage.getItem(LIST)||'[]')||[]; }catch(e){}
    if(!rows.length) return {uid:null, team:null};
    var row=rows.filter(function(l){
      return String(l.league_id)===String(leagueId);})[0];
    // Any row of theirs identifies the account; it is one Sleeper user
    // whichever league is on screen.
    var any=rows.filter(function(l){ return l.provider_user_id; })[0];
    return {uid:String((row&&row.provider_user_id)||(any&&any.provider_user_id)||'')||null,
            team:(row&&row.team_name)||null};
  }

  /** The team the reader picked on My Team, per league: a league added by id
   *  (every ESPN league, and a Sleeper one pasted in) has no account id to
   *  find theirs by, and without this it opened on roster 1 every time. */
  var PICKED='gsMyRoster';
  function picked(){
    try{ return JSON.parse(localStorage.getItem(PICKED)||'{}')||{}; }catch(e){ return {}; }
  }
  function remember(leagueId, rosterId){
    var all=picked();
    all[String(leagueId)]=String(rosterId);
    try{ localStorage.setItem(PICKED, JSON.stringify(all)); }catch(e){}
  }

  /** The roster id the reader owns in `lg` (from `league`), or null. */
  function myRoster(lg, leagueId){
    var who=mine(leagueId);
    if(who.uid){
      var hit=(lg.rosters||[]).filter(function(r){
        return String(r.owner_id)===String(who.uid);})[0];
      if(hit) return String(hit.roster_id);
    }
    var chose=picked()[String(leagueId)];
    if(chose && (lg.names||{})[chose]) return chose;
    if(who.team){
      // `names` reads "Team (manager)", so the stored team name is a prefix.
      var keys=Object.keys(lg.names||{});
      for(var i=0;i<keys.length;i++)
        if(String(lg.names[keys[i]]).indexOf(who.team)===0) return keys[i];
    }
    return null;
  }

  function api(id, path){
    return GSAPI.get('/league/'+encodeURIComponent(id)+path);
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

  /** Which of Sleeper's three published bases this league is closest to.
   *  A league whose settings could not be read is PPR, the basis every number
   *  here is published in - not standard, which a missing `rec` used to
   *  fall through to, quietly taking every catch off. */
  function basis(info){
    var sc=(info&&info.scoring_settings)||{};
    var rec=sc.rec;
    var i = (typeof rec!=='number')?0 : (rec>=0.75)?0 : (rec>=0.25)?1 : 2;  // ppr / half / std
    // Anything materially off the default is flagged so the page can say the
    // numbers are close rather than exact.
    var custom = (sc.pass_td!=null && Math.abs(sc.pass_td-4)>0.01)
      || (sc.rec_td!=null && Math.abs(sc.rec_td-6)>0.01)
      || Object.keys(sc).some(function(k){return k.indexOf('bonus')===0 && sc[k];});
    return {index:i, name:['PPR','half-PPR','standard'][i], custom:!!custom};
  }

  /** {player_id: points} under one basis - expected points: a Questionable or
   *  Doubtful player's projection times his chance of playing this week
   *  (`play`, fantasy.league.availability), as this site's own pages count it.
   *
   *  Once he is seen playing the chance is spent and the whole projection is
   *  what is left to come, as fantasy.site.matchups has it. The file only
   *  carries `play` for players not yet seen in a game when it was built
   *  (fantasy.site.players_index), and `live` - Sleeper's players_points for
   *  the week, where the caller has it - spends it for anyone with points
   *  since. Kickoff alone is not enough: an inactive player's game kicks off
   *  without him. */
  function points(wk, basisIndex, live){
    var out={}, play=wk.play||{};
    for(var pid in wk.proj){
      var p=play[pid];
      if(live&&live[pid]) p=1;
      out[pid]=wk.proj[pid][basisIndex]*(typeof p==='number'?p:1);
    }
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
          basis:basis, points:points, kickoffs:kickoffs,
          mine:mine, myRoster:myRoster, remember:remember};
})();
</script>{% endraw %}"""
