/* Power rankings for a reader's league (/fantasy/power/).
   Source file, loaded by gordstats.my_power (JS_TAG); see gordstats.js_assets. */
(function(){
  var host=document.getElementById('mp-host');
  if(!host||!window.GSL) return;
  var have=GSL.saved();
  if(!have||!have.id||have.site){
    // Drawn twice: once now, and again when the account call settles, because
    // whether to offer a sign-in or a league picker is not known at first paint.
    var none=function(){ host.innerHTML=window.GSLeague
      ? GSLeague.empty('mp-none','power rankings')
      : '<p class="mp-none">Pick a league above to see its power rankings.</p>'; };
    none();
    if(window.GSLeague&&GSLeague.ready) GSLeague.ready.then(none,none);
    return;
  }

  // The season this page ranks (section()): a league saved in another one
  // says so rather than being simulated on this season's board.
  var YEAR=parseInt(host.getAttribute('data-year')||'0',10)||0;
  var SIMS=10000;
  // What a reader sees while the full run finishes. Two thousand seasons is
  // a tenth of the work and lands within a point of the answer, so the table
  // appears almost at once and then settles rather than sitting empty.
  var FIRST=2000;

  function esc(v){
    return String(v==null?'':v).replace(/[&<>"']/g,function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});
  }
  function pct(v){ return Math.round(v*100)+'%'; }
  // matplotlib's RdYlGn, the eleven anchors pandas interpolates between, so a
  // reader's column is shaded on the same scale as the built page's.
  var RDYLGN=[[165,0,38],[215,48,39],[244,109,67],[253,174,97],[254,224,139],
              [255,255,191],[217,239,139],[166,217,106],[102,189,99],[26,152,80],
              [0,104,55]];
  function ramp(t){
    t=Math.min(Math.max(t,0),1);
    var x=t*(RDYLGN.length-1), i=Math.min(Math.floor(x),RDYLGN.length-2), f=x-i;
    var a=RDYLGN[i], b=RDYLGN[i+1];
    return [Math.round(a[0]+(b[0]-a[0])*f), Math.round(a[1]+(b[1]-a[1])*f),
            Math.round(a[2]+(b[2]-a[2])*f)];
  }
  /** A cell shaded the way the built table's `_heat` shades it: the column
   *  normalised over its own min and max, and the ramp's colour laid on as a
   *  wash whose strength grows with the distance from the middle - so the
   *  middle of a column is no colour at all. A background-image, not a
   *  background-color, so the themed cell underneath (white, zebra or navy)
   *  and the theme's own ink survive; `--heat` (CSS) is how strong the ends
   *  get in each theme. A solid fill here was a pale-yellow block at night. */
  function shade(value, lo, hi){
    if(value==null||value!==value||hi<=lo) return '';
    var t=Math.min(Math.max((value-lo)/(hi-lo),0),1);
    var strength=Math.abs(2*t-1);
    if(strength<0.03) return '';
    var c=ramp(t);
    var wash='rgb('+c[0]+' '+c[1]+' '+c[2]+' / calc(var(--heat, .35) * '
      +strength.toFixed(2)+'))';
    return 'background-image:linear-gradient('+wash+', '+wash+')';
  }
  function bounds(values){
    var ok=values.filter(function(v){ return v!=null&&v===v; });
    if(!ok.length) return [0,1];
    return [Math.min.apply(null,ok), Math.max.apply(null,ok)];
  }

  /** Each team's real record so far, and how far it sits from what its
   *  scores deserved - fantasy.league.power.actual_records, in the browser.
   *  `actual` is one array of scores per played week, in `order`. */
  function records(actual, schedule, median){
    var n=(actual[0]||[]).length, h2h=[], med=[], ties=[], allplay=[];
    for(var i=0;i<n;i++){ h2h.push(0); med.push(0); ties.push(0); allplay.push(0); }
    actual.forEach(function(week, w){
      // The sim's own count of a week (GSPower.weekWins): a tie is half a
      // win, the median game is won above the median.
      var a0=h2h.slice(), m0=med.slice();
      GSPower.weekWins(week, (schedule&&schedule[w])||null, median, h2h, med);
      for(var a=0;a<n;a++){
        if(h2h[a]-a0[a]===0.5) ties[a]++;
        if(med[a]-m0[a]===0.5) ties[a]++;
        // All-play: a win over every team scored under, half over a level one.
        for(var b=0;b<n;b++)
          if(b!==a) allplay[a]+=week[a]>week[b]?1:(week[a]===week[b]?0.5:0);
      }
    });
    var played=actual.length, perWeek=median?2:1;
    return h2h.map(function(w, i){
      var pct=played?allplay[i]/(played*(n-1)):0;
      return {wins:w+med[i], losses:perWeek*played-(w+med[i]), ties:ties[i],
              luck:(w+med[i])-pct*perWeek*played};
    });
  }
  /** W-L-T, as Sleeper writes a record, from wins and losses that count a
   *  tie as half of each. */
  function wlt(r){
    var t=r.ties||0;
    return (r.wins-t/2)+'-'+(r.losses-t/2)+(t?'-'+t:'');
  }

  function table(result, names, order, settling, real){
    var games=result.weeks*(result.median?2:1);
    var pw=bounds(result.teams.map(function(t){ return t.power; }));
    var po=bounds(result.teams.map(function(t){ return t.playoffOdds; }));
    // A seat's index in `order`, which is what `records` is laid out by.
    var seat={};
    order.forEach(function(rid, i){ seat[String(rid)]=i; });
    var played=real&&real.length?result.played:0;
    var luckBound=1;
    if(played) luckBound=Math.max(1, Math.max.apply(null,
      real.map(function(r){ return Math.abs(r.luck); })));

    // The built table's order (fantasy.site.power._rankings_table): what a
    // phone sees beside the name is what a reader came for - the record, then
    // the playoff and title odds - with the figure the rows are ranked by
    // after it, and the projection and the luck last. A played week with no
    // record for a seat keeps its cells, empty, so the columns stay aligned.
    var rows=result.teams.map(function(t, i){
      var mine=played&&real[seat[String(t.roster_id)]];
      return '<tr><td><span class="row-rank">'+(i+1)+'</span>'
        +esc(names[String(t.roster_id)]||('Roster '+t.roster_id))+'</td>'
        +(played?'<td>'+(mine?wlt(mine):'')+'</td>':'')
        +'<td style="'+shade(t.playoffOdds,po[0],po[1])+'">'+pct(t.playoffOdds)+'</td>'
        +'<td>'+pct(t.titleOdds)+'</td>'
        +'<td style="'+shade(t.power,pw[0],pw[1])+'">'+t.power.toFixed(1)+'</td>'
        +'<td>'+t.projWins.toFixed(1)+'-'+(games-t.projWins).toFixed(1)+'</td>'
        +(played?'<td style="'+(mine?shade(mine.luck,-luckBound,luckBound):'')+'">'
                 +(mine?(mine.luck>=0?'+':'')+mine.luck.toFixed(1):'')+'</td>':'')
        +'</tr>';
    }).join('');
    var head='<th>Team</th>'+(played?'<th>Record</th>':'')
      +'<th>Playoffs</th><th>Title</th><th>Power</th><th>Proj. Record</th>'
      +(played?'<th>Luck</th>':'');

    var caveats=[];
    if(result.unsupported.length){
      caveats.push('This league starts '+esc(result.unsupported.join(', '))
        +', which this site does not project. Those slots are left empty, so '
        +'every team here is understated by the same kind of player.');
    }
    if(result.unknownPlayers){
      caveats.push(result.unknownPlayers+' rostered player'
        +(result.unknownPlayers===1?' is':'s are')+' not on the projection '
        +'board and stand in as deep-bench depth.');
    }

    return (caveats.length?'<p class="mp-warn">'+caveats.join(' ')+'</p>':'')
      +'<div class="table-scroll"><table class="sticky-table pw-table"><thead><tr>'
      +head+'</tr></thead><tbody>'+rows+'</tbody></table></div>'
      +'<p class="mp-note">'
      +(settling?'<strong>Settling&hellip;</strong> ':'')
      +'Every roster played through the rest of the season '
      +result.sims.toLocaleString()+' times. <strong>100 is this league\u2019s '
      +'average</strong>; a point is one percent better. '
      +(played?('Weeks 1&ndash;'+result.played+' are what actually happened, not a '
                +'simulation; <strong>Record</strong> is what they returned'
                +(result.median?', the weekly median win included':'')
                +', and <strong>Luck</strong> is that record minus what an '
                +'all-play schedule says the scores deserved. '):'')
      +'</p>';
  }

  host.innerHTML='<p class="mp-load">Reading '+esc(have.name||'your league')
    +'\u2026</p>';

  GSPowerLeague.setup(have.id, YEAR).then(function(s){
    var league=s.league, order=s.order, run=s.run, spec=s.spec, played=s.played;
    spec.sims=FIRST;
    // What the played weeks actually returned, so the table can carry the
    // built page's Record and Luck columns rather than projections alone.
    var real=played?records(spec.actual, run.schedule, spec.median):null;
    var head=document.getElementById('pw-mine-h');
    if(head) head.textContent=league.info.name||'Your league';
    var built=document.getElementById('pw-built');
    var intro=document.getElementById('pw-intro');
    // A reader who has picked a league is here for that league: this site's
    // ranking would only raise the question of whose numbers are on screen.
    if(built) built.hidden=true;
    if(intro) intro.hidden=true;
    return GSPowerLeague.simulate(spec).then(function(quick){
      host.innerHTML=table(quick, league.names, order, true, real);
      spec.sims=SIMS;
      return GSPowerLeague.simulate(spec);
    }).then(function(full){
      host.innerHTML=table(full, league.names, order, false, real);
      var note=host.querySelector('.mp-note');
      if(note&&league.basis.custom){
        note.insertAdjacentHTML('beforeend',
          'This league\u2019s scoring is close to '+esc(league.basis.name)
          +' but not exactly it, so the numbers are approximate. ');
      }
      if(note){
        note.insertAdjacentHTML('beforeend',
          'The ranking beside this one blends an outside source; this is '
          +'this site\u2019s simulation alone.');
      }
    });
  }).catch(function(err){
    if(err instanceof TypeError) console.error(err);
    var why=err&&err.message;
    if(why==='undrafted'){
      host.innerHTML='<p class="mp-none">'+esc(have.name||'This league')+' has not drafted '
        +'yet. Its power rankings appear here after your draft.</p>';
      return;
    }
    // Last season's league is not this season's ranking: say which it is,
    // with the way to this season's.
    if(why==='other-season'){
      host.innerHTML=GSAPI.otherSeason(err.info, err.year, 'mp-none');
      return;
    }
    // The league could not be read: in the words of the site it is on (an
    // ESPN league kept private says how to open it), never "Sleeper may be
    // busy" for a league that is not on Sleeper.
    host.innerHTML='<p class="mp-none">'
      +(why==='board' ? 'Could not read this site\u2019s projections. Try again in a minute.'
        : (why==='league'||err instanceof TypeError)&&window.GSAPI&&GSAPI.problem
        ? GSAPI.problem(have.id)
        : 'Could not rank this league. Try again in a minute.')+'</p>';
  });
})();
