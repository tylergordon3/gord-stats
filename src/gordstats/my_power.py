"""
Power rankings for whichever league the reader has picked (/fantasy/power/).

The page beside this one ranks *this* site's league by playing its season ten
thousand times (`fantasy.league.power`). Doing the same for a reader's league
has to happen in the browser, because the rosters, the slots and the rules only
exist at Sleeper. So the simulation is ported here, and the numbers it draws
from are fetched: `fantasy.site.season_board` publishes the projection board,
which is the one part no browser could ever compute.

What the port has to add, and the built page never needed, is that every league
is different:

  * **Scoring.** The board is PPR, because this league plays PPR. The only
    difference between Sleeper's three bases is what a catch is worth, so the
    board ships each player's catch rate and half-PPR is `mu - rec/2`,
    standard `mu - rec`. `sd` and `mu_se` are scaled by the same ratio: a
    receiver's week-to-week swing comes partly from his catches, so a standard
    league's scores vary less as well as averaging less, and holding the
    coefficient of variation is closer than holding the spread.

  * **Slots.** The built page hardcodes QB/RB/RB/WR/WR/TE/FLEX/FLEX/K/DEF.
    Sleeper leagues have superflex, two kinds of half-flex, three receivers.
    So slots are filled narrowest-first from `roster_positions`, which is the
    order that does not strand an eligible player: a flex can take what a
    dedicated slot cannot, so it must choose after it.

  * **The bracket.** Six teams over three weeks with two byes is this league.
    The bracket here is built for whatever `playoff_teams` says, seeded the
    standard way, with byes for the top seeds when the field is not a power of
    two.

  * **The median win.** This league awards one every week and most do not.
    It is `settings.league_average_match`, and quietly assuming it doubles
    everybody's projected record.

One thing the port deliberately leaves out: the published page's headline
Rating is our simulation averaged with the FantasyPros League Analyzer, and
that is keyed to this league specifically. A reader's league has no such key,
so this shows the simulation alone - and says so, rather than printing a
smaller number beside a bigger one with no explanation.

The fast part of the port is an accident worth keeping: the lineup a manager
sets is chosen on *projection*, never on the scores about to happen, and the
projection does not change during a season. So each team's starting order at
each slot is fixed before the first simulated week, and the inner loop is a
walk rather than a sort. Ten thousand seasons of a twelve-team league run in
under three seconds.
"""

CSS = """<style>
.mp{margin:8px 0 22px}
.mp h2{margin:18px 0 6px;font-size:18px}
.mp-note{font-size:12.5px;color:#64748b;margin:0 0 10px;line-height:1.5}
.mp-none{font-size:14px;color:#475569}
.mp-load{font-size:13px;color:#64748b}
.mp-warn{font-size:12.5px;color:#92400e;background:#fffbeb;border:1px solid #fde68a;
  border-radius:8px;padding:8px 11px;margin:0 0 12px;line-height:1.5}
table.mp-t{width:100%;border-collapse:collapse;font-size:13.5px}
table.mp-t th{background:#eef2f7;color:#334155;padding:6px 9px;text-align:left;
  font-size:11.5px;text-transform:uppercase;letter-spacing:.03em;
  border:1px solid #e2e8f0;white-space:nowrap}
table.mp-t td{padding:6px 9px;border:1px solid #eef2f7;background:#fff;color:#0f172a}
table.mp-t td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
table.mp-t tr.me td{background:#fffbeb}
.mp-rank{display:inline-block;min-width:1.6em;color:#94a3b8;font-variant-numeric:tabular-nums}
.mp-sub{font-size:11px;color:#94a3b8;margin-left:5px}
.mp-scroll{overflow-x:auto}
/* The number above its own bar, not inside it. Printing it on top of a partial
   fill left the fill cutting through the digits, which reads as a rendering
   fault rather than as a scale. */
.mp-power{display:block;min-width:58px}
.mp-power b{display:block;font-weight:600;font-size:13.5px;text-align:right;
  font-variant-numeric:tabular-nums;color:#0f172a}
.mp-track{display:block;height:4px;margin-top:3px;border-radius:2px;background:#eef2f7}
.mp-track i{display:block;height:100%;border-radius:2px;background:#93c5fd}
@media (max-width:640px){
  table.mp-t th,table.mp-t td{padding:5px 6px;font-size:12.5px}
  table.mp-t .mp-hide{display:none}
}
@media (prefers-color-scheme: dark){
  .mp-note,.mp-none,.mp-load{color:#aab7c9}
  .mp-warn{color:#fcd34d;background:#2a2410;border-color:#4a3c13}
  table.mp-t th{background:#223052;color:#dde5ef;border-color:#2b3852}
  table.mp-t td{background:#16203a;border-color:#2b3852;color:#dde5ef}
  table.mp-t tr.me td{background:#33301a}
  .mp-power b{color:#dde5ef}
  .mp-track{background:#223052}
  .mp-track i{background:#2f5c96}
}
</style>"""


# The simulation itself, kept apart from the page so it can be run against the
# Python it was ported from without a page around it.
SIM_JS = """{% raw %}<script id="gs-power-sim">
// Written to run in either place. Ten thousand seasons is two or three seconds
// of solid arithmetic, which on a phone is a frozen page, so the page runs this
// in a Worker - built from this very element's text, so there is one copy of
// the simulation rather than one per thread. It also defines itself on the main
// thread, as the fallback for a browser that will not give us the Worker.
(function(root){
  'use strict';

  // ----- the rules a league can vary -------------------------------------- //

  // Which positions each Sleeper starting slot accepts. A slot not listed here
  // is one this site has no projections for (IDP, mostly); it is reported and
  // left empty rather than filled with a guess.
  var ELIGIBLE = {
    QB:['QB'], RB:['RB'], WR:['WR'], TE:['TE'], K:['K'],
    DEF:['DEF'], DST:['DEF'],
    FLEX:['RB','WR','TE'],
    WRRB_FLEX:['RB','WR'],
    REC_FLEX:['WR','TE'],
    SUPER_FLEX:['QB','RB','WR','TE']
  };
  var BENCH = {BN:1, IR:1, TAXI:1};

  // How long a player is out once he is out, in weeks: the middle of the
  // distribution of real absences. Most are one or two, a few end the season.
  var MEAN_ABSENCE = 3.0;
  var MIN_MU = 0.05, MIN_SD = 0.5;
  // What a catch is worth under each of Sleeper's three bases.
  var CATCH = [1.0, 0.5, 0.0];

  // ----- a reproducible stream -------------------------------------------- //
  // Seeded, because a ranking that changes when you reload is not a ranking.

  function Rng(seed){
    this.a = (seed >>> 0) || 1;
    this.b = 362436069; this.c = 521288629; this.d = 88675123;
    this.spare = null;
    for(var i = 0; i < 12; i++) this.next();          // shake off the seed
  }
  Rng.prototype.next = function(){                    // xorshift128
    var t = this.d, s = this.a;
    this.d = this.c; this.c = this.b; this.b = s;
    t ^= t << 11; t ^= t >>> 8; t ^= s; t ^= s >>> 19;
    this.a = t;
    return (t >>> 0) / 4294967296;
  };
  Rng.prototype.normal = function(){                  // Marsaglia polar
    if(this.spare !== null){ var v = this.spare; this.spare = null; return v; }
    var u, w, s;
    do { u = this.next()*2-1; w = this.next()*2-1; s = u*u + w*w; }
    while(s === 0 || s >= 1);
    var m = Math.sqrt(-2*Math.log(s)/s);
    this.spare = w*m;
    return u*m;
  };

  // ----- the board, in this league's scoring ------------------------------ //

  /** Board rows for the players on these rosters, rescaled to `basis`.
   *
   * A player the board has never heard of is a deep-bench flier, not a zero:
   * scoring him zero would quietly punish whoever rostered him. The built page
   * uses the same stand-in for the same reason.
   */
  function preparePlayers(board, posNames, rosters, basis){
    var catchValue = CATCH[basis] == null ? 1.0 : CATCH[basis];
    var players = [];
    for(var t = 0; t < rosters.length; t++){
      var held = rosters[t].players || [];
      for(var i = 0; i < held.length; i++){
        var pid = String(held[i]);
        var row = board[pid];
        if(row){
          var rec = row[6] || 0;
          var mu = Math.max(row[2] - rec * (1 - catchValue), MIN_MU);
          // Fewer points and a smaller swing: a receiver's week-to-week
          // variation is partly his catches, so the spread scales with the
          // mean rather than being carried over from PPR whole.
          var shrink = row[2] > 0 ? mu / row[2] : 1;
          players.push({id:pid, team:t, pos:posNames[row[0]], bye:row[1],
                        mu:mu, sd:Math.max(row[3]*shrink, MIN_SD),
                        muSe:row[4]*shrink, avail:row[5], out:row[7] || 0,
                        known:true});
        } else {
          players.push({id:pid, team:t, pos:'WR', bye:0, mu:3.0, sd:3.0,
                        muSe:3.0, avail:0.6, out:0, known:false});
        }
      }
    }
    return players;
  }

  /** Starting slots from `roster_positions`, narrowest eligibility first.
   *
   * The order is the whole point. A dedicated slot takes one position; a flex
   * takes what that dedicated slot could have taken. Filling the flex first
   * strands a quarterback on the bench behind a running back who could have
   * gone anywhere, so the narrow slots choose first.
   */
  function startingSlots(positions){
    var slots = [], unsupported = [];
    for(var i = 0; i < (positions || []).length; i++){
      var name = positions[i];
      if(BENCH[name]) continue;
      var takes = ELIGIBLE[name];
      if(!takes){
        if(unsupported.indexOf(name) < 0) unsupported.push(name);
        continue;
      }
      slots.push({name:name, takes:takes, width:takes.length, at:i});
    }
    slots.sort(function(a, b){ return (a.width - b.width) || (a.at - b.at); });
    return {slots:slots, unsupported:unsupported};
  }

  /** Per team, per slot, the players eligible for it in the order a manager
   *  would start them. Fixed for the whole simulation - see the module note. */
  function slotOrders(players, teams, slots){
    var byTeam = [];
    for(var t = 0; t < teams; t++){
      var mine = [];
      for(var i = 0; i < players.length; i++) if(players[i].team === t) mine.push(i);
      mine.sort(function(a, b){
        return (players[b].mu - players[a].mu) ||
               (players[a].id < players[b].id ? -1 : 1);
      });
      var lists = [];
      for(var s = 0; s < slots.length; s++){
        var takes = slots[s].takes, list = [];
        for(var j = 0; j < mine.length; j++){
          if(takes.indexOf(players[mine[j]].pos) >= 0) list.push(mine[j]);
        }
        lists.push(list);
      }
      byTeam.push(lists);
    }
    return byTeam;
  }

  // ----- the bracket ------------------------------------------------------ //

  /** Seed numbers in bracket order, so adjacent pairs are the standard meeting.
   *
   * [1,4,2,3] for four, [1,8,4,5,2,7,3,6] for eight. A field that is not a
   * power of two is padded to one, and the seeds past the end are byes - which
   * is how a six-team bracket gives its top two a week off.
   */
  function bracketOrder(size){
    var order = [1];
    while(order.length < size){
      var next = [], n = order.length * 2;
      for(var i = 0; i < order.length; i++){
        next.push(order[i]);
        next.push(n + 1 - order[i]);
      }
      order = next;
    }
    return order;
  }

  function bracketRounds(teams){
    var size = 1;
    while(size < teams) size *= 2;
    return Math.round(Math.log(size) / Math.LN2);
  }

  /** The champion's team index, from playoff-week points and the seeding. */
  function runBracket(points, seeds, week0){
    var size = 1;
    while(size < seeds.length) size *= 2;
    var order = bracketOrder(size);
    var field = [];
    for(var i = 0; i < size; i++){
      var seed = order[i];
      field.push(seed <= seeds.length ? seeds[seed - 1] : -1);   // -1 is a bye
    }
    var week = week0;
    while(field.length > 1){
      var next = [];
      for(var j = 0; j < field.length; j += 2){
        var a = field[j], b = field[j + 1];
        if(a < 0){ next.push(b); continue; }
        if(b < 0){ next.push(a); continue; }
        next.push(points[week][a] >= points[week][b] ? a : b);
      }
      field = next;
      week++;
    }
    return field[0];
  }

  /** (weeks, teams) opponent indices from a randomly rotated circle. */
  function roundRobin(rng, teams, weeks){
    var order = [];
    for(var i = 0; i < teams; i++) order.push(i);
    for(var k = teams - 1; k > 0; k--){                 // Fisher-Yates
      var j = Math.floor(rng.next() * (k + 1));
      var tmp = order[k]; order[k] = order[j]; order[j] = tmp;
    }
    var fixed = order[0], rotating = order.slice(1);
    var table = [];
    for(var w = 0; w < weeks; w++){
      var row = new Int32Array(teams);
      row[fixed] = rotating[0];
      row[rotating[0]] = fixed;
      for(var p = 1; p < teams / 2; p++){
        var a = rotating[p], b = rotating[rotating.length - p];
        row[a] = b; row[b] = a;
      }
      table.push(row);
      rotating = rotating.slice(1).concat(rotating.slice(0, 1));
    }
    return table;
  }

  // ----- one season ------------------------------------------------------- //

  /** Run `sims` seasons and summarise each team. See the module note. */
  function run(spec){
    var rosters = spec.rosters || [];
    var teams = rosters.length;
    if(!teams) return [];

    var players = preparePlayers(spec.board || {}, spec.posNames || [],
                                 rosters, spec.basis || 0);
    var found = startingSlots(spec.slots);
    var slots = found.slots;
    var regular = Math.max(spec.weeks || 14, 1);
    var playoffTeams = Math.min(Math.max(spec.playoffTeams || 6, 2), teams);
    var playoffWeeks = bracketRounds(playoffTeams);
    var total = regular + playoffWeeks;
    var orders = slotOrders(players, teams, slots);
    var sims = Math.max(spec.sims || 2000, 1);
    var rng = new Rng(spec.seed || 20260821);

    var actual = spec.actual || [];
    var played = Math.min(actual.length, regular);
    var schedule = spec.schedule || null;
    var median = !!spec.median;

    var n = players.length;
    var mu = new Float64Array(n), sd = new Float64Array(n),
        muSe = new Float64Array(n), avail = new Float64Array(n),
        leave = new Float64Array(n), held = new Int32Array(n),
        bye = new Int32Array(n);
    for(var i = 0; i < n; i++){
      mu[i] = players[i].mu; sd[i] = Math.max(players[i].sd, MIN_SD);
      muSe[i] = players[i].muSe; avail[i] = players[i].avail;
      held[i] = players[i].out; bye[i] = players[i].bye;
      // The chain's two rates: `back` comes out of MEAN_ABSENCE, and `leave`
      // is whatever makes the long-run share of weeks played come to `avail`.
      leave[i] = Math.min(Math.max((1/MEAN_ABSENCE) * (1 - avail[i]) /
                                   Math.max(avail[i], 1e-9), 0), 1);
    }
    var back = 1 / MEAN_ABSENCE;

    var playing = new Uint8Array(n), score = new Float64Array(n);
    var gd = new Float64Array(n), gc = new Float64Array(n),
        gscale = new Float64Array(n), gboost = new Float64Array(n);
    var used = new Uint8Array(n);

    var wins = [], pointsFor = [];
    for(var t = 0; t < teams; t++){ wins.push([]); pointsFor.push([]); }
    var madePlayoffs = new Float64Array(teams), titles = new Float64Array(teams);
    var weekPoints = [];
    for(var w = 0; w < total; w++) weekPoints.push(new Float64Array(teams));

    function gamma(i){
      // Marsaglia-Tsang. d, c and the shape<1 correction are set once a season
      // per player, because the shape only moves when the true rate does.
      for(;;){
        var x = rng.normal(), v = 1 + gc[i]*x;
        if(v <= 0) continue;
        v = v*v*v;
        var u = rng.next();
        if(u < 1 - 0.0331*x*x*x*x || Math.log(u) < 0.5*x*x + gd[i]*(1 - v + Math.log(v))){
          var g = gd[i]*v;
          if(gboost[i] > 0) g *= Math.pow(rng.next(), gboost[i]);
          return g * gscale[i];
        }
      }
    }

    for(var sim = 0; sim < sims; sim++){
      for(i = 0; i < n; i++){
        // One true rate per player for the year: the projection's own
        // uncertainty, which a ranking that treated projections as facts would
        // be throwing away along with its honesty about playoff odds.
        var trueMu = Math.max(mu[i] + rng.normal()*muSe[i], MIN_MU);
        var shape = (trueMu / sd[i]) * (trueMu / sd[i]);
        gscale[i] = sd[i]*sd[i] / trueMu;
        // A gamma matched on mean and variance, not a normal clipped at zero:
        // clipping adds points that were never projected, and adds most of
        // them to exactly the boom-or-bust rosters this page exists to judge.
        var a = shape < 1 ? shape + 1 : shape;
        gboost[i] = shape < 1 ? 1/shape : 0;
        gd[i] = a - 1/3;
        gc[i] = 1 / Math.sqrt(9*gd[i]);
        playing[i] = rng.next() < avail[i] ? 1 : 0;   // open in the steady state
      }

      for(var week = 0; week < total; week++){
        for(i = 0; i < n; i++){
          var draw = rng.next();
          playing[i] = playing[i] ? (draw >= leave[i] ? 1 : 0)
                                  : (draw < back ? 1 : 0);
          var sidelined = (week >= played) && (week < played + held[i]);
          var on = playing[i] && !sidelined && (week + 1) !== bye[i];
          score[i] = on ? gamma(i) : -1;              // -1 marks unavailable
        }
        for(t = 0; t < teams; t++){
          var lists = orders[t], totalPoints = 0;
          for(var s = 0; s < slots.length; s++){
            var list = lists[s];
            for(var m = 0; m < list.length; m++){
              var idx = list[m];
              if(used[idx] || score[idx] < 0) continue;
              used[idx] = 1;
              totalPoints += score[idx];
              break;                     // one player, one slot
            }
          }
          for(s = 0; s < slots.length; s++){
            var back2 = lists[s];
            for(m = 0; m < back2.length; m++) used[back2[m]] = 0;
          }
          weekPoints[week][t] = totalPoints;
        }
      }

      // Weeks that have happened are not drawn; they happened.
      for(week = 0; week < played; week++){
        for(t = 0; t < teams; t++) weekPoints[week][t] = actual[week][t];
      }

      var table = schedule || roundRobin(rng, teams, regular);
      var seasonWins = new Float64Array(teams), seasonPoints = new Float64Array(teams);
      for(week = 0; week < regular; week++){
        var row = weekPoints[week];
        for(t = 0; t < teams; t++) seasonPoints[t] += row[t];
        var pairs = table[week % table.length];
        if(pairs){
          for(t = 0; t < teams; t++){
            var opponent = pairs[t];
            if(opponent != null && opponent >= 0 && opponent !== t &&
               row[t] > row[opponent]) seasonWins[t] += 1;
          }
        }
        if(median){
          // The top half of the league takes a second win. Ranking the week's
          // scores is the same thing as comparing each to the median, and it
          // does not need a tie-break rule of its own.
          var order2 = [];
          for(t = 0; t < teams; t++) order2.push(t);
          order2.sort(function(a, b){ return row[b] - row[a]; });
          for(var r = 0; r < Math.floor(teams/2); r++) seasonWins[order2[r]] += 1;
        }
      }

      var seeded = [];
      for(t = 0; t < teams; t++) seeded.push(t);
      seeded.sort(function(a, b){
        return (seasonWins[b] - seasonWins[a]) || (seasonPoints[b] - seasonPoints[a]);
      });
      var seeds = seeded.slice(0, playoffTeams);
      for(r = 0; r < seeds.length; r++) madePlayoffs[seeds[r]] += 1;
      if(playoffWeeks > 0) titles[runBracket(weekPoints, seeds, regular)] += 1;

      for(t = 0; t < teams; t++){
        wins[t].push(seasonWins[t]);
        pointsFor[t].push(seasonPoints[t]);
      }
    }

    function percentile(values, p){
      var sorted = values.slice().sort(function(a, b){ return a - b; });
      var at = Math.min(sorted.length - 1,
                        Math.max(0, Math.round((p/100) * (sorted.length - 1))));
      return sorted[at];
    }

    var out = [], meanPerWeek = 0;
    for(t = 0; t < teams; t++){
      var sum = 0;
      for(i = 0; i < sims; i++) sum += pointsFor[t][i];
      var projPoints = sum / sims;
      var wSum = 0;
      for(i = 0; i < sims; i++) wSum += wins[t][i];
      meanPerWeek += projPoints / regular;
      out.push({roster_id:rosters[t].roster_id, index:t,
                projWins:wSum / sims,
                winsP10:percentile(wins[t], 10), winsP90:percentile(wins[t], 90),
                projPoints:projPoints,
                playoffOdds:madePlayoffs[t] / sims,
                titleOdds:titles[t] / sims});
    }
    meanPerWeek /= teams;
    for(t = 0; t < teams; t++){
      // One readable number, on the scale everyone already reads: points a
      // week against the league. 100 is average; a point is one percent.
      out[t].power = meanPerWeek > 0
        ? 100 * (out[t].projPoints / regular) / meanPerWeek : 100;
    }
    out.sort(function(a, b){ return b.power - a.power; });

    var missing = 0;
    for(i = 0; i < players.length; i++) if(!players[i].known) missing++;
    return {teams:out, sims:sims, weeks:regular, playoffWeeks:playoffWeeks,
            playoffTeams:playoffTeams, slots:slots.map(function(s){ return s.name; }),
            unsupported:found.unsupported, unknownPlayers:missing,
            played:played, median:median};
  }

  root.GSPower = {run:run, bracketOrder:bracketOrder, bracketRounds:bracketRounds,
                  startingSlots:startingSlots, preparePlayers:preparePlayers,
                  slotOrders:slotOrders, ELIGIBLE:ELIGIBLE, Rng:Rng};

  // `importScripts` exists in a Worker and nowhere else.
  if(typeof root.importScripts === 'function'){
    root.addEventListener('message', function(ev){
      try { root.postMessage({ok:true, result:run(ev.data)}); }
      catch(err){ root.postMessage({ok:false, error:String(err && err.message || err)}); }
    });
  }
})(typeof self !== 'undefined' ? self : this);
</script>{% endraw %}"""


JS = """{% raw %}<script>
(function(){
  var host=document.getElementById('mp-host');
  if(!host||!window.GSL) return;
  var have=GSL.saved();
  if(!have||!have.id||have.site){
    host.innerHTML='<p class="mp-none">Pick a league above, or '
      +'<a href="/fantasy/sync/">connect yours</a>, to rank it.</p>';
    return;
  }

  var API='https://api.sleeper.app/v1';
  var SIMS=10000;
  // What a reader sees while the full run finishes. Two thousand seasons is
  // a tenth of the work and lands within a point of the answer, so the table
  // appears almost at once and then settles rather than sitting empty.
  var FIRST=2000;
  var DEFAULT_WEEKS=14;

  function esc(v){
    return String(v==null?'':v).replace(/[&<>"]/g,function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});
  }
  function pct(v){ return Math.round(v*100)+'%'; }
  function get(path){
    return fetch(API+path).then(function(r){return r.ok?r.json():null;})
      .catch(function(){return null;});
  }

  /** Sleeper keeps a roster's points as an integer and its decimal, apart. */
  function points(s){ return (s.fpts||0)+((s.fpts_decimal||0)/100); }

  /** Every regular week's pairings, and the scores of the ones already played.
   *
   * Sleeper posts a week's matchup ids as soon as the schedule exists, so the
   * whole season's opponents are readable in advance; the points arrive as the
   * weeks do. A week counts as played only when every roster has a score -
   * part of a week is worse than none of it, because the teams still to play
   * would be simulated as having been shut out.
   */
  function season(id, weeks, order){
    var want=[];
    for(var w=1; w<=weeks; w++) want.push(w);
    return Promise.all(want.map(function(w){
      return get('/league/'+id+'/matchups/'+w).then(function(rows){
        return {week:w, rows:rows||[]};
      });
    })).then(function(all){
      var index={};
      order.forEach(function(rid, i){ index[String(rid)]=i; });
      var schedule=[], scores=[], played=0, stop=false;
      all.sort(function(a,b){ return a.week-b.week; });
      all.forEach(function(wk){
        var pairs=new Array(order.length), by={}, week=new Array(order.length);
        var complete=wk.rows.length===order.length;
        wk.rows.forEach(function(r){
          var seat=index[String(r.roster_id)];
          if(seat==null) return;
          var mid=r.matchup_id==null?null:String(r.matchup_id);
          if(mid!=null) (by[mid]=by[mid]||[]).push(seat);
          week[seat]=typeof r.points==='number'?r.points:0;
          if(!(r.points>0)) complete=false;
        });
        for(var k in by){
          var pair=by[k];
          if(pair.length===2){ pairs[pair[0]]=pair[1]; pairs[pair[1]]=pair[0]; }
        }
        for(var i=0;i<pairs.length;i++) if(pairs[i]==null) pairs[i]=-1;
        schedule.push(pairs);
        if(complete && !stop){ scores.push(week); played++; } else { stop=true; }
      });
      var any=schedule.some(function(row){
        return row.some(function(v){ return v>=0; }); });
      return {schedule:any?schedule:null, actual:scores, played:played};
    });
  }

  /** Run the simulation off the main thread, falling back to it if we must.
   *
   * Ten thousand seasons is seconds of solid arithmetic and a phone would
   * simply stop responding. The Worker is built from the simulation's own
   * <script> element, so there is one copy of it rather than one per thread.
   */
  function simulate(spec){
    return new Promise(function(resolve, reject){
      var src=document.getElementById('gs-power-sim');
      var url=null, worker=null;
      try{
        url=URL.createObjectURL(new Blob([src.textContent],
                                         {type:'text/javascript'}));
        worker=new Worker(url);
      }catch(e){
        if(url) URL.revokeObjectURL(url);
        // No Worker: run it here rather than show nothing. The page freezes
        // for a moment, which is worse than a Worker and better than a blank.
        try{ return resolve(window.GSPower.run(spec)); }
        catch(err){ return reject(err); }
      }
      worker.onmessage=function(ev){
        worker.terminate(); URL.revokeObjectURL(url);
        if(ev.data&&ev.data.ok) resolve(ev.data.result);
        else reject(new Error((ev.data&&ev.data.error)||'the simulation failed'));
      };
      worker.onerror=function(){
        worker.terminate(); URL.revokeObjectURL(url);
        try{ resolve(window.GSPower.run(spec)); }
        catch(err){ reject(err); }
      };
      worker.postMessage(spec);
    });
  }

  function table(result, names, order, settling){
    var best=Math.max.apply(null, result.teams.map(function(t){ return t.power; }));
    var worst=Math.min.apply(null, result.teams.map(function(t){ return t.power; }));
    var span=Math.max(best-worst, 1);
    var games=result.weeks*(result.median?2:1);
    var rows=result.teams.map(function(t, i){
      var width=Math.round(6+94*(t.power-worst)/span);
      var record=t.projWins.toFixed(1)+'-'+(games-t.projWins).toFixed(1);
      return '<tr><td><span class="mp-rank">'+(i+1)+'</span>'
        +esc(names[String(t.roster_id)]||('Roster '+t.roster_id))+'</td>'
        +'<td><span class="mp-power"><b>'+t.power.toFixed(1)+'</b>'
        +'<span class="mp-track"><i style="width:'+width+'%"></i></span></span></td>'
        +'<td class="n mp-hide">'+record+'</td>'
        +'<td class="n mp-hide">'+Math.round(t.projPoints)+'</td>'
        +'<td class="n">'+pct(t.playoffOdds)+'</td>'
        +'<td class="n">'+pct(t.titleOdds)+'</td></tr>';
    }).join('');

    var caveats=[];
    if(result.unsupported.length){
      caveats.push('This league starts '+esc(result.unsupported.join(', '))
        +', which this site does not project. Those slots are left empty, so '
        +'every team here is understated by the same kind of player.');
    }
    if(result.unknownPlayers){
      caveats.push(result.unknownPlayers+' rostered player'
        +(result.unknownPlayers===1?' is':'s are')+' not on the projection '
        +'board and stand in as deep-bench depth.');
    }

    return (caveats.length?'<p class="mp-warn">'+caveats.join(' ')+'</p>':'')
      +'<div class="mp-scroll"><table class="mp-t"><thead><tr>'
      +'<th>Team</th><th>Power</th><th class="mp-hide">Proj. record</th>'
      +'<th class="mp-hide">Proj. points</th><th>Playoffs</th><th>Title</th>'
      +'</tr></thead><tbody>'+rows+'</tbody></table></div>'
      +'<p class="mp-note">'
      +(settling?'<strong>Settling&hellip;</strong> ':'')
      +'Every roster played through the rest of the season '
      +result.sims.toLocaleString()+' times. <strong>100 is this league\\u2019s '
      +'average</strong>; a point is one percent better. '
      +(result.played?('Weeks 1&ndash;'+result.played+' are what actually '
                       +'happened, not a simulation. '):'')
      +'</p>';
  }

  host.innerHTML='<p class="mp-load">Reading '+esc(have.name||'your league')
    +'\\u2026</p>';

  Promise.all([
    GSL.league(have.id),
    fetch('/fantasy/season-board.json').then(function(r){
      return r.ok?r.json():null; }).catch(function(){ return null; })
  ]).then(function(o){
    var league=o[0], board=o[1];
    if(!board||!board.board) throw new Error('board');
    if(!league||!league.rosters.length) throw new Error('league');

    var settings=(league.info&&league.info.settings)||{};
    var weeks=Math.max((settings.playoff_week_start||(DEFAULT_WEEKS+1))-1, 1);
    var order=league.rosters.map(function(r){ return r.roster_id; })
      .sort(function(a,b){ return a-b; });
    var byId={};
    league.rosters.forEach(function(r){ byId[String(r.roster_id)]=r; });
    var rosters=order.map(function(rid){
      return {roster_id:rid, players:(byId[String(rid)].players)||[]};
    });

    host.innerHTML='<p class="mp-load">Playing '+esc(league.info.name||'the league')
      +'\\u2019s season out\\u2026</p>';

    return season(have.id, weeks, order).then(function(run){
      // Two sources have to agree about how much of the season has happened:
      // Sleeper, which has the scores, and the board, which has absorbed them
      // into each player's form. Taking the lesser keeps a week from being
      // counted as played by one and still projected by the other - the same
      // rule `power.rankings` follows on the page beside this one.
      var played=Math.min(run.played, board.week||0, weeks);
      var spec={board:board.board, posNames:board.pos, rosters:rosters,
                slots:league.slots, basis:league.basis.index, weeks:weeks,
                playoffTeams:settings.playoff_teams||6,
                median:!!settings.league_average_match,
                schedule:run.schedule,
                actual:run.actual.slice(0, played),
                sims:FIRST, seed:20260821};
      return simulate(spec).then(function(quick){
        host.innerHTML=table(quick, league.names, order, true);
        spec.sims=SIMS;
        return simulate(spec);
      }).then(function(full){
        host.innerHTML=table(full, league.names, order, false);
        var note=host.querySelector('.mp-note');
        if(note&&league.basis.custom){
          note.insertAdjacentHTML('beforeend',
            'This league\\u2019s scoring is close to '+esc(league.basis.name)
            +' but not exactly it, so the numbers are approximate. ');
        }
        if(note){
          note.insertAdjacentHTML('beforeend',
            'The ranking beside this one blends an outside source; this is '
            +'this site\\u2019s simulation alone.');
        }
      });
    });
  }).catch(function(err){
    if(err instanceof TypeError) console.error(err);
    host.innerHTML='<p class="mp-none">Could not rank this league. '
      +'Sleeper may be busy \\u2014 try again in a minute.</p>';
  });
})();
</script>{% endraw %}"""


def section() -> str:
    return CSS + "<div class='mp' id='mp-host'></div>"
