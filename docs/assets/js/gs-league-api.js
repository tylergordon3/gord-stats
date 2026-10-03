/* window.GSAPI: a reader's league, Sleeper or ESPN, in Sleeper's shapes.
   Source file, loaded by gordstats.league_api (JS_TAG); see gordstats.js_assets. */
window.GSAPI = window.GSAPI || (function(){
  var SLEEPER='https://api.sleeper.app/v1';
  var ESPN='https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl';
  // ESPN's proTeamId and defaultPositionId codes, as fantasy.league.ext_projections
  // has them (ESPN_TEAMS, ESPN_POSITIONS; tests/test_shared_js_assets.py holds the two equal).
  var TEAMS={"22": "ARI", "1": "ATL", "33": "BAL", "2": "BUF", "29": "CAR", "3": "CHI", "4": "CIN", "5": "CLE", "6": "DAL", "7": "DEN", "8": "DET", "9": "GB", "34": "HOU", "11": "IND", "30": "JAX", "12": "KC", "13": "LV", "24": "LAC", "14": "LAR", "15": "MIA", "16": "MIN", "17": "NE", "18": "NO", "19": "NYG", "20": "NYJ", "21": "PHI", "23": "PIT", "25": "SF", "26": "SEA", "27": "TB", "10": "TEN", "28": "WAS"},
      POS={"1": "QB", "2": "RB", "3": "WR", "4": "TE", "5": "K", "16": "DEF"};
  // ESPN lineup slot ids -> Sleeper's roster_positions names.
  var SLOTS={0:'QB',1:'QB',2:'RB',3:'WRRB_FLEX',4:'WR',5:'REC_FLEX',6:'TE',
             7:'SUPER_FLEX',8:'DL',9:'DL',10:'LB',11:'DL',12:'DB',13:'DB',14:'DB',
             15:'IDP_FLEX',16:'DEF',17:'K',23:'FLEX'};
  var ORDER=[0,1,2,4,6,23,3,5,7,16,17,8,9,11,10,12,13,14,15];
  var BENCH=20, IR=21;
  // Yardage and long-touchdown bonuses: a league with any is "custom".
  var BONUS=[15,16,17,18,35,36,37,38,45,46,56,57];
  var TX={FREEAGENT:'free_agent', WAIVER:'waiver', TRADE_ACCEPT:'trade',
          TRADE_UPHOLD:'trade'};
  var ID=/^espn:(\d{4}):(\d{1,12})$/;

  function parse(id){
    var m=ID.exec(String(id==null?'':id));
    return m?{season:+m[1], league:m[2]}:null;
  }
  function make(season, league){ return 'espn:'+season+':'+league; }
  function isEspn(id){ return !!parse(id); }

  /** A pasted league: an ESPN or Sleeper web address, an `espn:` id, or a
   *  bare number - Sleeper's are 18 or 19 digits, ESPN's at most 10. */
  function parseRef(v){
    v=String(v||'').trim();
    var m=/espn\.com\/football\/[^?#]*\?([^#]*)/i.exec(v);
    if(m){
      var q={};
      m[1].split('&').forEach(function(kv){
        var i=kv.indexOf('=');
        if(i>0) q[kv.slice(0,i)]=decodeURIComponent(kv.slice(i+1));
      });
      if(/^\d{1,12}$/.test(q.leagueId||''))
        return {provider:'espn', league:q.leagueId,
                season:/^\d{4}$/.test(q.seasonId||'')?+q.seasonId:null};
      return null;
    }
    m=/sleeper\.(?:com|app)\/leagues\/(\d{6,32})/i.exec(v);
    if(m) return {provider:'sleeper', id:m[1]};
    var e=parse(v);
    if(e) return {provider:'espn', id:v, league:e.league, season:e.season};
    if(/^\d{13,32}$/.test(v)) return {provider:'sleeper', id:v};
    if(/^\d{3,12}$/.test(v)) return {provider:'espn', league:v, season:null};
    return null;
  }

  // ------------------------------------------------------------- fetching --
  var cache={};
  // ESPN leagues that answered 401/403 - kept private by their commissioner -
  // by season and league, so a page that could not read one can say why in
  // ESPN's terms rather than Sleeper's (problem()).
  var refused={};
  /** One request's {status, data}, made once for the page: kept `ttl`
   *  seconds (0: the whole page view), shared while it is on its way, and
   *  dropped if it fails, so the next ask tries again. */
  function once(key, ttl, make){
    var hit=cache[key], now=Date.now();
    if(hit && (!ttl || now-hit.at<ttl*1000)) return hit.p;
    var p=make();
    function drop(){ if(cache[key] && cache[key].p===p) delete cache[key]; }
    p.then(function(res){ if(!res || res.status!==200) drop(); }, drop);
    cache[key]={at:now, p:p};
    return p;
  }
  /** {status, data} for one ESPN request; kept `ttl` seconds (0: the page). */
  function ask(season, league, views, extra, ttl){
    var q=views.map(function(v){ return 'view='+v; });
    if(extra) q.push(extra);
    var url=season>=2018
      ? ESPN+'/seasons/'+season+'/segments/0/leagues/'+league+'?'+q.join('&')
      : ESPN+'/leagueHistory/'+league+'?seasonId='+season+'&'+q.join('&');
    return once(url, ttl, function(){
      return fetch(url,{credentials:'omit'}).then(function(r){
        if(r.status===401 || r.status===403) refused[season+':'+league]=1;
        if(!r.ok) return {status:r.status, data:null};
        return r.json().then(function(d){
          return {status:200, data:Array.isArray(d)?(d[0]||null):d};
        });
      });
    });
  }
  // What a Sleeper page may poll while it is open: kept 30 seconds, not the
  // page view, so the next minute's poll reads the next minute's points.
  var MOVING=/\/(matchups|transactions)\/|^\/state\//;
  /** A Sleeper path's JSON (null where Sleeper said no), fetched once. */
  function sleeper(path){
    return once(SLEEPER+path, MOVING.test(path)?30:0, function(){
      return fetch(SLEEPER+path).then(function(r){
        if(!r.ok) return {status:r.status, data:null};
        return r.json().then(function(d){ return {status:200, data:d}; });
      });
    }).then(function(res){
      // A copy each: a page that sorts or annotates what it was handed must
      // not change what the next page is handed.
      return res.status===200 && res.data!=null ? JSON.parse(JSON.stringify(res.data)) : null;
    });
  }
  var BASE=['mSettings','mTeam','mStatus'];

  var ix=null, ids=null;
  /** The player index every reader page shares (GSL.players reads this). */
  function players(){
    return ix||(ix=fetch('/fantasy/players-index.json')
      .then(function(r){ return r.ok?r.json():{}; })
      .catch(function(){ return {}; }));
  }
  function norm(n){
    return String(n||'').toLowerCase()
      .replace(/\b(jr|sr|ii|iii|iv)\b\.?/g,'').replace(/[^a-z]/g,'');
  }
  /** The ESPN -> Sleeper id map, the name fallback, and the index itself. */
  function idMap(){
    return ids||(ids=Promise.all([
      fetch('/fantasy/espn-ids.json').then(function(r){ return r.ok?r.json():{}; })
        .catch(function(){ return {}; }),
      players()
    ]).then(function(o){
      var byName={}, index=o[1]||{};
      Object.keys(index).forEach(function(id){
        var p=index[id]||[], k=norm(p[0])+'|'+(p[1]||'');
        if(!(k in byName)) byName[k]=id;
      });
      return {ids:o[0]||{}, byName:byName, index:index, seen:{}};
    }));
  }

  // ------------------------------------------------------------ translate --
  /** One ESPN player id as the id the pages use. */
  function pid(M, espn, player){
    espn=Number(espn);
    if(M.seen[espn]) return M.seen[espn];
    var id;
    if(espn<0 || (player && player.defaultPositionId===16)){
      var team=(player && player.proTeamId>0) ? player.proTeamId : (-espn-16000);
      id=TEAMS[team]||('e'+espn);
    } else {
      id=M.ids[String(espn)];
      if(!id && player && player.fullName)
        id=M.byName[norm(player.fullName)+'|'+(POS[player.defaultPositionId]||'')];
      id=id||('e'+espn);
    }
    if(player && player.fullName && !M.index[id])
      M.index[id]=[player.fullName, POS[player.defaultPositionId]||'',
                   TEAMS[player.proTeamId]||''];
    if(player) M.seen[espn]=id;
    return id;
  }
  function ppe(e){ return (e && e.playerPoolEntry)||{}; }

  function teamName(t){
    return (t && (t.name || ((t.location||'')+' '+(t.nickname||'')).trim()))
      || ('Team '+(t&&t.id));
  }
  function owner(t){ return t.primaryOwner || (t.owners||[])[0] || ('team-'+t.id); }

  function slotsOf(s){
    var c=((s||{}).rosterSettings||{}).lineupSlotCounts||{}, out=[];
    ORDER.forEach(function(k){ for(var i=0;i<(+c[k]||0);i++) out.push(SLOTS[k]); });
    for(var j=0;j<(+c[BENCH]||0);j++) out.push('BN');
    return out;
  }
  /** Starters in roster_positions order, '0' for a slot left empty. */
  function lineup(entries, positions, M){
    var pool={};
    entries.forEach(function(e){
      var name=SLOTS[e.lineupSlotId];
      if(name) (pool[name]=pool[name]||[]).push(e);
    });
    return positions.filter(function(p){ return p!=='BN'; }).map(function(p){
      var e=(pool[p]||[]).shift();
      return e ? pid(M, e.playerId, ppe(e).player) : '0';
    });
  }
  function scoring(sc){
    var pts={}, custom=false;
    ((sc||{}).scoringItems||[]).forEach(function(i){
      pts[i.statId]=+i.points||0;
      if(i.statId===53 && i.pointsOverrides && Object.keys(i.pointsOverrides).length)
        custom=true;                                       // a TE premium
    });
    var out={rec:pts[53]||0, pass_td:pts[4]!=null?pts[4]:4,
             rec_td:pts[43]!=null?pts[43]:6, rush_td:pts[25]!=null?pts[25]:6,
             pass_yd:pts[3]||0, rush_yd:pts[24]||0, rec_yd:pts[42]||0,
             pass_int:pts[20]||0};
    if(custom || BONUS.some(function(k){ return pts[k]; })) out.bonus_espn=1;
    return out;
  }
  function complete(d, season){
    var st=d.status||{};
    return (+st.latestScoringPeriod||0)>(+st.finalScoringPeriod||99)
      || Date.now()>=Date.UTC(season+1,2,1);   // March: resolve() moves on too
  }
  function leagueOf(d, id){
    var e=parse(id), s=d.settings||{}, st=d.status||{};
    var sch=s.scheduleSettings||{}, acq=s.acquisitionSettings||{};
    var periods=sch.matchupPeriods||{}, reg=+sch.matchupPeriodCount||0;
    var regLast=(periods[reg]||[reg]).reduce(function(a,b){ return Math.max(a,+b); },0);
    var prev=(st.previousSeasons||[]).filter(function(y){ return y<e.season; })
      .sort().pop();
    var fin=+st.finalScoringPeriod||17, latest=+st.latestScoringPeriod||0;
    var dd=d.draftDetail||{}, done=complete(d, e.season);
    var c=(s.rosterSettings||{}).lineupSlotCounts||{};
    // The weeks of each playoff round (bracketOf's r): ESPN's periods can be
    // two weeks long, and a round's score is the sum of its weeks. Sleeper
    // says the same thing with playoff_round_type (0 one week a round, 1 a
    // two-week final, 2 two weeks a round), given here too for a page that
    // reads only that.
    var rw={}, lens=[];
    Object.keys(periods).map(Number).filter(function(k){ return k>reg; })
      .sort(function(x,y){ return x-y; }).forEach(function(k){
        rw[k-reg]=(periods[k]||[k]).map(Number);
        lens.push(rw[k-reg].length);
      });
    var rtype=!lens.length||lens.every(function(n){ return n<2; }) ? 0
      : lens.every(function(n){ return n>=2; }) ? 2
      : (lens[lens.length-1]>=2 && lens.slice(0,-1).every(function(n){ return n<2; })) ? 1 : 0;
    return {league_id:id, provider:'espn', sport:'nfl', season:String(e.season),
      name:s.name||('ESPN league '+e.league),
      status:done?'complete':dd.drafted?'in_season':dd.inProgress?'drafting':'pre_draft',
      total_rosters:(d.teams||[]).length,
      previous_league_id:prev?make(prev, e.league):null, draft_id:id,
      roster_positions:slotsOf(s), scoring_settings:scoring(s.scoringSettings),
      settings:{playoff_week_start:regLast+1, playoff_teams:+sch.playoffTeamCount||0,
        num_teams:(d.teams||[]).length, league_average_match:0,
        leg:done?fin:Math.max(1,Math.min(latest,fin)),
        last_scored_leg:done?fin:Math.max(0,Math.min(latest-1,fin)),
        playoff_round_type:rtype, round_weeks:lens.length?rw:null,
        reserve_slots:+c[IR]||0, taxi_slots:0, type:0,
        waiver_type:acq.isUsingAcquisitionBudget?2:0,
        waiver_budget:+acq.acquisitionBudget||0}};
  }
  function rostersOf(d, id, M, withPlayers){
    var positions=slotsOf(d.settings);
    return (d.teams||[]).map(function(t){
      var ent=withPlayers?((t.roster&&t.roster.entries)||[]):[];
      var rec=(t.record&&t.record.overall)||{};
      var pf=+rec.pointsFor||0, pa=+rec.pointsAgainst||0;
      return {roster_id:t.id, league_id:id, owner_id:owner(t),
        co_owners:(t.owners||[]).slice(1),
        players:ent.map(function(e){ return pid(M, e.playerId, ppe(e).player); }),
        starters:ent.length?lineup(ent, positions, M):[],
        reserve:ent.filter(function(e){ return e.lineupSlotId===IR; })
          .map(function(e){ return pid(M, e.playerId, ppe(e).player); }),
        taxi:[],
        settings:{wins:+rec.wins||0, losses:+rec.losses||0, ties:+rec.ties||0,
          fpts:Math.floor(pf), fpts_decimal:Math.round((pf-Math.floor(pf))*100),
          fpts_against:Math.floor(pa),
          fpts_against_decimal:Math.round((pa-Math.floor(pa))*100),
          waiver_position:+t.waiverRank||0},
        metadata:{team_name:teamName(t)}};
    });
  }
  function usersOf(d){
    var out=[], seen={};
    (d.teams||[]).forEach(function(t){
      var uid=owner(t);
      if(seen[uid]) return;
      seen[uid]=1;
      var m=(d.members||[]).filter(function(x){ return x.id===uid; })[0];
      out.push({user_id:uid, display_name:(m&&m.displayName)||teamName(t),
                metadata:{team_name:teamName(t)}, avatar:null});
    });
    return out;
  }
  function periodOf(periods, wk){
    for(var k in periods)
      if((periods[k]||[]).map(Number).indexOf(wk)>=0) return +k;
    return wk;
  }
  function side(s, mid, wk, single, M, positions){
    var r=s.rosterForCurrentScoringPeriod, by=s.pointsByScoringPeriod||{};
    var pts=(r && r.appliedStatTotal!=null) ? +r.appliedStatTotal
      : by[wk]!=null ? +by[wk] : single ? (+s.totalPoints||0) : 0;
    var ent=(r&&r.entries)||[], players=[], pp={}, ir=[];
    ent.forEach(function(e){
      var id=pid(M, e.playerId, ppe(e).player);
      players.push(id);
      pp[id]=Math.round((+ppe(e).appliedStatTotal||0)*100)/100;
      if(e.lineupSlotId===IR) ir.push(id);
    });
    var starters=ent.length?lineup(ent, positions, M):[];
    var row={roster_id:s.teamId, matchup_id:mid, points:Math.round(pts*100)/100,
      starters:starters, starters_points:starters.map(function(p){ return pp[p]||0; }),
      players:players, players_points:pp, custom_points:null};
    // Who sat on injured reserve that week: ESPN's lineups say, Sleeper's
    // rows do not, so it is there only where there was a lineup to read.
    if(ent.length) row.reserve=ir;
    return row;
  }
  /** Sleeper's /matchups/<wk>: one row per team, a shared matchup_id for the
   *  two sides of a game, null for a bye or a team out of the playoffs. */
  function matchupsOf(d, schedule, wk, M){
    var periods=((d.settings||{}).scheduleSettings||{}).matchupPeriods||{};
    var mp=periodOf(periods, wk), single=(periods[mp]||[1]).length<2;
    var positions=slotsOf(d.settings), out=[], placed={};
    (schedule||[]).filter(function(g){ return +g.matchupPeriodId===mp; })
      .forEach(function(g, i){
        [g.home, g.away].forEach(function(s){
          if(!s) return;
          placed[s.teamId]=1;
          out.push(side(s, g.away?i+1:null, wk, single, M, positions));
        });
      });
    (d.teams||[]).forEach(function(t){
      if(!placed[t.id]) out.push({roster_id:t.id, matchup_id:null, points:0,
        starters:[], starters_points:[], players:[], players_points:{},
        custom_points:null});
    });
    return out;
  }
  /** Sleeper's winners_bracket: r (round), m, t1, t2, w, l and p (1 for the
   *  final, 3 for the third-place game) out of ESPN's playoff tiers. */
  function bracketOf(d, schedule){
    var reg=+(((d.settings||{}).scheduleSettings)||{}).matchupPeriodCount||0;
    var games=(schedule||[]).filter(function(g){
      return +g.matchupPeriodId>reg && g.away && (g.playoffTierType==='WINNERS_BRACKET'
        || g.playoffTierType==='WINNERS_CONSOLATION_LADDER');
    });
    var last=games.reduce(function(a,g){ return Math.max(a,+g.matchupPeriodId); },0);
    var semiLosers={};
    games.forEach(function(g){
      if(+g.matchupPeriodId===last-1 && g.playoffTierType==='WINNERS_BRACKET'
         && g.winner!=='UNDECIDED')
        semiLosers[g.winner==='HOME'?g.away.teamId:g.home.teamId]=1;
    });
    return games.filter(function(g){
      return g.playoffTierType==='WINNERS_BRACKET' || +g.matchupPeriodId===last;
    }).map(function(g, i){
      var h=g.home.teamId, a=g.away.teamId;
      var w=g.winner==='HOME'?h:g.winner==='AWAY'?a:null;
      var o={r:+g.matchupPeriodId-reg, m:i+1, t1:h, t2:a, w:w,
             l:w==null?null:(w===h?a:h)};
      if(+g.matchupPeriodId===last){
        if(g.playoffTierType==='WINNERS_BRACKET') o.p=1;
        else if(semiLosers[h] && semiLosers[a]) o.p=3;
        else o.p=5;
      }
      return o;
    });
  }
  function draftsOf(d, id){
    var s=(d.settings||{}).draftSettings||{}, dd=d.draftDetail||{};
    var picks=dd.picks||[];
    var rounds=picks.reduce(function(a,p){ return Math.max(a,+p.roundId||0); },0);
    return [{draft_id:id, league_id:id, season:String(parse(id).season),
      type:String(s.type||'').toUpperCase()==='AUCTION'?'auction':'snake',
      status:dd.drafted?'complete':dd.inProgress?'drafting':'pre_draft',
      start_time:s.date||null,
      settings:{rounds:rounds||slotsOf(d.settings).length, teams:(d.teams||[]).length}}];
  }
  function picksOf(d, M){
    var order=(((d.settings||{}).draftSettings)||{}).pickOrder||[];
    return (((d.draftDetail||{}).picks)||[]).map(function(p){
      var id=pid(M, p.playerId, null), info=M.index[id]||[];
      var nm=String(info[0]||''), sp=nm.indexOf(' ');
      var meta={first_name:sp>0?nm.slice(0,sp):nm, last_name:sp>0?nm.slice(sp+1):'',
                position:info[1]||'', team:info[2]||''};
      if(p.bidAmount) meta.amount=String(p.bidAmount);
      return {pick_no:p.overallPickNumber, round:p.roundId,
        draft_slot:(order.indexOf(p.teamId)+1)||p.roundPickNumber,
        roster_id:p.teamId, picked_by:p.memberId||null, player_id:id,
        is_keeper:!!p.keeper, metadata:meta};
    });
  }
  function txOf(d, wk, M){
    return ((d.transactions)||[]).filter(function(t){
      return TX[t.type] && +t.scoringPeriodId===wk;
    }).map(function(t){
      var adds={}, drops={}, rids={}, na=0, nd=0;
      (t.items||[]).forEach(function(it){
        var id=pid(M, it.playerId, null);
        if(it.type==='ADD'||it.type==='TRADE'){ adds[id]=it.toTeamId; rids[it.toTeamId]=1; na++; }
        if(it.type==='DROP'||it.type==='TRADE'){ drops[id]=it.fromTeamId; rids[it.fromTeamId]=1; nd++; }
      });
      if(t.teamId) rids[t.teamId]=1;
      delete rids[0];
      return {transaction_id:String(t.id), type:TX[t.type], leg:wk,
        status:t.status==='EXECUTED'?'complete':'failed',
        created:+t.proposedDate||0, status_updated:+(t.processDate||t.proposedDate)||0,
        roster_ids:Object.keys(rids).map(Number), adds:na?adds:null, drops:nd?drops:null,
        settings:t.bidAmount?{waiver_bid:t.bidAmount}:null, creator:t.memberId||null};
    });
  }

  // --------------------------------------------------------------- routes --
  function espn(kind, id, rest, opts){
    var e=parse(id);
    if(!e) return Promise.resolve(null);
    var S=e.season, L=e.league;
    function base(){ return ask(S, L, BASE, '', 300); }
    function schedule(ttl){ return ask(S, L, ['mMatchupScore'], '', ttl||0); }
    function data(res){ return res && res.status===200 ? res.data : null; }
    return Promise.all([idMap(), base()]).then(function(o){
      var M=o[0], d=data(o[1]);
      if(!d) return null;
      if(kind==='draft'){
        if(rest==='/picks') return ask(S, L, ['mDraftDetail'], '', 0).then(function(r){
          var x=data(r); return x?picksOf({settings:d.settings, draftDetail:x.draftDetail}, M):null;
        });
        return rest?null:draftsOf(d, id)[0];
      }
      if(rest==='') return leagueOf(d, id);
      if(rest==='/users') return usersOf(d);
      if(rest==='/drafts') return draftsOf(d, id);
      if(rest==='/losers_bracket') return [];
      if(rest==='/rosters'){
        if(complete(d, S)) return rostersOf(d, id, M, false);
        return ask(S, L, ['mRoster'], '', 120).then(function(r){
          var x=data(r);
          if(!x) return null;
          var byId={};
          (x.teams||[]).forEach(function(t){ byId[t.id]=t.roster; });
          return rostersOf({settings:d.settings, teams:(d.teams||[]).map(function(t){
            var c={}; for(var k in t) c[k]=t[k]; c.roster=byId[t.id]; return c;
          })}, id, M, true);
        });
      }
      if(rest==='/winners_bracket') return schedule(300).then(function(r){
        var x=data(r); return x?bracketOf(d, x.schedule):null;
      });
      var m=/^\/matchups\/(\d{1,2})$/.exec(rest);
      if(m){
        var wk=+m[1], st=d.status||{}, latest=+st.latestScoringPeriod||0, done=complete(d, S);
        // Lineups for this week, last week and next (a page can be a day
        // ahead of ESPN), where a page shows who started - asked again after
        // 45 seconds, for a live page's poll - and for any other week played
        // when the caller asks for them: one request for that week, kept for
        // the page. Every other week, and the weeks further ahead that a
        // season's simulation reads its pairings from, come from the one
        // light schedule request.
        var near=!done && wk>=latest-1 && wk<=latest+1;
        var got=(near || (opts.lineups && (done || wk<=latest)))
          ? ask(S, L, ['mMatchupScore','mScoreboard'], 'scoringPeriodId='+wk, near?45:0)
          : schedule(300);
        return got.then(function(r){
          var x=data(r); return x?matchupsOf(d, x.schedule, wk, M):null;
        });
      }
      m=/^\/transactions\/(\d{1,2})$/.exec(rest);
      if(m) return ask(S, L, ['mTransactions2'], 'scoringPeriodId='+m[1], 120)
        .then(function(r){ var x=data(r); return x?txOf(x, +m[1], M):null; });
      return null;
    });
  }

  /** A Sleeper API path, answered by whichever site the league is on:
   *  the JSON, or null where the site said no (as `r.ok?r.json():null`).
   *  `opts.lineups`: an ESPN week's matchups with who started, for any week
   *  played rather than this week and last only (Sleeper's always have). */
  function get(path, opts){
    var m=/^\/(league|draft)\/([^\/?]+)(\/[^?]*)?$/.exec(path);
    if(m){
      var id=decodeURIComponent(m[2]);
      if(isEspn(id)) return espn(m[1], id, m[3]||'', opts||{});
    }
    return sleeper(path);
  }

  /** {roster id: team name} for a league: what a page that names the teams,
   *  and needs nothing else of the rosters, can have without ESPN's rosters
   *  (every player's stats ride along with them). null if it cannot be read. */
  function teams(id){
    var api='/league/'+encodeURIComponent(id), e=parse(id);
    if(e) return ask(e.season, e.league, BASE, '', 300).then(function(res){
      if(!res || res.status!==200 || !res.data) return null;
      var out={};
      (res.data.teams||[]).forEach(function(t){ out[String(t.id)]=teamName(t); });
      return out;
    });
    return Promise.all([get(api+'/rosters'), get(api+'/users')]).then(function(o){
      if(!o[0]) return null;
      var byUser={}, out={};
      (o[1]||[]).forEach(function(u){
        byUser[u.user_id]=(u.metadata&&u.metadata.team_name)||u.display_name||'';
      });
      o[0].forEach(function(r){
        out[String(r.roster_id)]=byUser[r.owner_id]||('Roster '+r.roster_id);
      });
      return out;
    });
  }

  var PRIVATE='ESPN keeps that league private. Its commissioner can open it '
    +'to the public in the league\u2019s settings (League Manager \u2192 '
    +'Basic Settings), and nothing else is needed \u2014 no ESPN login.';
  function esc(v){
    return String(v==null?'':v).replace(/[&<>"']/g,function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});
  }

  /** Whether ESPN refused this league as private on this page view. */
  function isPrivate(id){
    var e=parse(id);
    return !!(e && refused[e.season+':'+e.league]);
  }
  /** What to tell a reader whose league could not be read, in the words of
   *  the site it is on: ESPN's private-league advice where ESPN refused it,
   *  never "Sleeper may be busy" for a league that is not on Sleeper. */
  function problem(id){
    if(isPrivate(id)) return PRIVATE;
    var site=parse(id)?'ESPN':'Sleeper';
    return 'Could not read that league from '+site+'. '+site
      +' may be busy \u2014 try again in a minute.';
  }

  /** A league saved in another season, drawn as this week, is wrong all
   *  over: last year's rosters, scored against this year's games. null when
   *  `info` (the league, as get('/league/<id>') answers) is `year`'s;
   *  otherwise a note to draw instead, with the way to this season's - a
   *  button for ESPN, whose league keeps its id across seasons, and the bar
   *  above for Sleeper, which issues a new id each year. */
  function otherSeason(info, year, cls){
    var have=+((info||{}).season)||0;
    year=+year||0;
    if(!have || !year || have===year) return null;
    var e=parse(info.league_id), name=(info&&info.name)||'';
    var how=e
      ? '<button type="button" data-gs-season="'+esc(make(year, e.league))+'">Show its '
        +year+' season</button>'
      : 'Pick its '+year+' league in the bar above, or paste that league\u2019s id there.';
    return '<p class="'+esc(cls||'')+'" data-gs-other-season="'+have+'">This is your <b>'
      +have+'</b> league'+(name?' ('+esc(name)+')':'')+', not this season\u2019s, so this '
      +'week is not drawn from it. '+how+'</p>';
  }
  // The button above: this season's id, checked before it is saved.
  if(typeof document!=='undefined') document.addEventListener('click', function(ev){
    var b=ev.target&&ev.target.closest&&ev.target.closest('[data-gs-season]');
    if(!b) return;
    var e=parse(b.getAttribute('data-gs-season'));
    if(!e) return;
    b.disabled=true;
    resolve(e.league, e.season).then(function(res){
      if(res.id){
        try{ localStorage.setItem('gsSleeperLeague',
          JSON.stringify({id:res.id, name:res.name||'', provider:'espn'})); }catch(x){}
        location.reload();
        return;
      }
      b.disabled=false;
      b.insertAdjacentText('afterend', ' '+(res.error==='private' ? PRIVATE
        : res.error==='network' ? 'Could not reach ESPN. Try again in a minute.'
        : 'ESPN has no '+e.season+' season of that league yet.'));
    });
  });

  /** An ESPN league id (and season, if known) as {id, name, season}, or
   *  {error: 'private' | 'missing' | 'network'}. With no season, this one's
   *  is tried and then last year's - a league not yet renewed. */
  function resolve(league, season){
    var now=new Date(), yr=now.getUTCFullYear();
    var cur=now.getUTCMonth()<2?yr-1:yr;
    var tries=season?[season]:[cur, cur-1];
    function next(i){
      if(i>=tries.length) return Promise.resolve({error:'missing'});
      return ask(tries[i], league, BASE, '', 300).then(function(res){
        if(res.status===200 && res.data)
          return {id:make(tries[i], league), season:tries[i],
                  name:(res.data.settings||{}).name||''};
        if(res.status===401 || res.status===403) return {error:'private'};
        return next(i+1);
      }, function(){ return {error:'network'}; });
    }
    return next(0);
  }

  return {get:get, teams:teams, players:players, isEspn:isEspn, parse:parse,
          parseRef:parseRef, resolve:resolve, isPrivate:isPrivate, problem:problem,
          otherSeason:otherSeason, PRIVATE:PRIVATE,
          _espn:{leagueOf:leagueOf, rostersOf:rostersOf, usersOf:usersOf,
                 matchupsOf:matchupsOf, bracketOf:bracketOf, draftsOf:draftsOf,
                 picksOf:picksOf, txOf:txOf, scoring:scoring, slotsOf:slotsOf,
                 idMap:idMap}};
})();
