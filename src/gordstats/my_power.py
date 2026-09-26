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
from gordstats import tables


CSS = """<style>
.mp{margin:8px 0 22px}
.mp h2{margin:18px 0 6px;font-size:18px}
.mp-note{font-size:12.5px;color:#64748b;margin:0 0 10px;line-height:1.5}
.mp-none{font-size:14px;color:#475569}
.mp-load{font-size:13px;color:#64748b}
.mp-warn{font-size:12.5px;color:#92400e;background:#fffbeb;border:1px solid #fde68a;
  border-radius:8px;padding:8px 11px;margin:0 0 12px;line-height:1.5}
/* The table itself is the site's `sticky-table` inside `.table-scroll`, the
   same pair the built ranking beside it uses - a reader's league should not
   be a second look. What is left here is the page furniture around it: the
   loading line, the caveats and the note. The old `mp-t` table, its own rank
   column and its little power bars are gone with it. */
@media (prefers-color-scheme: dark){
  .mp-note,.mp-none,.mp-load{color:#aab7c9}
  .mp-warn{color:#fcd34d;background:#2a2410;border-color:#4a3c13}
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

  /** (weeks, teams) opponent indices from a randomly rotated circle.
   *
   * -1 means nobody, and every row starts that way. An odd-sized league leaves
   * one team out each week, which is what actually happens to it; filled with
   * zeroes instead, that team would have been scored against whoever sat at
   * index 0 - a phantom fixture, every week, for a league this page has no
   * other reason to get wrong.
   */
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
      for(i = 0; i < teams; i++) row[i] = -1;
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
    // Drawn twice: once now, and again when the account call settles, because
    // whether to offer a sign-in or a league picker is not known at first paint.
    var none=function(){ host.innerHTML=window.GSLeague
      ? GSLeague.empty('mp-none','power rankings')
      : '<p class="mp-none">Pick a league above to see its power rankings.</p>'; };
    none();
    if(window.GSLeague&&GSLeague.ready) GSLeague.ready.then(none,none);
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

  // matplotlib's RdYlGn, the eleven anchors pandas interpolates between, so a
  // reader's column is shaded on the same scale as the built page's.
  var RDYLGN=[[165,0,38],[215,48,39],[244,109,67],[253,174,97],[254,224,139],
              [255,255,191],[217,239,139],[166,217,106],[102,189,99],[26,152,80],
              [0,104,55]];
  function ramp(t){
    t=Math.min(Math.max(t,0),1);
    var x=t*(RDYLGN.length-1), i=Math.min(Math.floor(x),RDYLGN.length-2), f=x-i;
    var a=RDYLGN[i], b=RDYLGN[i+1];
    return [Math.round(a[0]+(b[0]-a[0])*f), Math.round(a[1]+(b[1]-a[1])*f),
            Math.round(a[2]+(b[2]-a[2])*f)];
  }
  /** A cell shaded like pandas' background_gradient: the column normalised
   *  over its own min and max, and the text flipped where the fill is dark. */
  function shade(value, lo, hi){
    if(value==null||value!==value||hi<=lo) return '';
    var c=ramp((value-lo)/(hi-lo));
    var lum=(0.299*c[0]+0.587*c[1]+0.114*c[2])/255;
    return 'background-color:rgb('+c[0]+','+c[1]+','+c[2]+');color:'
      +(lum<0.5?'#f8fafc':'#0f172a');
  }
  function bounds(values){
    var ok=values.filter(function(v){ return v!=null&&v===v; });
    if(!ok.length) return [0,1];
    return [Math.min.apply(null,ok), Math.max.apply(null,ok)];
  }

  /** Each team's real record so far, and how far it sits from what its
   *  scores deserved - fantasy.league.power.actual_records, in the browser.
   *  `actual` is one array of scores per played week, in `order`. */
  function records(actual, schedule, median){
    var n=(actual[0]||[]).length, h2h=[], med=[], allplay=[];
    for(var i=0;i<n;i++){ h2h.push(0); med.push(0); allplay.push(0); }
    actual.forEach(function(week, w){
      var pairs=(schedule&&schedule[w])||[];
      for(var a=0;a<n;a++){
        var b=pairs[a];
        if(b!=null&&b>=0&&week[a]>week[b]) h2h[a]+=1;
      }
      // Rank 0 is the week's top scorer, as the built page counts it.
      var seats=[];
      for(var i2=0;i2<n;i2++) seats.push(i2);
      seats.sort(function(x,y){ return week[y]-week[x]; });
      seats.forEach(function(seat, rank){
        if(median && rank < Math.floor(n/2)) med[seat]+=1;
        allplay[seat]+=(n-1)-rank;
      });
    });
    var played=actual.length, perWeek=median?2:1;
    return h2h.map(function(w, i){
      var pct=played?allplay[i]/(played*(n-1)):0;
      return {wins:w+med[i], losses:perWeek*played-(w+med[i]),
              luck:(w+med[i])-pct*perWeek*played};
    });
  }

  function table(result, names, order, settling, real){
    var games=result.weeks*(result.median?2:1);
    var pw=bounds(result.teams.map(function(t){ return t.power; }));
    var po=bounds(result.teams.map(function(t){ return t.playoffOdds; }));
    // A seat's index in `order`, which is what `records` is laid out by.
    var seat={};
    order.forEach(function(rid, i){ seat[String(rid)]=i; });
    var played=real&&real.length?result.played:0;
    var luckBound=1;
    if(played) luckBound=Math.max(1, Math.max.apply(null,
      real.map(function(r){ return Math.abs(r.luck); })));

    var rows=result.teams.map(function(t, i){
      var mine=real&&real[seat[String(t.roster_id)]];
      var record=played&&mine
        ? ('<td>'+mine.wins+'-'+mine.losses+'</td>'
           +'<td style="'+shade(mine.luck,-luckBound,luckBound)+'">'
           +(mine.luck>=0?'+':'')+mine.luck.toFixed(1)+'</td>')
        : '';
      return '<tr><td><span class="row-rank">'+(i+1)+'</span>'
        +esc(names[String(t.roster_id)]||('Roster '+t.roster_id))+'</td>'
        +'<td style="'+shade(t.power,pw[0],pw[1])+'">'+t.power.toFixed(1)+'</td>'
        +record
        +'<td>'+t.projWins.toFixed(1)+'-'+(games-t.projWins).toFixed(1)+'</td>'
        +'<td style="'+shade(t.playoffOdds,po[0],po[1])+'">'+pct(t.playoffOdds)+'</td>'
        +'<td>'+pct(t.titleOdds)+'</td></tr>';
    }).join('');
    var head='<th>Team</th><th>Power</th>'
      +(played?'<th>Record</th><th>Luck</th>':'')
      +'<th>Proj. Record</th><th>Playoffs</th><th>Title</th>';

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
      +'<div class="table-scroll"><table class="sticky-table"><thead><tr>'
      +head+'</tr></thead><tbody>'+rows+'</tbody></table></div>'
      +'<p class="mp-note">'
      +(settling?'<strong>Settling&hellip;</strong> ':'')
      +'Every roster played through the rest of the season '
      +result.sims.toLocaleString()+' times. <strong>100 is this league\\u2019s '
      +'average</strong>; a point is one percent better. '
      +(played?('Weeks 1&ndash;'+result.played+' are what actually happened, not a '
                +'simulation; <strong>Record</strong> is what they returned'
                +(result.median?', the weekly median win included':'')
                +', and <strong>Luck</strong> is that record minus what an '
                +'all-play schedule says the scores deserved. '):'')
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
      // What the played weeks actually returned, so the table can carry the
      // built page's Record and Luck columns rather than projections alone.
      var real=played?records(spec.actual, run.schedule, spec.median):null;
      var head=document.getElementById('pw-mine-h');
      if(head) head.textContent=league.info.name||'Your league';
      var built=document.getElementById('pw-built');
      var intro=document.getElementById('pw-intro');
      // A reader who has picked a league is here for that league: this site's
      // ranking would only raise the question of whose numbers are on screen.
      if(built) built.hidden=true;
      if(intro) intro.hidden=true;
      return simulate(spec).then(function(quick){
        host.innerHTML=table(quick, league.names, order, true, real);
        spec.sims=SIMS;
        return simulate(spec);
      }).then(function(full){
        host.innerHTML=table(full, league.names, order, false, real);
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
    return CSS + tables.dark_rows(".mp") + "<div class='mp' id='mp-host'></div>"
