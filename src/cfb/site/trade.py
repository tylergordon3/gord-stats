"""
Trade analyzer for the college fantasy league (docs/cfb/trade/): pick a deal
and see what it does to both teams' seasons. The page is
gordstats.trade_page, shared with the NFL league; this is its adapter.

The season is played the way the Power tab plays it (cfb.league_sim): every
remaining week each roster starts its best lineup on that week's projections
(cfb.weekly - byes, the opponent through the game model, the week's injury
tags), a lineup's week scatters around its projection, and the wins land on
Yahoo's standings with the median game, byes and the reseeded bracket after.
That simulation is Python and takes the rosters as given, so it is ported to
the browser here, and the page ships what it needs: every rostered player's
projection for each week left, and the best few free agents'.

The port works at the level league_sim does - a team's week is one normal
draw around its lineup's projection - and draws the same numbers for the same
team and week in both runs, so the two differ by the trade alone. A week
already being played stays as Yahoo has it: a trade cannot reach games under
way.

    python -m cfb.site.trade
"""
import json

import pandas as pd

from cfb import in_season, league_sim, predict, weekly, yahoo
from cfb.config import MY_TEAM, WEB_DIR
from cfb.site import write_page
from cfb.site.league_power import team_rosters
from gordstats import trade_page

OUTPUT = WEB_DIR / "trade" / "index.html"
SIMS = league_sim.SIMS
FA_PER_POS = 5                 # the free agents a trade may sign, and Pick up tries
RESERVE = ("IL", "IR")


def data(lg: dict = None, rosters: dict = None, board: pd.DataFrame = None,
         frame: pd.DataFrame = None, live: bool = True) -> dict:
    """Everything the browser's season needs, or {} before there is a season."""
    lg = yahoo.league() if lg is None else lg
    rosters = team_rosters() if rosters is None else rosters
    if not any(rosters.values()):
        return {}
    sched = league_sim.schedule(lg)
    if not sched:
        return {}
    if frame is None:
        frame, _m, _n = predict.season()
    board = (in_season.board(frame=frame) if board is None else board).drop_duplicates("yahoo_id")
    by_id = board.set_index(board["yahoo_id"].astype(str))
    cur = int(lg["current_week"])
    week_rosters = (yahoo.week_matchups(cur)["rosters"]
                    if cur in yahoo.archived_weeks() else {})
    # Yahoo's designations describe today, so they price the week at hand -
    # league_sim.weekly_means' rule.
    injuries = ({str(p["yahoo_id"]): p.get("status") or ""
                 for r in week_rosters.values() for p in r} if live else {})
    weeks = sorted(sched)
    playoff_start = int(lg["playoff_start_week"] or lg["end_week"] + 1)
    regular = [i for i, w in enumerate(weeks) if w < playoff_start] or list(range(len(weeks)))

    proj: dict = {}
    now: dict = {}
    for i, week in enumerate(weeks):
        span = sched[week]
        wk = weekly.week_projections(span["start"], span["end"], board=board, league=lg,
                                     frame=frame, injuries=injuries if i == 0 else None)
        if i == 0 and live:
            now = league_sim._live_week(week, wk, frame)
        for pid, v in wk["proj_week"].items():
            if str(pid) in by_id.index:
                proj.setdefault(str(pid), [None] * len(weeks))[i] = \
                    0.0 if pd.isna(v) else round(float(v), 2)

    held = {str(p) for ids in rosters.values() for p in ids}
    per_week = {pid: sum(v[i] or 0.0 for i in regular) / len(regular) for pid, v in proj.items()}
    free = []
    for pos in ("QB", "RB", "WR", "TE", "DEF"):
        pool = [pid for pid in proj if pid not in held and by_id.loc[pid, "pos"] == pos]
        free += sorted(pool, key=lambda p: -per_week[p])[:FA_PER_POS]
    free.sort(key=lambda p: -per_week[p])

    named = {str(p["yahoo_id"]): p for r in week_rosters.values() for p in r}
    players = {}
    for pid in sorted(held | set(free)):
        if pid in by_id.index:
            row = by_id.loc[pid]
            players[pid] = [str(row["player"]), str(row["pos"]), str(row.get("school") or ""),
                            proj.get(pid), injuries.get(pid, "")]
        elif pid in named:                  # on a roster, not on the board: unrated
            p = named[pid]
            players[pid] = [p.get("player") or pid, p.get("pos") or "?", p.get("team") or "",
                            None, injuries.get(pid, "")]

    lg, played = league_sim.standings(lg)
    keys = sorted(rosters)
    teams = {t["team_key"]: t for t in lg["teams"]}
    pairs = {str(w): [list(p) for p in sched[w]["pairs"]] for w in weeks}
    return {
        "weeks": weeks, "playoff_start": playoff_start, "end_week": int(lg["end_week"]),
        "field": int(lg.get("num_playoff_teams") or 0),
        "median": bool(lg.get("uses_median_score")),
        "reseed": bool(lg.get("uses_playoff_reseeding")),
        "slots": [[s["position"], int(s["count"])] for s in lg["roster"]],
        "active": sum(int(s["count"]) for s in lg["roster"] if s["position"] not in RESERVE),
        "teams": [{"key": k, "name": teams.get(k, {}).get("name") or k,
                   "wins": float(teams.get(k, {}).get("wins") or 0),
                   "ties": float(teams.get(k, {}).get("ties") or 0),
                   "losses": float(teams.get(k, {}).get("losses") or 0),
                   "pf": float(teams.get(k, {}).get("points_for") or 0)} for k in keys],
        "rosters": {k: [str(p) for p in dict.fromkeys(rosters[k])] for k in keys},
        "reserve": {k: [str(p["yahoo_id"]) for p in week_rosters.get(k, [])
                        if p.get("slot") in RESERVE] for k in keys},
        "pairs": pairs,
        "live": {k: [round(m, 3), round(v, 3)] for k, (m, v) in now.items()},
        "played": {str(w): got for w, got in played.items()},
        "players": players, "free": free,
        "mine": next((t["team_key"] for t in lg["teams"] if t["name"] == MY_TEAM), None),
        "sims": SIMS, "seed": league_sim.SEED,
    }


ADAPTER_JS = """{% raw %}<script>
window.GSTradeAdapter = (function(){
  'use strict';
  var D = JSON.parse(document.getElementById('tr-data').textContent);
  var FLEX = 'W/R/T', FLEX_POS = ['RB','WR','TE'], POSITIONS = ['QB','RB','WR','TE','DEF'];
  var SD_SHARE = 0.55, SD_FLOOR = 2.0;
  var W = D.weeks.length, N = D.teams.length;
  var keys = D.teams.map(function(t){ return t.key; });
  var REG = [];
  D.weeks.forEach(function(w, i){ if(w < D.playoff_start) REG.push(i); });
  var PER = REG.length ? REG : D.weeks.map(function(w, i){ return i; });

  function esc(v){
    return String(v==null?'':v).replace(/[&<>"]/g, function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; });
  }
  function p(pid){ return D.players[pid]; }
  function name(pid){ return p(pid) ? p(pid)[0] : pid; }
  function pos(pid){ return p(pid) ? p(pid)[1] : '?'; }
  function proj(pid, w){ var q = p(pid); return q && q[3] ? q[3][w] : null; }
  /** Points a week over the regular weeks left, byes counted as nothing. */
  function ppw(pid){
    var q = p(pid);
    if(!q || !q[3]) return null;
    var s = 0;
    PER.forEach(function(i){ s += q[3][i] || 0; });
    return s / PER.length;
  }
  function sd2(v){ var s = Math.max(SD_FLOOR, SD_SHARE * v); return s * s; }

  /** The best lineup on `value` (cfb.site.league_power.best_lineup): the
   *  dedicated slots take the top of their position whatever it scores, the
   *  flex the best skill player left who scores at all. */
  function lineup(ids, value){
    var pools = {};
    POSITIONS.forEach(function(ps){ pools[ps] = []; });
    ids.forEach(function(pid, k){
      var v = value(pid);
      if(v == null || !pools[pos(pid)]) return;
      pools[pos(pid)].push({id:pid, v:v, k:k});
    });
    POSITIONS.forEach(function(ps){
      pools[ps].sort(function(x, y){ return (y.v - x.v) || (x.k - y.k); });
    });
    var used = {}, mean = 0, v2 = 0, starters = [], flex = 0;
    POSITIONS.forEach(function(ps){ used[ps] = 0; });
    D.slots.forEach(function(s){
      var slot = s[0], n = s[1];
      if(slot === FLEX){ flex += n; return; }
      if(!pools[slot]) return;
      for(var i = 0; i < n; i++){
        var pool = pools[slot];
        if(used[slot] < pool.length){
          var q = pool[used[slot]];
          mean += q.v; v2 += sd2(q.v); starters.push(q.id);
        }
        used[slot]++;
      }
    });
    for(var f = 0; f < flex; f++){
      var at = null, best = 0;
      FLEX_POS.forEach(function(ps){
        var pool = pools[ps];
        if(used[ps] < pool.length && pool[used[ps]].v > best){ best = pool[used[ps]].v; at = ps; }
      });
      if(!at) continue;
      var q2 = pools[at][used[at]];
      mean += q2.v; v2 += sd2(q2.v); starters.push(q2.id);
      used[at]++;
    }
    return {mean:mean, v:v2, starters:starters};
  }

  /** mean[w][t] and sd[w][t] (cfb.league_sim.weekly_means). */
  function means(rosters){
    var M = [], S = [];
    for(var w = 0; w < W; w++){
      M.push(new Float64Array(N)); S.push(new Float64Array(N));
      for(var t = 0; t < N; t++){
        var live = w === 0 ? D.live[keys[t]] : null;
        var lu = live ? {mean:live[0], v:live[1]}
                      : lineup(rosters[keys[t]] || [], function(pid){ return proj(pid, w); });
        M[w][t] = lu.mean; S[w][t] = Math.sqrt(lu.v);
      }
    }
    return {M:M, S:S};
  }

  // xorshift128 and Marsaglia's polar method, seeded, as gordstats.my_power.
  function Rng(seed){
    this.a = (seed >>> 0) || 1; this.b = 362436069; this.c = 521288629; this.d = 88675123;
    this.spare = null;
    for(var i = 0; i < 12; i++) this.next();
  }
  Rng.prototype.next = function(){
    var t = this.d, s = this.a;
    this.d = this.c; this.c = this.b; this.b = s;
    t ^= t << 11; t ^= t >>> 8; t ^= s; t ^= s >>> 19;
    this.a = t;
    return (t >>> 0) / 4294967296;
  };
  Rng.prototype.normal = function(){
    if(this.spare !== null){ var v = this.spare; this.spare = null; return v; }
    var u, x, s;
    do { u = this.next()*2-1; x = this.next()*2-1; s = u*u + x*x; } while(s === 0 || s >= 1);
    var m = Math.sqrt(-2*Math.log(s)/s);
    this.spare = x*m;
    return u*m;
  };

  /** The champion from the seeds (cfb.league_sim._bracket): the top seeds
   *  sit out round one until the field is a power of two, then the best left
   *  meets the worst, reseeded each round where the league does. */
  function bracket(seeds, score, rounds, reseed){
    var alive = seeds.slice(), size = 1, rnd = 0, seedOf = {};
    while(size < seeds.length) size *= 2;
    var byes = size - seeds.length;
    seeds.forEach(function(t, i){ seedOf[t] = i; });
    while(alive.length > 1){
      var sit = [], play = alive;
      if(byes){ sit = alive.slice(0, byes); play = alive.slice(byes); byes = 0; }
      var k = Math.floor(play.length / 2), win = [], r = Math.min(rnd, rounds - 1);
      for(var i = 0; i < k; i++){
        var hi = play[i], lo = play[play.length - 1 - i];
        win.push(score(r, hi) >= score(r, lo) ? hi : lo);
      }
      alive = sit.concat(win);
      if(reseed) alive.sort(function(x, y){ return seedOf[x] - seedOf[y]; });
      rnd++;
    }
    return alive[0];
  }

  /** {teamKey: Stat}: cfb.league_sim.simulate, on these rosters. */
  function simulate(rosters, sims){
    var mm = means(rosters), M = mm.M, S = mm.S;
    var idx = {};
    keys.forEach(function(k, i){ idx[k] = i; });
    var wins0 = new Float64Array(N), pf0 = new Float64Array(N);
    D.teams.forEach(function(t, i){ wins0[i] = t.wins + 0.5 * t.ties; pf0[i] = t.pf; });
    var pairs = D.weeks.map(function(w){
      return (D.pairs[String(w)] || []).map(function(pr){ return [idx[pr[0]], idx[pr[1]]]; })
        .filter(function(pr){ return pr[0] != null && pr[1] != null; });
    });
    // The bracket's rounds in week order: a played one as it happened, the
    // rest drawn like any other week.
    var rounds = [];
    for(var wk = D.playoff_start; wk <= D.end_week; wk++){
      var got = D.played[String(wk)];
      if(got) rounds.push({fixed:keys.map(function(k){ return +(got[k] || 0); })});
      else if(D.weeks.indexOf(wk) >= 0) rounds.push({at:D.weeks.indexOf(wk)});
    }
    if(!rounds.length) rounds.push({at:W - 1});
    var field = Math.min(D.field, N), size = 1;
    while(size < field) size *= 2;
    var winSum = new Float64Array(N), made = new Float64Array(N), bye = new Float64Array(N),
        title = new Float64Array(N);
    var s = new Float64Array(W * N), totW = new Float64Array(N), totPF = new Float64Array(N);
    var order = [], rng = new Rng(D.seed || 20260928);
    var half = Math.floor(N / 2);
    function score(r, t){
      var rd = rounds[r];
      return rd.fixed ? rd.fixed[t] : s[rd.at * N + t];
    }
    for(var sim = 0; sim < sims; sim++){
      for(var w = 0; w < W; w++)
        for(var t = 0; t < N; t++) s[w*N + t] = M[w][t] + S[w][t] * rng.normal();
      for(t = 0; t < N; t++){ totW[t] = wins0[t]; totPF[t] = pf0[t]; }
      for(var j = 0; j < REG.length; j++){
        w = REG[j];
        var base = w * N;
        for(t = 0; t < N; t++) totPF[t] += s[base + t];
        pairs[w].forEach(function(pr){
          var x = s[base + pr[0]], y = s[base + pr[1]];
          if(x > y) totW[pr[0]] += 1; else if(y > x) totW[pr[1]] += 1;
          else { totW[pr[0]] += 0.5; totW[pr[1]] += 0.5; }
        });
        if(D.median){
          var rank = [];
          for(t = 0; t < N; t++) rank.push(t);
          rank.sort(function(x, y){ return s[base + y] - s[base + x]; });
          for(var r = 0; r < half; r++) totW[rank[r]] += 1;
        }
      }
      order.length = 0;
      for(t = 0; t < N; t++){ order.push(t); winSum[t] += totW[t]; }
      order.sort(function(x, y){ return (totW[y] - totW[x]) || (totPF[y] - totPF[x]); });
      if(field){
        var seeds = order.slice(0, field);
        for(r = 0; r < seeds.length; r++) made[seeds[r]] += 1;
        for(r = 0; r < size - field; r++) bye[seeds[r]] += 1;
        title[field > 1 ? bracket(seeds, score, rounds.length, D.reseed) : seeds[0]] += 1;
      }
    }
    var games = REG.length * (D.median ? 2 : 1), out = {};
    D.teams.forEach(function(team, i){
      var wins = winSum[i] / sims, per = 0;
      PER.forEach(function(w){ per += M[w][i]; });
      out[team.key] = {ppw:per / PER.length, wins:wins,
                       losses:team.losses + games - (wins - wins0[i]),
                       playoffs:made[i] / sims, bye:bye[i] / sims, title:title[i] / sims};
    });
    return out;
  }

  // ----- the deal ---------------------------------------------------------- //

  var FREE = D.free.slice();
  function starters(ids){ return lineup(ids, ppw).starters; }

  function settle(key, ids, sent, got, signed, lines, cut){
    var aside = {};
    (D.reserve[key] || []).forEach(function(pid){ aside[pid] = 1; });
    var active = ids.filter(function(pid){ return !aside[pid]; });
    var line = starters(ids);
    var was = starters(ids.filter(function(pid){ return got.indexOf(pid) < 0; }).concat(sent));
    if(active.length > D.active){
      var start = {};
      line.forEach(function(pid){ start[pid] = 1; });
      active.filter(function(pid){ return !start[pid] && got.indexOf(pid) < 0; })
        .sort(function(x, y){ return (ppw(x) || 0) - (ppw(y) || 0); })
        .slice(0, active.length - D.active)
        .forEach(function(pid){
          if(cut) cut.push(pid);
          ids.splice(ids.indexOf(pid), 1);
          lines.push('Drops ' + esc(name(pid)) + ' (' + esc(pos(pid)) + ') to make room.');
        });
    } else if(sent.length > got.length){
      var want = sent.map(pos);
      got.forEach(function(pid){ var k = want.indexOf(pos(pid)); if(k >= 0) want.splice(k, 1); });
      var room = Math.min(sent.length - got.length, Math.max(D.active - active.length, 0));
      for(var i = 0; i < room; i++){
        var at = want[i];
        var pick = FREE.filter(function(pid){ return !signed[pid] && (!at || pos(pid) === at); })[0]
          || FREE.filter(function(pid){ return !signed[pid] && FLEX_POS.indexOf(pos(pid)) >= 0; })[0];
        if(!pick) break;
        signed[pick] = 1;
        ids.push(pick);
        lines.push('Signs ' + esc(name(pick)) + ', the best free agent at ' + esc(pos(pick))
                   + ' (' + ppw(pick).toFixed(1) + ' a week).');
      }
    }
    var now = starters(ids);
    var inn = now.filter(function(pid){ return was.indexOf(pid) < 0; });
    var off = was.filter(function(pid){ return now.indexOf(pid) < 0 && sent.indexOf(pid) < 0; });
    if(inn.length) lines.push('Starts ' + inn.map(function(pid){ return esc(name(pid)); }).join(', ') + '.');
    if(off.length) lines.push('To the bench: ' + off.map(function(pid){ return esc(name(pid)); }).join(', ') + '.');
  }

  function short(n){
    var parts = String(n || '').split(' ');
    return parts.length < 2 ? n : parts[0].charAt(0) + '. ' + parts.slice(1).join(' ');
  }

  var before = null;
  function load(){
    return new Promise(function(resolve){
      var players = {};
      keys.forEach(function(k){
        var aside = {};
        (D.reserve[k] || []).forEach(function(pid){ aside[pid] = 1; });
        (D.rosters[k] || []).forEach(function(pid){
          var q = p(pid) || [pid, '?', '', null, ''];
          var tag = aside[pid] ? 'IL' : (q[4] && q[4] !== 'Q' ? q[4] : '');
          players[pid] = {name:q[0], short:pos(pid) === 'DEF' ? q[0] : short(q[0]), pos:q[1],
                          ppw:ppw(pid), tag:tag};
        });
      });
      FREE.forEach(function(pid){
        var q = p(pid) || [pid, '?', '', null, ''];
        players[pid] = {name:q[0], short:pos(pid) === 'DEF' ? q[0] : short(q[0]), pos:q[1],
                        ppw:ppw(pid), tag:q[4] && q[4] !== 'Q' ? q[4] : ''};
      });
      var mine = null;
      try{ mine = localStorage.getItem('cfbMyTeam'); }catch(e){}
      if(!mine || keys.indexOf(mine) < 0) mine = D.mine;
      // A tick for the page to paint "Reading the league" before the work.
      setTimeout(function(){
        before = simulate(D.rosters, D.sims);
        resolve({teams:D.teams.map(function(t){ return {id:t.key, name:t.name}; }),
                 mine:mine, players:players, rosters:D.rosters, before:before,
                 sims:D.sims, unit:'Pts/wk',
                 note:'Points are a week over the regular season left, on this site\\u2019s '
                      + 'weekly projections, byes counted as nothing.',
                 pickNote:'Each free agent added to your team, your lowest-projected bench '
                      + 'player dropped when the roster is full, and the rest of the season '
                      + 'played ' + D.sims.toLocaleString() + ' times each way with the same '
                      + 'luck. Points are a week over the regular season left.'});
      }, 30);
    });
  }

  function evaluate(tr){
    var rosters = {};
    keys.forEach(function(k){ rosters[k] = (D.rosters[k] || []).slice(); });
    rosters[tr.a] = rosters[tr.a].filter(function(pid){ return tr.give.indexOf(pid) < 0; }).concat(tr.get);
    rosters[tr.b] = rosters[tr.b].filter(function(pid){ return tr.get.indexOf(pid) < 0; }).concat(tr.give);
    var signed = {}, moves = {};
    moves[tr.a] = []; moves[tr.b] = [];
    settle(tr.a, rosters[tr.a], tr.give, tr.get, signed, moves[tr.a]);
    settle(tr.b, rosters[tr.b], tr.get, tr.give, signed, moves[tr.b]);
    return new Promise(function(resolve){
      setTimeout(function(){ resolve({after:simulate(rosters, D.sims), moves:moves}); }, 30);
    });
  }

  function candidates(){ return FREE.slice(); }

  /** One free agent onto `key`'s roster, against the same seasons as now. */
  function pickup(key, pid){
    var rosters = {};
    keys.forEach(function(k){ rosters[k] = (D.rosters[k] || []).slice(); });
    rosters[key] = rosters[key].concat([pid]);
    var cut = [];
    settle(key, rosters[key], [], [pid], {}, [], cut);
    return new Promise(function(resolve){
      setTimeout(function(){
        resolve({before:before[key], after:simulate(rosters, D.sims)[key], drop:cut[0] || null});
      }, 0);
    });
  }

  function remember(key){ try{ localStorage.setItem('cfbMyTeam', key); }catch(e){} }

  return {load:load, evaluate:evaluate, remember:remember, candidates:candidates, pickup:pickup,
          _simulate:simulate, _means:means, _lineup:lineup, _bracket:bracket};
})();
</script>{% endraw %}"""

INTRO = ("<p>Pick a deal, or a free agent, and see what it does to the season: points a "
         "week, record, and the chance of making the playoffs and winning it all.</p>")

METHOD = ("<p>The rest of the season is played out " + f"{SIMS:,}" + " times with the rosters "
          "as they are and " + f"{SIMS:,}" + " times as they would be, with the same luck both "
          "times, so the difference is the trade. It is the simulation behind the Power tab: "
          "each week's best lineup on this site's weekly projections (byes, opponents, injury "
          "tags), the median game, and the bracket with its byes and reseeding. A week already "
          "being played stays as it is. A team taking more players than it sends drops its "
          "lowest-projected bench player; one sending more signs the best free agent at the "
          "position it gave up.</p>")


def body() -> str:
    got = data()
    if not got:
        return (trade_page.CSS + "<p>The trade analyzer opens once the season has rosters "
                "and a schedule.</p>")
    return (INTRO + trade_page.section('/cfb/trade/')
            + "<details class='section' id='method'><summary>How it works</summary>"
            + METHOD + "</details>" + data_script(got)
            + trade_page.JS + ADAPTER_JS + trade_page.start())


def data_script(got: dict) -> str:
    """The data as an inert <script>: `</` escaped so a name cannot end it,
    and outside Liquid so a name cannot be read as a tag."""
    blob = json.dumps(got, separators=(",", ":")).replace("</", "<\\/")
    return ("{% raw %}<script type='application/json' id='tr-data'>" + blob
            + "</script>{% endraw %}")


def generate():
    write_page(OUTPUT, "Trades & Pickups", body(),
               description="What a trade does to both teams' seasons in the college fantasy "
                           "league: points a week, record, playoff and title odds.")


if __name__ == "__main__":
    generate()
