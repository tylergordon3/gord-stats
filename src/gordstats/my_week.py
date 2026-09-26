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

  function logo(team){
    if(!team) return '';
    var abbr=(LOGO_FIX[team]||team).toLowerCase();
    return '<img class="rd-logo" src="'+LOGO.replace('{abbr}',esc(abbr))
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

  return {load:load, gameFor:gameFor, projFor:projFor, when:when,
          gameCell:gameCell, totalCell:totalCell, oppCell:oppCell, wxCell:wxCell,
          moveCell:moveCell, playerCell:playerCell,
          heat:heat, ordinal:ordinal, wxIcon:wxIcon, fmt:fmt, esc:esc};
})();
</script>{% endraw %}"""
