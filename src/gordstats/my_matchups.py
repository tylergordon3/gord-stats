"""
"Your league this week" on the NFL matchups page.

The built page is this league's: its scoreboard, its median tracker, its four
projection sources scored against each other, all of it out of an archive the
Pi writes. None of that exists for someone else's league, and pretending
otherwise would mean rebuilding the archive per reader.

What does exist, keyless and CORS-open, is Sleeper's own view of any league:
who plays whom this week, both full rosters, and every player's points as they
land. So the reader's league is rendered *in the built page's own layout* -
the scoreboard, then a section per matchup with the two-column header, the win
bar, the paired phone view and the two roster tables - because a reader
looking at his own league should be reading the same page, not a plainer one
beside it.

Names come from /fantasy/players-index.json and the week's numbers from
/fantasy/week-context.json and /fantasy/week-projections.json, all written by
the build; `gordstats.my_week` holds the cells, so a row here is the row the
built page emits.

Three honest differences from the built league, all of them stated on the
page rather than papered over:

  * **Two projection columns, not four.** This site collects ESPN's and
    FantasyPros' weekly numbers for its own league's rosters only, so a
    reader gets GordStats and Sleeper. The blend the Pts cell runs on is the
    mean of what exists, which is the built page's rule with fewer inputs.
  * **The win bar's spread is the fallback one.** The built bar reads each
    player's week-to-week standard deviation off the projection board, which
    is not published; every player here takes the share-of-projection
    fallback the built page uses for a player it has no figure for.
  * **No best-lineup swap line.** It needs kickoffs and lock rules that the
    reader's own dashboard (/fantasy/roster/) already does properly, and
    guessing at the opponent's lineup is not worth a wrong answer.
"""

CSS = """<style>
.mm{margin:10px 0 18px}
.mm-head{display:flex;flex-wrap:wrap;gap:9px;align-items:baseline;margin:0 0 10px}
.mm-head h2{margin:0;font-size:18px}
.mm-note{font-size:12.5px;color:#64748b;margin:0 0 11px;line-height:1.5}
/* The reader's own matchup is first and says so - on the scoreboard, on the
   phone card and on the section itself. Every other matchup in the league is
   worth reading; this is the one they came for. */
.mm-tag{font-size:10.5px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;
  color:#1a7f4b;background:#d5efdd;border-radius:999px;padding:1px 7px;margin-left:8px;
  vertical-align:1px}
tr.mm-yours td{box-shadow:inset 0 2px 0 #1a7f4b,inset 0 -2px 0 #1a7f4b}
tr.mm-yours td:first-child{box-shadow:inset 4px 0 0 #1a7f4b,inset 0 2px 0 #1a7f4b,
  inset 0 -2px 0 #1a7f4b}
a.mu-card.mm-yours{border-color:#1a7f4b;box-shadow:inset 3px 0 0 #1a7f4b}
details.section.mm-yours>summary{color:#1a7f4b}
@media (prefers-color-scheme: dark){
  .mm-note{color:#8fa0b8}
  .mm-tag{color:#8ff0bd;background:#123c2e}
  tr.mm-yours td{box-shadow:inset 0 2px 0 #6ee7b7,inset 0 -2px 0 #6ee7b7}
  tr.mm-yours td:first-child{box-shadow:inset 4px 0 0 #6ee7b7,inset 0 2px 0 #6ee7b7,
    inset 0 -2px 0 #6ee7b7}
  a.mu-card.mm-yours{border-color:#6ee7b7;box-shadow:inset 3px 0 0 #6ee7b7}
  details.section.mm-yours>summary{color:#8ff0bd}
}
</style>"""

JS = """{% raw %}<script>
(function(){
  var KEY='gsSleeperLeague';
  var host=document.getElementById('mm-host');
  if(!host) return;
  var WEEK=parseInt(host.dataset.week||'0',10);
  var built=document.getElementById('mm-built');
  var W=window.GSWeek;
  var CTX=null, PROJ={}, WEEKPROJ={}, INDEX={}, SLOTS=[], BENCH={BN:1,IR:1,TAXI:1};
  var LEAGUE_ID='';
  var AVATAR='https://sleepercdn.com/avatars/thumbs/';

  function saved(){
    try{ return JSON.parse(localStorage.getItem(KEY)||'null'); }catch(e){ return null; }
  }
  function esc(s){ return W.esc(s); }
  function fmt(v){ return W.fmt(v); }

  // ----- one player ------------------------------------------------------- //

  /** Name, position, team and injury for a rostered id, best source first:
   *  this week's projection row (his current team), then the player index.
   *  Mirrors fantasy.site.matchups.player_card. */
  function card(pid){
    var key=String(pid), meta=INDEX[key]||[], row=WEEKPROJ[key]||[];
    if(key.length<=3 && /^[A-Za-z]+$/.test(key))
      return {id:key, name:key+' D/ST', pos:'DEF', team:key, injury:''};
    return {id:key, name:meta[0]||('Player '+key), pos:meta[1]||'',
            team:row[3]||meta[2]||'', injury:row[4]||''};
  }

  /** This site's own projection for him, zero on a bye - the built page's
   *  rule, and the one `projFor` already applies to the blend. */
  function gsFor(c){
    if(c.team && CTX.teams && !CTX.teams[c.team]) return 0;
    var v=CTX.gs&&CTX.gs[c.id];
    return v==null?null:v;
  }

  /** The blend the Pts cell runs on: the mean of the sources that have him. */
  function blend(c){
    return W.projFor(CTX, c.id, c.team, PROJ[c.id]);
  }

  // ----- one roster ------------------------------------------------------- //

  /** [{pid, slot}] in lineup order - starters by slot, then bench, then IR:
   *  fantasy.site.matchups.roster_rows, in the browser. */
  function rosterRows(row, reserve){
    var starters=row.starters||[], rows=[], started={}, ir={};
    starters.forEach(function(pid,i){
      rows.push({pid:String(pid), slot:SLOTS[i]||'?'});
      started[String(pid)]=1;
    });
    (reserve||[]).forEach(function(p){ if(!started[String(p)]) ir[String(p)]=1; });
    (row.players||[]).forEach(function(p){
      var key=String(p);
      if(!started[key] && !ir[key]) rows.push({pid:key, slot:'BN'});
    });
    (row.players||[]).forEach(function(p){
      var key=String(p);
      if(ir[key]) rows.push({pid:key, slot:'IR'});
    });
    return rows;
  }

  function side(row, roster, name, mgr, avatar){
    var rows=rosterRows(row, (roster&&roster.reserve)||[]);
    var pts=row.players_points||{};
    var starters=[], bench=[];
    rows.forEach(function(r){ (BENCH[r.slot]?bench:starters).push(r); });
    var gs=0, sp=0, exp=0, varr=0, states={};
    starters.forEach(function(r){
      if(r.pid==='0') return;
      var c=card(r.pid), g=W.gameFor(CTX, c.team);
      gs+=gsFor(c)||0;
      sp+=PROJ[c.id]||0;
      var e=W.expected(pts[c.id], blend(c), g);
      exp+=e[0]; varr+=e[1];
      states[g?(g.state||'pre'):'bye']=1;
    });
    var total=Number(row.points||0);
    // Done when nothing is still to come; a bye is not something to wait for.
    var st=(!states['pre']&&!states['in'])?'post'
      :((total>0||states['in']||states['post'])?'in':'pre');
    var set=(roster&&roster.settings)||{};
    return {key:String(row.roster_id), name:name, mgr:mgr, avatar:avatar,
            rec:(set.wins||0)+'-'+(set.losses||0)+(set.ties?('-'+set.ties):''),
            rows:rows, starters:starters, bench:bench, pts:pts, total:total,
            gs:gs, sp:sp, exp:exp, varr:varr, state:st};
  }

  // ----- the roster table ------------------------------------------------- //

  var N_COLS=6;

  function playerRow(r, s){
    if(r.pid==='0')
      return '<tr class="starter"><td class="mu-pts">&mdash;</td>'
        +'<td class="mu-slot">'+esc(r.slot)+'</td>'
        +'<td class="mu-p"><span class="mu-meta">empty</span></td><td class="mu-g"></td>'
        +'<td>&mdash;</td><td>&mdash;</td></tr>';
    var c=card(r.pid), g=W.gameFor(CTX, c.team), p=s.pts[c.id];
    var inj=c.injury
      ? '<span class="inj" title="'+esc(c.injury)+'">'+esc(tag(c.injury))+'</span>' : '';
    return '<tr class="'+(BENCH[r.slot]?'bench':'starter')
      +((g&&g.state==='in')?' live':'')+((g&&g.state==='post')?' done':'')
      +'" data-pid="'+esc(c.id)
      +'" data-team="'+esc(c.team)+'">'
      +'<td class="mu-pts">'+W.hybridScore(p, blend(c), g)+'</td>'
      +'<td class="mu-slot">'+esc(r.slot)+'</td>'
      +'<td class="mu-p"><span class="mu-pc"><span class="nm">'+W.logo(c.team,'mu-logo')
      +esc(c.name)+'</span> <span class="mu-lbl"><span class="mu-meta">'+esc(c.pos)
      +((c.team&&c.pos!=='DEF')?(' \\u00b7 '+esc(c.team)):'')+'</span>'+inj+'</span></span></td>'
      +'<td class="mu-g">'+W.gameCell(g)+'</td>'
      +'<td class="mu-gs">'+fmt(gsFor(c))+'</td>'
      +'<td>'+fmt(PROJ[c.id]!=null?PROJ[c.id]:null)+'</td></tr>';
  }
  var INJURY={Questionable:'Q',Doubtful:'D',Out:'O',IR:'IR',PUP:'PUP',
              Sus:'SUS',NA:'NA',DNR:'DNR',COV:'COV'};
  function tag(v){ return INJURY[v]||String(v).slice(0,3).toUpperCase(); }

  function rosterTable(s){
    var body=s.starters.map(function(r){ return playerRow(r,s); }).join('');
    var hexp=0;
    s.starters.forEach(function(r){
      if(r.pid==='0') return;
      var c=card(r.pid);
      hexp+=W.expected(s.pts[c.id], blend(c), W.gameFor(CTX, c.team))[0];
    });
    body+='<tr class="total"><td class="mu-pts">'
      +W.scoreCell(s.total, hexp, s.state, hexp, true)
      +'</td><td></td><td class="mu-p">Starters</td><td></td>'
      +'<td class="mu-gs">'+fmt(s.gs)+'</td><td>'+fmt(s.sp)+'</td></tr>';
    if(s.bench.length){
      body+='<tr class="sep"><td colspan="'+N_COLS+'">Bench</td></tr>'
        +s.bench.map(function(r){ return playerRow(r,s); }).join('');
    }
    return '<div class="table-scroll" data-roster="'+esc(s.key)+'">'
      +'<table class="mu-roster"><thead><tr>'
      +"<th class='mu-pts' title='Points scored, with the live expected final under "
      +"them; the blended projection before kickoff'>Pts</th>"
      +'<th>Slot</th><th>Player</th><th>Game</th>'
      +"<th title='GordStats projection for this week'>GS</th>"
      +"<th title='Sleeper&#39;s own projection for this week'>Slpr</th>"
      +'</tr></thead><tbody>'+body+'</tbody></table></div>';
  }

  // ----- the paired phone view -------------------------------------------- //

  function pairView(a, b){
    function cell(s, r){
      if(!r || r.pid==='0') return W.pairCell(null);
      var c=card(r.pid);
      return W.pairCell(c, s.pts[c.id], blend(c), W.gameFor(CTX, c.team));
    }
    function rows(la, lb, bench){
      var out='', n=Math.max(la.length, lb.length);
      for(var i=0;i<n;i++){
        var ra=la[i]||null, rb=lb[i]||null;
        out+='<div class="mu-pr'+(bench?' bench':'')+'">'+cell(a,ra)
          +'<div class="mu-pslot">'+esc((ra||rb||{}).slot||'')+'</div>'
          +cell(b,rb)+'</div>';
      }
      return out;
    }
    var total='<div class="mu-pr total">'
      +'<div class="mu-pp"><div class="mu-pn"><span class="nm">Starters</span></div>'
      +'<span class="mu-pts">'+fmt(a.total)+'</span></div><div class="mu-pslot"></div>'
      +'<div class="mu-pp"><span class="mu-pts">'+fmt(b.total)+'</span>'
      +'<div class="mu-pn"><span class="nm">Starters</span></div></div></div>';
    var bench='';
    if(a.bench.length||b.bench.length)
      bench='<div class="mu-pbench-h">Bench</div>'+rows(a.bench, b.bench, true);
    return '<div class="mu-pair">'+rows(a.starters, b.starters, false)+total+bench+'</div>';
  }

  // ----- a matchup, and the scoreboard over them --------------------------- //

  function avatarImg(src){
    return src?('<img class="mu-tlogo" src="'+esc(src)+'" alt="" loading="lazy">'):'';
  }
  function label(s){
    return esc(s.name)
      +((s.mgr&&s.name.indexOf(s.mgr)<0)?(' <span class="mu-meta">('+esc(s.mgr)+')</span>'):'');
  }

  function matchup(a, b, anchor, started, yours){
    var lead=(!started||a.total===b.total)?null:(a.total>b.total?'a':'b');
    var final=(a.state==='post'&&b.state==='post');
    function sideHtml(s, which){
      var big=started?fmt(s.total):fmt(s.gs);
      var sub=started
        ? ('GordStats <b>'+fmt(s.gs)+'</b> \\u00b7 Sleeper <b>'+fmt(s.sp)+'</b>')
        : ('projected \\u00b7 Sleeper <b>'+fmt(s.sp)+'</b>');
      return '<div class="mu-side '+(which==='b'?'r':'')+'">'+avatarImg(s.avatar)
        +'<div><div class="nm">'+label(s)+'<span class="rec">'+esc(s.rec)+'</span></div>'
        +'<div class="num'+(lead===which?' lead':'')+'">'+big+'</div>'
        +'<div class="sub">'+sub+'</div></div></div>';
    }
    var wpa=W.winProb(a.exp, a.varr, b.exp, b.varr);
    var bar=final?'':('<div class="mu-wp"><i style="width:'+Math.round(wpa*100)+'%"></i>'
      +'<i class="b" style="width:'+Math.round((1-wpa)*100)+'%"></i></div>'
      +'<div class="mu-wp-lbl"><span>'+Math.round(wpa*100)+'% (GordStats)</span>'
      +'<span>'+Math.round((1-wpa)*100)+'%</span></div>');
    var edge=a.gs-b.gs;
    var note=final
      ? ('GordStats projected '+fmt(a.gs)+'\\u2013'+fmt(b.gs)+' going in, Sleeper '
         +fmt(a.sp)+'\\u2013'+fmt(b.sp)+'.')
      : ('GordStats has <b>'+esc(edge>=0?a.name:b.name)+'</b> by '
         +Math.abs(edge).toFixed(1)+' on projection ('+fmt(a.gs)+'\\u2013'+fmt(b.gs)
         +'); Sleeper has '+fmt(a.sp)+'\\u2013'+fmt(b.sp)+'.');
    var body='<div class="mu-head">'+sideHtml(a,'a')
      +'<div class="mu-mid">'+(final?'Final':(started?'Live':'Preview'))+'</div>'
      +sideHtml(b,'b')+'</div>'+bar+'<p class="mu-note">'+note+'</p>'
      +pairView(a,b)
      +'<div class="mu-grid"><div><div class="mu-who">'+esc(a.name)+'</div>'
      +rosterTable(a)+'</div><div><div class="mu-who">'+esc(b.name)+'</div>'
      +rosterTable(b)+'</div></div>';
    return '<details class="section'+(yours?' mm-yours':'')+'" id="'+anchor
      +'" open><summary>'+esc(a.name)
      +'<span class="mu-vs-sum">vs</span>'+esc(b.name)
      +(yours?'<span class="mm-tag">yours</span>':'')+'</summary>'+body+'</details>';
  }

  function board(pairs, started){
    var cards=pairs.map(function(p){
      var done=(p.a.state==='post'&&p.b.state==='post');
      function one(s, wp){
        var num=started?('<span class="num">'+fmt(s.total)+'</span>')
          :('<span class="num proj" title="GordStats projection">'+fmt(s.gs)+'</span>');
        return '<div class="mu-cs">'+avatarImg(s.avatar)+'<span class="nm">'+esc(s.name)
          +'</span>'+num
          +(done?'':('<span class="wp">'+Math.round(wp*100)+'%</span>'))+'</div>';
      }
      return '<a class="mu-card'+(p.mine?' mm-yours':'')+'" href="#'+p.anchor+'">'
        +one(p.a,p.wp)+one(p.b,1-p.wp)+'</a>';
    }).join('');
    function num(v, o){
      var lead=(v!=null&&o!=null&&v>o);
      return '<td>'+(lead?'<b class=lead>':'')+fmt(v)+(lead?'</b>':'')+'</td>';
    }
    var rows=pairs.map(function(p){
      var a=p.a, b=p.b;
      return '<tr'+(p.mine?' class="mm-yours"':'')+'><td class="mu-t"><a href="#'
        +p.anchor+'">'+avatarImg(a.avatar)
        +esc(a.name)+'</a></td>'
        +(started?num(a.total,b.total):'')+num(a.sp,b.sp)+num(a.gs,b.gs)
        +'<td class="mu-vs">vs</td>'
        +num(b.gs,a.gs)+num(b.sp,a.sp)+(started?num(b.total,a.total):'')
        +'<td class="mu-t r"><a href="#'+p.anchor+'">'+esc(b.name)+avatarImg(b.avatar)
        +'</a></td></tr>';
    }).join('');
    var pts=started?'<th>Pts</th>':'';
    return '<div class="mu-cards">'+cards+'</div>'
      +'<div class="mu-board-wrap"><div class="table-scroll">'
      +'<table class="mu-board"><thead><tr>'
      +'<th>Team</th>'+pts
      +"<th title='Sleeper&#39;s projection for the lineup as set'>Sleeper</th>"
      +"<th title='GordStats projected total for the lineup as set'>GS Proj</th>"
      +'<th></th><th>GS Proj</th><th>Sleeper</th>'+pts+'<th>Team</th>'
      +'</tr></thead><tbody>'+rows+'</tbody></table></div></div>';
  }

  // ----- putting the week together ---------------------------------------- //

  function render(rows, rosters, users, info){
    var byUser={}, byRoster={};
    users.forEach(function(u){
      var src=(u.metadata&&u.metadata.avatar)||(u.avatar?(AVATAR+u.avatar):'');
      byUser[u.user_id]={name:(u.metadata&&u.metadata.team_name)||u.display_name||'Team',
                         mgr:u.display_name||'', avatar:src};
    });
    rosters.forEach(function(r){ byRoster[String(r.roster_id)]=r; });

    function who(r){
      var ro=byRoster[String(r.roster_id)]||{};
      return byUser[ro.owner_id]||{name:'Roster '+r.roster_id, mgr:'', avatar:''};
    }
    // An odd league leaves somebody without an opponent, and Sleeper says so
    // by giving that roster no matchup id. Dropping the row would drop the
    // team off the week entirely, so it is named instead.
    var by={}, idle=[];
    rows.forEach(function(r){
      if(r.matchup_id==null){ idle.push(who(r).name); return; }
      (by[r.matchup_id]=by[r.matchup_id]||[]).push(r);
    });
    var ids=Object.keys(by).sort(function(a,b){ return a-b; });
    if(!ids.length){
      host.innerHTML='<p class="mm-note">Sleeper has no week '+WEEK
        +' matchups for this league yet.</p>';
      return;
    }
    var pairs=[];
    ids.forEach(function(mid, i){
      var pair=by[mid];
      var sides=pair.slice(0,2).map(function(r){
        var u=who(r);
        return side(r, byRoster[String(r.roster_id)]||{}, u.name, u.mgr, u.avatar);
      });
      if(sides.length!==2){ idle.push(sides.length?sides[0].name:''); return; }
      pairs.push({anchor:'mm-'+mid, a:sides[0], b:sides[1],
                  wp:W.winProb(sides[0].exp, sides[0].varr, sides[1].exp, sides[1].varr)});
    });
    var started=pairs.some(function(p){
      return p.a.total>0 || p.b.total>0 || p.a.state!=='pre' || p.b.state!=='pre';
    });
    // Theirs first. The built page has no "you" to put first - it is one
    // league's own page - but a reader opening this has come to see one
    // matchup, and it was wherever Sleeper's ids happened to put it.
    var names={};
    rosters.forEach(function(r){ names[String(r.roster_id)]=who(r).name; });
    var mine=GSL.myRoster({rosters:rosters, names:names}, LEAGUE_ID);
    pairs.forEach(function(p){
      p.mine=!!mine && (p.a.key===String(mine) || p.b.key===String(mine));
      // Their own team on the left, so the two sides never swap between the
      // scoreboard and the section below it.
      if(p.mine && p.b.key===String(mine)){
        var t=p.a; p.a=p.b; p.b=t; p.wp=1-p.wp;
      }
    });
    pairs.sort(function(x,y){ return (y.mine?1:0)-(x.mine?1:0); });
    var off=idle.filter(Boolean);
    host.innerHTML=board(pairs, started)
      + (off.length?('<p class="mm-note">No opponent this week: '
         +off.map(esc).join(', ')+'.</p>'):'')
      + pairs.map(function(p){
          return matchup(p.a, p.b, p.anchor, started, p.mine); }).join('');
  }

  function show(league){
    var id=league.id;
    LEAGUE_ID=String(id);
    host.innerHTML='<p class="mm-note">Reading '+esc(league.name||'your league')+'\\u2026</p>';
    if(built) built.hidden=true;
    var API='https://api.sleeper.app/v1/league/'+encodeURIComponent(id);
    Promise.all([
      fetch(API+'/matchups/'+WEEK).then(function(r){return r.ok?r.json():[];}),
      fetch(API+'/rosters').then(function(r){return r.ok?r.json():[];}),
      fetch(API+'/users').then(function(r){return r.ok?r.json():[];}),
      GSL.players(),
      fetch(API).then(function(r){return r.ok?r.json():{};}).catch(function(){return {};}),
      GSL.week(),
      W.load()
    ]).then(function(out){
      var rows=out[0]||[], rosters=out[1]||[], users=out[2]||[];
      INDEX=out[3]||{};
      var info=out[4]||{}, wk=out[5]||{proj:{}};
      CTX=out[6]||{teams:{},gs:{}};
      WEEKPROJ=wk.proj||{};
      // Sleeper's three bases, as everywhere else: a half-PPR league must not
      // be shown PPR numbers.
      var basis=GSL.basis(info);
      PROJ=GSL.points(wk, basis.index);
      SLOTS=(info.roster_positions||[]).filter(function(x){ return !BENCH[x]; });
      var bar=document.getElementById('mm-bar');
      if(bar){
        bar.innerHTML='<h2>'+esc(league.name||info.name||'Your league')
          +' &middot; week '+WEEK+'</h2>'
          +'<span class="mm-note">Live points from Sleeper, in this page\\u2019s layout. '
          +'<b>Pts</b> is the blend of the two projections below it until a player\\u2019s '
          +'game kicks off, then his points with the expected final under them. Scored on '
          +esc(basis.name)+(basis.custom?' (the nearest of Sleeper\\u2019s three bases to '
          +'this league\\u2019s scoring)':'')+'. The built league\\u2019s four sources, '
          +'median tracker and lineup advice are its own - your best lineup is on the '
          +'<a href="/fantasy/roster/">team dashboard</a>.</span>';
      }
      render(rows, rosters, users, info);
    }).catch(function(){
      host.innerHTML='<p class="mm-note">Could not read that league from Sleeper.</p>';
    });
  }

  var have=saved();
  if(!have||!have.id||have.site) return;      // the built league is the default
  show(have);
})();
</script>{% endraw %}"""


def section(week: int, year: int) -> str:
    """The container the script fills, and the note explaining what it is."""
    return (CSS + f"<div class='mm' id='mm-wrap'>"
            f"<div class='mm-head' id='mm-bar'></div>"
            f"<div id='mm-host' data-week='{int(week)}' data-year='{int(year)}'></div>"
            "</div>")
