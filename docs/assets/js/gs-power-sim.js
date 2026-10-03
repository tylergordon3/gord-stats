/* window.GSPower: the season simulation, on the page or in a Worker.
   Source file, loaded by gordstats.my_power (SIM_JS_TAG); see gordstats.js_assets. */
// Written to run in either place. Ten thousand seasons is two or three seconds
// of solid arithmetic, which on a phone is a frozen page, so the page runs this
// in a Worker - built from this very file (or this element's text, when it is
// inline), so there is one copy of the simulation rather than one per thread.
// It also defines itself on the main thread, as the fallback for a browser
// that will not give us the Worker.
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
          // `out` weeks held out, starting `from` weeks after the board's
          // week (fantasy.site.season_board: 1 for a player already seen in
          // the week the board has not absorbed yet; an older board has no
          // such field, and its holds start with the week).
          players.push({id:pid, team:t, pos:posNames[row[0]], bye:row[1],
                        mu:mu, sd:Math.max(row[3]*shrink, MIN_SD),
                        muSe:row[4]*shrink, avail:row[5], out:row[7] || 0,
                        from:row[8] || 0, known:true});
        } else {
          players.push({id:pid, team:t, pos:'WR', bye:0, mu:3.0, sd:3.0,
                        muSe:3.0, avail:0.6, out:0, from:0, known:false});
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

  /** Weeks each of `rounds` playoff rounds lasts, from `spec.roundWeeks`
   *  (GSPowerLeague.roundLengths: Sleeper's playoff_round_type, ESPN's
   *  matchup periods). One week a round wherever it says nothing. */
  function roundLengths(given, rounds){
    var out = [];
    for(var r = 0; r < rounds; r++){
      var n = given && given[r];
      out.push(n >= 2 ? Math.floor(n) : 1);
    }
    return out;
  }

  /** The champion's team index, from playoff-week points and the seeding.
   *
   * Round one is the standard draw, byes to the top seeds. After it the
   * bracket is fixed - the 1 seed meets the 4/5 winner - or, `reseed`
   * (Sleeper's playoff_seed_type 1, ESPN's playoffReseed), redrawn every
   * round so the best seed left meets the worst left. Higher points wins,
   * the better seed on a tie. `decided` is [[team index, ...] per round]:
   * whoever Sleeper's winners bracket says lost a round already played loses
   * it here too, and every round after. `lens` is the weeks each round lasts
   * (one where not given): a two-week round is won on both weeks' points
   * together, as Sleeper and ESPN decide it, and the next round starts after
   * both. fantasy.league.power._bracket is the same bracket in Python, one
   * week a round.
   */
  function runBracket(points, seeds, week0, reseed, decided, lens){
    var size = 1;
    while(size < seeds.length) size *= 2;
    var order = bracketOrder(size);
    // Bracket positions as seed numbers (0 is the top seed), -1 a bye.
    var field = [];
    for(var i = 0; i < size; i++) field.push(order[i] <= seeds.length ? order[i] - 1 : -1);
    var round = 0, at = week0, out = {};
    while(field.length > 1){
      var lost = decided && decided[round];
      if(lost) for(var q = 0; q < lost.length; q++) out[lost[q]] = 1;
      var span = (lens && lens[round] >= 2) ? Math.floor(lens[round]) : 1;
      var week = points[at] || points[points.length - 1];
      if(span > 1){
        // The round's score is the sum of its weeks.
        var sum = Array.prototype.slice.call(week);
        for(var k = 1; k < span; k++){
          var more = points[at + k] || points[points.length - 1];
          for(var z = 0; z < sum.length; z++) sum[z] += more[z];
        }
        week = sum;
      }
      var next = [];
      for(var j = 0; j < field.length; j += 2){
        var a = field[j], b = field[j + 1];
        if(a < 0){ next.push(b); continue; }
        if(b < 0){ next.push(a); continue; }
        var pa = out[seeds[a]] ? -Infinity : week[seeds[a]];
        var pb = out[seeds[b]] ? -Infinity : week[seeds[b]];
        next.push(pa >= pb ? a : b);
      }
      if(reseed && next.length > 2){
        // Best left against worst left: sorted, then paired from the ends.
        next.sort(function(x, y){ return x - y; });
        var paired = [];
        for(var k = 0; k < next.length / 2; k++) paired.push(next[k], next[next.length - 1 - k]);
        next = paired;
      }
      field = next;
      at += span;
      round++;
    }
    return seeds[field[0]];
  }

  /** One week's results added into `h2h` and `med` (arrays by team): a win
   *  is 1 and a tie half of one, as Sleeper's W-L-T counts it in a standings
   *  race. The median game is won by scoring above the week's median - in an
   *  even league the mean of the middle two, so two teams level across it
   *  take half each; an odd league's top half by rank wins it, as before.
   *  fantasy.league.power.actual_results counts the played weeks the same. */
  function weekWins(row, pairs, median, h2h, med){
    var n = row.length, t;
    if(pairs){
      for(t = 0; t < n; t++){
        var o = pairs[t];
        if(o == null || o < 0 || o === t) continue;
        if(row[t] > row[o]) h2h[t] += 1;
        else if(row[t] === row[o]) h2h[t] += 0.5;
      }
    }
    if(!median || n < 2) return;
    var order = [];
    for(t = 0; t < n; t++) order.push(t);
    order.sort(function(a, b){ return row[b] - row[a]; });
    var half = Math.floor(n / 2);
    if(n % 2 === 0){
      var mid = (row[order[half - 1]] + row[order[half]]) / 2;
      for(t = 0; t < n; t++) med[t] += row[t] > mid ? 1 : row[t] === mid ? 0.5 : 0;
    } else {
      for(var r = 0; r < half; r++) med[order[r]] += 1;
    }
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
    // `pool`: players on no roster who still draw their numbers - the free
    // agents a trade may sign, and whoever it drops. With them in every run
    // the set of players is the same whichever rosters are handed in.
    if(spec.pool && spec.pool.length){
      var seen = {};
      for(var q = 0; q < players.length; q++) seen[players[q].id] = 1;
      var extra = preparePlayers(spec.board || {}, spec.posNames || [],
        [{players:spec.pool.filter(function(id){ return !seen[String(id)]; })}],
        spec.basis || 0);
      for(q = 0; q < extra.length; q++){ extra[q].team = -1; players.push(extra[q]); }
    }
    // `stable` lays the players out by id rather than by roster, so every
    // player draws the same numbers whichever team holds him. The trade page
    // runs a league twice, before and after a deal, and with the draws shared
    // the difference between the runs is the deal rather than the dice.
    if(spec.stable) players.sort(function(a, b){ return a.id < b.id ? -1 : a.id > b.id ? 1 : 0; });
    var found = startingSlots(spec.slots);
    var slots = found.slots;
    var regular = Math.max(spec.weeks || 14, 1);
    var playoffTeams = Math.min(Math.max(spec.playoffTeams || 6, 2), teams);
    var rounds = bracketRounds(playoffTeams);
    // A round can be two weeks (Sleeper's playoff_round_type, ESPN's
    // matchup periods): the bracket then takes more weeks than it has rounds.
    var lens = roundLengths(spec.roundWeeks, rounds);
    var playoffWeeks = 0;
    for(var lr = 0; lr < lens.length; lr++) playoffWeeks += lens[lr];
    var total = regular + playoffWeeks;
    var orders = slotOrders(players, teams, slots);
    var sims = Math.max(spec.sims || 2000, 1);
    var rng = new Rng(spec.seed || 20260821);

    var actual = spec.actual || [];
    var played = Math.min(actual.length, regular);
    var schedule = spec.schedule || null;
    var median = !!spec.median;
    // The bracket as the league plays it, and as far as it has been played:
    // `playoffActual` is the real scores of the playoff weeks over, `decided`
    // who Sleeper's winners bracket has knocked out, round by round. Both only
    // once every regular week is in - a team knocked out stops holding title
    // odds, as fantasy.league.power has it (playoff_points, bracket_losers).
    var reseed = !!spec.reseed;
    var over = played >= regular;
    var playoffActual = over ? (spec.playoffActual || []).slice(0, playoffWeeks) : [];
    var decided = over ? (spec.decided || null) : null;
    // The week the board counts its holds from (its own `week`, the last NFL
    // week it absorbed), so a hold lands on the NFL weeks it is about however
    // far this league has got - one whose scores lag, or whose regular season
    // is over, would otherwise slide every hold onto the wrong weeks. Without
    // it, the weeks played, as before.
    var holdWeek = (spec.holdWeek != null && isFinite(+spec.holdWeek))
      ? Math.max(Math.floor(+spec.holdWeek), 0) : played;

    var n = players.length;
    var mu = new Float64Array(n), sd = new Float64Array(n),
        muSe = new Float64Array(n), avail = new Float64Array(n),
        leave = new Float64Array(n), held = new Int32Array(n),
        heldFrom = new Int32Array(n), bye = new Int32Array(n);
    for(var i = 0; i < n; i++){
      mu[i] = players[i].mu; sd[i] = Math.max(players[i].sd, MIN_SD);
      muSe[i] = players[i].muSe; avail[i] = players[i].avail;
      held[i] = players[i].out; bye[i] = players[i].bye;
      heldFrom[i] = holdWeek + (players[i].from || 0);
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
    var restPoints = new Float64Array(teams);
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
          var sidelined = (week >= played) && (week >= heldFrom[i]) &&
                          (week < heldFrom[i] + held[i]);
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
      for(week = 0; week < playoffActual.length; week++){
        for(t = 0; t < teams; t++) weekPoints[regular + week][t] = playoffActual[week][t] || 0;
      }

      var table = schedule || roundRobin(rng, teams, regular);
      var seasonWins = new Float64Array(teams), seasonPoints = new Float64Array(teams);
      for(week = 0; week < regular; week++){
        var row = weekPoints[week];
        for(t = 0; t < teams; t++){
          seasonPoints[t] += row[t];
          if(week >= played) restPoints[t] += row[t];
        }
        weekWins(row, table[week % table.length], median, seasonWins, seasonWins);
      }

      var seeded = [];
      for(t = 0; t < teams; t++) seeded.push(t);
      seeded.sort(function(a, b){
        return (seasonWins[b] - seasonWins[a]) || (seasonPoints[b] - seasonPoints[a]);
      });
      var seeds = seeded.slice(0, playoffTeams);
      for(var r = 0; r < seeds.length; r++) madePlayoffs[seeds[r]] += 1;
      if(playoffWeeks > 0) titles[runBracket(weekPoints, seeds, regular, reseed, decided, lens)] += 1;

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
                // Points a week over the regular weeks still to be played.
                restPerWeek:regular > played ? restPoints[t] / sims / (regular - played) : 0,
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
    for(i = 0; i < players.length; i++) if(!players[i].known && players[i].team >= 0) missing++;
    return {teams:out, sims:sims, weeks:regular, playoffWeeks:playoffWeeks,
            playoffRounds:rounds, roundWeeks:lens,
            playoffTeams:playoffTeams, slots:slots.map(function(s){ return s.name; }),
            unsupported:found.unsupported, unknownPlayers:missing,
            played:played, median:median};
  }

  root.GSPower = {run:run, bracketOrder:bracketOrder, bracketRounds:bracketRounds,
                  roundLengths:roundLengths, runBracket:runBracket, weekWins:weekWins,
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
