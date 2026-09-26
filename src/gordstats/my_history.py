"""
League history for whichever league the reader has picked (/fantasy/history/).

Everything here comes from Sleeper, keylessly, in the browser: a league's
seasons chain backwards through `previous_league_id`, and each season gives up
its final records (one call), its champion (one call at the winners bracket)
and, walked week by week, who played whom.

Managers are identified by `owner_id`, which is stable across seasons; team
names are not - people rename their team most years - so the all-time table
aggregates on the owner and shows the name they go by now.

Records here are Sleeper's own, which in a league playing a weekly median
counts two results a week. That is why a fourteen-week season shows a 28-game
record, and the page says so rather than leaving it to be puzzled out.

The cheap half (records, champions) renders first; head-to-head needs every
week of every season and fills in behind it.
"""


CSS = """<style>
.hi{margin:8px 0 20px}
.hi h2{margin:20px 0 6px;font-size:18px}
.hi-note{font-size:12.5px;color:#64748b;margin:0 0 10px;line-height:1.5}
.hi-none{font-size:14px;color:#475569}
.hi-crown{color:#b45309;font-weight:800}
.hi-sub{font-size:11px;color:#94a3b8;margin-left:5px}
table.hi-h2h td,table.hi-h2h th{text-align:center;font-size:12.5px;padding:5px 7px}
table.hi-h2h th.row,table.hi-h2h td.row{text-align:left;font-weight:700;white-space:nowrap;
  position:sticky;left:0;background:#eef2f7;z-index:1}
table.hi-h2h td.self{background:#f1f5f9;color:#94a3b8}
.hi-w{color:#15803d;font-weight:700}
.hi-l{color:#b91c1c}
.hi-load{font-size:12.5px;color:#64748b}
/* The controls over the grid: a season, a book, a manager. */
.hi-bar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:0 0 10px;
  font-size:13px;color:#475569}
.hi-bar label{display:inline-flex;align-items:center;gap:7px;min-width:0}
.hi-bar select{font:inherit;font-size:13px;padding:6px 10px;border:1px solid #cbd5e1;
  border-radius:8px;background:#fff;color:#0f172a;cursor:pointer;max-width:min(100%,320px)}
.hi-seg{display:inline-flex;background:#e2e8f0;border-radius:999px;padding:3px}
.hi-seg button{font:inherit;font-size:12.5px;font-weight:700;border:0;border-radius:999px;
  padding:5px 12px;background:transparent;color:#475569;cursor:pointer}
.hi-seg button.on{background:#fff;color:#0f172a;box-shadow:0 1px 3px rgba(15,23,42,.2)}
/* One manager's season: the two books, then what he scores and gives up. */
.hi-tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));
  gap:8px;margin:0 0 12px}
.hi-tile{border:1px solid #e2e8f0;border-radius:8px;background:#fff;padding:8px 11px;
  text-align:center}
.hi-tile b{display:block;font-size:18px;font-weight:800;color:#0f172a;line-height:1.2}
.hi-tile span{font-size:11px;color:#64748b}
/* Rival, nemesis, favourite - the three relationships worth naming. */
.hi-rivals{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));
  gap:8px;margin:0 0 14px}
.hi-rival{border-left:4px solid #cbd5e1;background:#f8fafc;border-radius:6px;padding:8px 11px}
.hi-rival.rival{border-color:#2a78d6}
.hi-rival.nemesis{border-color:#b91c1c}
.hi-rival.victim{border-color:#15803d}
.hi-rival .k{display:block;font-size:11px;text-transform:uppercase;letter-spacing:.04em;
  color:#64748b;font-weight:700}
.hi-rival .v{display:block;font-size:17px;font-weight:800;color:#0f172a}
.hi-rival .s{display:block;font-size:12px;color:#64748b}
@media (max-width:560px){
  .hi-bar{gap:7px}
  .hi-bar select{flex:1;min-width:0;max-width:none}
  .hi-seg button{padding:5px 9px;font-size:12px}
}
@media (prefers-color-scheme: dark){
  .hi-note,.hi-none,.hi-load{color:#aab7c9}
  .hi-bar{color:#aab7c9}
  .hi-bar select{background:#16203a;border-color:#2b3852;color:#dde5ef}
  .hi-bar select option{background:#16203a;color:#dde5ef}
  .hi-seg{background:#223052}
  .hi-seg button{color:#aab7c9}
  .hi-seg button.on{background:#0b1220;color:#e8eef7}
  .hi-tile{background:#16203a;border-color:#2b3852}
  .hi-tile b{color:#e8eef7}
  .hi-tile span{color:#aab7c9}
  .hi-rival{background:#16203a;border-left-color:#2b3852}
  .hi-rival .k,.hi-rival .s{color:#aab7c9}
  .hi-rival .v{color:#f1f5f9}
  table.hi-h2h th.row,table.hi-h2h td.row{background:#223052}
  table.hi-h2h td.self{background:#1b2540;color:#64748b}
  .hi-crown{color:#e0a92a}
  .hi-w{color:#6ee7b7}
  .hi-l{color:#ff9b91}
}
/* The tables are the site's `sticky-table` inside `.table-scroll` - the pair
   every built table on these pages uses. This section now sits beside them on
   League Home and Analytics, and two table styles on one page reads as two
   different features. `.n` stays: it right-aligns the figures these tables
   put in text columns. */
table.sticky-table td.n{text-align:right;font-variant-numeric:tabular-nums}
table.sticky-table tr.me td{background:#fffbeb}
@media (prefers-color-scheme: dark){
  table.sticky-table tr.me td{background:#33301a}
}
</style>"""

JS = """{% raw %}<script>
(function(){
  var host=document.getElementById('hi-host');
  if(!host||!window.GSL) return;
  var have=GSL.saved();
  if(!have||!have.id||have.site){
    // Drawn twice: once now, and again when the account call settles, because
    // whether to offer a sign-in or a league picker is not known at first paint.
    var none=function(){ host.innerHTML=window.GSLeague
      ? GSLeague.empty('hi-none','history')
      : '<p class="hi-none">Pick a league above to see its history.</p>'; };
    none();
    if(window.GSLeague&&GSLeague.ready) GSLeague.ready.then(none,none);
    return;
  }

  var API='https://api.sleeper.app/v1';
  var MAX_SEASONS=12;
  function get(path){
    return fetch(API+path).then(function(r){return r.ok?r.json():null;})
      .catch(function(){return null;});
  }
  function esc(v){
    return String(v==null?'':v).replace(/[&<>"]/g,function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});
  }
  function pts(s){
    // Sleeper keeps points as an integer and its decimal part, separately.
    return (s.fpts||0)+((s.fpts_decimal||0)/100);
  }
  function against(s){
    return (s.fpts_against||0)+((s.fpts_against_decimal||0)/100);
  }

  /** Every season of this league, newest first. */
  function chain(id){
    var out=[], seen={};
    function step(lid){
      if(!lid||seen[lid]||out.length>=MAX_SEASONS) return Promise.resolve(out);
      seen[lid]=1;
      return get('/league/'+lid).then(function(d){
        if(!d||!d.league_id) return out;
        out.push(d);
        return step(d.previous_league_id);
      });
    }
    return step(id);
  }

  /** One season: who was in it, what they did, and who won. */
  function season(lg){
    return Promise.all([
      get('/league/'+lg.league_id+'/rosters'),
      get('/league/'+lg.league_id+'/users'),
      get('/league/'+lg.league_id+'/winners_bracket')
    ]).then(function(o){
      var rosters=o[0]||[], users=o[1]||[], bracket=o[2]||[];
      var who={};
      users.forEach(function(u){
        who[u.user_id]={team:(u.metadata&&u.metadata.team_name)||u.display_name||'Team',
                        manager:u.display_name||''};
      });
      // The championship game is the one placing first; a season still being
      // played has no bracket at all.
      var final=bracket.filter(function(m){return m.p===1;})[0];
      var championRoster=final?final.w:null;
      var teams=rosters.map(function(r){
        var s=r.settings||{};
        return {roster_id:r.roster_id, owner:r.owner_id,
                team:(who[r.owner_id]||{}).team||('Roster '+r.roster_id),
                manager:(who[r.owner_id]||{}).manager||'',
                wins:s.wins||0, losses:s.losses||0, ties:s.ties||0,
                pf:pts(s), pa:against(s),
                champion:r.roster_id===championRoster};
      });
      return {season:lg.season, league_id:lg.league_id, name:lg.name,
              status:lg.status, teams:teams, bracket:bracket,
              playoff_start:(lg.settings||{}).playoff_week_start||15};
    });
  }

  function recordOf(t){
    return t.wins+'-'+t.losses+(t.ties?'-'+t.ties:'');
  }

  function renderChampions(seasons){
    var done=seasons.filter(function(s){
      return s.teams.some(function(t){return t.champion;});});
    if(!done.length){
      return '<h2>Champions</h2><p class="hi-none">No season has finished yet.</p>';
    }
    var rows=done.map(function(s){
      var c=s.teams.filter(function(t){return t.champion;})[0];
      return '<tr><td class="n">'+esc(s.season)+'</td>'
        +'<td><span class="hi-crown">&#9818;</span> '+esc(c.team)
        +'<span class="hi-sub">'+esc(c.manager)+'</span></td>'
        +'<td class="n">'+recordOf(c)+'</td>'
        +'<td class="n">'+c.pf.toFixed(1)+'</td></tr>';
    }).join('');
    return '<h2>Champions</h2><div class="table-scroll"><table class="sticky-table"><thead><tr><th>Season</th>'
      +'<th>Winner</th><th>Record</th><th>Points</th></tr></thead><tbody>'
      +rows+'</tbody></table></div>';
  }

  function renderSeasons(seasons){
    var html='<h2>Season by season</h2>';
    seasons.forEach(function(s){
      var teams=s.teams.slice().sort(function(a,b){
        return (b.wins-a.wins) || (b.pf-a.pf);});
      html+='<h3 style="margin:14px 0 4px;font-size:15px">'+esc(s.season)
        +(s.status&&s.status!=='complete'?' <span class="hi-sub">in progress</span>':'')
        +'</h3><div class="table-scroll"><table class="sticky-table"><thead><tr><th>Team</th><th>Record</th>'
        +'<th>Points for</th><th>Points against</th></tr></thead><tbody>';
      teams.forEach(function(t){
        html+='<tr'+(t.champion?' class="me"':'')+'><td>'
          +(t.champion?'<span class="hi-crown">&#9818;</span> ':'')+esc(t.team)
          +'<span class="hi-sub">'+esc(t.manager)+'</span></td>'
          +'<td class="n">'+recordOf(t)+'</td>'
          +'<td class="n">'+t.pf.toFixed(1)+'</td>'
          +'<td class="n">'+t.pa.toFixed(1)+'</td></tr>';
      });
      html+='</tbody></table></div>';
    });
    return html;
  }

  function renderAllTime(seasons){
    var by={};
    seasons.forEach(function(s){
      s.teams.forEach(function(t){
        if(!t.owner) return;
        var a=by[t.owner]=by[t.owner]||{team:t.team, manager:t.manager, wins:0,
                                        losses:0, ties:0, pf:0, titles:0, seasons:0};
        a.wins+=t.wins; a.losses+=t.losses; a.ties+=t.ties;
        a.pf+=t.pf; a.seasons+=1;
        if(t.champion) a.titles+=1;
        // The name they go by now: seasons arrive newest first.
        if(a.seasons===1){ a.team=t.team; a.manager=t.manager; }
      });
    });
    var rows=Object.keys(by).map(function(k){return by[k];})
      .sort(function(a,b){
        return (b.titles-a.titles) || (b.wins-a.wins) || (b.pf-a.pf);});
    if(!rows.length) return '';
    return '<h2>All time</h2><div class="table-scroll"><table class="sticky-table"><thead><tr><th>Manager</th>'
      +'<th>Seasons</th><th>Titles</th><th>Record</th><th>Points</th></tr></thead><tbody>'
      + rows.map(function(r){
          return '<tr><td>'+esc(r.team)+'<span class="hi-sub">'+esc(r.manager)
            +'</span></td><td class="n">'+r.seasons+'</td>'
            +'<td class="n">'+(r.titles?'<span class="hi-crown">'+r.titles+'</span>':'0')
            +'</td><td class="n">'+r.wins+'-'+r.losses+(r.ties?'-'+r.ties:'')+'</td>'
            +'<td class="n">'+r.pf.toFixed(0)+'</td></tr>';
        }).join('')
      +'</tbody></table></div>';
  }

  //: A placement game is not a meeting anybody remembers - the same two
  //: constants fantasy.league.head_to_head uses.
  var PLACEMENT={3:1, 5:1};
  var MIN_SPLIT=3;          // meetings before an opponent can be a nemesis

  /** Every game anyone in this league has played, as one flat log.
   *
   *  `{season, week, kind, a, b, ap, bp}` with a and b as owner ids, because
   *  a manager keeps his owner id across seasons and renames his team most
   *  of them. Regular-season weeks come from the matchup feed; playoff games
   *  are the winners bracket's own pairings, looked up in the same feed for
   *  their scores, so a consolation game is not counted as a playoff meeting.
   */
  function gameLog(seasons){
    var jobs=[];
    seasons.forEach(function(s){
      var last=Math.max(1,(s.playoff_start||15)-1);
      var owner={};
      s.teams.forEach(function(t){ owner[t.roster_id]=t.owner; });
      var weeks={};
      for(var w=1; w<=last; w++) weeks[w]='regular';
      (s.bracket||[]).forEach(function(g){
        if(PLACEMENT[g.p] || !(g.t1&&g.t2)) return;
        weeks[(s.playoff_start||15)+(g.r||1)-1]='playoff';
      });
      Object.keys(weeks).forEach(function(w){
        jobs.push(get('/league/'+s.league_id+'/matchups/'+w).then(function(rows){
          return {season:s, week:parseInt(w,10), kind:weeks[w],
                  rows:rows||[], owner:owner};
        }));
      });
    });
    return Promise.all(jobs).then(function(weeks){
      var log=[];
      weeks.forEach(function(wk){
        var pts={};
        wk.rows.forEach(function(r){ pts[r.roster_id]=r.points||0; });
        if(wk.kind==='playoff'){
          (wk.season.bracket||[]).forEach(function(g){
            if(PLACEMENT[g.p] || !(g.t1&&g.t2)) return;
            if((wk.season.playoff_start||15)+(g.r||1)-1 !== wk.week) return;
            push(log, wk, wk.owner[g.t1], wk.owner[g.t2], pts[g.t1], pts[g.t2], 'playoff');
          });
          return;
        }
        var by={};
        wk.rows.forEach(function(r){
          if(r.matchup_id==null) return;
          (by[r.matchup_id]=by[r.matchup_id]||[]).push(r);
        });
        Object.keys(by).forEach(function(m){
          var pair=by[m];
          if(pair.length!==2) return;
          push(log, wk, wk.owner[pair[0].roster_id], wk.owner[pair[1].roster_id],
               pair[0].points||0, pair[1].points||0, 'regular');
        });
      });
      return log;
    });
  }

  function push(log, wk, a, b, ap, bp){
    if(!a||!b||a===b) return;
    if(ap==null||bp==null) return;
    if(!ap && !bp) return;                     // a week nobody has played yet
    log.push({season:wk.season.season, week:wk.week, kind:wk.kind,
              a:a, b:b, ap:ap, bp:bp});
  }

  /** One manager's games, from his own side. */
  function logFor(log, who, season){
    var out=[];
    log.forEach(function(g){
      if(season && g.season!==season) return;
      var mine=g.a===who, theirs=g.b===who;
      if(!mine && !theirs) return;
      var pf=mine?g.ap:g.bp, pa=mine?g.bp:g.ap;
      out.push({season:g.season, week:g.week, kind:g.kind,
                opp:mine?g.b:g.a, pf:pf, pa:pa, margin:pf-pa,
                result:pf>pa?'W':pf<pa?'L':'T'});
    });
    return out;
  }

  /** Per opponent, both books together and apart - team_profiles._splits. */
  function splits(games){
    var by={};
    games.forEach(function(g){
      var s=by[g.opp]=by[g.opp]||{opp:g.opp, games:0, w:0, l:0,
                                  rw:0, rl:0, pw:0, pl:0, margin:0, pf:0, reg:0};
      s.games++; s.margin+=g.margin;
      if(g.result==='W') s.w++; else if(g.result==='L') s.l++;
      if(g.kind==='playoff'){ if(g.result==='W') s.pw++; else if(g.result==='L') s.pl++; }
      else { if(g.result==='W') s.rw++; else if(g.result==='L') s.rl++; s.pf+=g.pf; s.reg++; }
    });
    return Object.keys(by).map(function(k){
      var s=by[k];
      s.margin=s.margin/s.games;
      s.pct=s.games?s.w/s.games:0;
      s.avg=s.reg?s.pf/s.reg:null;
      return s;
    });
  }

  /** Rival, nemesis, favourite - team_profiles.rivals, same rules. */
  function rivalsOf(games){
    var sp=splits(games);
    if(!sp.length) return {};
    var out={};
    out.rival=sp.slice().sort(function(a,b){
      return (b.games-a.games) || (Math.abs(a.margin)-Math.abs(b.margin));})[0];
    var enough=sp.filter(function(s){ return s.games>=MIN_SPLIT; });
    if(enough.length){
      var nem=enough.slice().sort(function(a,b){
        return (a.pct-b.pct) || (a.margin-b.margin);})[0];
      var fav=enough.slice().sort(function(a,b){
        return (b.pct-a.pct) || (b.margin-a.margin);})[0];
      if(nem.pct<0.5) out.nemesis=nem;
      if(fav.pct>0.5) out.victim=fav;
    }
    return out;
  }

  /** Manager names, once, by owner id - the id is what survives a rename. */
  function managers(seasons){
    var names={};
    seasons.forEach(function(s){
      s.teams.forEach(function(t){
        if(t.owner && !names[t.owner]) names[t.owner]=t.manager||t.team;
      });
    });
    return names;
  }

  /** The grid, for one book and one season (or all of them). */
  function renderGrid(names, log, kind, season){
    var ids=Object.keys(names);
    if(ids.length<2) return '<p class="hi-none">Not enough played yet.</p>';
    ids.sort(function(a,b){ return names[a].toLowerCase()<names[b].toLowerCase()?-1:1; });
    var w={};
    log.forEach(function(g){
      if(kind!=='all' && g.kind!==kind) return;
      if(season!=='all' && g.season!==season) return;
      if(g.ap===g.bp) return;
      var win=g.ap>g.bp?g.a:g.b, lose=win===g.a?g.b:g.a;
      (w[win]=w[win]||{})[lose]=((w[win]||{})[lose]||0)+1;
    });
    var any=false;
    var body='';
    ids.forEach(function(a){
      body+='<tr><td class="row">'+esc(names[a])+'</td>';
      ids.forEach(function(b){
        if(a===b){ body+='<td class="self">&middot;</td>'; return; }
        var won=((w[a]||{})[b])||0, lost=((w[b]||{})[a])||0;
        if(won+lost) any=true;
        body+='<td>'+(won+lost
          ? '<span class="'+(won>lost?'hi-w':won<lost?'hi-l':'')+'">'+won+'&#8211;'+lost+'</span>'
          : '<span class="hi-load">&mdash;</span>')+'</td>';
      });
      body+='</tr>';
    });
    if(!any) return '<p class="hi-none">No '+(kind==='playoff'?'playoff':'')
      +' meetings on record for that season.</p>';
    return '<div class="table-scroll"><table class="sticky-table hi-h2h">'
      +'<thead><tr><th class="row"></th>'
      + ids.map(function(i){return '<th>'+esc(names[i].slice(0,10))+'</th>';}).join('')
      +'</tr></thead><tbody>'+body+'</tbody></table></div>';
  }

  function rec(w,l){ return w+'&#8211;'+l; }

  /** One manager: the two books, the rivals, and every opponent. */
  function renderProfile(names, log, who, season){
    var games=logFor(log, who, season==='all'?null:season);
    if(!games.length)
      return '<p class="hi-none">No games on record for '+esc(names[who])
        +(season==='all'?'':' in '+esc(season))+'.</p>';
    var reg=games.filter(function(g){return g.kind==='regular';});
    var po=games.filter(function(g){return g.kind==='playoff';});
    function tally(list){
      var w=0,l=0,pf=0,pa=0;
      list.forEach(function(g){ if(g.result==='W')w++; else if(g.result==='L')l++;
                                pf+=g.pf; pa+=g.pa; });
      return {w:w, l:l, pf:list.length?pf/list.length:0, pa:list.length?pa/list.length:0};
    }
    var r=tally(reg), p=tally(po);
    var wins=games.filter(function(g){return g.result==='W';});
    var losses=games.filter(function(g){return g.result==='L';});
    function avg(list){
      if(!list.length) return null;
      return list.reduce(function(t,g){return t+g.margin;},0)/list.length;
    }
    var rv=rivalsOf(games);
    function card(kind, label, s){
      if(!s) return '';
      return '<div class="hi-rival '+kind+'"><span class="k">'+label+'</span>'
        +'<span class="v">'+esc(names[s.opp]||'Unknown')+'</span>'
        +'<span class="s">'+rec(s.w,s.l)+' in '+s.games+' meeting'
        +(s.games===1?'':'s')+' &middot; '+(s.margin>=0?'+':'')
        +s.margin.toFixed(1)+' a game</span></div>';
    }
    var tiles='<div class="hi-tiles">'
      +'<div class="hi-tile"><b>'+rec(r.w,r.l)+'</b><span>Regular season</span></div>'
      +'<div class="hi-tile"><b>'+(po.length?rec(p.w,p.l):'&mdash;')+'</b><span>Playoffs</span></div>'
      +'<div class="hi-tile"><b>'+r.pf.toFixed(1)+'</b><span>Points a game</span></div>'
      +'<div class="hi-tile"><b>'+r.pa.toFixed(1)+'</b><span>Allowed a game</span></div>'
      +'<div class="hi-tile"><b>'+(avg(wins)==null?'&mdash;':'+'+avg(wins).toFixed(1))
      +'</b><span>Average win</span></div>'
      +'<div class="hi-tile"><b>'+(avg(losses)==null?'&mdash;':avg(losses).toFixed(1))
      +'</b><span>Average loss</span></div></div>';
    var cards='<div class="hi-rivals">'+card('rival','Rival',rv.rival)
      +card('nemesis','Nemesis',rv.nemesis)+card('victim','Favourite opponent',rv.victim)
      +'</div>';
    var rows=splits(games).sort(function(a,b){ return b.games-a.games; })
      .map(function(s){
        var star=(rv.rival&&s.opp===rv.rival.opp)?' &#9733;':'';
        return '<tr><td>'+esc(names[s.opp]||'Unknown')+star+'</td>'
          +'<td class="n"><span class="'+(s.w>s.l?'hi-w':s.w<s.l?'hi-l':'')+'">'
          +rec(s.w,s.l)+'</span></td>'
          +'<td class="n">'+rec(s.rw,s.rl)+'</td>'
          +'<td class="n">'+(s.pw+s.pl?rec(s.pw,s.pl):'&mdash;')+'</td>'
          +'<td class="n">'+(s.avg==null?'&mdash;':s.avg.toFixed(1))+'</td>'
          +'<td class="n">'+(s.margin>=0?'+':'')+s.margin.toFixed(1)+'</td></tr>';
      }).join('');
    return tiles+cards
      +'<div class="table-scroll"><table class="sticky-table"><thead><tr>'
      +'<th>Opponent</th><th>Overall</th><th>Regular</th><th>Playoffs</th>'
      +'<th>Points a game</th><th>Margin</th></tr></thead><tbody>'
      +rows+'</tbody></table></div>';
  }

  /** The head-to-head block: a season, a book, and a manager, each a control
   *  that redraws the two things below it. All of it off one game log, so
   *  moving through seasons costs no further requests. */
  function wire(slot, seasons, log){
    var names=managers(seasons);
    var codes=seasons.map(function(s){ return s.season; });
    var state={season:'all', kind:'regular', who:null};
    var ids=Object.keys(names).sort(function(a,b){
      return names[a].toLowerCase()<names[b].toLowerCase()?-1:1; });
    state.who=ids.indexOf(String(MINE))>=0?String(MINE):ids[0];

    slot.innerHTML='<h2>Head to head</h2>'
      +'<div class="hi-bar">'
      +'<label>Season <select id="hi-season"><option value="all">All seasons</option>'
      + codes.map(function(c){ return '<option value="'+esc(c)+'">'+esc(c)+'</option>'; }).join('')
      +'</select></label>'
      +'<div class="hi-seg" id="hi-kind">'
      +'<button type="button" class="on" data-kind="regular">Regular season</button>'
      +'<button type="button" data-kind="playoff">Playoffs</button>'
      +'<button type="button" data-kind="all">Both</button></div>'
      +'</div>'
      +'<p class="hi-note" id="hi-legend"></p>'
      +'<div id="hi-grid"></div>'
      +'<h2>Managers</h2>'
      +'<div class="hi-bar"><label>Manager <select id="hi-who">'
      + ids.map(function(i){
          return '<option value="'+esc(i)+'"'+(i===state.who?' selected':'')+'>'
            +esc(names[i])+'</option>'; }).join('')
      +'</select></label></div><div id="hi-profile"></div>';

    function draw(){
      document.getElementById('hi-legend').innerHTML =
        (state.kind==='playoff'
          ? 'Winners-bracket elimination games only - placement games are not meetings anybody remembers. '
          : state.kind==='all' ? 'Regular season and winners-bracket playoffs together. '
          : 'Regular-season meetings, head to head. ')
        + 'Read across: wins for the manager on the left.';
      document.getElementById('hi-grid').innerHTML =
        renderGrid(names, log, state.kind, state.season);
      document.getElementById('hi-profile').innerHTML =
        renderProfile(names, log, state.who, state.season);
    }
    document.getElementById('hi-season').addEventListener('change', function(){
      state.season=this.value; draw(); });
    document.getElementById('hi-who').addEventListener('change', function(){
      state.who=this.value; draw(); });
    document.getElementById('hi-kind').addEventListener('click', function(e){
      var b=e.target.closest('button[data-kind]');
      if(!b) return;
      state.kind=b.dataset.kind;
      Array.prototype.forEach.call(this.querySelectorAll('button'), function(x){
        x.classList.toggle('on', x===b); });
      draw();
    });
    draw();
  }

  // Their own manager, so the profile opens on them rather than on whoever
  // sorts first - the same id the picker and the dashboard read.
  var MINE=(window.GSL&&GSL.mine?GSL.mine(have.id).uid:null)||'';

  host.innerHTML='<p class="hi-load">Reading '+esc(have.name||'your league')+'\\u2026</p>';
  chain(have.id)
    .then(function(lgs){
      if(!lgs.length) throw new Error('none');
      return Promise.all(lgs.map(season));
    })
    .then(function(seasons){
      var span=seasons.length>1
        ? seasons[seasons.length-1].season+'\\u2013'+seasons[0].season
        : seasons[0].season;
      var head='<p class="hi-note"><strong>'+esc(seasons[0].name||'This league')
        +'</strong> &middot; '+seasons.length+' season'+(seasons.length===1?'':'s')
        +' &middot; '+esc(span)+'. Records are Sleeper\\u2019s own: a league playing '
        +'a weekly median scores two results a week, which is why a fourteen-week '
        +'season can show a 28-game record.</p>';
      host.innerHTML=head+renderChampions(seasons)+renderAllTime(seasons)
        +'<div id="hi-h2h"><h2>Head to head</h2>'
        +'<p class="hi-load">Reading every week of every season\\u2026</p></div>'
        +renderSeasons(seasons);

      // The expensive half, once the rest is on screen.
      gameLog(seasons).then(function(log){
        var slot=document.getElementById('hi-h2h');
        if(!slot) return;
        if(!log.length){
          slot.innerHTML='<h2>Head to head</h2>'
            +'<p class="hi-none">Not enough played yet.</p>';
          return;
        }
        wire(slot, seasons, log);
      });
    })
    .catch(function(){
      host.innerHTML='<p class="hi-none">Could not read that league from Sleeper.</p>';
    });
})();
</script>{% endraw %}"""


def section() -> str:
    return CSS + "<div class='hi' id='hi-host'></div>"
