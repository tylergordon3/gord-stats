"""
Waivers and trades for whichever league the reader has picked
(/fantasy/waivers/).

Sleeper keeps transactions per week, so this walks every week of every season
in the league's chain. Each one carries who added whom, who was dropped, and
what it cost: a waiver claim has its FAAB bid in `settings.waiver_bid`, and a
trade can move budget as well as players.

Player ids are numeric except for defences, which Sleeper keys by team code
("GB"). The player index carries all thirty-two, so both resolve the same way.

Failed claims are kept and shown separately: being outbid is half the story of
a waiver wire, and a log that silently drops them makes every claim look
uncontested.
"""

CSS = """<style>
.wv{margin:8px 0 20px}
.wv h2{margin:20px 0 6px;font-size:18px}
.wv-note{font-size:12.5px;color:#64748b;margin:0 0 10px;line-height:1.5}
.wv-none{font-size:14px;color:#475569}
.wv-bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:0 0 10px;
  font-size:13px;color:#475569}
.wv-bar select{font:inherit;font-size:13px;padding:5px 9px;border:1px solid #cbd5e1;
  border-radius:8px}
.wv-in{color:#15803d;font-weight:600}
.wv-out{color:#b91c1c}
.wv-pos{font-size:10.5px;color:#94a3b8;font-weight:700;margin-left:4px}
.wv-how{font-size:11.5px;color:#64748b;white-space:nowrap}
.wv-bid{font-weight:800;color:#0f172a}
.wv-when{font-size:11.5px;color:#64748b;white-space:nowrap}
.wv-failed td{background:#fdf6f6;color:#94a3b8}
.wv-more{font:inherit;font-size:12.5px;padding:6px 14px;border-radius:999px;
  border:1px solid #cbd5e1;background:#fff;color:#334155;cursor:pointer;margin:10px 0 0}
.wv-load{font-size:12.5px;color:#64748b}
@media (prefers-color-scheme: dark){
  .wv-note,.wv-none,.wv-how,.wv-when,.wv-load,.wv-bar{color:#aab7c9}
  .wv-in{color:#6ee7b7}
  .wv-out{color:#ff9b91}
  .wv-bid{color:#f1f5f9}
  .wv-failed td{background:#2a1e1e;color:#7f8ea3}
  .wv-bar select,.wv-more{background:#16203a;border-color:#2b3852;color:#dde5ef}
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
  var host=document.getElementById('wv-host');
  if(!host||!window.GSL) return;
  var have=GSL.saved();
  if(!have||!have.id||have.site){
    // Drawn twice: once now, and again when the account call settles, because
    // whether to offer a sign-in or a league picker is not known at first paint.
    var none=function(){ host.innerHTML=window.GSLeague
      ? GSLeague.empty('wv-none','waivers')
      : '<p class="wv-none">Pick a league above to see its waivers.</p>'; };
    none();
    if(window.GSLeague&&GSLeague.ready) GSLeague.ready.then(none,none);
    return;
  }

  var API='https://api.sleeper.app/v1';
  var MAX_SEASONS=12, WEEKS=18, PAGE=40;
  var shown=PAGE, state=null;

  function get(p){
    return fetch(API+p).then(function(r){return r.ok?r.json():null;})
      .catch(function(){return null;});
  }
  function esc(v){
    return String(v==null?'':v).replace(/[&<>"]/g,function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});
  }
  function when(ms){
    var d=new Date(ms);
    return isNaN(d)?'':d.toLocaleDateString([], {year:'numeric', month:'short', day:'numeric'});
  }

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

  /** roster_id -> manager, for one season. */
  function managers(lid){
    return Promise.all([get('/league/'+lid+'/rosters'), get('/league/'+lid+'/users')])
      .then(function(o){
        var rosters=o[0]||[], users=o[1]||[], who={}, out={};
        users.forEach(function(u){
          who[u.user_id]=(u.metadata&&u.metadata.team_name)||u.display_name||'Team';
        });
        rosters.forEach(function(r){
          out[r.roster_id]=who[r.owner_id]||('Roster '+r.roster_id);
        });
        return out;
      });
  }

  function player(index, pid){
    var meta=index[String(pid)];
    if(!meta) return esc(pid);
    return esc(meta[0])+'<span class="wv-pos">'+esc(meta[1])+'</span>';
  }

  function collect(seasons, index){
    var jobs=[];
    seasons.forEach(function(s){
      for(var w=1; w<=WEEKS; w++){
        jobs.push(get('/league/'+s.league_id+'/transactions/'+w)
          .then(function(rows){ return {season:s.season, names:s.names, rows:rows||[]}; }));
      }
    });
    return Promise.all(jobs).then(function(weeks){
      var all=[];
      weeks.forEach(function(wk){
        wk.rows.forEach(function(t){
          if(!t || !t.type) return;
          all.push({
            season: wk.season, names: wk.names, type: t.type,
            status: t.status, created: t.created || 0,
            adds: t.adds || {}, drops: t.drops || {},
            rosters: t.roster_ids || [],
            bid: (t.settings && t.settings.waiver_bid) || 0,
            budget: t.waiver_budget || [],
          });
        });
      });
      all.sort(function(a,b){ return b.created-a.created; });
      return all;
    });
  }

  function howCell(t){
    if(t.type==='trade') return '<span class="wv-how">Trade</span>';
    if(t.type==='waiver'){
      return '<span class="wv-how">Waiver</span>'
        + (t.bid ? ' <span class="wv-bid">$'+t.bid+'</span>' : '');
    }
    return '<span class="wv-how">Free agent</span>';
  }

  function rowsFor(list, index){
    return list.map(function(t){
      var ins=Object.keys(t.adds).map(function(pid){
        return '<div class="wv-in">+ '+player(index,pid)
          +' <span class="wv-how">'+esc(t.names[t.adds[pid]]||'')+'</span></div>';
      }).join('');
      var outs=Object.keys(t.drops).map(function(pid){
        return '<div class="wv-out">&minus; '+player(index,pid)
          +' <span class="wv-how">'+esc(t.names[t.drops[pid]]||'')+'</span></div>';
      }).join('');
      var faab=(t.budget||[]).map(function(b){
        return '<div class="wv-how">$'+b.amount+' '+esc(t.names[b.sender]||'')
          +' &rarr; '+esc(t.names[b.receiver]||'')+'</div>';
      }).join('');
      return '<tr'+(t.status!=='complete'?' class="wv-failed"':'')+'>'
        +'<td class="wv-when">'+when(t.created)
          // The date already carries a year. The season is only worth saying
          // when the two differ - a playoff move in January belongs to the
          // season before it.
          +(String(new Date(t.created).getFullYear())!==String(t.season)
            ? '<div class="wv-how">'+esc(t.season)+' season</div>' : '')
          +'</td>'
        +'<td>'+howCell(t)+(t.status!=='complete'
            ? '<div class="wv-how">'+esc(t.status)+'</div>' : '')+'</td>'
        +'<td>'+(ins||'<span class="wv-how">&mdash;</span>')+'</td>'
        +'<td>'+(outs||'<span class="wv-how">&mdash;</span>')+faab+'</td></tr>';
    }).join('');
  }

  function summary(all){
    var by={};
    all.forEach(function(t){
      if(t.status!=='complete') return;
      t.rosters.forEach(function(rid){
        var name=t.names[rid];
        if(!name) return;
        var a=by[name]=by[name]||{claims:0, faab:0, adds:0, drops:0, trades:0};
        if(t.type==='trade') a.trades+=1;
        else if(t.type==='waiver'){ a.claims+=1; a.faab+=t.bid||0; }
        else a.adds+=1;
      });
      Object.keys(t.drops).forEach(function(pid){
        var name=t.names[t.drops[pid]];
        if(by[name]) by[name].drops+=1;
      });
    });
    var rows=Object.keys(by).sort(function(a,b){
      return (by[b].claims+by[b].adds)-(by[a].claims+by[a].adds);});
    if(!rows.length) return '';
    var faabUsed=rows.some(function(n){ return by[n].faab>0; });
    return '<h2>Who works the wire</h2><table class="sticky-table"><thead><tr><th>Manager</th>'
      +'<th>Claims</th>'+(faabUsed?'<th>FAAB</th>':'')
      +'<th>Free agents</th><th>Drops</th><th>Trades</th></tr></thead><tbody>'
      + rows.map(function(n){
          var a=by[n];
          return '<tr><td>'+esc(n)+'</td><td class="n">'+a.claims+'</td>'
            +(faabUsed?'<td class="n">$'+a.faab+'</td>':'')
            +'<td class="n">'+a.adds+'</td><td class="n">'+a.drops+'</td>'
            +'<td class="n">'+a.trades+'</td></tr>';
        }).join('')
      +'</tbody></table>';
  }

  function draw(){
    var seasonPick=document.getElementById('wv-season');
    var typePick=document.getElementById('wv-type');
    var season=seasonPick?seasonPick.value:'';
    var kind=typePick?typePick.value:'';
    var list=state.all.filter(function(t){
      if(season && t.season!==season) return false;
      if(kind==='failed') return t.status!=='complete';
      if(kind && t.type!==kind) return false;
      if(!kind && t.status!=='complete') return false;   // failed only when asked for
      return true;
    });
    var slot=document.getElementById('wv-log');
    slot.innerHTML='<table class="sticky-table"><thead><tr><th>When</th><th>How</th>'
      +'<th>In</th><th>Out</th></tr></thead><tbody>'
      + (list.length ? rowsFor(list.slice(0, shown), state.index)
         : '<tr><td colspan="4"><span class="wv-none">Nothing here.</span></td></tr>')
      +'</tbody></table>'
      + (list.length>shown
         ? '<button class="wv-more" id="wv-more">Show more ('
           +(list.length-shown)+' left)</button>' : '');
    var more=document.getElementById('wv-more');
    if(more) more.addEventListener('click',function(){ shown+=PAGE; draw(); });
  }

  host.innerHTML='<p class="wv-load">Reading '+esc(have.name||'your league')+'\\u2026</p>';
  chain(have.id)
    .then(function(lgs){
      if(!lgs.length) throw new Error('none');
      return Promise.all(lgs.map(function(lg){
        return managers(lg.league_id).then(function(names){
          return {league_id:lg.league_id, season:lg.season, name:lg.name, names:names};
        });
      }));
    })
    .then(function(seasons){
      return Promise.all([seasons, collect(seasons, null), GSL.players()]);
    })
    .then(function(o){
      var seasons=o[0], all=o[1], index=o[2]||{};
      state={all:all, index:index, seasons:seasons};
      var complete=all.filter(function(t){return t.status==='complete';}).length;
      host.innerHTML=
        '<p class="wv-note"><strong>'+esc(seasons[0].name||'This league')+'</strong> &middot; '
        +complete+' completed move'+(complete===1?'':'s')+' across '+seasons.length
        +' season'+(seasons.length===1?'':'s')+'. A failed claim is somebody being '
        +'outbid, so they are kept - pick <em>Failed claims</em> to see them.</p>'
        + summary(all)
        + '<h2>Every move</h2>'
        + '<div class="wv-bar"><label>Season <select id="wv-season">'
        + '<option value="">All</option>'
        + seasons.map(function(s){
            return '<option value="'+esc(s.season)+'">'+esc(s.season)+'</option>';
          }).join('')
        + '</select></label><label>Kind <select id="wv-type">'
        + '<option value="">Completed</option><option value="waiver">Waivers</option>'
        + '<option value="free_agent">Free agents</option>'
        + '<option value="trade">Trades</option>'
        + '<option value="failed">Failed claims</option>'
        + '</select></label></div><div id="wv-log"></div>';
      ['wv-season','wv-type'].forEach(function(id){
        document.getElementById(id).addEventListener('change',function(){
          shown=PAGE; draw();});
      });
      draw();
    })
    .catch(function(){
      host.innerHTML='<p class="wv-none">Could not read that league from Sleeper.</p>';
    });
})();
</script>{% endraw %}"""


def section() -> str:
    return CSS + "<div class='wv' id='wv-host'></div>"
