"""
"Your team this week" on the NFL team dashboard (/fantasy/roster/).

The built page is this league's: its start/sit, its waiver adds, its projection
board. For a reader's own league the same questions have to be answered from
what Sleeper will hand a browser - their roster, their slots, their scoring -
against the projections this build publishes.

The lineup itself is `gordstats.lineup.plan` ported to JavaScript. Two
implementations of the same greedy selection is a real risk, so
`tests/test_my_team_planner.py` runs both over the same fixtures in a browser
and asserts they agree; if the Python changes and this does not, that test
fails rather than the page quietly recommending a different lineup.

What is exact and what is not: PPR, half-PPR and standard leagues are exact,
because Sleeper prices every player under all three and the league's own
`scoring_settings.rec` picks the column. A league further from the default -
six-point passing touchdowns, reception bonuses - is approximated by the
nearest of the three, and the page says so.
"""

CSS = """<style>
.mt{margin:10px 0 18px}
.mt h2{margin:16px 0 6px;font-size:18px}
.mt-note{font-size:12.5px;color:#64748b;margin:0 0 10px;line-height:1.5}
.mt-warn{color:#b45309;font-weight:600}
.mt-pick{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:0 0 10px;font-size:13px}
.mt-pick select{font:inherit;font-size:13px;padding:6px 9px;border:1px solid #cbd5e1;
  border-radius:8px}
table.mt-t{width:100%;border-collapse:collapse;font-size:13.5px}
table.mt-t th{background:#eef2f7;color:#334155;padding:6px 9px;text-align:left;font-size:11.5px;
  text-transform:uppercase;letter-spacing:.03em;border:1px solid #e2e8f0;white-space:nowrap}
table.mt-t td{padding:6px 9px;border:1px solid #eef2f7;background:#fff;color:#0f172a}
table.mt-t td.n{text-align:right;font-variant-numeric:tabular-nums;font-weight:700}
table.mt-t tr.bench td{background:#f8fafc;color:#64748b}
table.mt-t tr.bench td.nm{font-weight:500}
.mt-slot{font-weight:800;font-size:11.5px;color:#475569;white-space:nowrap}
.mt-pos{font-size:10.5px;color:#94a3b8;font-weight:700;margin-left:5px}
.mt-lock{font-size:10.5px;color:#94a3b8;margin-left:5px}
table.mt-t tr.mt-move td{background:#ecfdf5;border-color:#a7f3d0}
table.mt-t tr.mt-out td{background:#fef2f2;border-color:#fecaca;color:#0f172a}
table.mt-t tr.mt-out td.nm{font-weight:600}
.mt-swap{margin:0 0 10px;padding:11px 13px;border:1px solid #a7f3d0;border-radius:10px;
  background:#ecfdf5;font-size:13.5px;line-height:1.6}
.mt-swap b{color:#15803d}
.mt-none{font-size:13.5px;color:#475569}
@media (prefers-color-scheme: dark){
  .mt-note,.mt-none{color:#aab7c9}
  table.mt-t th{background:#223052;color:#dde5ef;border-color:#2b3852}
  table.mt-t td{background:#16203a;border-color:#2b3852;color:#dde5ef}
  table.mt-t tr.bench td{background:#1b2540;color:#8fa0b8}
  .mt-slot{color:#aab7c9}
  .mt-swap{background:#14332a;border-color:#1f5f47}
  .mt-swap b{color:#6ee7b7}
  table.mt-t tr.mt-move td{background:#14332a;border-color:#1f5f47}
  table.mt-t tr.mt-out td{background:#3a1d1d;border-color:#7f1d1d;color:#dde5ef}
  .mt-pick select{background:#16203a;border-color:#2b3852;color:#dde5ef}
}
</style>"""

# The planner, ported from gordstats.lineup.plan. Kept deliberately close to
# the Python - same names, same order - so the two can be read side by side.
PLANNER_JS = """{% raw %}<script>
window.GSPlan = function(players, slotCounts, proj, kickoff, locked, flex, flexPositions,
                         bench, reserve){
  bench = bench || 'BN';
  reserve = reserve || ['IR','IL'];
  var isReserve = function(s){ return reserve.indexOf(s) >= 0; };
  var value = {}, byId = {};
  players.forEach(function(p){
    value[p.id] = (proj[p.id] == null || isNaN(proj[p.id])) ? 0 : proj[p.id];
    byId[p.id] = p;
  });
  var open = {};
  for (var k in slotCounts) open[k] = slotCounts[k];

  var slot = {}, pool = [];
  players.forEach(function(p){
    if (locked.indexOf(p.id) >= 0){
      slot[p.id] = p.slot;
      if (open[p.slot] != null) open[p.slot] -= 1;
    } else if (isReserve(p.slot)){
      slot[p.id] = p.slot;                       // injured list: not available
    } else {
      pool.push(p.id);
    }
  });

  // Who starts: dedicated slots by projection, then the flex.
  var ranked = {};
  pool.slice().sort(function(a,b){ return value[b] - value[a]; }).forEach(function(pid){
    (ranked[byId[pid].pos] = ranked[byId[pid].pos] || []).push(pid);
  });
  var chosen = {};
  for (var pos in open){
    if (pos !== flex) chosen[pos] = (ranked[pos] || []).slice(0, Math.max(open[pos], 0));
  }
  var flexed = [];
  for (var n = 0; n < Math.max(open[flex] || 0, 0); n++){
    var best = null;
    flexPositions.forEach(function(p){
      var rest = (ranked[p] || []).slice((chosen[p] || []).length)
        .filter(function(i){ return flexed.indexOf(i) < 0; });
      if (rest.length && (best === null || value[rest[0]] > value[best])) best = rest[0];
    });
    if (best === null) break;
    flexed.push(best);
  }

  // Which slot: pool a position's starters, latest kickoffs to the flex.
  var positions = {};
  for (var c in chosen) positions[c] = true;
  flexed.forEach(function(i){ positions[byId[i].pos] = true; });
  var LATE = 8.64e15;
  Object.keys(positions).forEach(function(pos){
    var group = (chosen[pos] || []).concat(
      flexed.filter(function(i){ return byId[i].pos === pos; }));
    var nFlex = flexed.filter(function(i){ return byId[i].pos === pos; }).length;
    // Latest first; between equal kickoffs whoever is already in the flex
    // stays, then the weaker projection takes it as the likelier swap.
    group.sort(function(a, b){
      var ka = kickoff[a] == null ? LATE : kickoff[a];
      var kb = kickoff[b] == null ? LATE : kickoff[b];
      if (ka !== kb) return kb - ka;
      var fa = byId[a].slot !== flex, fb = byId[b].slot !== flex;
      if (fa !== fb) return fa ? 1 : -1;
      return value[a] - value[b];
    });
    group.forEach(function(pid, i){ slot[pid] = i < nFlex ? flex : pos; });
  });
  pool.forEach(function(pid){ if (slot[pid] == null) slot[pid] = bench; });

  var off = [bench].concat(reserve);
  var start = Object.keys(slot).filter(function(p){ return off.indexOf(slot[p]) < 0; });
  var sitting = pool.filter(function(p){ return slot[p] === bench; });
  var cover = {};
  start.forEach(function(pid){
    if (locked.indexOf(pid) >= 0) return;
    var mine = byId[pid];
    cover[pid] = sitting.filter(function(b){
      return value[b] > 0
        && (byId[b].pos === mine.pos
            || (slot[pid] === flex && flexPositions.indexOf(byId[b].pos) >= 0))
        && kickoff[b] != null
        && (kickoff[b] >= (kickoff[pid] == null ? LATE : kickoff[pid]));
    }).sort(function(a, b){ return value[b] - value[a]; });
  });
  return {slot: slot, start: start, cover: cover};
};
</script>{% endraw %}"""


VIEW_JS = """{% raw %}<script>
(function(){
  var host=document.getElementById('mt-host');
  if(!host||!window.GSL||!window.GSPlan) return;
  var built=document.getElementById('mt-built');
  var have=GSL.saved();
  if(!have||!have.id||have.site) return;        // the built league is the default

  var BENCH='BN', RESERVE=['IR','IL','TAXI'];
  var FLEX='FLEX', FLEX_POS=['RB','WR','TE'];
  // Sleeper's other flex names, mapped onto the one the planner knows.
  var FLEXLIKE={'FLEX':['RB','WR','TE'],'WRRB_FLEX':['RB','WR'],
                'REC_FLEX':['WR','TE'],'SUPER_FLEX':['QB','RB','WR','TE']};

  function esc(s){
    return String(s==null?'':s).replace(/[&<>"]/g,function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});
  }
  function num(v){ return (v==null||isNaN(v))?'-':(Math.round(v*10)/10).toFixed(1); }

  function slotCounts(slots){
    var counts={}, flexName=null;
    slots.forEach(function(s){
      if(s===BENCH||RESERVE.indexOf(s)>=0) return;
      if(FLEXLIKE[s]) flexName=flexName||s;
      counts[s]=(counts[s]||0)+1;
    });
    return {counts:counts, flex:flexName||FLEX,
            positions:FLEXLIKE[flexName||FLEX]||FLEX_POS};
  }

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
    return out;
  }

  function render(lg, wk, index, rosterId){
    var roster=lg.rosters.filter(function(r){return String(r.roster_id)===String(rosterId);})[0];
    if(!roster){ host.innerHTML='<p class="mt-none">No roster.</p>'; return; }

    var conf=slotCounts(lg.slots);
    var here=current(roster, lg.slots);
    var proj=GSL.points(wk, lg.basis.index);
    var kick=GSL.kickoffs(wk);
    var now=Date.now();

    var players=(roster.players||[]).map(function(p){
      var pid=String(p), meta=index[pid]||['Player '+pid,''];
      return {id:pid, pos:meta[1]||'', slot:here[pid]||BENCH, name:meta[0]};
    });
    var locked=players.filter(function(p){
      return kick[p.id]!=null && kick[p.id]<=now;
    }).map(function(p){return p.id;});

    var out=GSPlan(players, conf.counts, proj, kick, locked,
                   conf.flex, conf.positions, BENCH, RESERVE);

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

    html+='<table class="mt-t"><thead><tr><th>Slot</th><th>Player</th>'
      +'<th style="text-align:right">Proj</th><th>Now</th></tr></thead><tbody>';
    rows.forEach(function(r){
      var p=r.p, moved=out.slot[p.id]!==p.slot;
      var into=moved&&r.slot!==BENCH, outOf=moved&&r.slot===BENCH;
      var cls=(r.slot===BENCH?'bench':'')+(into?' mt-move':'')+(outOf?' mt-out':'');
      html+='<tr class="'+cls+'"><td class="mt-slot">'+esc(r.slot)+'</td>'
        +'<td class="nm">'+esc(p.name)+'<span class="mt-pos">'+esc(p.pos)+'</span>'
        +(locked.indexOf(p.id)>=0?'<span class="mt-lock">locked</span>':'')+'</td>'
        +'<td class="n">'+num(proj[p.id])+'</td>'
        +'<td class="mt-slot">'+(moved?esc(p.slot):'')+'</td></tr>';
    });
    host.innerHTML=html+'</tbody></table>'
      +'<p class="mt-note">Scoring read from your league: <b>'+esc(lg.basis.name)+'</b>.'
      +(lg.basis.custom
        ? ' <span class="mt-warn">Your league also scores something this site does not '
          +'publish a basis for (a six-point passing touchdown, or a bonus), so these '
          +'are the nearest of the three rather than exact.</span>'
        : '')
      +' A player whose game has started is locked where he is.</p>';
  }

  function start(){
    host.innerHTML='<p class="mt-note">Reading '+esc(have.name||'your league')+'\\u2026</p>';
    if(built) built.hidden=true;
    Promise.all([GSL.league(have.id), GSL.week(), GSL.players()])
      .then(function(o){
        var lg=o[0], wk=o[1], index=o[2];
        var bar=document.getElementById('mt-bar');
        var keys=Object.keys(lg.names);
        if(bar){
          bar.innerHTML='<label>Team <select id="mt-who">'
            +keys.map(function(k){
              return '<option value="'+esc(k)+'">'+esc(lg.names[k])+'</option>';}).join('')
            +'</select></label>';
          document.getElementById('mt-who').addEventListener('change',function(){
            render(lg, wk, index, this.value);});
        }
        render(lg, wk, index, keys[0]);
      })
      .catch(function(){
        host.innerHTML='<p class="mt-none">Could not read that league from Sleeper.</p>';
      });
  }
  start();
})();
</script>{% endraw %}"""


def section() -> str:
    """The container the script fills."""
    return (CSS + "<div class='mt' id='mt-wrap'>"
            "<h2>Your team this week</h2>"
            "<div class='mt-pick' id='mt-bar'></div>"
            "<div id='mt-host'></div></div>")
