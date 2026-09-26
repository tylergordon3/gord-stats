"""
The built pages' table cells, in the browser, for a reader's own league.

/fantasy/roster/ and /fantasy/matchups/ render this site's league on the Pi,
where the whole of `fantasy.site.roster.Week` is available: every projection,
every line, every forecast, and how each defence has been treating the
position. A reader's league is rendered at view time from Sleeper, which has
none of that, so those tables were four columns beside the built twelve - the
same information, laid out as if it were a different feature.

`fantasy.site.week_context` publishes the numbers; this holds the cells, so
there is one description of what a row looks like rather than a Python one and
a drifting JavaScript one. The classes are the built page's own (`rd-*`,
`mu-*`), which are already in the stylesheet on these pages - so matching the
format is a matter of emitting the same markup, not restyling anything.

Two honest differences from the built page, both stated on the page rather
than papered over:

  * **Proj** is the mean of the sources that have the player. This site
    collects ESPN's and FantasyPros' weekly numbers only for its own league's
    rosters, so for somebody else's league that mean is over GordStats and
    Sleeper. `roster.Week.blend` already averages whatever it has; the rule is
    the same, the inputs are fewer.
  * A **defence** with no finished week to rate yet shows a dash, exactly as
    the built page does.
"""

JS = """{% raw %}<script>
window.GSWeek = (function(){
  'use strict';

  var LOGO='https://a.espncdn.com/i/teamlogos/nfl/500/{abbr}.png';
  var LOGO_FIX={WAS:'wsh'};
  var INJURY={Questionable:'Q',Doubtful:'D',Out:'O',IR:'IR',PUP:'PUP',
              Sus:'SUS',NA:'NA',DNR:'DNR',COV:'COV'};
  var PILL={'in':'\\u25b2 Start','out':'\\u25bc Bench','swap':'\\u21c4 Move'};
  // ESPN condition codes, as gordstats.roster_page groups them.
  var WX_RAIN=[12,13,14,18,39,40], WX_STORM=[15,16,17,41,42],
      WX_SNOW=[19,20,21,22,23,24,25,26,29,43,44];

  function esc(v){
    return String(v==null?'':v).replace(/[&<>"]/g,function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});
  }
  function fmt(v,dec){
    if(v==null||v!==v) return '\\u2014';
    return Number(v).toFixed(dec==null?1:dec);
  }
  function ordinal(n){
    var s=(n%100>=10&&n%100<=20)?'th':({1:'st',2:'nd',3:'rd'}[n%10]||'th');
    return n+s;
  }
  /** Green where a defence gives points up, red where it does not - the same
   *  scale as the matchup-strength page. */
  function heat(v,low,high){
    if(v==null||v!==v) return '';
    low=low==null?0.85:low; high=high==null?1.15:high;
    var t=Math.min(Math.max((v-low)/Math.max(high-low,1e-9),0),1);
    var c=t<0.5?[211,47,47]:[46,125,50];
    return 'background:rgba('+c[0]+','+c[1]+','+c[2]+','
      +(Math.abs(t-0.5)*2*0.45).toFixed(2)+')';
  }
  function wxIcon(cond){
    if(cond==null) return '';
    if(WX_SNOW.indexOf(cond)>=0) return '\\u2744\\ufe0f';
    if(WX_STORM.indexOf(cond)>=0) return '\\u26c8\\ufe0f';
    if(WX_RAIN.indexOf(cond)>=0) return '\\ud83c\\udf27\\ufe0f';
    if(cond===11||cond===37) return '\\ud83c\\udf2b\\ufe0f';
    if(cond===32) return '\\ud83d\\udca8';
    if([1,2,30,33,34].indexOf(cond)>=0) return '\\u2600\\ufe0f';
    if([3,4,5,35,36].indexOf(cond)>=0) return '\\u26c5';
    return '\\u2601\\ufe0f';
  }
  /** "Sun 1:00p" - the short kickoff the cover column prints, matching
   *  fantasy.site.roster._when. Rendered in the reader's own timezone, which
   *  is the one they are deciding in. */
  function when(g){
    if(!g||!g.date) return 'bye';
    var d=new Date(g.date);
    if(isNaN(d)) return '';
    var day=['Sun','Mon','Tue','Wed','Thu','Fri','Sat'][d.getDay()];
    var h=d.getHours(), ap=h<12?'a':'p';
    h=h%12; if(h===0) h=12;
    return day+' '+h+':'+String(d.getMinutes()).padStart(2,'0')+ap;
  }

  /** The dashboard styles its marks `.rd-logo`, the matchup pages `.mu-logo`,
   *  and each stylesheet is only on its own page - a logo carrying the other
   *  page's class gets the theme's framed-thumbnail treatment instead. */
  function logo(team,cls){
    if(!team) return '';
    var abbr=(LOGO_FIX[team]||team).toLowerCase();
    return '<img class="'+(cls||'rd-logo')+'" src="'+LOGO.replace('{abbr}',esc(abbr))
      +'" alt="" loading="lazy">';
  }

  // ----- cells, mirroring fantasy.site.roster ----------------------------- //

  /** "W 35-14 at GB", "Live 7-3 vs NYJ", or "at IND - Sun 1:00p". */
  function gameCell(g){
    if(!g) return '<span class="bye">Bye</span>';
    var where=g.home?'vs':'at', opp=esc(g.opp||'');
    var st=g.state||'pre';
    if(st==='post'&&g.sf!=null&&g.sa!=null){
      var res=g.sf>g.sa?'W':(g.sf<g.sa?'L':'T');
      return '<span class="fin">'+res+' '+Math.round(g.sf)+'\\u2013'
        +Math.round(g.sa)+'</span> '+where+' '+opp;
    }
    if(st==='in'){
      var sc=(g.sf!=null&&g.sa!=null)?(' '+Math.round(g.sf)+'\\u2013'+Math.round(g.sa)):'';
      return '<span class="live">Live'+sc+'</span> '+where+' '+opp;
    }
    return where+' '+opp+(g.when?(' &middot; '+esc(g.when)):'');
  }

  /** The market's number for his side; for a defence, what it should allow. */
  function totalCell(g,pos){
    if(!g) return '<td>&mdash;</td>';
    var v=(pos==='DEF')?g.against:g['for'];
    if(v==null) return "<td title='No line posted yet'>&mdash;</td>";
    return '<td>'+Number(v).toFixed(1)
      +(pos==='DEF'?'<span class="rd-rk">allowed</span>':'')+'</td>';
  }

  function oppCell(ctx,g,pos){
    if(!g) return '<td>&mdash;</td>';
    var row=ctx.dvp&&ctx.dvp[g.opp];
    if(!row||!row[pos]) return "<td title='No finished week to rate this defence on yet'>&mdash;</td>";
    var v=row[pos][0], rank=row[pos][1], games=row.games, n=ctx.dvp.n||32;
    return "<td style='"+heat(v)+"' title='Fantasy points "+esc(g.opp)
      +' has allowed to '+pos+'s against the league average, over '+games+' game'
      +(games===1?'':'s')+"; 1.00 is par. Rank 1 is the toughest defence; the higher "
      +"the number the more it gives up.'>"+v.toFixed(2)
      +'<span class="rd-rk">'+ordinal(rank)+' of '+n+'</span></td>';
  }

  function wxCell(ctx,g){
    if(!g) return '<td>&mdash;</td>';
    var wx=ctx.wx&&ctx.wx[g.gid];
    if(!wx) return "<td class='rd-wx' title='No forecast yet - they appear a few days out'>&mdash;</td>";
    if(wx.indoors) return '<td class="rd-wx">\\ud83c\\udfdf\\ufe0f Indoors</td>';
    var bad=WX_RAIN.concat(WX_STORM,WX_SNOW).indexOf(wx.cond)>=0
      || (wx.temp!=null && wx.temp<=32);
    var bits=[];
    if(wx.temp!=null) bits.push(Math.round(wx.temp)+'\\u00b0');
    if(wx.text) bits.push(esc(wx.text));
    return '<td class="rd-wx'+(bad?' bad':'')+'">'+wxIcon(wx.cond)+' '+bits.join(' ')+'</td>';
  }

  function moveCell(kind,wasSlot){
    if(!kind) return '<td class="rd-mv"></td>';
    return '<td class="rd-mv"><span class="rd-pill '+kind+'">'+PILL[kind]
      +'</span><span class="rd-to">now '+esc(wasSlot)+'</span></td>';
  }

  function playerCell(card,extra){
    var inj=card.injury
      ? '<span class="rd-inj" title="'+esc(card.injury)+'">'
        +esc(INJURY[card.injury]||card.injury.slice(0,3).toUpperCase())+'</span>'
      : '';
    return '<td class="rd-p">'+logo(card.team)+'<span class="nm">'+esc(card.name)
      +'</span><span class="rd-lbl">'+esc(card.pos)+' &middot; '+esc(card.team||'FA')
      +'</span>'+inj+(extra||'')+'</td>';
  }

  // ----- the dashboard's phone cards -------------------------------------- //
  //
  // Mirrors gordstats.roster_page.player_card / phone_lineup. Below 760px the
  // built page replaces its twelve-column table with one card per player and
  // a Current/Suggested toggle; a reader's league had only the table, which
  // on a phone is a sideways scroll through twelve columns.

  var SLOT_CLASS={'W/R/T':'FX','FLEX':'FX','WRRB_FLEX':'FX','REC_FLEX':'FX',
                  'SUPER_FLEX':'FX','IL':'BN','IR':'BN','TAXI':'BN'};
  var DO={'in':'\\u25b2 START at {new}','out':'\\u25bc BENCH',
          'swap':'\\u21c4 MOVE to {new}'};
  var DONE={'in':'\\u25b2 START - now on the bench','out':'\\u25bc BENCH - now at {now}',
            'swap':'\\u21c4 MOVE here - now at {now}'};

  /** The fields a card draws, for one player - roster.card_info. */
  function cardInfo(ctx,p,proj,note){
    var g=gameFor(ctx,p.team);
    var c={name:p.name, pos:p.pos, team:p.team||'FA', logo:logo(p.team),
           game:gameCell(g), proj:proj, projNote:note||'proj', inj:p.injury||''};
    if(!g) return c;
    c.oppLabel=(g.home?'vs ':'@ ')+(g.opp||'');
    var row=ctx.dvp&&ctx.dvp[g.opp];
    if(row&&row[p.pos]){ c.oppValue=row[p.pos][0]; c.oppRank=row[p.pos][1]; }
    var bits=[], wx=ctx.wx&&ctx.wx[g.gid];
    if(wx&&wx.indoors) bits.push('\\ud83c\\udfdf\\ufe0f indoors');
    else if(wx){
      var text=wxIcon(wx.cond)+' '+(wx.temp!=null?(Math.round(wx.temp)+'\\u00b0 '):'')
        +esc(wx.text||'');
      var bad=WX_RAIN.concat(WX_STORM,WX_SNOW).indexOf(wx.cond)>=0
        || (wx.temp!=null && wx.temp<=32);
      bits.push(bad?("<b style='color:#b45309'>"+text+'</b>'):text);
    }
    var total=(p.pos==='DEF')?g.against:g['for'];
    if(total!=null)
      bits.push((p.pos==='DEF'?'allows ':'team total ')+Number(total).toFixed(1));
    if(bits.length) c.extra="<div class='rd-c-sub'>"+bits.join(' &middot; ')+'</div>';
    return c;
  }

  function oppBox(c){
    var label=esc(c.oppLabel||'');
    if(c.oppValue==null||c.oppValue!==c.oppValue)
      return label?("<div class='rd-c-opp'>"+label+'</div>'):"<div class='rd-c-opp'></div>";
    var tone=c.oppValue>=1.05?'soft':(c.oppValue<=0.95?'hard':'par');
    return "<div class='rd-c-opp "+tone+"'>"+c.oppValue.toFixed(2)
      +'<b>'+ordinal(c.oppRank)+'</b>'+label+'</div>';
  }

  /** One player as a card. `suggested` shows the lineup to set rather than
   *  the one that is set now. */
  function phoneCard(c,suggested){
    var slot=suggested?c['new']:c.slot, kind=c.kind||'';
    var words=(suggested?DONE:DO)[kind]||'';
    var doLine=words
      ? "<div class='rd-c-do'>"
        +words.replace('{new}',esc(c['new'])).replace('{now}',esc(c.slot))+'</div>'
      : '';
    var inj=c.inj?(" <span class='rd-inj'>"+esc(c.inj)+'</span>'):'';
    var lock=c.locked?" <span class='rd-tag lock'>locked</span>":'';
    return "<div class='rd-card "+kind+(c.off?' bn':'')+"'>"
      +"<div class='rd-c-slot "+(SLOT_CLASS[slot]||slot)+"'>"+esc(slot)
      +'<small>'+esc(slot!==c.pos?(c.pos||''):'')+'</small></div>'
      +"<div class='rd-c-main'><div class='rd-c-nm'>"+(c.logo||'')+esc(c.name)+inj+lock
      +"</div><div class='rd-c-sub'>"+esc(c.team||'')+' &middot; '+(c.game||'')+'</div>'
      +(c.extra||'')+doLine+'</div>'
      +"<div class='rd-c-proj'>"+(c.proj==null?'&mdash;':Number(c.proj).toFixed(1))
      +'<small>'+esc(c.projNote||'proj')+'</small></div>'+oppBox(c)+'</div>';
  }

  /** The roster as cards twice - the lineup to set, and the one set now -
   *  with the toggle on top. roster_page.CARD_JS already listens for it. */
  function phoneLineup(cards,slotRank,off,nowTotal,bestTotal){
    function part(items,suggested){
      var start=[], bench=[];
      items.forEach(function(c){
        (off.indexOf(suggested?c['new']:c.slot)>=0?bench:start).push(c);
      });
      return '<h4>Starters</h4>'+start.map(function(c){
          c.off=false; return phoneCard(c,suggested);}).join('')
        +'<h4>Bench</h4>'+bench.map(function(c){
          c.off=true; return phoneCard(c,suggested);}).join('');
    }
    // Two passes over the same objects, and `off` is set per pass, so each
    // gets its own copies rather than the second rewriting the first.
    function copy(list){ return list.map(function(c){
      var o={}; for(var k in c) o[k]=c[k]; return o; }); }
    var byNew=copy(cards).sort(function(a,b){
      var ra=slotRank[a['new']], rb=slotRank[b['new']];
      if(ra==null) ra=99; if(rb==null) rb=99;
      return ra-rb || (b.proj||0)-(a.proj||0);
    });
    var gain=bestTotal-nowTotal;
    var toggle="<div class='rd-toggle'>"
      +"<div class='rd-tot'><b>"+fmt(nowTotal)+"</b><span>As set</span></div>"
      +"<div class='rd-seg'><button type='button' data-mode='cur'>Current</button>"
      +"<button type='button' class='on' data-mode='new'>Suggested</button></div>"
      +"<div class='rd-tot new'><b>"+fmt(bestTotal)
      +(gain>=0.05?('<i>+'+fmt(gain)+'</i>'):'')+"</b><span>Best lineup</span></div></div>";
    return "<div class='rd-phone'>"+toggle
      +"<div class='rd-cards' data-mode='cur' style='display:none'>"+part(copy(cards),false)
      +"</div><div class='rd-cards' data-mode='new'>"+part(byNew,true)+'</div></div>';
  }

  /** The key above the table, roster_page.legend. */
  function legend(){
    return "<div class='rd-legend'><span><i class='in'></i>Bench &rarr; start</span>"
      +"<span><i class='out'></i>Starter &rarr; bench</span>"
      +"<span><i class='swap'></i>Swap slots for kickoff order</span></div>";
  }

  // ----- the matchups page's paired phone view ---------------------------- //

  /** "Ja'Marr Chase" -> "J. Chase": a full name does not fit half a phone. */
  function shortName(name){
    var parts=String(name||'').split(/\\s+/);
    if(parts.length<2||parts[parts.length-1]==='D/ST') return String(name||'');
    return parts[0].charAt(0)+'. '+parts.slice(1).join(' ');
  }

  /** The .mu-pts cell: one figure, always the one that matters. Mirrors
   *  gordstats.matchup_page.score_cell. `exp` is the live expected final,
   *  which this side does not compute - the built cell falls back to "live"
   *  for exactly that case, so it reads the same. */
  function scoreCell(pts,proj,state,exp,markProj){
    if(state==='post')
      return '<b class="mu-now">'+fmt(pts||0)+'</b><span class="mu-exp">final</span>';
    if(state==='in'){
      var sub=exp!=null?('&rarr; '+fmt(exp)):'live';
      return '<b class="mu-now">'+fmt(pts||0)+'</b><span class="mu-exp live">'+sub+'</span>';
    }
    if(state==='bye'&&!pts)
      return '<b class="mu-now proj">&mdash;</b><span class="mu-exp">bye</span>';
    if(pts) return '<b class="mu-now">'+fmt(pts)+'</b><span class="mu-exp"></span>';
    return '<b class="mu-now proj">'+fmt(proj)+'</b><span class="mu-exp">'
      +((markProj&&proj!=null)?'proj':'')+'</span>';
  }

  /** The .mu-pts cell on the blended projection, mirroring
   *  fantasy.site.matchups.hybrid_score: what the sources expect before
   *  kickoff, points plus the unplayed share of it during the game, points
   *  after. `expected` needs the week's context, so this lives beside it. */
  function hybridScore(pts,proj,g){
    var state=g?(g.state||'pre'):'bye';
    return scoreCell(pts,proj,state,state==='in'?expected(pts,proj,g)[0]:null);
  }

  /** One side of a paired row, mirroring fantasy.site.matchups._pair_cell. */
  function pairCell(card,pts,proj,g){
    if(!card) return '<div class="mu-pp empty" aria-hidden="true"></div>';
    var inj=card.injury
      ? '<span class="inj">'+esc(INJURY[card.injury]||card.injury.slice(0,3).toUpperCase())+'</span>'
      : '';
    var live=(g&&g.state==='in')?' live':'';
    return '<div class="mu-pp'+live+'" data-pid="'+esc(card.id)+'"><div class="mu-pn">'
      +'<span class="nm" title="'+esc(card.name)+'">'+logo(card.team,'mu-logo')
      +esc(shortName(card.name))+'</span>'
      +'<span class="mu-pm">'+esc(card.pos)
      +((card.team&&card.pos!=='DEF')?(' \u00b7 '+esc(card.team)):'')+inj+'</span>'
      +'<span class="mu-g">'+gameCell(g)+'</span></div>'
      +'<div class="mu-pcol"><span class="mu-pts">'+hybridScore(pts,proj,g)
      +'</span></div></div>';
  }

  // ----- expected finals, mirroring fantasy.site.matchups ----------------- //

  /** The spread of a player's week. The built page reads the projection
   *  board's own standard deviation where it has one; that is not published,
   *  so every player takes the fallback the built page uses for a player it
   *  has no figure for. The shape is the same, the spread a little wider. */
  function sdFor(proj){ return Math.max(2, 0.6*(proj||0)); }

  /** (expected final, variance) for one player: the projection before
   *  kickoff, the points once it is over, and in between the points so far
   *  plus the unplayed share of the projection. */
  function expected(pts,proj,g){
    proj=Number(proj||0); pts=Number(pts||0);
    var left=1-(g?Number(g.el||0):0);
    return [pts+proj*left, sdFor(proj)*sdFor(proj)*left];
  }

  function erf(x){
    var t=1/(1+0.3275911*Math.abs(x));
    var y=1-(((((1.061405429*t-1.453152027)*t+1.421413741)*t-0.284496736)*t
      +0.254829592)*t)*Math.exp(-x*x);
    return x>=0?y:-y;
  }
  /** P(A outscores B), on a normal over the difference of expected finals,
   *  with the same floor on the spread the built page uses so a matchup that
   *  is all but over still reads as odds rather than a certainty. */
  function winProb(ea,va,eb,vb){
    var sd=Math.sqrt(Math.max(va+vb,4));
    return 0.5*(1+erf(((ea-eb)/sd)/Math.SQRT2));
  }

  // ----- the week's context ----------------------------------------------- //

  var cached=null;
  function load(){
    if(cached) return cached;
    cached=fetch('/fantasy/week-context.json')
      .then(function(r){ return r.ok?r.json():null; })
      .then(function(d){ return d||{teams:{},wx:{},dvp:{},gs:{},week:0}; })
      .catch(function(){ return {teams:{},wx:{},dvp:{},gs:{},week:0}; });
    return cached;
  }

  /** One team's game, with this side's scores resolved. */
  function gameFor(ctx,team){
    var g=ctx.teams&&ctx.teams[team];
    if(!g) return null;
    return g;
  }

  /** The blend the built page prints: the mean of the sources that have him.
   *  Fewer sources here than there - see the module note. */
  function projFor(ctx,pid,team,sleeperPts){
    if(team && ctx.teams && !ctx.teams[team]) return 0;     // a bye
    var vals=[];
    var gs=ctx.gs&&ctx.gs[pid];
    if(gs!=null) vals.push(gs);
    if(sleeperPts!=null) vals.push(sleeperPts);
    if(!vals.length) return null;
    return vals.reduce(function(a,b){return a+b;},0)/vals.length;
  }

  return {load:load, gameFor:gameFor, projFor:projFor, when:when, logo:logo,
          sdFor:sdFor, expected:expected, winProb:winProb,
          shortName:shortName, scoreCell:scoreCell, pairCell:pairCell,
          hybridScore:hybridScore,
          gameCell:gameCell, totalCell:totalCell, oppCell:oppCell, wxCell:wxCell,
          moveCell:moveCell, playerCell:playerCell,
          cardInfo:cardInfo, phoneCard:phoneCard, phoneLineup:phoneLineup,
          legend:legend,
          heat:heat, ordinal:ordinal, wxIcon:wxIcon, fmt:fmt, esc:esc};
})();
</script>{% endraw %}"""
