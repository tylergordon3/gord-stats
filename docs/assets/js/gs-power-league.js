/* window.GSPowerLeague: a league read into the simulation's terms.
   Source file, loaded by gordstats.my_power (LEAGUE_JS_TAG); see gordstats.js_assets. */
window.GSPowerLeague = (function(){
  var DEFAULT_WEEKS=14;

  function get(path){
    return GSAPI.get(path).catch(function(){ return null; });
  }

  /** Every regular week's pairings, and the scores of the ones already played.
   *
   * A week counts as played only when every roster has a score - part of a
   * week is worse than none of it, because the teams still to play would be
   * simulated as having been shut out.
   */
  function season(id, weeks, order){
    var want=[];
    for(var w=1; w<=weeks; w++) want.push(w);
    return Promise.all(want.map(function(w){
      return get('/league/'+id+'/matchups/'+w).then(function(rows){
        return {week:w, rows:rows||[]};
      });
    })).then(function(all){
      var index={};
      order.forEach(function(rid, i){ index[String(rid)]=i; });
      var schedule=[], scores=[], played=0, stop=false;
      all.sort(function(a,b){ return a.week-b.week; });
      all.forEach(function(wk){
        var pairs=new Array(order.length), by={}, week=new Array(order.length);
        var complete=wk.rows.length===order.length;
        wk.rows.forEach(function(r){
          var seat=index[String(r.roster_id)];
          if(seat==null) return;
          var mid=r.matchup_id==null?null:String(r.matchup_id);
          if(mid!=null) (by[mid]=by[mid]||[]).push(seat);
          week[seat]=typeof r.points==='number'?r.points:0;
          if(!(r.points>0)) complete=false;
        });
        for(var k in by){
          var pair=by[k];
          if(pair.length===2){ pairs[pair[0]]=pair[1]; pairs[pair[1]]=pair[0]; }
        }
        for(var i=0;i<pairs.length;i++) if(pairs[i]==null) pairs[i]=-1;
        schedule.push(pairs);
        if(complete && !stop){ scores.push(week); played++; } else { stop=true; }
      });
      var any=schedule.some(function(row){
        return row.some(function(v){ return v>=0; }); });
      return {schedule:any?schedule:null, actual:scores, played:played};
    });
  }

  /** [[seat, ...] per round]: who Sleeper's winners bracket says lost each
   *  round already decided, seats indexed by `order` - or null before any.
   *  Only elimination games: a team is out from the round after its first
   *  loss, and a game with an out team in it is a placement game (third,
   *  fifth) and is not read. fantasy.league.power.bracket_losers, here. */
  function losers(rows, order){
    var index={}, out={}, rounds={}, res=[];
    order.forEach(function(rid, i){ index[String(rid)]=i; });
    (rows||[]).forEach(function(m){ if(m&&m.r!=null) rounds[+m.r]=1; });
    Object.keys(rounds).map(Number).sort(function(a,b){ return a-b; }).forEach(function(r){
      var lost=[];
      rows.forEach(function(m){
        if(!m||m.r==null||+m.r!==r) return;
        if(typeof m.t1!=='number'||typeof m.t2!=='number') return;
        if(out[m.t1]||out[m.t2]||m.w==null||m.l==null) return;
        lost.push(m.l);
      });
      lost.forEach(function(l){ out[l]=1; });
      res.push(lost.map(function(l){ return index[String(l)]; })
        .filter(function(v){ return v!=null; }));
    });
    return res.some(function(x){ return x.length; })?res:null;
  }

  /** Weeks each of `rounds` playoff rounds lasts, in round order, from the
   *  league's settings. Sleeper's playoff_round_type: 0 one week a round, 1
   *  a two-week final, 2 two weeks every round (2020 called that last one 1,
   *  as gs-history's roundWeeks has it) - checked against real leagues'
   *  brackets, where a two-week round goes to the higher two-week total. An
   *  ESPN league (GSAPI) gives its matchup periods instead, as round_weeks
   *  {round: [weeks]}. */
  function roundLengths(info, rounds){
    var s=(info&&info.settings)||{}, rw=s.round_weeks, out=[];
    var type=+s.playoff_round_type||0;
    if(String(info&&info.season)==='2020' && type===1) type=2;
    for(var r=1; r<=rounds; r++){
      var n=rw ? ((rw[r]||rw[String(r)]||[]).length||1)
        : (type===2 || (type===1 && r===rounds)) ? 2 : 1;
      out.push(n);
    }
    return out;
  }

  /** The playoffs as far as they have gone, once the regular season is in:
   *  {actual: each playoff week Sleeper has scored, a score per seat (0 for a
   *  team not playing), decided: losers(winners_bracket)}. `weeks` is how
   *  many weeks the bracket takes - more than its rounds where a round is
   *  two weeks long. */
  function playoffs(id, first, weeks, scored, order){
    var want=[];
    for(var w=first; w<first+weeks && w<=scored; w++) want.push(w);
    var index={};
    order.forEach(function(rid, i){ index[String(rid)]=i; });
    return Promise.all(want.map(function(w){
      return get('/league/'+id+'/matchups/'+w);
    }).concat([get('/league/'+id+'/winners_bracket')])).then(function(all){
      var bracket=all.pop();
      var actual=all.map(function(rows){
        var week=order.map(function(){ return 0; });
        (rows||[]).forEach(function(r){
          var seat=index[String(r.roster_id)];
          if(seat!=null&&typeof r.points==='number') week[seat]=r.points;
        });
        return week;
      });
      return {actual:actual, decided:losers(bracket||[], order)};
    });
  }

  // The Workers running in each lane (see simulate).
  var lanes={};

  /** Stop every run in `lane`: each promise rejects with "superseded". */
  function stop(lane){
    (lanes[lane]||[]).slice().forEach(function(job){ job.stop(); });
  }

  /** Run the simulation in a Worker built from its own <script> element -
   *  its file (gs-power-sim.js, already in the cache) when the page loads it
   *  by src, its text when it is inline - falling back to the main thread if
   *  there is no Worker to be had.
   *
   *  `lane`, when given, files the run under a name that stop(lane) can end:
   *  a reader tapping through deals should not leave a Worker grinding on
   *  every deal passed over. Runs without one are left alone. */
  function simulate(spec, lane){
    return new Promise(function(resolve, reject){
      var src=document.getElementById('gs-power-sim');
      var url=null, worker=null;
      try{
        if(src.src) worker=new Worker(src.src);
        else {
          url=URL.createObjectURL(new Blob([src.textContent], {type:'text/javascript'}));
          worker=new Worker(url);
        }
      }catch(e){
        if(url) URL.revokeObjectURL(url);
        try{ return resolve(window.GSPower.run(spec)); }
        catch(err){ return reject(err); }
      }
      var job={};
      function done(){
        worker.terminate(); if(url) URL.revokeObjectURL(url);
        if(lane&&lanes[lane]){
          var at=lanes[lane].indexOf(job);
          if(at>=0) lanes[lane].splice(at, 1);
        }
      }
      job.stop=function(){ done(); reject(new Error('superseded')); };
      if(lane) (lanes[lane]=lanes[lane]||[]).push(job);
      worker.onmessage=function(ev){
        done();
        if(ev.data&&ev.data.ok) resolve(ev.data.result);
        else reject(new Error((ev.data&&ev.data.error)||'the simulation failed'));
      };
      worker.onerror=function(){
        done();
        try{ resolve(window.GSPower.run(spec)); }
        catch(err){ reject(err); }
      };
      worker.postMessage(spec);
    });
  }

  /** One league read into a simulation spec: {league, board, order, weeks,
   *  played, run, spec}. The caller sets `sims` and anything else it needs.
   *
   *  `year` is the season the page is for (the board's, when not given). A
   *  league saved in another season is rejected with Error('other-season'),
   *  carrying `info` and `year` for GSAPI.otherSeason to word: last season's
   *  rosters and schedule played out on this season's board are no season at
   *  all. Checked before the rosters, which ESPN does not send for a season
   *  that is over. */
  function setup(id, year){
    return Promise.all([
      GSL.league(id),
      fetch('/fantasy/season-board.json').then(function(r){
        return r.ok?r.json():null; }).catch(function(){ return null; })
    ]).then(function(o){
      var league=o[0], board=o[1];
      if(!board||!board.board) throw new Error('board');
      var want=+year||+board.year||0;
      if(league&&window.GSAPI&&GSAPI.otherSeason&&GSAPI.otherSeason(league.info, want)){
        var other=new Error('other-season');
        other.info=league.info; other.year=want;
        throw other;
      }
      if(!league||!league.rosters.length) throw new Error('league');
      // Rosters and nobody on them: the league has not drafted. Simulated, it
      // read as roster 1 winning every title on an empty lineup.
      if(!league.rosters.some(function(r){ return (r.players||[]).length; }))
        throw new Error('undrafted');
      var settings=(league.info&&league.info.settings)||{};
      var weeks=Math.max((settings.playoff_week_start||(DEFAULT_WEEKS+1))-1, 1);
      var order=league.rosters.map(function(r){ return r.roster_id; })
        .sort(function(a,b){ return a-b; });
      var byId={};
      league.rosters.forEach(function(r){ byId[String(r.roster_id)]=r; });
      var rosters=order.map(function(rid){
        return {roster_id:rid, players:(byId[String(rid)].players)||[]};
      });
      return season(id, weeks, order).then(function(run){
        // Sleeper has the scores and the board has absorbed them into form;
        // the lesser of the two (and of Sleeper's own last scored week) keeps
        // a week from being counted as played by one and projected by the
        // other - the rule fantasy.league.power.rankings follows.
        var scored=typeof settings.last_scored_leg==='number'?settings.last_scored_leg:weeks;
        var played=Math.min(run.played, board.week||0, weeks, scored);
        var field=Math.min(Math.max(settings.playoff_teams||6, 2), order.length);
        var rounds=0;
        while((1<<rounds)<field) rounds++;
        var lens=roundLengths(league.info, rounds);
        var spec={board:board.board, posNames:board.pos, rosters:rosters,
                  slots:league.slots, basis:league.basis.index, weeks:weeks,
                  playoffTeams:settings.playoff_teams||6,
                  // playoff_seed_type 1 (Sleeper's; GSAPI maps ESPN's
                  // playoffReseed to it): the bracket is redrawn every
                  // round, best seed left against worst left.
                  reseed:+settings.playoff_seed_type===1,
                  // Two-week rounds are won on both weeks together.
                  roundWeeks:lens,
                  // The board's holds count from its own week.
                  holdWeek:board.week||0,
                  median:!!settings.league_average_match,
                  schedule:run.schedule,
                  actual:run.actual.slice(0, played),
                  sims:2000, seed:20260821};
        var out={league:league, board:board, order:order, weeks:weeks,
                 played:played, run:run, spec:spec};
        if(played<weeks) return out;
        // The regular season is in: the playoff weeks played are taken as
        // they happened, and the rounds Sleeper has settled as it settled
        // them - a team knocked out stops holding title odds.
        var span=lens.reduce(function(a, b){ return a+b; }, 0);
        return playoffs(id, weeks+1, span, scored, order)
          .then(function(p){
            spec.playoffActual=p.actual;
            spec.decided=p.decided;
            return out;
          }, function(){ return out; });
      });
    });
  }

  return {season:season, simulate:simulate, stop:stop, setup:setup, losers:losers,
          playoffs:playoffs, roundLengths:roundLengths};
})();
