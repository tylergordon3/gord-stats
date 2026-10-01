"""
Trade analyzer for the NFL league (docs/fantasy/trade/): pick a deal and see
what it does to both teams' seasons - and the same for any reader's own
Sleeper or public ESPN league, picked in the league bar.

The page is gordstats.trade_page; this is its adapter. It runs the season on
gordstats.my_power's simulation - the one that ranks a reader's league on the
Power tab, checked against fantasy.league.power - so a trade is judged on the
same board, slots, schedule, median game and bracket as the rankings. Every
league runs in the browser, this site's own included: a deal has to be played
out the moment it is picked.

What the adapter adds to the simulation:

  * the same draws both times (`stable`), and the free agents a trade might
    sign drawn in every run (`pool`), so the two runs differ by the trade;
  * roster limits: a team taking more players than it sends drops its
    lowest-projected bench player once its active roster is full, and one
    sending more signs the best free agent at the position it gave up;
  * the league's trade deadline, from Sleeper's settings - past it, the page
    says the deal is a what-if.

    python -m fantasy.site.trade
"""
from fantasy import paths
from fantasy.config import MY_MANAGER, ROSTER_NAMES, UPCOMING_LEAGUE_ID
from fantasy.site import layout
from gordstats import my_league, my_league_data, my_power, trade_page
from gordstats.frontmatter import add_front_matter

OUT = paths.WEB_FANTASY_DIR / "trade" / "index.html"
SIMS = 5000

ADAPTER_JS = """{% raw %}<script>
window.GSTradeAdapter = (function(){
  'use strict';
  var SITE = '__SITE__', SITE_MINE = '__MINE__', SIMS = __SIMS__, FA_PER_POS = 3;
  var CATCH = [1.0, 0.5, 0.0];
  var st = null, ix = {}, id = null, fa = [];

  function leagueId(){
    var have = GSL.saved();
    return (have && have.id && !have.site) ? String(have.id) : SITE;
  }
  function esc(v){
    return String(v==null?'':v).replace(/[&<>"]/g, function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; });
  }
  function short(name, pos){
    var parts = String(name || '').split(' ');
    if(pos === 'DEF' || parts.length < 2) return name;
    return parts[0].charAt(0) + '. ' + parts.slice(1).join(' ');
  }
  /** Points a game in this league's scoring (the board is PPR). */
  function mu(pid){
    var row = st.board.board[pid];
    if(!row) return null;
    var c = CATCH[st.spec.basis] == null ? 1 : CATCH[st.spec.basis];
    return Math.max(row[2] - (row[6] || 0) * (1 - c), 0.05);
  }
  function pos(pid){
    var row = st.board.board[pid];
    if(row) return st.board.pos[row[0]];
    var p = ix[pid];
    return p ? p[1] : '?';
  }
  function name(pid){
    var p = ix[pid];
    return p ? p[0] : pid;
  }
  function roster(rid){
    return st.league.rosters.filter(function(r){ return String(r.roster_id) === String(rid); })[0] || {};
  }

  /** The lineup a manager would set on projection alone, narrowest slot
   *  first (gordstats.my_power's fill, without the week's injuries). */
  function starters(ids){
    var slots = GSPower.startingSlots(st.league.slots).slots;
    var pool = ids.map(function(pid){ return {id:pid, pos:pos(pid), mu:mu(pid) || 0}; })
      .sort(function(x, y){ return (y.mu - x.mu) || (x.id < y.id ? -1 : 1); });
    var used = {}, out = [];
    slots.forEach(function(s){
      for(var i = 0; i < pool.length; i++){
        var p = pool[i];
        if(used[p.id] || s.takes.indexOf(p.pos) < 0) continue;
        used[p.id] = 1; out.push(p.id); break;
      }
    });
    return out;
  }

  /** How many players a roster may carry outside IR and the taxi squad. */
  function activeLimit(){
    return (st.league.slots || []).filter(function(s){
      return s !== 'IR' && s !== 'TAXI'; }).length;
  }
  function reserved(rid){
    var r = roster(rid), out = {};
    (r.reserve || []).concat(r.taxi || []).forEach(function(p){ out[String(p)] = 1; });
    return out;
  }

  /** One side of the deal made legal: drops when full, signings when short. */
  function settle(rid, ids, sent, got, signed, lines){
    var aside = reserved(rid);
    var active = ids.filter(function(p){ return !aside[p]; });
    var limit = activeLimit();
    var line = starters(ids);
    var was = starters(ids.filter(function(p){ return got.indexOf(p) < 0; }).concat(sent));
    if(active.length > limit){
      var start = {}; line.forEach(function(p){ start[p] = 1; });
      var cut = active.filter(function(p){ return !start[p] && got.indexOf(p) < 0; })
        .sort(function(x, y){ return (mu(x) || 0) - (mu(y) || 0); })
        .slice(0, active.length - limit);
      cut.forEach(function(p){
        ids.splice(ids.indexOf(p), 1);
        lines.push('Drops ' + esc(name(p)) + ' (' + esc(pos(p)) + ') to make room.');
      });
    } else if(sent.length > got.length){
      // The positions it gave up and did not get back, best first.
      var want = sent.map(pos);
      got.forEach(function(p){ var k = want.indexOf(pos(p)); if(k >= 0) want.splice(k, 1); });
      var room = Math.min(sent.length - got.length, Math.max(limit - active.length, 0));
      for(var i = 0; i < room; i++){
        var at = want[i];
        var pick = fa.filter(function(p){ return !signed[p] && (!at || pos(p) === at); })[0]
          || fa.filter(function(p){ return !signed[p] && ['RB','WR','TE'].indexOf(pos(p)) >= 0; })[0];
        if(!pick) break;
        signed[pick] = 1;
        ids.push(pick);
        lines.push('Signs ' + esc(name(pick)) + ', the best free agent at ' + esc(pos(pick))
                   + ' (' + mu(pick).toFixed(1) + ' a game).');
      }
    }
    var now = starters(ids);
    var inn = now.filter(function(p){ return was.indexOf(p) < 0; });
    var off = was.filter(function(p){ return now.indexOf(p) < 0 && sent.indexOf(p) < 0; });
    if(inn.length) lines.push('Starts ' + inn.map(function(p){ return esc(name(p)); }).join(', ') + '.');
    if(off.length) lines.push('To the bench: ' + off.map(function(p){ return esc(name(p)); }).join(', ') + '.');
  }

  function stats(res){
    var games = res.weeks * (res.median ? 2 : 1), out = {};
    res.teams.forEach(function(t){
      out[String(t.roster_id)] = {
        ppw: t.restPerWeek || t.projPoints / res.weeks,
        wins: t.projWins, losses: games - t.projWins,
        playoffs: t.playoffOdds, title: t.titleOdds};
    });
    return out;
  }

  function load(){
    id = leagueId();
    return Promise.all([GSPowerLeague.setup(id), GSL.players()]).then(function(o){
      st = o[0]; ix = o[1] || {};
      var league = st.league, settings = (league.info && league.info.settings) || {};
      // The free agents a deal could sign: the best few at each position that
      // nobody in this league holds.
      var by = {};
      Object.keys(st.board.board).forEach(function(pid){
        if(league.held[pid]) return;
        var p = pos(pid);
        (by[p] = by[p] || []).push(pid);
      });
      fa = [];
      Object.keys(by).forEach(function(p){
        fa = fa.concat(by[p].sort(function(x, y){ return mu(y) - mu(x); }).slice(0, FA_PER_POS));
      });
      fa.sort(function(x, y){ return mu(y) - mu(x); });
      st.spec.stable = true;
      st.spec.pool = fa.slice();
      st.spec.sims = SIMS;

      var players = {}, rosters = {};
      league.rosters.forEach(function(r){
        var rid = String(r.roster_id), aside = reserved(rid);
        rosters[rid] = (r.players || []).map(String);
        rosters[rid].forEach(function(pid){
          var row = st.board.board[pid], m = mu(pid), out = row ? row[7] : 0;
          players[pid] = {name:name(pid), short:short(name(pid), pos(pid)), pos:pos(pid),
                          ppw:m, tag: aside[pid] ? 'IR' : (out ? 'Out ' + out + 'w' : '')};
        });
      });
      var teams = st.order.map(function(rid){
        return {id:String(rid), name:league.names[String(rid)] || ('Roster ' + rid)};
      });
      var mine = null;
      if(id === SITE){
        try{ mine = localStorage.getItem('nflMyTeam'); }catch(e){}
        mine = mine || SITE_MINE;
      } else {
        mine = GSL.myRoster(league, id);
      }

      var notes = [];
      var week = settings.leg || (st.played + 1);
      if(settings.trade_deadline && settings.trade_deadline < 99 && week > settings.trade_deadline){
        notes.push('Trades closed after week ' + settings.trade_deadline
                   + ' in this league, so this is a what-if.');
      }
      if(league.basis.custom){
        notes.push('This league\\u2019s scoring is close to ' + esc(league.basis.name)
                   + ' but not exactly it, so the numbers are approximate.');
      }
      notes.push('Points are a game on this site\\u2019s rest-of-season board, in '
                 + esc(league.basis.name) + ' scoring.');
      return GSPowerLeague.simulate(st.spec).then(function(res){
        if(res.unknownPlayers){
          notes.push(res.unknownPlayers + ' rostered player' + (res.unknownPlayers === 1 ? ' is' : 's are')
                     + ' not on the board and count as deep-bench depth.');
        }
        return {league:league.info.name, teams:teams, mine:mine, players:players,
                rosters:rosters, before:stats(res), sims:SIMS, unit:'Pts/wk',
                note:notes.join(' ')};
      });
    });
  }

  function evaluate(tr){
    var rosters = st.spec.rosters.map(function(r){
      return {roster_id:r.roster_id, players:(r.players || []).map(String)};
    });
    var A = rosters.filter(function(r){ return String(r.roster_id) === tr.a; })[0];
    var B = rosters.filter(function(r){ return String(r.roster_id) === tr.b; })[0];
    A.players = A.players.filter(function(p){ return tr.give.indexOf(p) < 0; }).concat(tr.get);
    B.players = B.players.filter(function(p){ return tr.get.indexOf(p) < 0; }).concat(tr.give);
    var signed = {}, moves = {};
    moves[tr.a] = []; moves[tr.b] = [];
    settle(tr.a, A.players, tr.give, tr.get, signed, moves[tr.a]);
    settle(tr.b, B.players, tr.get, tr.give, signed, moves[tr.b]);
    var spec = {};
    for(var k in st.spec) spec[k] = st.spec[k];
    spec.rosters = rosters;
    return GSPowerLeague.simulate(spec).then(function(res){
      return {after:stats(res), moves:moves};
    });
  }

  function remember(rid){
    if(id === SITE){ try{ localStorage.setItem('nflMyTeam', String(rid)); }catch(e){} }
    else GSL.remember(id, rid);
  }

  return {load:load, evaluate:evaluate, remember:remember};
})();
</script>{% endraw %}"""

INTRO = ("<p>Pick a deal and see what it does to both teams: points a week, record, and the "
         "chance of making the playoffs and winning it all. Works for your own Sleeper or "
         "ESPN league too &mdash; pick it above.</p>")

METHOD = ("<p>The rest of the season is played out " + f"{SIMS:,}" + " times with the rosters as "
          "they are and " + f"{SIMS:,}" + " times as they would be, with the same luck both "
          "times, so the difference is the trade. It is the simulation behind the Power tab: "
          "this site's rest-of-season projections, each league's own slots, schedule, median "
          "game and bracket, byes and injuries. A team taking more players than it sends drops "
          "its lowest-projected bench player; one sending more signs the best free agent at the "
          "position it gave up.</p>")


def adapter_js() -> str:
    # The site's own manager opens on his own team, as on the Team tab.
    mine = next((str(k) for k, v in ROSTER_NAMES.items() if v == MY_MANAGER), "")
    return (ADAPTER_JS.replace("__SITE__", str(UPCOMING_LEAGUE_ID))
            .replace("__MINE__", mine).replace("__SIMS__", str(SIMS)))


def body() -> str:
    return (INTRO + my_league.bar() + trade_page.section()
            + layout.details("How it works", METHOD, anchor="method")
            + my_league_data.JS + my_league.JS + my_power.SIM_JS + my_power.LEAGUE_JS
            + trade_page.JS + adapter_js() + trade_page.start())


def generate():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(add_front_matter(
        layout.HEAD + body(), "Trade Analyzer", updated=False,
        description="What a trade does to both teams' seasons: points a week, record, "
                    "playoff and title odds, before and after."),
        encoding="utf-8")
    print(f"Wrote Trade Analyzer -> {OUT}")


if __name__ == "__main__":
    generate()
