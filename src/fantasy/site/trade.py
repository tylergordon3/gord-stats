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
from gordstats import how, my_league, my_league_data, my_power, trade_page
from gordstats.frontmatter import add_front_matter

OUT = paths.WEB_FANTASY_DIR / "trade" / "index.html"
SIMS = 5000
PICK_SIMS = 2000

ADAPTER_JS = """{% raw %}<script>
window.GSTradeAdapter = (function(){
  'use strict';
  var SITE = '__SITE__', SITE_MINE = '__MINE__', SIMS = __SIMS__, FA_PER_POS = 3;
  // Pick up: the free agents tried for the reader's team, and how many seasons
  // each - fewer than a trade's, since a wire of them is played out in turn;
  // the shared draws keep the difference steady.
  var PICK = {QB:2, RB:5, WR:5, TE:3, K:1, DEF:1}, PICK_SIMS = __PICK_SIMS__;
  var CATCH = [1.0, 0.5, 0.0];
  var st = null, ix = {}, id = null, fa = [], picks = [], pickBase = null;
  var LANE = 'trade';

  function leagueId(){
    var have = GSL.saved();
    return (have && have.id && !have.site) ? String(have.id) : SITE;
  }
  function esc(v){
    return String(v==null?'':v).replace(/[&<>"']/g, function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; });
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
  /** The next-man-up effect the board names for a player ([points a game,
   *  the injured teammate, weeks]), as a chip: "+4.9 Achane out". */
  function boost(pid){
    var v = (st.board.next || {})[pid];
    if(!v) return null;
    var who = String(name(v[1]) || '').split(' ').slice(-1)[0];
    var a = Math.abs(v[0]).toFixed(1);
    return [v[0], (v[0] > 0 ? '+' : '\u2212') + a + ' ' + who + ' out'];
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
  /** Which of a roster's reserve lists a player is on: 'reserve' (IR),
   *  'taxi', or null for the active roster. */
  function reserveKind(rid, pid){
    var r = roster(rid);
    if((r.reserve || []).map(String).indexOf(pid) >= 0) return 'reserve';
    if((r.taxi || []).map(String).indexOf(pid) >= 0) return 'taxi';
    return null;
  }
  /** The empty IR and taxi places a roster has once `sent` has gone. Sleeper
   *  keeps the counts in settings (reserve_slots, taxi_slots); a league that
   *  lists them among its slots says so there. */
  function reserveRoom(rid, sent){
    var r = roster(rid), slots = st.league.slots || [];
    var set = (st.league.info && st.league.info.settings) || {};
    function count(name){ return slots.filter(function(s){ return s === name; }).length; }
    function kept(list){
      return (list || []).filter(function(p){ return sent.indexOf(String(p)) < 0; }).length;
    }
    return {reserve: Math.max(Math.max(count('IR'), set.reserve_slots || 0) - kept(r.reserve), 0),
            taxi: Math.max(Math.max(count('TAXI'), set.taxi_slots || 0) - kept(r.taxi), 0)};
  }

  /** One side of the deal made legal: drops when full, signings when short.
   *
   *  Only the active roster starts and only it counts against the limit. A
   *  player arriving off the other team's IR or taxi squad goes onto this
   *  team's while it has the room: counted active, he made a team taking a
   *  hurt player "drop" a healthy one to fit him, and a starter on IR was
   *  being picked into the lineup. `from` is the roster he came from (none
   *  for a free agent). */
  function settle(rid, ids, sent, got, signed, lines, cut, from){
    var own = reserved(rid), aside = {};
    Object.keys(own).forEach(function(p){ aside[p] = 1; });
    if(from){
      var room = reserveRoom(rid, sent);
      got.forEach(function(p){
        var kind = reserveKind(from, p);
        if(kind && room[kind] > 0){ aside[p] = 1; room[kind]--; }
      });
    }
    function activeOf(list){ return list.filter(function(p){ return !aside[p]; }); }
    var active = activeOf(ids);
    var limit = activeLimit();
    var line = starters(active);
    var was = starters(ids.filter(function(p){ return got.indexOf(p) < 0; }).concat(sent)
      .filter(function(p){ return !own[p]; }));
    if(active.length > limit){
      var start = {}; line.forEach(function(p){ start[p] = 1; });
      var dropped = active.filter(function(p){ return !start[p] && got.indexOf(p) < 0; })
        .sort(function(x, y){ return (mu(x) || 0) - (mu(y) || 0); })
        .slice(0, active.length - limit);
      dropped.forEach(function(p){
        if(cut) cut.push(p);
        ids.splice(ids.indexOf(p), 1);
        lines.push('Drops ' + esc(name(p)) + ' (' + esc(pos(p)) + ') to make room.');
      });
    } else if(sent.length > got.length){
      // The positions it gave up and did not get back, best first.
      var want = sent.map(pos);
      got.forEach(function(p){ var k = want.indexOf(pos(p)); if(k >= 0) want.splice(k, 1); });
      var open = Math.min(sent.length - got.length, Math.max(limit - active.length, 0));
      for(var i = 0; i < open; i++){
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
    var now = starters(activeOf(ids));
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
    pickBase = null;
    // The league the deal is in, for its link (trade_page's leagueKey): the
    // one read here, and 'site' for this site's own, as links have carried it.
    var key = id === SITE ? 'site' : id;
    var setup = GSPowerLeague.setup(id).catch(function(err){
      if(err && err.message === 'undrafted') return null;
      // Saved in another season: last season's rosters are no trade to play
      // out on this season's board.
      if(err && err.message === 'other-season') return {other:err};
      throw err;
    });
    return Promise.all([setup, GSL.players(), GSL.week()]).then(function(o){
      if(!o[0]){
        return {teams:[], leagueId:key,
                empty:'This league has not drafted yet. Trades and pickups can '
                + 'be played out here after your draft.'};
      }
      if(o[0].other){
        // GSAPI's note, as the words of the page's message (trade_page's
        // msg() puts what it is handed in a paragraph of its own).
        var box = document.createElement('div');
        box.innerHTML = GSAPI.otherSeason(o[0].other.info, o[0].other.year, 'tr-msg') || '';
        return {teams:[], leagueId:key,
                empty: box.firstElementChild ? box.firstElementChild.innerHTML : ''};
      }
      st = o[0]; ix = o[1] || {};
      var wk = o[2] || {proj:{}, kick:{}};
      /** A free agent worth signing: priced on real data (the board's
       *  stand-in rows for players it has none on carry no uncertainty -
       *  retired players among them), back before the regular season ends,
       *  and either projected this week, on bye, or hurt for a while. */
      function available(pid){
        var row = st.board.board[pid];
        // Out for the rest of the regular season (ESPN's return date): no use.
        // row[8] is the week his hold starts after (season_board out_from).
        var rest = Math.max(st.weeks - st.played, 1);
        if(!row || !(row[4] > 0) || (row[7] || 0) + (row[8] || 0) >= rest) return false;
        var team = ix[pid] && ix[pid][2];
        return !!((wk.proj || {})[pid] || (row[7] || 0) > 0
                  || (team && wk.kick && !wk.kick[team]));
      }
      var league = st.league, settings = (league.info && league.info.settings) || {};
      // The free agents a deal could sign: the best few at each position that
      // nobody in this league holds.
      var by = {};
      Object.keys(st.board.board).forEach(function(pid){
        if(league.held[pid] || !available(pid)) return;
        var p = pos(pid);
        (by[p] = by[p] || []).push(pid);
      });
      fa = [];
      Object.keys(by).forEach(function(p){
        fa = fa.concat(by[p].sort(function(x, y){ return mu(y) - mu(x); }).slice(0, FA_PER_POS));
      });
      fa.sort(function(x, y){ return mu(y) - mu(x); });
      picks = [];
      Object.keys(PICK).forEach(function(p){
        picks = picks.concat((by[p] || []).slice(0, PICK[p]));
      });
      picks.sort(function(x, y){ return mu(y) - mu(x); });
      st.spec.stable = true;
      // Every player either mode may add or drop draws in every run: the
      // free agents, and everyone rostered now (the simulation skips a pool
      // player who is on a roster, so the run before the deal is the same).
      // The draws are dealt in turn down the list of players, so a player
      // dropped out of it moved everyone after him onto other draws - noise
      // of two or three points of playoff odds, as big as the pickups shown.
      var everyone = [];
      league.rosters.forEach(function(r){
        (r.players || []).forEach(function(p){ everyone.push(String(p)); });
      });
      st.spec.pool = fa.concat(picks.filter(function(p){ return fa.indexOf(p) < 0; }))
        .concat(everyone);
      st.spec.sims = SIMS;

      var players = {}, rosters = {};
      league.rosters.forEach(function(r){
        var rid = String(r.roster_id), aside = reserved(rid);
        rosters[rid] = (r.players || []).map(String);
        rosters[rid].forEach(function(pid){
          var row = st.board.board[pid], m = mu(pid), out = row ? row[7] : 0;
          players[pid] = {name:name(pid), short:short(name(pid), pos(pid)), pos:pos(pid),
                          ppw:m, tag: aside[pid] ? 'IR' : (out ? 'Out ' + out + 'w' : ''),
                          boost:boost(pid)};
        });
      });
      picks.forEach(function(pid){
        var row = st.board.board[pid], out = row ? row[7] : 0;
        players[pid] = {name:name(pid), short:short(name(pid), pos(pid)), pos:pos(pid),
                        ppw:mu(pid), tag: out ? 'Out ' + out + 'w' : '', boost:boost(pid)};
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
        return {league:league.info.name, leagueId:key, teams:teams, mine:mine, players:players,
                rosters:rosters, before:stats(res), sims:SIMS, unit:'Pts/wk',
                note:notes.join(' '),
                pickNote:'Each free agent added to your team, your lowest-projected bench '
                  + 'player dropped when the roster is full, and the rest of the season played '
                  + PICK_SIMS.toLocaleString() + ' times each way with the same luck. Points '
                  + 'are a game on this site\u2019s board, in ' + esc(league.basis.name)
                  + ' scoring.'};
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
    settle(tr.a, A.players, tr.give, tr.get, signed, moves[tr.a], null, tr.b);
    settle(tr.b, B.players, tr.get, tr.give, signed, moves[tr.b], null, tr.a);
    var spec = {};
    for(var k in st.spec) spec[k] = st.spec[k];
    spec.rosters = rosters;
    // A new deal stops whatever the page was still playing out - the deal
    // tapped past, the pickups it moved on from - rather than finishing it
    // for nobody.
    GSPowerLeague.stop(LANE);
    return GSPowerLeague.simulate(spec, LANE).then(function(res){
      return {after:stats(res), moves:moves};
    });
  }

  function candidates(){ return picks.slice(); }

  /** One free agent onto `rid`'s roster, played out against the same
   *  number of seasons with nobody added. */
  function pickup(rid, pid){
    if(!pickBase){
      var base = {};
      for(var k in st.spec) base[k] = st.spec[k];
      base.sims = PICK_SIMS;
      // Stopped by a deal (evaluate), it is run again next time.
      pickBase = GSPowerLeague.simulate(base, LANE).then(stats, function(err){
        pickBase = null;
        throw err;
      });
    }
    var rosters = st.spec.rosters.map(function(r){
      return {roster_id:r.roster_id, players:(r.players || []).map(String)};
    });
    var mine = rosters.filter(function(r){ return String(r.roster_id) === String(rid); })[0];
    mine.players = mine.players.concat([pid]);
    var cut = [];
    settle(String(rid), mine.players, [], [pid], {}, [], cut);
    var spec = {};
    for(var k2 in st.spec) spec[k2] = st.spec[k2];
    spec.rosters = rosters;
    spec.sims = PICK_SIMS;
    return pickBase.then(function(before){
      return GSPowerLeague.simulate(spec, LANE).then(function(res){
        return {before:before[String(rid)], after:stats(res)[String(rid)], drop:cut[0] || null};
      });
    });
  }

  function remember(rid){
    if(id === SITE){ try{ localStorage.setItem('nflMyTeam', String(rid)); }catch(e){} }
    else GSL.remember(id, rid);
  }

  return {load:load, evaluate:evaluate, remember:remember,
          candidates:candidates, pickup:pickup};
})();
</script>{% endraw %}"""

# How a deal is played out is the trade-analyzer explainer (gordstats.how),
# opened in a dialog from the chip at the end of the intro.
INTRO = ("<p>Pick a deal, or a free agent, and see what it does to the season: points a "
         "week, record, and the chance of making the playoffs and winning it all. Works for your "
         "own Sleeper or ESPN league too &mdash; pick it above. " + how.button("trade-analyzer")
         + "</p>")


def adapter_js() -> str:
    # The site's own manager opens on his own team, as on the Team tab.
    mine = next((str(k) for k, v in ROSTER_NAMES.items() if v == MY_MANAGER), "")
    return (ADAPTER_JS.replace("__SITE__", str(UPCOMING_LEAGUE_ID))
            .replace("__MINE__", mine).replace("__SIMS__", str(SIMS))
            .replace("__PICK_SIMS__", str(PICK_SIMS)))


def body() -> str:
    return (INTRO + my_league.bar() + trade_page.section('/fantasy/trade/', league=True)
            + my_league_data.JS_TAG + my_league.JS_TAG + my_power.SIM_JS_TAG
            + my_power.LEAGUE_JS_TAG + trade_page.JS_TAG + adapter_js() + trade_page.start()
            + how.JS_TAG)


def generate():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(add_front_matter(
        layout.HEAD + body(), "Trades & Pickups", updated=False,
        description="What a trade or a waiver pickup does to a season: points a week, "
                    "record, playoff and title odds, before and after."),
        encoding="utf-8")
    print(f"Wrote Trades & Pickups -> {OUT}")


if __name__ == "__main__":
    generate()
