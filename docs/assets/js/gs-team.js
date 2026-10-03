/* "Your team this week" on /fantasy/roster/, for a reader's league.
   Source file, loaded by gordstats.my_team (VIEW_JS_TAG); see gordstats.js_assets. */
(function(){
  var host=document.getElementById('mt-host');
  if(!host||!window.GSL||!window.GSPlan) return;
  var built=document.getElementById('mt-built');
  var have=GSL.saved();
  if(!have||!have.id||have.site) return;        // the built league is the default

  var BENCH='BN', RESERVE=['IR','IL','TAXI'];
  var ADDS_SHOWN=8, MIN_GAIN=0.5;   // the built page's numbers
  // Sleeper's own words for a player who will not play.
  var OUT={'Out':1,'Doubtful':1,'IR':1,'PUP':1,'NA':1,'Sus':1,'DNR':1,'COV':1};

  function esc(s){
    return String(s==null?'':s).replace(/[&<>"']/g,function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});
  }
  function num(v){ return (v==null||isNaN(v))?'-':(Math.round(v*10)/10).toFixed(1); }

  // Every flex-like slot the league has (GSPlan.slots): the first is the
  // planner's `flex`, the rest go in as further flexes.
  function slotCounts(slots){ return GSPlan.slots(slots, [BENCH].concat(RESERVE)); }

  /** Where each player sits now, from the roster's starters array. */
  function current(roster, slots){
    var out={}, starters=roster.starters||[];
    var i=0;
    slots.forEach(function(s){
      if(s===BENCH||RESERVE.indexOf(s)>=0) return;
      var pid=starters[i++];
      if(pid&&pid!=='0') out[String(pid)]=s;
    });
    (roster.players||[]).forEach(function(p){
      if(!out[String(p)]) out[String(p)]=BENCH;
    });
    (roster.reserve||[]).forEach(function(p){ out[String(p)]='IR'; });
    // A dynasty taxi squad cannot start either; unmapped, it read as bench.
    (roster.taxi||[]).forEach(function(p){ out[String(p)]='TAXI'; });
    return out;
  }

  /** Free agents who project past someone this roster would start.
   *
   *  Same rule as the built page: each is set against the weakest unlocked
   *  starter in a slot he could take, and the gain is what the lineup total
   *  would move by. A player on a bye, already playing, or ruled out is not an
   *  add - which is why the injury status ships with the projections.
   */
  function adds(lg, wk, index, players, out, proj, kick, now, conf){
    var starters=players.filter(function(p){
      return out.start.indexOf(p.id)>=0 && kick[p.id]!=null && kick[p.id]>now;
    });
    if(!starters.length) return '';

    var found=[];
    for(var pid in wk.proj){
      if(lg.held[pid]) continue;                       // somebody in this league has him
      var row=wk.proj[pid];
      if(OUT[row[4]]) continue;
      if(kick[pid]==null || kick[pid]<=now) continue;  // bye, or already playing
      var value=proj[pid];
      if(!value || value<=0) continue;
      var meta=index[pid]; if(!meta) continue;
      var pos=meta[1];
      var rivals=starters.filter(function(s){
        return s.pos===pos
          || (conf.eligible[out.slot[s.id]]||[]).indexOf(pos)>=0;
      });
      if(!rivals.length) continue;
      var worst=rivals.reduce(function(a,b){
        return (proj[a.id]||0)<=(proj[b.id]||0)?a:b;});
      var gain=value-(proj[worst.id]||0);
      if(gain>=MIN_GAIN) found.push({pid:pid, name:meta[0], pos:pos, value:value,
                                     worst:worst, gain:gain});
    }
    if(!found.length){
      return '<h2>Waiver adds</h2><p class="mt-none">Nobody unrostered in your '
        + 'league projects to outscore a starter this week.</p>';
    }
    found.sort(function(a,b){ return b.gain-a.gain; });

    var html='<h2>Waiver adds</h2><table class="mt-t"><thead><tr><th>Add</th>'
      +'<th style="text-align:right">Proj</th><th>Would start over</th>'
      +'<th style="text-align:right">Gain</th></tr></thead><tbody>';
    found.slice(0, ADDS_SHOWN).forEach(function(f){
      html+='<tr><td class="nm">'+esc(f.name)+'<span class="mt-pos">'+esc(f.pos)
        +'</span></td><td class="n">'+num(f.value)+'</td>'
        +'<td>'+esc(f.worst.name)+' <span class="mt-pos">'+num(proj[f.worst.id])+'</span></td>'
        +'<td class="n" style="color:#15803d">+'+num(f.gain)+'</td></tr>';
    });
    return html+'</tbody></table>';
  }

  function render(lg, wk, index, rosterId, ctx, live){
    var roster=lg.rosters.filter(function(r){return String(r.roster_id)===String(rosterId);})[0];
    if(!roster){ host.innerHTML='<p class="mt-none">No roster.</p>'; return; }

    var W=window.GSWeek;
    var conf=slotCounts(lg.slots);
    conf.ctx=ctx; conf.pts=(live&&live[String(rosterId)])||{};
    var here=current(roster, lg.slots);
    // Sleeper's points so far for everyone in the league: a Questionable
    // player who has scored has played, and his chance of playing is spent.
    var seen={};
    Object.keys(live||{}).forEach(function(r){
      var pp=live[r]||{};
      for(var k in pp) seen[k]=pp[k];
    });
    var sleeper=GSL.points(wk, lg.basis.index, seen);
    conf.sleeper=sleeper;
    var kick=GSL.kickoffs(wk);
    var now=Date.now();

    var players=(roster.players||[]).map(function(p){
      var pid=String(p), meta=index[pid]||['Player '+pid,''];
      var row=(wk.proj||{})[pid]||[];
      return {id:pid, pos:meta[1]||'', slot:here[pid]||BENCH, name:meta[0],
              team:row[3]||'', injury:row[4]||''};
    });
    var byId={};
    players.forEach(function(p){ byId[p.id]=p; });

    // The Proj column is the built page's blend - the mean of the sources that
    // have him - not Sleeper's number alone. See gordstats.my_week for why
    // there are fewer sources here than on the built page.
    var proj={};
    players.forEach(function(p){
      var v=W.projFor(ctx,p.id,p.team,sleeper[p.id]);
      proj[p.id]=v==null?0:v;
    });
    var locked=players.filter(function(p){
      return kick[p.id]!=null && kick[p.id]<=now;
    }).map(function(p){return p.id;});

    var out=GSPlan(players, conf.counts, proj, kick, locked,
                   conf.flex, conf.positions, BENCH, RESERVE, conf.more);

    // Order: starting slots as the league lists them, then the bench.
    var order=[], seen={};
    lg.slots.forEach(function(s){ if(s!==BENCH&&RESERVE.indexOf(s)<0&&!seen[s]){seen[s]=1;order.push(s);} });
    order.push(BENCH);
    var rows=[];
    order.forEach(function(s){
      players.filter(function(p){return out.slot[p.id]===s;})
        .sort(function(a,b){return (proj[b.id]||0)-(proj[a.id]||0);})
        .forEach(function(p){ rows.push({p:p, slot:s}); });
    });

    var moves=players.filter(function(p){ return out.slot[p.id]!==p.slot; });
    var total=players.filter(function(p){return out.start.indexOf(p.id)>=0;})
      .reduce(function(t,p){return t+(proj[p.id]||0);},0);
    var nowTotal=players.filter(function(p){
      return p.slot!==BENCH && RESERVE.indexOf(p.slot)<0;
    }).reduce(function(t,p){return t+(proj[p.id]||0);},0);

    var html='';
    if(moves.length){
      var gain=total-nowTotal;
      html+='<div class="mt-swap"><b>'+moves.length+' change'
        +(moves.length===1?'':'s')+'</b> to your lineup, worth <b>'
        +(gain>0?'+':'')+num(gain)+'</b> projected'
        +(lg.basis.custom?' (approximate — see below)':'')+'.</div>';
    } else {
      html+='<p class="mt-none">Your lineup already matches the recommendation.</p>';
    }

    // The built page's table, cell for cell - see gordstats.my_week. Its
    // classes are already in the stylesheet on this page, so matching the
    // format is a matter of emitting the same markup.
    //
    // `rd`, inside `rd-desk rd-scroll`, because that is what the built page
    // emits and what the stylesheet is written against. It used to say
    // `rd-t sticky-table`, which matches nothing on this page: the table fell
    // back to the theme's default, every team logo rendered as a framed
    // thumbnail the height of a row, and the names were pushed out of sight.
    var W=window.GSWeek, ctx=conf.ctx||W.blank();
    html+=W.legend();
    html+='<div class="rd-desk rd-scroll"><table class="rd"><thead><tr>'
      +"<th title='Where he belongs this week'>Slot</th>"
      +"<th title='What it takes to get him there'>Change</th>"
      +'<th>Player</th><th>Game</th>'
      +"<th title='His team’s implied points from the spread and total; for a "
      +"defence, what it is expected to allow'>Team total</th>"
      +"<th title='What the opposing defence has allowed to this position against "
      +"the league average. 1.00 is par; rank 1 is the toughest.'>Opp vs pos</th>"
      +'<th>Weather</th><th>Proj</th><th>GS</th><th>Sleeper</th><th>Pts</th>'
      +"<th title='The best bench player who could still take his place'>Late-swap cover</th>"
      +'</tr></thead><tbody>';
    var benched=false, cards=[];
    rows.forEach(function(r){
      var p=r.p, bench=r.slot===BENCH||RESERVE.indexOf(r.slot)>=0;
      var split=(bench&&!benched)?' rd-split':''; benched=benched||bench;
      var kind=p.slot===r.slot?'':(bench?'out':(p.slot===BENCH||RESERVE.indexOf(p.slot)>=0?'in':'swap'));
      var g=W.gameFor(ctx,p.team), isLocked=locked.indexOf(p.id)>=0;
      var cover=(out.cover||{})[p.id];
      var coverTd;
      if(bench||cover==null){ coverTd='<td class="rd-cov none">&mdash;</td>'; }
      else if(cover.length){
        var c=byId[cover[0]], cg=W.gameFor(ctx,c.team);
        coverTd='<td class="rd-cov">'+esc(c.name)+' <span class="rd-lbl">'
          +W.fmt(proj[cover[0]])+' &middot; '+W.when(cg)+'</span></td>';
      } else {
        coverTd='<td class="rd-cov '+(p.injury?'warn':'none')+'">nobody later</td>';
      }
      var scored=(conf.pts||{})[p.id];
      var done=g&&g.state==='post';
      // The same player for the phone view, which is the same information in
      // the layout that fits a phone.
      var card=W.cardInfo(ctx, p, proj[p.id], done&&scored!=null?'spent':'proj');
      card.id=p.id; card.slot=p.slot; card['new']=r.slot;
      card.kind=kind; card.locked=isLocked; card.done=!!done;
      cards.push(card);
      html+='<tr class="'+(bench?'rd-bn':'rd-st')+split+(kind?' rd-'+kind:'')
        +(done?' rd-done':'')+'">'
        +'<td class="rd-slot">'+esc(r.slot)+'</td>'
        +W.moveCell(kind,p.slot)
        +W.playerCell(p, isLocked?'<span class="rd-tag lock">locked</span>':'')
        +'<td class="rd-g">'+W.gameCell(g)+'</td>'
        +W.totalCell(g,p.pos)+W.oppCell(ctx,g,p.pos)+W.wxCell(ctx,g)
        +(done&&scored!=null
          ? "<td class='rd-spent' title='His game is over; the points column is what "
            +"he actually scored'>"+W.fmt(proj[p.id])+'</td>'
          : '<td><b>'+W.fmt(proj[p.id])+'</b></td>')
        +'<td>'+W.fmt(ctx.gs&&ctx.gs[p.id])+'</td>'
        +'<td>'+W.fmt(conf.sleeper&&conf.sleeper[p.id])+'</td>'
        +'<td>'+((g&&(g.state==='in'||g.state==='post')&&scored!=null)?W.fmt(scored):'&mdash;')+'</td>'
        +coverTd+'</tr>';
    });
    html+='</tbody></table></div>';
    // Below 760px the table is display:none and this takes its place. The
    // table is the lineup to set; the cards are handed over in the order the
    // roster is set in, because the toggle's Current side shows exactly that
    // and phoneLineup re-sorts its own Suggested side.
    var slotRank={};
    order.forEach(function(s,i){ slotRank[s]=i; });
    RESERVE.forEach(function(s){ slotRank[s]=order.length+1; });
    var curOrder={};
    (roster.starters||[]).forEach(function(pid,i){ curOrder[String(pid)]=i; });
    (roster.players||[]).forEach(function(pid,i){
      var key=String(pid);
      if(curOrder[key]==null) curOrder[key]=1000+i;          // the bench, after
    });
    cards.sort(function(a,b){ return (curOrder[a.id]||0)-(curOrder[b.id]||0); });
    html+=W.phoneLineup(cards, slotRank, [BENCH].concat(RESERVE), nowTotal, total);
    html+=adds(lg, wk, index, players, out, proj, kick, now, conf);
    host.innerHTML=html
      +'<p class="mt-note">Scoring read from your league: <b>'+esc(lg.basis.name)+'</b>.'
      +(lg.basis.custom
        ? ' <span class="mt-warn">Your league also scores something this site does not '
          +'publish a basis for (a six-point passing touchdown, or a bonus), so these '
          +'are the nearest of the three rather than exact.</span>'
        : '')
      +' A player whose game has started is locked where he is.</p>';
  }

  function start(){
    host.innerHTML='<p class="mt-note">Reading '+esc(have.name||'your league')+'\u2026</p>';
    if(built) built.hidden=true;
    Promise.all([GSL.league(have.id), GSL.week(), GSL.players(),
                 window.GSWeek.load()])
      .then(function(o){
        var lg=o[0], wk=o[1], index=o[2], ctx=o[3]||window.GSWeek.blank();
        // Another week's context is none: its byes are not this week's.
        if(ctx.week && wk.week && +ctx.week!==+wk.week) ctx=window.GSWeek.blank();
        // What everyone has actually scored this week, so the Pts column and
        // the finished-game rule have something to read. Its own request
        // because nothing else here needs it, and a failure costs one column.
        return GSAPI.get('/league/'+encodeURIComponent(have.id)+'/matchups/'
                         +(wk.week||ctx.week||1))
          .then(function(rows){ return rows||[]; })
          .catch(function(){ return []; })
          .then(function(rows){
            var live={};
            (rows||[]).forEach(function(r){
              live[String(r.roster_id)]=r.players_points||{};
            });
            return [lg, wk, index, ctx, live];
          });
      })
      .then(function(o){
        var lg=o[0], wk=o[1], index=o[2], ctx=o[3], live=o[4];
        var bar=document.getElementById('mt-bar');
        // Nothing came back: say why, in the words of the site it is on.
        if(!lg.info.league_id && !lg.rosters.length){
          host.innerHTML='<p class="mt-none">'+GSAPI.problem(have.id)+'</p>';
          return;
        }
        // A league saved in another season is not this week's lineup.
        var other=GSAPI.otherSeason(lg.info, wk.year, 'mt-none');
        if(other){ host.innerHTML=other; return; }
        var keys=Object.keys(lg.names);
        // Their own team, not roster 1. The account stores the reader's
        // Sleeper user id with each league they synced, so the roster it owns
        // is the one to open on; without it (a league entered by id, or a row
        // from before the id was stored) the first is all there is.
        var start=GSL.myRoster(lg, have.id) || keys[0];
        if(bar){
          bar.innerHTML='<label>Team <select id="mt-who">'
            +keys.map(function(k){
              return '<option value="'+esc(k)+'"'+(k===start?' selected':'')+'>'
                +esc(lg.names[k])+'</option>';}).join('')
            +'</select></label>';
          document.getElementById('mt-who').addEventListener('change',function(){
            GSL.remember(have.id, this.value);
            render(lg, wk, index, this.value, ctx, live);});
        }
        render(lg, wk, index, start, ctx, live);
      })
      .catch(function(e){
        var net=e&&e.name==='TypeError'&&/fetch|network|load failed/i.test(String(e.message||''));
        if(!net && window.console) console.error('[my-team]', e);
        host.innerHTML='<p class="mt-none">'+GSAPI.problem(have.id)+'</p>';
      });
  }
  start();
})();
