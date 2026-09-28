"""
League Home for whichever league the reader has picked, in the built page's
own format.

The built League Home is two things: All-Time Metrics (record, points, strength
of schedule and of victory, expected wins) and a profile per manager (the two
books, rival, nemesis and favourite, every game by margin, every opponent,
season by season) - fantasy.site.homepage and fantasy.site.team_profiles, out
of this league's archive. A reader's league used to get something else
entirely: champions, a table per season, an all-time table and a
head-to-head grid, one after another - longer, plainer, and a different page
from the one everybody else was looking at.

Everything the built page computes is there in Sleeper's history - every
season through `previous_league_id`, every week's matchups, the winners
bracket - and gordstats.my_history already reads it (window.GSHist). So this
draws the built page's two sections from it, with the built page's markup
(team_profiles.CSS applies to both) and the built page's arithmetic:

  * Record, PF and PA are Sleeper's season records summed - a league playing a
    weekly median counts two results a week, as the built table does.
  * SOS is (2 x opponents' win % + opponents' opponents' win %) / 3 over every
    regular-season meeting; SOV the win % of the opponents beaten; Exp W the
    Pythagorean share of the head-to-head games (constant EXPW_RATIO), with
    the actual head-to-head wins in brackets.
  * Profiles are team_profiles.profile, rule for rule: regular season is head
    to head only, playoffs are winners-bracket games, a nemesis needs three
    meetings.

The full history (champions, season tables, the head-to-head grid) and the
drafts keep pages of their own, linked underneath.
"""
from fantasy.config import EXPW_RATIO

CSS = """<style>
#lh-mine table.sticky-table td.n{text-align:right;font-variant-numeric:tabular-nums}
#lh-mine .mh-load{font-size:12.5px;color:#64748b}
@media (prefers-color-scheme: dark){ #lh-mine .mh-load{color:#aab7c9} }
</style>"""

JS = """{% raw %}<script>
(function(){
  // The arithmetic, reachable without a league on the page (for tests, and
  // for anything else that wants the built page's numbers for a reader's).
  window.GSHome={metrics:metrics, finish:finish};
  var RATIO=__EXPW_RATIO__;
  var H_PLACEMENT={3:1, 5:1};
  // matplotlib's RdYlGn, the map the built table's gradients are painted in.
  var RDYLGN=['#a50026','#d73027','#f46d43','#fdae61','#fee08b','#ffffbf',
              '#d9ef8b','#a6d96a','#66bd63','#1a9850','#006837'];
  var esc=function(v){ return String(v==null?'':v).replace(/[&<>"]/g,function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];}); };
  var metricsHost=document.getElementById('mh-metrics');
  var teamsHost=document.getElementById('mh-teams');
  var H=window.GSHist;
  if(!metricsHost||!teamsHost||!H||!window.GSL) return;
  var have=GSL.saved();
  // Only ever shown for a league that is not this site's (my_league.takeover).
  if(!have||!have.id||have.site) return;
  function fmt(v,d){ return v==null||isNaN(v)?'&mdash;':Number(v).toFixed(d==null?1:d); }
  function seasonName(s){ s=parseInt(s,10); return s+'-'+(s+1); }
  function avg(list){ return list.length?list.reduce(function(a,b){return a+b;},0)/list.length:0; }

  // ----- colours, as pandas' background_gradient paints the built table --- //

  function hex(c){ return [1,3,5].map(function(i){ return parseInt(c.slice(i,i+2),16); }); }
  function ramp(t){
    t=Math.max(0,Math.min(1,isNaN(t)?0.5:t));
    var x=t*(RDYLGN.length-1), i=Math.min(Math.floor(x),RDYLGN.length-2), f=x-i;
    var a=hex(RDYLGN[i]), b=hex(RDYLGN[i+1]);
    return a.map(function(v,k){ return Math.round(v+(b[k]-v)*f); });
  }
  function lum(rgb){
    var c=rgb.map(function(v){ v/=255; return v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4); });
    return 0.2126*c[0]+0.7152*c[1]+0.0722*c[2];
  }
  // styles.GRADIENT_INK: light text only on the darkest fills.
  function paint(value, lo, hi, reverse){
    var t=hi>lo?(value-lo)/(hi-lo):0.5;
    var rgb=ramp(reverse?1-t:t);
    return 'background-color:rgb('+rgb.join(',')+');color:'+(lum(rgb)<0.22?'#f1f1f1':'#000000');
  }

  // ----- All-Time Metrics ------------------------------------------------- //

  function metrics(seasons, log, names){
    var by={};
    seasons.forEach(function(s){
      s.teams.forEach(function(t){
        if(!t.owner) return;
        var a=by[t.owner]=by[t.owner]||{owner:t.owner, w:0, l:0, pf:0, pa:0, titles:0};
        a.w+=t.wins; a.l+=t.losses; a.pf+=t.pf; a.pa+=t.pa;
        if(t.champion) a.titles++;
      });
    });
    var winp={};
    Object.keys(by).forEach(function(k){
      var a=by[k]; winp[k]=(a.w+a.l)?a.w/(a.w+a.l):0; a.opps=[]; a.beat=[]; a.hw=0; a.hl=0; });
    log.forEach(function(g){
      if(g.kind!=='regular') return;
      [[g.a,g.b,g.ap,g.bp],[g.b,g.a,g.bp,g.ap]].forEach(function(x){
        var me=by[x[0]]; if(!me||!by[x[1]]) return;
        me.opps.push(x[1]);
        if(x[2]>x[3]){ me.beat.push(x[1]); me.hw++; } else if(x[2]<x[3]) me.hl++;
      });
    });
    var ow={};
    Object.keys(by).forEach(function(k){ ow[k]=avg(by[k].opps.map(function(o){ return winp[o]; })); });
    var rows=Object.keys(by).map(function(k){
      var a=by[k], oow=avg(a.opps.map(function(o){ return ow[o]; }));
      var games=a.hw+a.hl;
      var share=(a.pf||a.pa)?Math.pow(a.pf,RATIO)/(Math.pow(a.pf,RATIO)+Math.pow(a.pa,RATIO)):0;
      return {owner:k, name:names[k]||'Manager', titles:a.titles, w:a.w, l:a.l, pf:a.pf, pa:a.pa,
              sos:(ow[k]*2+oow)/3, sov:avg(a.beat.map(function(o){ return winp[o]; })),
              expw:share*games, hw:a.hw};
    }).sort(function(a,b){ return (b.w-a.w)||(b.pf-a.pf); });
    if(!rows.length) return '<p class="mh-load">Nothing played yet.</p>';
    function range(key){
      var v=rows.map(function(r){ return r[key]; });
      return [Math.min.apply(null,v), Math.max.apply(null,v)];
    }
    var sos=range('sos'), sov=range('sov');
    var diffs=rows.map(function(r){ return r.hw-r.expw; });
    var dlo=Math.min.apply(null,diffs), dhi=Math.max.apply(null,diffs);
    var body=rows.map(function(r,i){
      return '<tr><td>'+esc(r.name)+'</td>'
        +'<td>'+(r.titles?new Array(r.titles+1).join('&#128081;'):'-')+'</td>'
        +'<td>'+r.w+'-'+r.l+'</td>'
        +'<td class="n">'+fmt(r.pf,3)+'</td><td class="n">'+fmt(r.pa,3)+'</td>'
        +'<td style="'+paint(r.sos,sos[0],sos[1],true)+'">'+fmt(r.sos,3)+'</td>'
        +'<td style="'+paint(r.sov,sov[0],sov[1],false)+'">'+fmt(r.sov,3)+'</td>'
        +'<td style="'+paint(diffs[i],dlo,dhi,false)+'">'+fmt(r.expw,1)+' ('+r.hw+')</td></tr>';
    }).join('');
    return '<p><strong>PF / PA</strong>: points for and against, all seasons.</p>'
      +'<p><strong>SOS</strong> (strength of schedule): green easier, red harder.</p>'
      +'<p><strong>SOV</strong> (strength of victory): green = wins over stronger teams, red = over weaker ones.</p>'
      +'<p><strong>Exp W (Actual)</strong>: head-to-head wins expected from points scored and '
      +'allowed (Pythagorean, constant '+RATIO+'), actual in parentheses; green beat it, red fell short.</p>'
      +'<div class="table-scroll"><table class="sticky-table"><thead><tr><th>Team</th><th>Titles</th>'
      +'<th>Record</th><th>PF</th><th>PA</th><th>SOS</th><th>SOV</th><th>Exp W (Actual)</th>'
      +'</tr></thead><tbody>'+body+'</tbody></table></div>';
  }

  // ----- Team profiles: fantasy.site.team_profiles, in the browser --------- //

  function rec(list){
    var w=0,l=0,t=0;
    list.forEach(function(g){ if(g.result==='W')w++; else if(g.result==='L')l++; else t++; });
    return w+'&ndash;'+l+(t?'&ndash;'+t:'');
  }
  function pct(list){
    if(!list.length) return 0;
    var w=0,t=0; list.forEach(function(g){ if(g.result==='W')w++; else if(g.result==='T')t++; });
    return (w+0.5*t)/list.length;
  }

  /** The winners-bracket result for one season - team_profiles._finish. */
  function finish(s, owner){
    var mine=s.teams.filter(function(t){ return t.owner===owner; })[0];
    if(!mine) return '';
    if(mine.champion) return 'Champion';
    var games=(s.bracket||[]).filter(function(g){
      return !H_PLACEMENT[g.p] && (g.t1===mine.roster_id||g.t2===mine.roster_id); });
    if(!games.length){
      var decided=(s.bracket||[]).some(function(g){ return g.p===1 && g.w; });
      return decided?'Missed playoffs':'In progress';
    }
    var last=games.sort(function(a,b){ return (a.r||0)-(b.r||0); })[games.length-1];
    if(last.p===1) return last.w?(last.w===mine.roster_id?'Champion':'Runner-up'):'Playoffs';
    if(last.l!==mine.roster_id) return 'Playoffs';        // still in it
    var rounds=Math.max.apply(null,(s.bracket||[]).map(function(g){ return g.r||0; }));
    return {1:'Lost semifinal',2:'Lost quarterfinal'}[rounds-(last.r||0)]||'Playoffs';
  }
  function tile(k,v,sub){
    return '<div class="tp-tile"><div class="k">'+k+'</div><div class="v">'+v+'</div>'
      +'<div class="s">'+(sub||'')+'</div></div>';
  }
  function card(kind,label,s,names){
    if(!s) return '';
    return '<div class="tp-rival '+kind+'"><div class="k">'+label+'</div>'
      +'<div class="v">'+esc(names[s.opp]||'Unknown')+'</div>'
      +'<div class="s">'+s.w+'&ndash;'+s.l+' in '+s.games+' meetings, avg margin '
      +(s.margin>=0?'+':'')+s.margin.toFixed(1)+'</div></div>';
  }

  function vsTable(games, names, rivalId){
    var by={};
    games.forEach(function(g){
      var s=by[g.opp]=by[g.opp]||{opp:g.opp,w:0,l:0,games:0,margin:0,rw:0,rl:0,pw:0,pl:0,pf:0,pa:0,reg:0};
      s.games++; s.margin+=g.margin;
      if(g.result==='W') s.w++; else if(g.result==='L') s.l++;
      if(g.kind==='playoff'){ if(g.result==='W') s.pw++; else if(g.result==='L') s.pl++; }
      else { if(g.result==='W') s.rw++; else if(g.result==='L') s.rl++; s.pf+=g.pf; s.pa+=g.pa; s.reg++; }
    });
    var sp=Object.keys(by).map(function(k){
      var s=by[k]; s.margin/=s.games; s.pct=s.games?(s.w+0.5*(s.games-s.w-s.l))/s.games:0; return s; })
      .sort(function(a,b){ return (b.pct-a.pct)||(b.margin-a.margin); });
    if(!sp.length) return '';
    var most=Math.max(1, Math.max.apply(null, sp.map(function(s){ return Math.max(s.w,s.l); })));
    var rows=sp.map(function(s){
      var po=(s.pw+s.pl)?'<span class="tp-po" title="Playoff record against">PO '+s.pw+'&ndash;'+s.pl+'</span>':'';
      var name=esc(names[s.opp]||'Unknown')+(s.opp===rivalId?' &#9733;':'');
      var av=s.reg?(s.pf/s.reg).toFixed(1)+'&ndash;'+(s.pa/s.reg).toFixed(1):'';
      return '<tr><td class="opp">'+name+'</td>'
        +'<td class="bars"><div class="tp-bar" title="'+s.w+' wins, '+s.l+' losses">'
        +'<div class="l"><i style="width:'+Math.round(100*s.l/most)+'%"></i></div>'
        +'<div class="r"><i style="width:'+Math.round(100*s.w/most)+'%"></i></div></div></td>'
        +'<td class="rec">'+s.rw+'&ndash;'+s.rl+po+'</td>'
        +'<td class="avg score" title="Average score, regular season">'+av+'</td>'
        +'<td class="avg" title="Average margin, every meeting">'+(s.margin>=0?'+':'')+s.margin.toFixed(1)+'</td></tr>';
    }).join('');
    return '<div class="table-scroll"><table class="tp-vs"><tbody>'+rows+'</tbody></table></div>'
      +'<p class="tp-key">Bars: <b class="l">losses</b> left, <b class="w">wins</b> right, every '
      +'meeting. Then the regular-season record (PO: playoffs), the average regular-season score, '
      +'and the average margin. &#9733; rival.</p>';
  }

  function seasonsTable(games, seasons, owner){
    var rows=seasons.map(function(s){
      var reg=games.filter(function(g){ return g.kind==='regular' && g.season===s.season; });
      if(!reg.length) return '';
      var fin=finish(s, owner);
      return '<tr><td>'+seasonName(s.season)+'</td><td>'+rec(reg)+'</td>'
        +'<td>'+avg(reg.map(function(g){return g.pf;})).toFixed(1)+'</td>'
        +'<td>'+avg(reg.map(function(g){return g.pa;})).toFixed(1)+'</td>'
        +'<td>'+(function(m){ return (m>=0?'+':'')+m.toFixed(1); })(avg(reg.map(function(g){return g.margin;})))+'</td>'
        +'<td class="'+(fin==='Champion'?'fin champ':'fin')+'">'+fin+'</td></tr>';
    }).join('');
    return '<div class="table-scroll"><table class="tp-seasons"><thead><tr><th>Season</th>'
      +'<th>Record</th><th>PF/g</th><th>PA/g</th><th>Margin</th><th>Playoffs</th></tr></thead>'
      +'<tbody>'+rows+'</tbody></table></div>';
  }

  function profile(owner, seasons, log, names, current){
    var games=H.logFor(log, owner);
    if(!games.length) return '<div class="tp-card"><p>No games on record for '
      +esc(names[owner])+' yet.</p></div>';
    var reg=games.filter(function(g){ return g.kind==='regular'; });
    var po=games.filter(function(g){ return g.kind==='playoff'; });
    var wins=reg.filter(function(g){ return g.result==='W'; });
    var losses=reg.filter(function(g){ return g.result==='L'; });
    var played=seasons.filter(function(s){ return s.teams.some(function(t){ return t.owner===owner; }); });
    var titles=played.filter(function(s){ return finish(s, owner)==='Champion'; });
    var trips=played.filter(function(s){
      return po.some(function(g){ return g.season===s.season; }); }).length;
    var cur=current[owner]||{};
    var head='<div class="tp-head">'+(cur.avatar?'<img src="'+esc(cur.avatar)+'" alt="" loading="lazy">':'')
      +'<div><div class="tp-name">'+esc(names[owner])
      +(titles.length?'<span class="tp-trophy">&#127942; '
        +titles.map(function(s){ return seasonName(s.season); }).join(', ')+'</span>':'')+'</div>'
      +'<div class="tp-sub">'+(cur.team?esc(cur.team)+' &middot; ':'')+played.length+' season'
      +(played.length===1?'':'s')+', '+trips+' playoff trip'+(trips===1?'':'s')+'</div></div></div>';
    var mw=wins.length?avg(wins.map(function(g){return g.margin;})):null;
    var ml=losses.length?avg(losses.map(function(g){return g.margin;})):null;
    var tiles=tile('Regular season', rec(reg), Math.round(pct(reg)*100)+'% &middot; head-to-head')
      +tile('Playoffs', po.length?rec(po):'&mdash;', titles.length+' title'+(titles.length===1?'':'s'))
      +tile('Points for', avg(reg.map(function(g){return g.pf;})).toFixed(1), 'per game')
      +tile('Points against', avg(reg.map(function(g){return g.pa;})).toFixed(1), 'per game')
      +tile('Margin in wins', mw==null?'&mdash;':'+'+mw.toFixed(1),
            wins.length?'biggest +'+Math.max.apply(null,wins.map(function(g){return g.margin;})).toFixed(1):'')
      +tile('Margin in losses', ml==null?'&mdash;':ml.toFixed(1),
            losses.length?'worst '+Math.min.apply(null,losses.map(function(g){return g.margin;})).toFixed(1):'');
    var rv=H.rivalsOf(games);
    // One opponent can be both the rival and the nemesis (or favourite): one card, both labels.
    var labels=['Rival'], extra='';
    [['nemesis','Nemesis'],['victim','Favorite opponent']].forEach(function(k){
      var s=rv[k[0]]; if(!s) return;
      if(rv.rival && s.opp===rv.rival.opp) labels.push(k[1]);
      else extra+=card(k[0],k[1],s,names);
    });
    var cards=card('rival', labels.join(' &amp; '), rv.rival, names)+extra;
    var strip='<div class="strip-wide">'+H.stripSvg(games, names, owner, 640, 5.5, 11)+'</div>'
      +'<div class="strip-narrow">'+H.stripSvg(games, names, owner, 340, 4.5, 10)+'</div>'
      +'<p class="tp-key">One dot per game, by margin: <b class="w">wins</b> right of zero, '
      +'<b class="l">losses</b> left; ringed dots are playoff games. Hover or tap a dot for the game.</p>';
    return '<div class="tp-card">'+head+'<div class="tp-tiles">'+tiles+'</div>'
      +'<div class="tp-rivals">'+cards+'</div>'
      +'<h4>Every game</h4>'+strip
      +'<h4>Against each manager</h4>'+vsTable(games, names, rv.rival?rv.rival.opp:null)
      +'<h4>Season by season</h4>'+seasonsTable(games, seasons, owner)+'</div>';
  }

  function teams(seasons, log, names){
    var current={};
    (seasons[0]||{teams:[]}).teams.forEach(function(t){
      if(t.owner) current[t.owner]={team:t.team, avatar:t.avatar}; });
    var ids=Object.keys(names).filter(function(k){
      return log.some(function(g){ return g.a===k||g.b===k; }); })
      .sort(function(a,b){ return names[a].toLowerCase()<names[b].toLowerCase()?-1:1; });
    if(!ids.length) return '<p class="mh-load">Nothing played yet.</p>';
    var key='tp-team:'+have.id, pick=null;
    try{ pick=localStorage.getItem(key); }catch(e){}
    var mine=(GSL.mine?GSL.mine(have.id).uid:null)||'';
    if(ids.indexOf(pick)<0) pick=ids.indexOf(String(mine))>=0?String(mine):ids[0];
    var options=ids.map(function(k){
      return '<option value="'+esc(k)+'"'+(k===pick?' selected':'')+'>'+esc(names[k])
        +((current[k]||{}).team?' &mdash; '+esc(current[k].team):'')+'</option>'; }).join('');
    teamsHost.innerHTML='<div class="tp"><div class="tp-pick"><label for="mh-select">Team</label>'
      +'<select id="mh-select">'+options+'</select>'
      +'<span class="tp-note">Regular season is head-to-head only; playoffs are '
      +'winners-bracket elimination games.</span></div><div id="mh-profile"></div></div>';
    function show(k){
      document.getElementById('mh-profile').innerHTML=profile(k, seasons, log, names, current);
      try{ localStorage.setItem(key,k); }catch(e){}
    }
    document.getElementById('mh-select').addEventListener('change',function(){ show(this.value); });
    show(pick);
  }

  metricsHost.innerHTML=teamsHost.innerHTML='<p class="mh-load">Reading '
    +esc(have.name||'your league')+'\\u2026</p>';
  H.loadState()
    .then(function(){ return H.chain(have.id); })
    .then(function(lgs){
      if(!lgs.length) throw new Error('none');
      return Promise.all(lgs.map(H.season));
    })
    .then(function(seasons){
      return H.gameLog(seasons).then(function(log){
        // Names are the managers', as the built table's are, by owner id -
        // the one thing that survives a team being renamed every August.
        var names=H.managers(seasons);
        metricsHost.innerHTML=metrics(seasons, log, names);
        teams(seasons, log, names);
      });
    })
    .catch(function(){
      metricsHost.innerHTML='<p class="mh-load">Could not read that league from Sleeper.</p>';
      teamsHost.innerHTML='';
    });
})();
</script>{% endraw %}""".replace("__EXPW_RATIO__", str(EXPW_RATIO))


def section(nav: str, links: str) -> str:
    """The two built sections, filled in the browser, and the links to the
    pages the rest of a league's history lives on."""
    return (CSS + nav
            + '<h2 id="mh-metrics-h">All-Time Metrics</h2><div id="mh-metrics"></div>'
            + '<h2 id="mh-teams-h">Teams</h2><div id="mh-teams"></div>' + links)
