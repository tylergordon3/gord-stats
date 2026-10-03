/* window.GSTrade: the trade analyzer, both fantasy leagues.
   Source file, loaded by gordstats.trade_page (JS_TAG); see gordstats.js_assets. */
window.GSTrade = function(host, adapter){
  'use strict';
  if(!host || !adapter) return;
  var POS = {QB:0, RB:1, WR:2, TE:3, K:4, DEF:5};
  var data = null, a = null, b = null, give = {}, get = {}, seq = 0, timer = null;
  var tapped = false, shown = false, elsewhere = '';
  var mode = /(?:^|[#&])pickup(?:&|$)/.test(location.hash) ? 'pickup' : 'trade';

  function esc(v){
    return String(v==null?'':v).replace(/[&<>"']/g, function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; });
  }
  function pct(v){
    if(v == null || v !== v) return '&ndash;';
    if(v > 0 && v < 0.005) return '&lt;1%';
    if(v < 1 && v > 0.995) return '&gt;99%';
    return Math.round(v*100) + '%';
  }
  function keys(o){ return Object.keys(o).filter(function(k){ return o[k]; }); }
  function msg(text){
    out().innerHTML = '<p class="tr-msg">' + text + '</p>';
  }
  function out(){ return host.querySelector('.tr-out') || host; }

  // ----- the deal in the address, so it can be sent to the other manager --- //

  /** Which league the deal is in. It rides in the link (the fifth part), so
   *  a deal sent from one league is never laid over another's rosters -
   *  Sleeper numbers every league's rosters from 1. The adapter's own id
   *  where it gives one; else the reader's league the page reads ('site' for
   *  this site's); '' where there is no choice of league (the college page).
   *  A link without one (sent before this) is taken as it always was. */
  function leagueKey(){
    if(data && data.leagueId) return String(data.leagueId);
    if(!window.GSL || !GSL.saved) return '';
    var h = GSL.saved();
    return (h && h.id && !h.site) ? String(h.id) : 'site';
  }
  function readHash(){
    var m = /(?:^|[#&])trade=([^&]*)/.exec(location.hash);
    if(!m) return null;
    var raw;
    // A link cut short in a chat ("%E2%8" ...) is no deal, not a broken page.
    try{ raw = decodeURIComponent(m[1]); }catch(e){ return null; }
    var p = raw.split('~');
    return {a:p[0], b:p[1], give:(p[2]||'').split('.').filter(Boolean),
            get:(p[3]||'').split('.').filter(Boolean), league:p[4] || ''};
  }
  function dealHash(){
    var g = keys(give), t = keys(get), lg = leagueKey();
    var parts = [a, b, g.join('.'), t.join('.')];
    if(lg) parts.push(lg);
    return (a && b && (g.length || t.length))
      ? '#trade=' + encodeURIComponent(parts.join('~')) : '';
  }
  function writeHash(){
    var h = mode === 'pickup' ? '#pickup' : dealHash();
    try{ history.replaceState(null, '', location.pathname + location.search + h); }
    catch(e){}
  }

  // ----- drawing ---------------------------------------------------------- //

  function options(selected, skip){
    return data.teams.map(function(t){
      if(t.id === skip) return '';
      return '<option value="' + esc(t.id) + '"' + (t.id === selected ? ' selected' : '')
        + '>' + esc(t.name) + '</option>';
    }).join('');
  }

  /** An injury tag, and a next-man-up chip where the adapter has one. */
  function chips(p, more){
    var html = (p.tag ? '<span class="tr-tag">' + esc(p.tag) + '</span>' : '')
      + (p.boost ? '<span class="tr-boost ' + (p.boost[0] > 0 ? 'up' : 'down') + '">'
         + esc(p.boost[1]) + '</span>' : '') + (more || '');
    return html ? '<span class="tr-chips">' + html + '</span>' : '';
  }

  function list(team, picked, side){
    var ids = (data.rosters[team] || []).slice().sort(function(x, y){
      var p = data.players[x] || {}, q = data.players[y] || {};
      return ((POS[p.pos] == null ? 9 : POS[p.pos]) - (POS[q.pos] == null ? 9 : POS[q.pos]))
        || ((q.ppw || 0) - (p.ppw || 0));
    });
    return ids.map(function(id){
      var p = data.players[id] || {name:id, pos:'?'};
      return '<button type="button" class="tr-p" data-side="' + side + '" data-id="' + esc(id)
        + '" aria-pressed="' + (picked[id] ? 'true' : 'false') + '">'
        + '<span class="tr-pos">' + esc(p.pos) + '</span>'
        + '<span class="tr-name"><span class="tr-full">' + esc(p.name) + '</span>'
        + '<span class="tr-short">' + esc(p.short || p.name) + '</span></span>'
        + chips(p)
        + '<span class="tr-ppw">' + (p.ppw == null ? '' : p.ppw.toFixed(1)) + '</span>'
        + '</button>';
    }).join('');
  }

  function modeBar(){
    if(!adapter.pickup) return '';
    return '<div class="tr-mode" role="group" aria-label="Mode">'
      + '<button type="button" data-mode="trade" aria-pressed="' + (mode === 'trade') + '">Trade</button>'
      + '<button type="button" data-mode="pickup" aria-pressed="' + (mode === 'pickup') + '">Pick up</button>'
      + '</div>';
  }
  function bindMode(){
    Array.prototype.forEach.call(host.querySelectorAll('.tr-mode button'), function(el){
      el.addEventListener('click', function(){
        var m = el.getAttribute('data-mode');
        if(m === mode) return;
        // A tap's evaluation still waiting would otherwise fire into the
        // other view (and, being newer, cancel its pickups part way).
        clearTimeout(timer);
        mode = m; seq++;
        draw();
      });
    });
  }

  function settle(){ host.classList.remove('tr-wait'); }
  function draw(){
    settle();
    if(mode === 'pickup' && adapter.pickup) return drawPickup();
    host.innerHTML = modeBar() + '<div class="tr-teams">'
      + '<label>Your team<select class="tr-a">' + options(a) + '</select></label>'
      + '<label>Trading with<select class="tr-b">' + options(b, a) + '</select></label>'
      + '</div>'
      + '<div class="tr-sides">'
      + '<div class="tr-side"><h3>You send</h3><div class="tr-list">' + list(a, give, 'a')
      + '</div></div>'
      + '<div class="tr-side"><h3>You get</h3><div class="tr-list">' + list(b, get, 'b')
      + '</div></div></div>'
      + '<div class="tr-out" aria-live="polite"></div>'
      + (data.note ? '<p class="tr-note">' + data.note + '</p>' : '');
    bindMode();
    // draw() ends by running the deal, so a change runs it once - a second
    // run() after it played every trade out twice.
    host.querySelector('.tr-a').addEventListener('change', function(ev){
      clearTimeout(timer);
      a = ev.target.value;
      if(b === a) b = first(a);
      give = {}; get = {};
      if(adapter.remember) adapter.remember(a);
      draw();
    });
    host.querySelector('.tr-b').addEventListener('change', function(ev){
      clearTimeout(timer);
      b = ev.target.value; get = {};
      draw();
    });
    Array.prototype.forEach.call(host.querySelectorAll('.tr-p'), function(el){
      el.addEventListener('click', function(){
        var set = el.getAttribute('data-side') === 'a' ? give : get;
        var id = el.getAttribute('data-id');
        set[id] = !set[id];
        tapped = true;
        el.setAttribute('aria-pressed', set[id] ? 'true' : 'false');
        clearTimeout(timer);
        timer = setTimeout(run, 450);
      });
    });
    run();
  }

  function team(id){
    return data.teams.filter(function(t){ return t.id === id; })[0] || {name:''};
  }
  function first(skip){
    var t = data.teams.filter(function(x){ return x.id !== skip; })[0];
    return t ? t.id : null;
  }

  function now(){
    var x = data.before[a], y = data.before[b];
    if(!x || !y) return '';
    return '<p class="tr-now">Now: ' + esc(team(a).name) + ' ' + pct(x.playoffs)
      + ' to make the playoffs, ' + pct(x.title) + ' to win it all; '
      + esc(team(b).name) + ' ' + pct(y.playoffs) + ' and ' + pct(y.title) + '.</p>';
  }

  function delta(before, after, kind){
    var d = after - before, text, cls;
    if(kind === 'pct'){
      var pts = Math.round(d*100);
      text = (pts > 0 ? '+' : pts < 0 ? '\u2212' : '\u00b1') + Math.abs(pts);
      cls = pts > 0 ? 'up' : pts < 0 ? 'down' : 'flat';
    } else {
      var r = Math.round(d*10)/10;
      text = (r > 0 ? '+' : r < 0 ? '\u2212' : '\u00b1') + Math.abs(r).toFixed(1);
      cls = r > 0 ? 'up' : r < 0 ? 'down' : 'flat';
    }
    return '<td class="tr-d ' + cls + '">' + text + '</td>';
  }

  function card(id, you, before, after, moves){
    function row(label, x, y, show, kind){
      return '<tr><th>' + label + '</th><td class="tr-was">' + show(x) + '</td>'
        + '<td>' + show(y) + '</td>' + delta(x, y, kind) + '</tr>';
    }
    var rec = function(s){ return s.wins.toFixed(1) + '-' + s.losses.toFixed(1); };
    return '<div class="tr-card"><h3>' + (you ? '<span class="tr-you">You</span>' : '')
      + esc(team(id).name) + '</h3>'
      + '<table class="tr-t"><thead><tr><th></th><th>Now</th><th>After</th><th></th></tr></thead>'
      + row(data.unit || 'Pts/wk', before.ppw, after.ppw,
            function(v){ return v.toFixed(1); }, 'num')
      + '<tr><th>Record</th><td class="tr-was">' + rec(before) + '</td><td>' + rec(after)
      + '</td>' + delta(before.wins, after.wins, 'num') + '</tr>'
      + row('Playoffs', before.playoffs, after.playoffs, pct, 'pct')
      + row('Title', before.title, after.title, pct, 'pct')
      + '</table>'
      + ((moves && moves.length) ? '<ul class="tr-moves"><li>' + moves.join('</li><li>')
         + '</li></ul>' : '')
      + '</div>';
  }

  function verdict(x0, x1, y0, y1){
    // Judged on the title, the thing both teams are playing for; the playoffs
    // are the headline because they move most and read most plainly.
    var mine = x1.title - x0.title, theirs = y1.title - y0.title;
    var edge = mine - theirs, close = Math.abs(edge) < 0.01, word;
    // Which way each side moves, as the line below rounds it, comes first: a
    // deal that costs you title odds is never "Better for you" because it
    // costs them more.
    function way(d){ return d >= 0.005 ? 1 : d <= -0.005 ? -1 : 0; }
    var wm = way(mine), wt = way(theirs);
    if(wm > 0 && wt > 0) word = 'Helps you both' + (close ? '' : edge > 0 ? ', you more' : ', them more');
    else if(wm < 0 && wt < 0) word = '<span class="down">Hurts you both</span>'
      + (close ? '' : edge > 0 ? ', them more' : ', you more');
    else if(close) word = 'About even';
    else word = edge > 0 ? '<span class="up">Better for you</span>'
                         : '<span class="down">Better for them</span>';
    function pts(d){
      var r = Math.round(d*100);
      return (r > 0 ? '+' : r < 0 ? '−' : '±') + Math.abs(r);
    }
    return '<p class="tr-verdict">' + word + '</p><p class="tr-now">Title odds '
      + pts(mine) + ' for you, ' + pts(theirs) + ' for them.</p>';
  }

  /** The Share button, pointed at this deal: the address carries it. */
  function share(g, t){
    var tpl = document.getElementById('tr-share'), acts = host.querySelector('.tr-acts');
    if(!tpl || !acts || !tpl.content) return;
    var btn = tpl.content.firstElementChild.cloneNode(true);
    function names(ids){
      return ids.map(function(id){ return (data.players[id] || {}).name || id; }).join(' and ');
    }
    btn.setAttribute('data-url', btn.getAttribute('data-url') + dealHash());
    btn.setAttribute('data-text', 'Trade idea: ' + (g.length ? names(g) : 'nothing') + ' for '
                     + (t.length ? names(t) : 'nothing') + '.');
    acts.insertBefore(btn, acts.firstChild);
  }

  // ----- pick up: the waiver wire in playoff odds ---------------------------- //

  /** A change in points of percentage: a tenth under ten, whole above. */
  function signed(d){
    var r = Math.round(d*1000)/10, a = Math.abs(r);
    return {text:(r > 0 ? '+' : r < 0 ? '−' : '±') + (a < 10 ? a.toFixed(1) : Math.round(a)),
            cls:r > 0 ? 'up' : r < 0 ? 'down' : 'flat'};
  }
  function who(id, short){
    var p = data.players[id] || {name:id, pos:'?'};
    return short ? (p.short || p.name) : p.name;
  }

  function drawPickup(){
    host.innerHTML = modeBar()
      + '<div class="tr-teams tr-one"><label>Your team<select class="tr-a">' + options(a)
      + '</select></label></div>'
      + '<div class="tr-out" aria-live="polite"></div>'
      + (data.pickNote ? '<p class="tr-note">' + data.pickNote + '</p>' : '');
    bindMode();
    host.querySelector('.tr-a').addEventListener('change', function(ev){
      clearTimeout(timer);
      a = ev.target.value;
      if(b === a) b = first(a);
      // The trade picked before is between other rosters now: kept, it came
      // back on Trade as a deal nobody made (and rode along in the link).
      give = {}; get = {};
      if(adapter.remember) adapter.remember(a);
      drawPickup();
    });
    runPickups();
  }

  function runPickups(){
    writeHash();
    var me = ++seq, cands = (adapter.candidates && adapter.candidates(a)) || [];
    if(!cands.length){ msg('No free agents on the board to try.'); return; }
    var results = {}, base = null, done = 0;
    function row(id){
      var p = data.players[id] || {pos:'?'}, r = results[id];
      var drop = r ? (r.drop ? esc(who(r.drop, true)) : 'open spot') : '';
      // The drop is said twice: in its own column on a desktop, and on a
      // phone on the line under the player, after any tag (CSS shows one).
      var head = '<td class="tr-pk-p"><span class="tr-pk-in"><span class="tr-pos">' + esc(p.pos) + '</span>'
        + '<span class="tr-name"><span class="tr-full">' + esc(who(id)) + '</span>'
        + '<span class="tr-short">' + esc(who(id, true)) + '</span></span>'
        + chips(p, r ? '<span class="tr-pk-sub">' + (r.drop ? 'Drop ' + drop : 'Into an open spot')
                       + '</span>' : '')
        + '<span class="tr-ppw">' + (p.ppw == null ? '' : p.ppw.toFixed(1)) + '</span></span></td>';
      if(r === undefined) return '<tr>' + head + '<td class="tr-pk-drop">&hellip;</td><td></td><td></td></tr>';
      if(r === null) return '<tr>' + head + '<td class="tr-pk-fail" colspan="3">could not play out</td></tr>';
      var dp = signed(r.dp), dt = signed(r.dt);
      return '<tr>' + head
        + '<td class="tr-pk-drop">' + drop + '</td>'
        + '<td class="tr-d ' + dp.cls + '">' + dp.text + '</td>'
        + '<td class="tr-d ' + dt.cls + '">' + dt.text + '</td></tr>';
    }
    function helps(){
      return cands.some(function(id){
        var r = results[id];
        return r && (Math.round(r.dt*1000) > 0 || Math.round(r.dp*1000) > 0);
      });
    }
    function render(){
      var order = cands.slice();
      if(done === cands.length){
        order.sort(function(x, y){
          var p = results[x] || {dt:-1, dp:-1}, q = results[y] || {dt:-1, dp:-1};
          return (q.dt - p.dt) || (q.dp - p.dp);
        });
      }
      out().innerHTML = (done < cands.length
          ? '<p class="tr-msg">Playing each pickup out&hellip; ' + done + ' of ' + cands.length + '</p>'
          : (base ? '<p class="tr-now">Now: ' + esc(team(a).name) + ' ' + pct(base.playoffs)
                    + ' to make the playoffs, ' + pct(base.title) + ' to win it all. '
                    + (helps() ? 'Best pickup first, by what he does to the title odds.'
                       : '<b>None of these beats your bench right now</b> &mdash; each costs '
                         + 'more in the player dropped than he adds.') + '</p>' : ''))
        + '<div class="tr-pk-wrap"><table class="tr-pk"><thead><tr><th>Pick up</th><th class="tr-pk-drop">Drop</th>'
        + '<th>Playoffs</th><th>Title</th></tr></thead><tbody>'
        + order.map(row).join('') + '</tbody></table></div>';
    }
    render();
    // One at a time: a phone never has two simulations going at once.
    var i = 0;
    (function next(){
      if(me !== seq) return;
      if(i >= cands.length) return;
      var id = cands[i++];
      adapter.pickup(a, id).then(function(r){
        if(me !== seq) return;
        base = r.before;
        results[id] = {dp:r.after.playoffs - r.before.playoffs, dt:r.after.title - r.before.title,
                       drop:r.drop};
      }, function(err){
        if(err instanceof TypeError && window.console) console.error(err);
        results[id] = null;
      }).then(function(){
        if(me !== seq) return;
        done++;
        render();
        next();
      });
    })();
  }

  /** On a phone the two lists stand a screen or more tall, so the verdict
   *  lands out of sight under them. The first time a deal the reader built
   *  (a player tapped on each side) plays out, bring it up - smoothly, and
   *  only when it is not already on screen. Once: after that the reader
   *  knows where it is, and a page that keeps moving is worse. */
  function reveal(g, t){
    if(shown || !tapped || !g.length || !t.length) return;
    if(!window.matchMedia || !matchMedia('(max-width:640px)').matches) return;
    shown = true;
    var el = out(), r = el.getBoundingClientRect();
    if(r.top >= 0 && r.top < innerHeight - 120) return;
    var css = getComputedStyle(document.documentElement);
    var top = (parseFloat(css.getPropertyValue('--header-h')) || 0)
            + (parseFloat(css.getPropertyValue('--pin-h')) || 0) + 8;
    try{ scrollTo({top: r.top + pageYOffset - top, behavior: 'smooth'}); }
    catch(e){ scrollTo(0, r.top + pageYOffset - top); }
  }

  function run(){
    // Trades only: a timer set by a tap can come due after the reader has
    // switched to Pick up.
    if(mode === 'pickup' && adapter.pickup) return;
    writeHash();
    var g = keys(give), t = keys(get), me = ++seq;
    if(!g.length && !t.length){
      out().innerHTML = (elsewhere ? '<p class="tr-msg">' + elsewhere + '</p>' : '')
        + '<p class="tr-msg">Tap players on both sides to see what the trade '
        + 'does to both seasons.</p>' + now();
      return;
    }
    elsewhere = '';
    msg('Playing the season out ' + (data.sims ? data.sims.toLocaleString() + ' times ' : '')
        + 'each way&hellip;');
    adapter.evaluate({a:a, b:b, give:g, get:t}).then(function(res){
      if(me !== seq) return;                   // a newer pick has taken over
      var x0 = data.before[a], x1 = res.after[a], y0 = data.before[b], y1 = res.after[b];
      out().innerHTML = verdict(x0, x1, y0, y1)
        + '<div class="tr-cards">' + card(a, true, x0, x1, (res.moves || {})[a])
        + card(b, false, y0, y1, (res.moves || {})[b]) + '</div>'
        + '<div class="tr-acts"><button type="button" class="tr-clear">Clear the trade</button></div>';
      share(g, t);
      reveal(g, t);
      out().querySelector('.tr-clear').addEventListener('click', function(){
        give = {}; get = {}; draw();
      });
    }).catch(function(err){
      if(me !== seq) return;
      if(err instanceof TypeError && window.console) console.error(err);
      msg('Could not play this trade out. Try again in a minute.');
    });
  }

  msg('Reading the league&hellip;');
  adapter.load().then(function(d){
    data = d;
    if(!d || !d.teams || d.teams.length < 2){
      settle();
      msg(d && d.empty ? d.empty : 'This league has no rosters to trade between yet.');
      return;
    }
    var ids = d.teams.map(function(t){ return t.id; });
    var h = readHash(), here = leagueKey();
    // A deal from another league is not laid over this one's rosters (roster
    // 3 here is somebody else entirely); the reader is told where it is from.
    if(h && h.league && here && h.league !== here){
      elsewhere = 'The trade in this link was made in '
        + (h.league === 'site' ? 'this site\u2019s league' : 'another league')
        + ', not the one on screen. Pick that league in the bar above to see it.';
      h = null;
    }
    if(h && ids.indexOf(h.a) >= 0 && ids.indexOf(h.b) >= 0 && h.a !== h.b){
      a = h.a; b = h.b;
      h.give.forEach(function(id){ if((d.rosters[a] || []).indexOf(id) >= 0) give[id] = true; });
      h.get.forEach(function(id){ if((d.rosters[b] || []).indexOf(id) >= 0) get[id] = true; });
    } else {
      a = ids.indexOf(d.mine) >= 0 ? d.mine : ids[0];
      b = first(a);
    }
    draw();
  }).catch(function(err){
    if(err instanceof TypeError && window.console) console.error(err);
    // In the words of the site the league is on: an ESPN league kept
    // private says how to open it.
    var lg = leagueKey();
    settle();
    msg(lg && lg !== 'site' && window.GSAPI && GSAPI.problem ? esc(GSAPI.problem(lg))
        : 'Could not read this league. It may be busy &mdash; try again in a minute.');
  });
};
