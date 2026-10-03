/* window.GSPlan: the lineup planner (gordstats.lineup.plan, ported).
   Source file, loaded by gordstats.my_team (PLANNER_JS_TAG); see gordstats.js_assets. */
window.GSPlan = function(players, slotCounts, proj, kickoff, locked, flex, flexPositions,
                         bench, reserve, moreFlexes){
  bench = bench || 'BN';
  reserve = reserve || ['IR','IL'];
  // Every flex slot, with who may fill it; filled narrowest first (a stable
  // sort, so ties keep the caller's order) - see lineup.plan.
  var flexes = [[flex, flexPositions]].concat(moreFlexes || []);
  var eligible = {};
  flexes.forEach(function(f){ eligible[f[0]] = f[1]; });
  var fillOrder = flexes.slice().sort(function(a, b){ return a[1].length - b[1].length; });
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
    if (!eligible[pos]) chosen[pos] = (ranked[pos] || []).slice(0, Math.max(open[pos], 0));
  }
  var flexed = [];                                  // [[id, flex slot]]
  var flexedIds = function(){ return flexed.map(function(f){ return f[0]; }); };
  fillOrder.forEach(function(f){
    for (var n = 0; n < Math.max(open[f[0]] || 0, 0); n++){
      var taken = flexedIds(), best = null;
      f[1].forEach(function(p){
        var rest = (ranked[p] || []).slice((chosen[p] || []).length)
          .filter(function(i){ return taken.indexOf(i) < 0; });
        if (rest.length && (best === null || value[rest[0]] > value[best])) best = rest[0];
      });
      if (best === null) break;
      flexed.push([best, f[0]]);
    }
  });

  // Which slot: pool a position's starters, latest kickoffs to the flex.
  var positions = {};
  for (var c in chosen) positions[c] = true;
  flexed.forEach(function(f){ positions[byId[f[0]].pos] = true; });
  var LATE = 8.64e15;
  Object.keys(positions).forEach(function(pos){
    var mineFlexed = flexed.filter(function(f){ return byId[f[0]].pos === pos; });
    var group = (chosen[pos] || []).concat(mineFlexed.map(function(f){ return f[0]; }));
    var names = mineFlexed.map(function(f){ return f[1]; })
      .sort(function(a, b){ return eligible[b].length - eligible[a].length; });
    // Latest first; between equal kickoffs whoever is already in a flex
    // stays, then the weaker projection takes it as the likelier swap.
    group.sort(function(a, b){
      var ka = kickoff[a] == null ? LATE : kickoff[a];
      var kb = kickoff[b] == null ? LATE : kickoff[b];
      if (ka !== kb) return kb - ka;
      var fa = !eligible[byId[a].slot], fb = !eligible[byId[b].slot];
      if (fa !== fb) return fa ? 1 : -1;
      return value[a] - value[b];
    });
    group.forEach(function(pid, i){ slot[pid] = i < names.length ? names[i] : pos; });
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
            || (eligible[slot[pid]] || []).indexOf(byId[b].pos) >= 0)
        && kickoff[b] != null
        && (kickoff[b] >= (kickoff[pid] == null ? LATE : kickoff[pid]));
    }).sort(function(a, b){ return value[b] - value[a]; });
  });
  return {slot: slot, start: start, cover: cover};
};

// Who may fill each flex slot a league names - Sleeper's names, which GSAPI
// gives ESPN's slots too. One table for every page that sets or judges a
// lineup (this dashboard, the recap), so none can think a slot takes a
// position another says it does not.
window.GSPlan.FLEXES = {FLEX: ['RB','WR','TE'], WRRB_FLEX: ['RB','WR'],
                        REC_FLEX: ['WR','TE'], SUPER_FLEX: ['QB','RB','WR','TE'],
                        IDP_FLEX: ['DL','LB','DB']};

/** A league's slots as the planner takes them: `counts` of each starting
 *  slot, the first flex-like slot as `flex` (FLEX in a league with none)
 *  with its `positions`, the rest as `more` flexes, filled narrowest first,
 *  and `eligible` for every one. `off` are the slots nobody starts from.
 *  Every flex used to be FLEX alone, so a superflex beside it read as a
 *  position nobody plays - left empty, the QB2 benched. */
window.GSPlan.slots = function(slots, off){
  var F = window.GSPlan.FLEXES, counts = {}, names = [];
  (slots || []).forEach(function(s){
    if ((off || []).indexOf(s) >= 0) return;
    if (F[s] && names.indexOf(s) < 0) names.push(s);
    counts[s] = (counts[s] || 0) + 1;
  });
  var first = names[0] || 'FLEX', eligible = {};
  names.concat([first]).forEach(function(n){ eligible[n] = F[n]; });
  return {counts: counts, flex: first, positions: F[first], eligible: eligible,
          more: names.slice(1).map(function(n){ return [n, F[n]]; })};
};
