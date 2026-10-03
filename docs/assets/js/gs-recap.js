/* window.GSRecap: the weekly recap's rules (gordstats.recap, ported).
   Source file, loaded by gordstats.my_recap (CORE_JS_TAG); see gordstats.js_assets. */
window.GSRecap=(function(){
  'use strict';
  // Who may fill each flex a league names is the planner's own table
  // (gordstats.my_team, GSPlan.FLEXES), so the best lineup here is the one
  // the team dashboard would set.
  var OFF={BN:1, IR:1, TAXI:1};

  // ----- Python's formatting ----------------------------------------------- //

  /** format(x, '.<d>f'). toFixed rounds an exact binary tie up, Python to
   *  the even digit - 81.25 is "81.2" there and "81.3" here - and a tie is
   *  what a percentage like 13/16 is. */
  function fixed(x, d){
    x=Number(x);
    var s=x.toFixed(d), exact=Math.abs(x).toFixed(60);
    if(/^50*$/.test(exact.slice(exact.indexOf('.')+1+d))){
      var p=Math.pow(10,d), down=(Math.floor(Math.abs(x)*p)/p).toFixed(d);
      if(+down.charAt(down.length-1)%2===0) s=(x<0?'-':'')+down;
    }
    return s;
  }
  /** round(x, 2). */
  function r2(x){ return +fixed(x,2); }
  /** recap.num: two places, no trailing zeros. */
  function num(x){ return fixed(x,2).replace(/0+$/,'').replace(/\.$/,''); }
  /** html.escape. */
  function esc(v){
    return String(v==null?'':v).replace(/[&<>"']/g,function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#x27;'}[c];});
  }
  function pct1(p){ return fixed(p*100,1); }

  /** Python's max()/min() with a key: the first of the best, never a later
   *  tie - which team an award names turns on it. */
  function pick(list, key, sign){
    var out=null, v=0;
    list.forEach(function(x){
      var k=key(x);
      if(out===null || sign*(k-v)>0){ out=x; v=k; }
    });
    return out;
  }
  function maxBy(list, key){ return pick(list, key, 1); }
  function minBy(list, key){ return pick(list, key, -1); }
  function keyCmp(a, b){ return a<b?-1:a>b?1:0; }

  // ----- a week --------------------------------------------------------------- //

  function total(list){ return list.reduce(function(t,p){ return t+p.pts; },0); }

  /** recap.Side, its figures worked out once. `best` is {id: 1}. */
  function side(key, points, starters, bench, best){
    var started=r2(total(starters));
    // Never under what was started: a player started out of position cannot
    // make a lineup "better than the best".
    var mx=r2(Math.max(total(starters.concat(bench).filter(function(p){
      return best[p.id]; })), started));
    return {key:key, points:points, starters:starters, bench:bench, best:best,
            started:started, max:mx, left:r2(mx-started), pct:mx>0?started/mx:1};
  }

  /** The planner's reading of a league's slots (GSPlan.slots, as the team
   *  dashboard reads them): the first flex-like slot is its `flex`, the rest
   *  go in as further flexes, filled narrowest first. */
  function slotConf(slots){ return window.GSPlan.slots(slots, Object.keys(OFF)); }

  /** Name and position for a rostered id, as my_matchups names him: a
   *  defence is its team code. */
  function card(pid, index){
    if(pid.length<=3 && /^[A-Za-z]+$/.test(pid)) return {name:pid+' D/ST', pos:'DEF'};
    var m=index[pid]||[];
    return {name:m[0]||('Player '+pid), pos:m[1]||''};
  }

  function sideOf(r, ctx, starting, conf, irWeek){
    var key=String(r.roster_id), pts={}, pp=r.players_points||{};
    Object.keys(pp).forEach(function(p){ pts[String(p)]=Number(pp[p]||0); });
    function player(pid, slot){
      var c=card(pid, ctx.index||{});
      return {id:pid, name:c.name, pos:c.pos, pts:pts[pid]||0, slot:slot};
    }
    var starters=[], seen={};
    (r.starters||[]).forEach(function(pid, i){
      pid=String(pid);
      seen[pid]=1;
      if(pid!=='0') starters.push(player(pid, starting[i]||'?'));
    });
    // Who could not have started: injured reserve - that week's where the
    // site says (ESPN), otherwise today's less anyone who scored (see the
    // top of gordstats.my_recap) - and a taxi squad.
    var out={};
    if(irWeek && irWeek[key]) irWeek[key].forEach(function(p){ out[String(p)]=1; });
    else ((ctx.reserve||{})[key]||[]).forEach(function(p){
      if(!pts[String(p)]) out[String(p)]=1; });
    ((ctx.taxi||{})[key]||[]).forEach(function(p){ out[String(p)]=1; });
    var bench=[];
    (r.players||[]).forEach(function(pid){
      pid=String(pid);
      if(seen[pid]||out[pid]) return;
      seen[pid]=1;
      bench.push(player(pid, ''));
    });
    // The best lineup by what each player scored: the dashboard's planner on
    // points instead of projections, nobody locked - except a starter with no
    // position here, who is held where he started rather than dropped, so
    // the rest of the lineup is still judged.
    var value={}, locked=[];
    var players=starters.concat(bench).map(function(p){
      value[p.id]=p.pts;
      if(p.slot && !p.pos) locked.push(p.id);
      return {id:p.id, pos:p.pos, slot:p.slot||'BN'};
    });
    var plan=window.GSPlan(players, conf.counts, value, {}, locked, conf.flex,
                           conf.positions, 'BN', ['IR','TAXI'], conf.more);
    var best={};
    plan.start.forEach(function(id){ best[id]=1; });
    var s=side(key, Number(r.points||0), starters, bench, best);
    s.held=locked.length;
    return s;
  }

  /** One week as a recap.Week, from Sleeper's /matchups/<wk> rows (or GSAPI's
   *  ESPN translation): fantasy.site.recap.build_week, less the projections
   *  and the power moves. `ctx` is {slots, index, teams, reserve, taxi,
   *  median, playoffStart}; `irWeek` {roster id: [ids]} where the site says
   *  who was on injured reserve that week. */
  function build(k, rows, ctx, irWeek){
    var starting=(ctx.slots||[]).filter(function(s){ return !OFF[s]; });
    var conf=slotConf(ctx.slots||[]);
    var by={}, mids=[], held={};
    rows.forEach(function(r){
      held[String(r.roster_id)]=(r.players||[]).map(String);
      if(r.matchup_id==null) return;           // a bye: no game, nothing to award
      var m=String(r.matchup_id);
      if(!by[m]){ by[m]=[]; mids.push(m); }
      by[m].push(r);
    });
    mids.sort(function(a,b){ return a-b; });
    var sides={}, order=[], games=[], unplaced=0;
    mids.forEach(function(m){
      var keys=[];
      by[m].forEach(function(r){
        var s=sideOf(r, ctx, starting, conf, irWeek);
        sides[s.key]=s; order.push(s.key); keys.push(s.key);
        unplaced+=s.held;
        // Every side is named somewhere on the page: one the league's teams
        // do not cover still needs a name, not a thrown error.
        if(ctx.teams && !ctx.teams[s.key]) ctx.teams[s.key]={name:'Roster '+s.key, avatar:''};
      });
      if(keys.length===2) games.push(keys);
    });
    // Sleeper plays the median in the regular season only.
    return {number:k, teams:ctx.teams, games:games, sides:sides, order:order,
            median:!!ctx.median && !(ctx.playoffStart && k>=ctx.playoffStart),
            flex:window.GSPlan.FLEXES, pickups:[], held:held, unplaced:unplaced};
  }

  /** New to a roster this week and not traded for - fantasy.site.recap's rule,
   *  off the rosters, because Sleeper files a Tuesday claim under the week
   *  before. `prev` is the week before's {roster id: [ids]}, null for the
   *  first week, whose pickups are the claims since the draft; `txs` the
   *  transactions of this week and the one before. */
  function pickups(week, prev, txs){
    var traded={}, claimed={};
    txs.forEach(function(t){
      if(t.status!=='complete' || !t.adds) return;
      Object.keys(t.adds).forEach(function(pid){
        var rid=String(t.adds[pid]);
        if(t.type==='trade') traded[rid+'|'+pid]=1;
        else if((t.type==='waiver'||t.type==='free_agent') && +t.leg<=week.number)
          (claimed[rid]=claimed[rid]||{})[pid]=1;
      });
    });
    var out=[];
    week.order.forEach(function(key){
      var s=week.sides[key], all=s.starters.concat(s.bench), fresh={};
      if(prev){
        // A team with no roster the week before (an ESPN bye) is not a team
        // whose every player is new.
        if(!(prev[key]||[]).length) return;
        var had={};
        prev[key].forEach(function(p){ had[String(p)]=1; });
        all.forEach(function(p){ if(!had[p.id] && !traded[key+'|'+p.id]) fresh[p.id]=1; });
      } else fresh=claimed[key]||{};
      var on={};
      s.starters.forEach(function(p){ on[p.id]=1; });
      all.forEach(function(p){ if(fresh[p.id]) out.push({key:key, player:p, started:!!on[p.id]}); });
    });
    return out;
  }

  // ----- the awards: gordstats.recap.awards ------------------------------------ //

  function sidesOf(week){ return week.order.map(function(k){ return week.sides[k]; }); }

  /** recap.results, in its order: [[key, opponent, margin]], a game's two
   *  sides in turn, the margin positive for the winner. */
  function results(week){
    var out=[];
    week.games.forEach(function(g){
      var m=week.sides[g[0]].points-week.sides[g[1]].points;
      out.push([g[0], g[1], m], [g[1], g[0], -m]);
    });
    return out;
  }

  function accepts(slot, pos, flex){
    return slot===pos || ((flex||{})[slot]||[]).indexOf(pos)>=0;
  }
  /** recap.swap: the benched player the best lineup wanted, over a starter
   *  it did not, who could have taken his slot. [benched, started] or null. */
  function swap(s, flex){
    var sat=s.bench.filter(function(p){ return s.best[p.id]; });
    var out=s.starters.filter(function(p){ return !s.best[p.id]; });
    var found=null;
    sat.forEach(function(b){
      out.forEach(function(st){
        if(accepts(st.slot, b.pos, flex) && b.pts>st.pts)
          if(found===null || b.pts-st.pts>found[0]) found=[b.pts-st.pts, b, st];
      });
    });
    return found?[found[1], found[2]]:null;
  }
  function who(p){
    return (p.pos==='DEF'||p.pos==='')?esc(p.name):(esc(p.name)+', '+esc(p.pos));
  }
  function swapLine(pair){
    if(!pair) return '';
    return 'Started '+esc(pair[1].name)+' ('+num(pair[1].pts)+') over '
      +esc(pair[0].name)+' ('+num(pair[0].pts)+')';
  }
  function A(label, key, stat, detail, tone){
    return {label:label, key:key, stat:stat, detail:detail||'', tone:tone||''};
  }

  function awards(week){
    var S=week.sides, T=week.teams, res=results(week), at={};
    res.forEach(function(r){ at[r[0]]=r; });
    var all=sidesOf(week);
    var order=all.slice().sort(function(a,b){ return b.points-a.points; });
    var n=order.length;
    function name(k){ return esc(T[k].name); }
    var out=[];
    var top=order[0], low=order[n-1];
    var lead=maxBy(top.starters, function(p){ return p.pts; });
    out.push(A('High score', top.key, num(top.points),
               lead?('Led by '+esc(lead.name)+', '+num(lead.pts)):'', 'good'));
    out.push(A('Low score', low.key, num(low.points),
               low.left>=5?('Left '+num(low.left)+' on the bench'):((n-1)+' teams scored more'),
               'bad'));

    var decided=res.filter(function(r){ return r[2]>0; });
    if(decided.length){
      var x=maxBy(decided, function(r){ return r[2]; });
      out.push(A('Blowout', x[0], 'by '+num(x[2]),
                 'Over '+name(x[1])+', '+num(S[x[0]].points)+'&ndash;'+num(S[x[1]].points),
                 'good'));
      x=minBy(decided, function(r){ return r[2]; });
      out.push(A('Nail-biter', x[0], 'by '+num(x[2]),
                 'Over '+name(x[1])+', '+num(S[x[0]].points)+'&ndash;'+num(S[x[1]].points)));
      x=minBy(decided, function(r){ return S[r[0]].points; });
      var more=order.filter(function(s){ return s.points>S[x[0]].points; }).length;
      out.push(A('Luckiest win', x[0], num(S[x[0]].points),
                 more+' team'+(more!==1?'s':'')+' scored more &mdash; just not '+name(x[1]),
                 'good'));
      var loser=maxBy(decided.map(function(r){ return r[1]; }),
                      function(o){ return S[o].points; });
      var fewer=order.filter(function(s){ return s.points<S[loser].points; }).length;
      out.push(A('Toughest loss', loser, num(S[loser].points),
                 'Would have beaten '+fewer+' of the other '+(n-1)+' teams', 'bad'));
    }

    // Lost a game the bench would have won: the loser's best lineup beats
    // what the winner actually scored.
    var cost=res.filter(function(r){ return r[2]<0 && S[r[0]].max>S[r[1]].points; })
      .map(function(r){ return [r[0], r[1], S[r[0]].max-S[r[1]].points]; });
    if(cost.length){
      var c=maxBy(cost, function(r){ return r[2]; });
      out.push(A('Cost them the game', c[0], 'lost by '+num(-at[c[0]][2]),
                 'Best lineup: '+num(S[c[0]].max)+'. '+swapLine(swap(S[c[0]], week.flex)),
                 'bad'));
    }

    var byPct=all.slice().sort(function(a,b){ return (b.pct-a.pct)||(b.points-a.points); });
    var best=byPct[0];
    var perfect=byPct.filter(function(s){ return s.left<0.005; })
      .map(function(s){ return s.key; });
    var others=perfect.filter(function(k){ return k!==best.key; }).map(name);
    out.push(A('Best lineup', best.key, pct1(best.pct)+'%',
               perfect.indexOf(best.key)>=0
                 ? ('The best possible lineup'+(others.length?(' &mdash; so did '+others.join(', ')):''))
                 : (num(best.left)+' short of the best possible'),
               'good'));
    var worst=maxBy(all, function(s){ return s.left; });
    if(worst.left>0)
      out.push(A('Most left on the bench', worst.key, num(worst.left),
                 swapLine(swap(worst, week.flex)) || (pct1(worst.pct)+'% of the best lineup'),
                 'bad'));

    // Beat / Missed the projection and the power moves need this site's own
    // archive (see the top of gordstats.my_recap): a reader's league has none.

    var starters=[], benched=[];
    all.forEach(function(s){
      s.starters.forEach(function(p){ starters.push([s.key, p]); });
      s.bench.forEach(function(p){ benched.push([s.key, p]); });
    });
    if(starters.length){
      var t=maxBy(starters, function(x){ return x[1].pts; });
      out.push(A('Player of the week', t[0], num(t[1].pts), who(t[1]), 'good'));
    }
    if(benched.length){
      var b=maxBy(benched, function(x){ return x[1].pts; });
      if(b[1].pts>0)
        out.push(A('Bench star', b[0], num(b[1].pts), who(b[1])+', never left the bench'));
    }
    var started=(week.pickups||[]).filter(function(pk){ return pk.started; });
    if(started.length){
      var pk=maxBy(started, function(x){ return x.player.pts; });
      out.push(A('Pickup of the week', pk.key, num(pk.player.pts),
                 who(pk.player)+', added '+(week.number===1?'since the draft':'this week'),
                 'good'));
    }
    return out;
  }

  /** recap.headline: one plain sentence. */
  function headline(week){
    var S=week.sides, T=week.teams, all=sidesOf(week);
    var top=maxBy(all, function(s){ return s.points; });
    var parts=[T[top.key].name+' top-scored with '+num(top.points)];
    var worst=maxBy(all, function(s){ return s.left; });
    if(worst.left>=1) parts.push(T[worst.key].name+' left '+num(worst.left)+' on the bench');
    var lost=results(week).filter(function(r){ return r[2]<0 && S[r[0]].max>S[r[1]].points; });
    if(lost.length)
      parts.push(lost.length+' team'+(lost.length===1?' was':'s were')+' beaten by their own bench');
    var text=parts.length===1?parts[0]
      :parts.slice(0,-1).join(', ')+' and '+parts[parts.length-1];
    return 'Week '+week.number+': '+text+'.';
  }

  /** recap.season: lineup accuracy to date, best first. */
  function season(weeks){
    var rows={}, keys=[];
    weeks.forEach(function(w){
      w.order.forEach(function(k){
        var s=w.sides[k], r=rows[k];
        if(!r){ r=rows[k]={key:k, started:0, max:0, perfect:0, weeks:0}; keys.push(k); }
        r.started+=s.started; r.max+=s.max; r.weeks+=1;
        r.perfect+=(s.left<0.005)?1:0;
      });
    });
    return keys.map(function(k){
      var r=rows[k];
      r.pct=r.max>0?r.started/r.max:1;
      r.left=r2(r.max-r.started);
      return r;
    }).sort(function(a,b){ return (b.pct-a.pct)||keyCmp(a.key, b.key); });
  }

  // ----- the markup: gordstats.recap's, cell for cell ---------------------------- //

  function avatar(t){
    if(!t.avatar) return '<span class="rc-av"></span>';
    return '<img class="rc-av" src="'+esc(t.avatar)+'" alt="" width="22" '
      +'height="22" loading="lazy">';
  }
  function q(p){
    return p>=0.995?'q5':p>=0.95?'q4':p>=0.9?'q3':p>=0.85?'q2':'q1';
  }
  function median(week){
    var v=sidesOf(week).map(function(s){ return s.points; }).sort(function(a,b){ return a-b; });
    var n=v.length, h=Math.floor(n/2);
    return n%2?v[h]:(v[h-1]+v[h])/2;
  }

  function games(week){
    var S=week.sides, T=week.teams;
    var med=week.median?median(week):null;
    var out=week.games.map(function(g){
      var sa=S[g[0]], sb=S[g[1]];
      function one(s, won){
        var chip='';
        if(med!==null){
          var up=s.points>med;
          chip='<span class="rc-med '+(up?'w':'l')+'" title="Against the median, '+num(med)
            +'">Med '+(up?'W':'L')+'</span>';
        }
        return '<div class="rc-side'+(won?' w':'')+'">'+avatar(T[s.key])
          +'<span class="nm">'+esc(T[s.key].name)+'</span>'+chip
          +'<span class="sc">'+num(s.points)+'</span></div>';
      }
      return '<div class="rc-game">'+one(sa, sa.points>sb.points)+one(sb, sb.points>sa.points)
        +'<div class="rc-meta">by '+num(Math.abs(sa.points-sb.points))+' &middot; best lineups '
        +num(sa.max)+' / '+num(sb.max)+'</div></div>';
    });
    var note=med!==null
      ? ('<p class="rc-note">The winner of each game is in bold. <b>Med W</b> / '
         +'<b>Med L</b> is each team\'s second game, against the week\'s median ('
         +num(med)+').</p>')
      : '';
    return '<div class="rc-games">'+out.join('')+'</div>'+note;
  }

  function awardCards(week){
    var T=week.teams;
    return '<div class="rc-awards">'+awards(week).map(function(a){
      return '<div class="rc-award '+a.tone+'"><div class="lb">'+a.label+'</div>'
        +'<div class="row">'+avatar(T[a.key])+'<span class="tm">'+esc(T[a.key].name)
        +'</span><span class="st">'+a.stat+'</span></div>'
        +(a.detail?'<div class="dt">'+a.detail+'</div>':'')+'</div>';
    }).join('')+'</div>';
  }

  /** The table, to date. With `toDate` null the season is not in yet: the
   *  week's own order, and the season cells waiting (o.pending) or empty. */
  function accuracy(week, toDate, o){
    o=o||{};
    var T=week.teams, S=week.sides;
    var list=toDate||sidesOf(week).slice()
      .sort(function(a,b){ return (b.pct-a.pct)||keyCmp(a.key, b.key); });
    function wait(pf){
      return o.pending
        ? '<td class="'+(pf?'pf ':'')+'rc-wait" title="Reading the season">&hellip;</td>'
        : '<td'+(pf?' class="pf"':'')+'>&ndash;</td>';
    }
    var rows=list.map(function(r){
      var s=S[r.key];
      var wk=s?('<td class="'+q(s.pct)+'">'+pct1(s.pct)+'%</td><td>'+num(s.left)+'</td>')
        :'<td>&ndash;</td><td>&ndash;</td>';
      var yours=o.mine!=null && String(o.mine)===r.key;
      var season=toDate
        ? ('<td class="'+q(r.pct)+'">'+pct1(r.pct)+'%</td><td>'+num(r.left)+'</td>'
           +'<td class="pf">'+r.perfect+'</td>')
        : wait(false)+wait(false)+wait(true);
      return '<tr'+(yours?' class="rc-me" title="Your team"':'')+'><td><span class="tmw">'
        +avatar(T[r.key])+'<span>'+esc(T[r.key].name)+'</span></span></td>'+wk+season+'</tr>';
    });
    return '<div class="rc-wrap"><table class="rc-acc"><thead><tr><th>Team</th>'
      +'<th>Wk '+week.number+'</th><th>Left</th><th>Season</th><th>Left</th>'
      +'<th class="pf" title="Weeks with the best possible lineup">Perfect</th></tr></thead><tbody>'
      +rows.join('')+'</tbody></table></div>'
      +'<p class="rc-note">Share of the best possible lineup each team started: points '
      +'started over the most its roster could have scored that week, by what every '
      +'player actually scored (injured reserve left out). <b>Left</b> is the '
      +'difference - points left on the bench. The season figure is total points over '
      +'total maximum.'
      +(toDate?'':o.pending?' The season columns fill in as the earlier weeks are read.'
                :' Not every earlier week could be read, so there is no season figure.')
      +'</p>';
  }

  /** The week chips. Links to this page's own #week-N, so the address says
   *  which week is on screen and the back button steps through them. */
  function weekNav(numbers, current){
    return '<nav class="rc-weeks" aria-label="Week">'+numbers.map(function(n){
      return n===current?('<span>'+n+'</span>'):('<a href="#week-'+n+'">'+n+'</a>');
    }).join('')+'</nav>';
  }

  /** One week's recap - recap.page, less the share button, which the page
   *  adds (its address is the reader's league's, not this site's week). */
  function view(week, numbers, toDate, o){
    o=o||{};
    return '<p class="rc-lead">'+esc(headline(week))+'</p>'
      +weekNav(numbers, week.number)
      +'<h2>Scores</h2>'+games(week)
      +'<h2>Awards</h2>'+awardCards(week)
      +'<h2>Lineup accuracy</h2>'+accuracy(week, toDate, o)
      +(o.foot||'');
  }

  return {fixed:fixed, num:num, esc:esc, side:side, slotConf:slotConf,
          build:build, pickups:pickups, awards:awards, headline:headline, season:season,
          games:games, awardCards:awardCards, accuracy:accuracy, weekNav:weekNav,
          view:view};
})();
