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
@media (prefers-color-scheme: dark){
  .hi-note,.hi-none,.hi-load{color:#aab7c9}
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
              status:lg.status, teams:teams,
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
    return '<h2>Champions</h2><table class="sticky-table"><thead><tr><th>Season</th>'
      +'<th>Winner</th><th>Record</th><th>Points</th></tr></thead><tbody>'
      +rows+'</tbody></table>';
  }

  function renderSeasons(seasons){
    var html='<h2>Season by season</h2>';
    seasons.forEach(function(s){
      var teams=s.teams.slice().sort(function(a,b){
        return (b.wins-a.wins) || (b.pf-a.pf);});
      html+='<h3 style="margin:14px 0 4px;font-size:15px">'+esc(s.season)
        +(s.status&&s.status!=='complete'?' <span class="hi-sub">in progress</span>':'')
        +'</h3><table class="sticky-table"><thead><tr><th>Team</th><th>Record</th>'
        +'<th>Points for</th><th>Points against</th></tr></thead><tbody>';
      teams.forEach(function(t){
        html+='<tr'+(t.champion?' class="me"':'')+'><td>'
          +(t.champion?'<span class="hi-crown">&#9818;</span> ':'')+esc(t.team)
          +'<span class="hi-sub">'+esc(t.manager)+'</span></td>'
          +'<td class="n">'+recordOf(t)+'</td>'
          +'<td class="n">'+t.pf.toFixed(1)+'</td>'
          +'<td class="n">'+t.pa.toFixed(1)+'</td></tr>';
      });
      html+='</tbody></table>';
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
    return '<h2>All time</h2><table class="sticky-table"><thead><tr><th>Manager</th>'
      +'<th>Seasons</th><th>Titles</th><th>Record</th><th>Points</th></tr></thead><tbody>'
      + rows.map(function(r){
          return '<tr><td>'+esc(r.team)+'<span class="hi-sub">'+esc(r.manager)
            +'</span></td><td class="n">'+r.seasons+'</td>'
            +'<td class="n">'+(r.titles?'<span class="hi-crown">'+r.titles+'</span>':'0')
            +'</td><td class="n">'+r.wins+'-'+r.losses+(r.ties?'-'+r.ties:'')+'</td>'
            +'<td class="n">'+r.pf.toFixed(0)+'</td></tr>';
        }).join('')
      +'</tbody></table>';
  }

  /** Who played whom, every regular-season week of every season. */
  function headToHead(seasons){
    var jobs=[];
    seasons.forEach(function(s){
      var last=Math.max(1,(s.playoff_start||15)-1);
      var owner={};
      s.teams.forEach(function(t){ owner[t.roster_id]=t.owner; });
      for(var w=1; w<=last; w++){
        jobs.push(get('/league/'+s.league_id+'/matchups/'+w)
          .then(function(rows){ return {rows:rows||[], owner:owner}; }));
      }
    });
    return Promise.all(jobs).then(function(weeks){
      var h2h={};
      weeks.forEach(function(wk){
        var by={};
        wk.rows.forEach(function(r){
          if(r.matchup_id==null) return;
          (by[r.matchup_id]=by[r.matchup_id]||[]).push(r);
        });
        Object.keys(by).forEach(function(m){
          var pair=by[m];
          if(pair.length!==2) return;
          var a=pair[0], b=pair[1];
          var ao=wk.owner[a.roster_id], bo=wk.owner[b.roster_id];
          if(!ao||!bo||ao===bo) return;
          if((a.points||0)===(b.points||0)) return;       // a tie counts for neither
          var win=(a.points||0)>(b.points||0)?ao:bo;
          var lose=win===ao?bo:ao;
          (h2h[win]=h2h[win]||{})[lose]=((h2h[win]||{})[lose]||0)+1;
        });
      });
      return h2h;
    });
  }

  function renderH2H(seasons, h2h){
    var names={};
    seasons.forEach(function(s){
      s.teams.forEach(function(t){
        if(t.owner && !names[t.owner]) names[t.owner]=t.manager||t.team;
      });
    });
    var ids=Object.keys(names);
    if(ids.length<2) return '';
    ids.sort(function(a,b){ return names[a].toLowerCase()<names[b].toLowerCase()?-1:1; });
    var html='<h2>Head to head</h2><p class="hi-note">Regular-season meetings, '
      +'every season. Read across: wins for the manager on the left.</p>'
      +'<div class="table-scroll"><table class="sticky-table hi-h2h"><thead><tr><th class="row"></th>'
      + ids.map(function(i){return '<th>'+esc(names[i].slice(0,10))+'</th>';}).join('')
      +'</tr></thead><tbody>';
    ids.forEach(function(a){
      html+='<tr><td class="row">'+esc(names[a])+'</td>';
      ids.forEach(function(b){
        if(a===b){ html+='<td class="self">&middot;</td>'; return; }
        var w=((h2h[a]||{})[b])||0, l=((h2h[b]||{})[a])||0;
        html+='<td>'+(w+l
          ? '<span class="'+(w>l?'hi-w':w<l?'hi-l':'')+'">'+w+'&#8211;'+l+'</span>'
          : '<span class="hi-load">&mdash;</span>')+'</td>';
      });
      html+='</tr>';
    });
    return html+'</tbody></table></div>';
  }

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
      headToHead(seasons).then(function(h2h){
        var slot=document.getElementById('hi-h2h');
        if(slot) slot.innerHTML=renderH2H(seasons, h2h)
          || '<h2>Head to head</h2><p class="hi-none">Not enough played yet.</p>';
      });
    })
    .catch(function(){
      host.innerHTML='<p class="hi-none">Could not read that league from Sleeper.</p>';
    });
})();
</script>{% endraw %}"""


def section() -> str:
    return CSS + "<div class='hi' id='hi-host'></div>"
