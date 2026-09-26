"""
Draft analytics for whichever league the reader has picked
(/fantasy/draft-review/).

The board is free: Sleeper's picks carry the player's name, position and team
inline, so no lookup is needed to draw who took whom.

What a pick was *worth* is the harder half, and it is answered here without
ADP. This site's ADP is its own league's and means nothing for a stranger's,
so instead each pick is set against what it returned: every drafted player is
ranked by the points he actually scored that season, and a pick taken 40th
whose player finished 12th among those drafted is +28. That is the same
question "value against ADP" asks - did this cost less than it gave back -
answered from results rather than from somebody else's market.

Season totals come from /fantasy/season-points/<year>.json, written by
fantasy.site.players_index: Sleeper's own season endpoint is 2.3 MB a year,
and a reader looking at four drafts should not pull nine megabytes to find out
how they did.
"""

CSS = """<style>
.dr{margin:8px 0 20px}
.dr h2{margin:20px 0 6px;font-size:18px}
.dr-note{font-size:12.5px;color:#64748b;margin:0 0 10px;line-height:1.5}
.dr-none{font-size:14px;color:#475569}
.dr-bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:0 0 10px;
  font-size:13px;color:#475569}
.dr-bar select{font:inherit;font-size:13px;padding:5px 9px;border:1px solid #cbd5e1;
  border-radius:8px}
.dr-up{color:#15803d;font-weight:700}
.dr-down{color:#b91c1c;font-weight:700}
.dr-pos{font-size:10.5px;color:#94a3b8;font-weight:700;margin-left:4px}
table.dr-b{border-collapse:collapse;font-size:11.5px;width:100%}
table.dr-b th{background:#eef2f7;color:#334155;padding:4px 6px;font-size:10.5px;
  text-transform:uppercase;letter-spacing:.03em;border:1px solid #e2e8f0;
  white-space:nowrap;text-align:left}
table.dr-b th.rd{position:sticky;left:0;z-index:1}
table.dr-b td{padding:4px 6px;border:1px solid #eef2f7;background:#fff;
  color:#0f172a;white-space:nowrap;max-width:132px;overflow:hidden;
  text-overflow:ellipsis}
table.dr-b td.rd{position:sticky;left:0;background:#eef2f7;font-weight:800;z-index:1}
.dr-nm{font-weight:600}
.dr-v{font-variant-numeric:tabular-nums;font-size:10.5px;margin-left:4px}
@media (prefers-color-scheme: dark){
  .dr-note,.dr-none,.dr-bar{color:#aab7c9}
  .dr-up{color:#6ee7b7}
  .dr-down{color:#ff9b91}
  .dr-bar select{background:#16203a;border-color:#2b3852;color:#dde5ef}
  /* The draft board is its own table - too many narrow columns for the
     site's - and its dark rules used to share a selector with the summary
     table that has now become a `sticky-table`. */
  table.dr-b th,table.dr-b td.rd{background:#223052;color:#dde5ef;
    border-color:#2b3852}
  table.dr-b td{background:#16203a;border-color:#2b3852;color:#dde5ef}
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
  var host=document.getElementById('dr-host');
  if(!host||!window.GSL) return;
  var have=GSL.saved();
  if(!have||!have.id||have.site){
    // Drawn twice: once now, and again when the account call settles, because
    // whether to offer a sign-in or a league picker is not known at first paint.
    var none=function(){ host.innerHTML=window.GSLeague
      ? GSLeague.empty('dr-none','drafts')
      : '<p class="dr-none">Pick a league above to see its drafts.</p>'; };
    none();
    if(window.GSLeague&&GSLeague.ready) GSLeague.ready.then(none,none);
    return;
  }

  var API='https://api.sleeper.app/v1', MAX_SEASONS=12;
  var state={seasons:[], basis:0};

  function get(p){
    return fetch(API+p).then(function(r){return r.ok?r.json():null;})
      .catch(function(){return null;});
  }
  function esc(v){
    return String(v==null?'':v).replace(/[&<>"]/g,function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});
  }
  function signed(n){
    return (n>0?'+':'')+n;
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

  var pointsCache={};
  function seasonPoints(year){
    if(pointsCache[year]) return pointsCache[year];
    pointsCache[year]=fetch('/fantasy/season-points/'+year+'.json')
      .then(function(r){ return r.ok?r.json():{}; })
      .catch(function(){ return {}; });
    return pointsCache[year];
  }

  /** One season's draft: the picks, who made them, and what they returned. */
  function draftFor(lg){
    return Promise.all([
      get('/league/'+lg.league_id+'/drafts'),
      get('/league/'+lg.league_id+'/rosters'),
      get('/league/'+lg.league_id+'/users'),
      seasonPoints(lg.season)
    ]).then(function(o){
      var drafts=o[0]||[], rosters=o[1]||[], users=o[2]||[], points=o[3]||{};
      if(!drafts.length) return null;
      var draft=drafts[0];
      var who={};
      users.forEach(function(u){
        who[u.user_id]=(u.metadata&&u.metadata.team_name)||u.display_name||'Team';
      });
      var byRoster={};
      rosters.forEach(function(r){ byRoster[r.roster_id]=who[r.owner_id]||('Roster '+r.roster_id); });

      return get('/draft/'+draft.draft_id+'/picks').then(function(picks){
        picks=picks||[];
        if(!picks.length) return null;
        var basis=state.basis;
        picks.forEach(function(p){
          var m=p.metadata||{};
          p._name=((m.first_name||'')+' '+(m.last_name||'')).trim()||('#'+p.player_id);
          p._pos=m.position||'';
          p._by=byRoster[p.roster_id]||who[p.picked_by]||'';
          var row=points[String(p.player_id)];
          p._pts=row?row[basis]:null;
        });
        // What each pick returned: drafted players ranked by the points they
        // actually scored. A pick taken 40th whose player finished 12th among
        // those drafted is +28.
        var scored=picks.filter(function(p){ return p._pts!=null; })
          .sort(function(a,b){ return b._pts-a._pts; });
        scored.forEach(function(p,i){ p._finish=i+1; });
        picks.forEach(function(p){
          p._value=(p._finish!=null)?(p.pick_no-p._finish):null;
        });
        return {season:lg.season, name:lg.name, status:lg.status,
                rounds:(draft.settings||{}).rounds||0, type:draft.type,
                picks:picks, teams:byRoster,
                complete:lg.status==='complete'};
      });
    });
  }

  function summary(d){
    var by={};
    d.picks.forEach(function(p){
      if(!p._by) return;
      var a=by[p._by]=by[p._by]||{n:0, scored:0, value:0, best:null, worst:null};
      a.n+=1;
      if(p._value==null) return;
      a.scored+=1; a.value+=p._value;
      if(!a.best||p._value>a.best._value) a.best=p;
      if(!a.worst||p._value<a.worst._value) a.worst=p;
    });
    var names=Object.keys(by).filter(function(n){ return by[n].scored; });
    if(!names.length) return '';
    names.sort(function(a,b){ return (by[b].value/by[b].scored)-(by[a].value/by[a].scored); });
    return '<h2>How each manager drafted</h2><div class="table-scroll"><table class="sticky-table"><thead><tr>'
      +'<th>Manager</th><th>Picks</th><th>Avg value</th><th>Best</th><th>Worst</th>'
      +'</tr></thead><tbody>'
      + names.map(function(n){
          var a=by[n], avg=Math.round(a.value/a.scored);
          return '<tr><td>'+esc(n)+'</td><td class="n">'+a.n+'</td>'
            +'<td class="n"><span class="'+(avg>0?'dr-up':avg<0?'dr-down':'')+'">'
            +signed(avg)+'</span></td>'
            +'<td>'+esc(a.best._name)+'<span class="dr-pos">'+esc(a.best._pos)+'</span>'
            +' <span class="dr-up dr-v">'+signed(a.best._value)+'</span></td>'
            +'<td>'+esc(a.worst._name)+'<span class="dr-pos">'+esc(a.worst._pos)+'</span>'
            +' <span class="dr-down dr-v">'+signed(a.worst._value)+'</span></td></tr>';
        }).join('')
      +'</tbody></table></div>';
  }

  function board(d){
    var slots={};
    d.picks.forEach(function(p){ slots[p.draft_slot]=1; });
    var cols=Object.keys(slots).map(Number).sort(function(a,b){return a-b;});
    if(!cols.length) return '';
    var byRound={};
    d.picks.forEach(function(p){
      (byRound[p.round]=byRound[p.round]||{})[p.draft_slot]=p;
    });
    var rounds=Object.keys(byRound).map(Number).sort(function(a,b){return a-b;});
    // The slot's own manager, taken from round one.
    var headers=cols.map(function(c){
      var first=(byRound[rounds[0]]||{})[c];
      return first?first._by:('Slot '+c);
    });
    var html='<h2>The board</h2><p class="dr-note">Each pick with what it '
      +'returned beside it. A snake draft reverses every round, so the same '
      +'column is the same manager throughout.</p><div class="table-scroll">'
      +'<table class="dr-b"><thead><tr><th class="rd">Rd</th>'
      + headers.map(function(h){return '<th>'+esc(String(h).slice(0,14))+'</th>';}).join('')
      +'</tr></thead><tbody>';
    rounds.forEach(function(r){
      html+='<tr><td class="rd">'+r+'</td>';
      cols.forEach(function(c){
        var p=(byRound[r]||{})[c];
        if(!p){ html+='<td></td>'; return; }
        var v=p._value;
        html+='<td><span class="dr-nm">'+esc(p._name)+'</span>'
          +'<span class="dr-pos">'+esc(p._pos)+'</span>'
          +(v==null?'':' <span class="dr-v '+(v>0?'dr-up':v<0?'dr-down':'')+'">'
            +signed(v)+'</span>')
          +'</td>';
      });
      html+='</tr>';
    });
    return html+'</tbody></table></div>';
  }

  function draw(){
    var pick=document.getElementById('dr-season');
    var year=pick?pick.value:state.seasons[0].season;
    var d=state.seasons.filter(function(s){return s.season===year;})[0];
    var slot=document.getElementById('dr-body');
    if(!d){ slot.innerHTML='<p class="dr-none">No draft on record for that season.</p>'; return; }
    var partial=!d.complete
      ? '<p class="dr-note">This season is still being played, so value is '
        +'measured on the points scored so far.</p>' : '';
    slot.innerHTML=partial+summary(d)+board(d);
  }

  host.innerHTML='<p class="dr-note">Reading '+esc(have.name||'your league')+'\\u2026</p>';
  chain(have.id)
    .then(function(lgs){
      if(!lgs.length) throw new Error('none');
      // The scoring the league plays, so "what it returned" is in its own
      // points rather than this site's.
      return GSL.league(have.id).then(function(info){
        state.basis=info.basis.index;
        return Promise.all(lgs.map(draftFor));
      });
    })
    .then(function(all){
      state.seasons=all.filter(Boolean);
      if(!state.seasons.length){
        host.innerHTML='<p class="dr-none">Sleeper has no draft on record for this league.</p>';
        return;
      }
      host.innerHTML='<div class="dr-bar"><label>Season <select id="dr-season">'
        + state.seasons.map(function(s){
            return '<option value="'+esc(s.season)+'">'+esc(s.season)+'</option>';
          }).join('')
        +'</select></label></div>'
        +'<p class="dr-note"><strong>Value</strong> is where a pick was taken '
        +'against where its player finished among everyone drafted that season, '
        +'in this league\\u2019s scoring. Taken 40th, finished 12th, is +28. '
        +'It is not measured against ADP: this site\\u2019s ADP is its own '
        +'league\\u2019s and says nothing about yours.</p>'
        +'<div id="dr-body"></div>';
      document.getElementById('dr-season').addEventListener('change',draw);
      draw();
    })
    .catch(function(){
      host.innerHTML='<p class="dr-none">Could not read that league from Sleeper.</p>';
    });
})();
</script>{% endraw %}"""


def section() -> str:
    return CSS + "<div class='dr' id='dr-host'></div>"
