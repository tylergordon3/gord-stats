"""
The trade analyzer, shared by both fantasy leagues (/fantasy/trade/ and
/cfb/trade/): pick a deal between two teams and see what it does to both
seasons - points a week, projected record, playoff and title odds - before
and after.

Most trade tools price players on a chart and add up the two sides. This asks
the question a manager actually has: does this make *my* season better? A
running back is worth more to a team starting a backup at RB than to one with
three, and a playoff spot is worth more to a 3-2 team than to a 5-0 one. So
each league's own rest-of-season simulation is run twice, as the rosters are
and as they would be, and the page shows the difference.

Two things make that difference honest:

  * **The same luck both times.** Both runs draw the same numbers for the
    same players (and, in the college league, the same team-week scatter), so
    a player who gets hurt in week 9 of simulated season 412 gets hurt there
    whoever owns him. What is left between the runs is the trade.
  * **Rosters stay legal.** A team taking more players than it sends drops
    its lowest-projected bench player; one sending more signs the best free
    agent at the position it gave up. The page names both.

This module is the page: the pickers, the player lists and the result. Each
league supplies an adapter, `window.GSTradeAdapter`, with two calls:

    load()          -> Promise of {league, teams: [{id, name}], mine,
                       players: {pid: {name, short, pos, ppw, tag}},
                       rosters: {teamId: [pid]}, before: {teamId: Stat},
                       note, sims, unit}
    evaluate(trade) -> Promise of {after: {teamId: Stat},
                       moves: {teamId: [html]}}
    remember(teamId)   optional: store the reader's team

where trade is {a, b, give: [pid from a], get: [pid from b]} and a Stat is
{ppw, wins, losses, playoffs, title}.

The adapters: fantasy.site.trade (the NFL league and any reader's Sleeper or
ESPN league, on gordstats.my_power's simulation) and cfb.site.trade (the
Yahoo college league, on a port of cfb.league_sim).
"""

CSS = """<style>
.tr{margin:6px 0 24px}
.tr-teams{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:0 0 12px}
.tr-teams label{display:flex;flex-direction:column;gap:3px;font-size:12px;font-weight:600;
  color:#64748b;min-width:0}
.tr-teams select{font-size:15px;min-height:40px;padding:4px 8px;border:1px solid #cbd5e1;
  border-radius:8px;background:#fff;color:#0f172a;min-width:0;width:100%}
.tr-sides{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.tr-side{min-width:0}
.tr-side h3{font-size:13px;margin:0 0 4px;color:#475569;font-weight:700;
  text-transform:uppercase;letter-spacing:.03em}
.tr-list{display:flex;flex-direction:column;border:1px solid #e2e8f0;border-radius:10px;
  overflow:hidden}
.tr-p{display:flex;align-items:center;gap:6px;min-height:40px;padding:3px 8px;border:0;
  border-top:1px solid #eef2f7;background:#fff;color:#0f172a;font:inherit;font-size:14px;
  text-align:left;cursor:pointer;width:100%}
.tr-p:first-child{border-top:0}
.tr-p[aria-pressed="true"]{background:#dbeafe;box-shadow:inset 3px 0 0 #2563eb}
.tr-pos{flex:none;width:30px;font-size:11px;font-weight:700;text-align:center;border-radius:4px;
  padding:2px 0;background:#e2e8f0;color:#334155}
.tr-name{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tr-short{display:none}
.tr-tag{flex:none;font-size:11px;font-weight:700;color:#b91c1c}
.tr-ppw{flex:none;font-size:13px;color:#475569;font-variant-numeric:tabular-nums}
.tr-out{margin:14px 0 0}
.tr-msg{font-size:14px;color:#475569;margin:0}
.tr-now{font-size:13px;color:#475569;margin:6px 0 0}
.tr-verdict{font-size:16px;font-weight:700;margin:0 0 2px}
.tr-verdict+.tr-now{margin:0 0 10px}
.tr-verdict .up{color:#15803d}.tr-verdict .down{color:#b91c1c}
.tr-cards{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.tr-card{border:1px solid #e2e8f0;border-radius:10px;padding:10px 12px;min-width:0}
.tr-card h3{font-size:14px;margin:0 0 6px;overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap}
.tr-you{display:inline-block;font-size:11px;font-weight:700;color:#fff;background:#2563eb;
  border-radius:4px;padding:1px 5px;margin:0 6px 0 0;vertical-align:1px}
.tr h3{text-align:left}
.tr .tr-t{display:table;width:100%;margin:0;border:0;border-collapse:collapse;font-size:14px;
  font-variant-numeric:tabular-nums}
/* The theme paints every th dark and boxes every td; this table is four
   numbers a row and wants neither. */
.tr .tr-t th,.tr .tr-t td{background:none;border:0;box-shadow:none;color:inherit}
.tr .tr-t th{text-align:left;font-weight:600;color:#64748b;font-size:12.5px;padding:3px 0}
.tr .tr-t td{text-align:right;padding:3px 0 3px 6px;white-space:nowrap}
.tr .tr-t thead th{text-align:right;font-size:11px;font-weight:600;color:#64748b;
  text-transform:uppercase;letter-spacing:.03em;padding:0 0 2px 6px}
.tr .tr-t td.tr-was{color:#64748b}
.tr .tr-t td.tr-d{font-weight:700;min-width:38px}
.tr .tr-t td.up{color:#15803d}.tr .tr-t td.down{color:#b91c1c}
.tr .tr-t td.flat{color:#64748b;font-weight:400}
.tr-moves{margin:8px 0 0;padding:0 0 0 16px;font-size:12.5px;color:#475569;line-height:1.45}
.tr-note{font-size:12.5px;color:#64748b;line-height:1.5;margin:10px 0 0}
.tr-clear{font:inherit;font-size:13px;border:0;background:none;color:#2563eb;cursor:pointer;
  padding:8px 0;min-height:40px}
@media (max-width:640px){
  .tr-sides,.tr-cards{gap:8px}
  .tr-p{font-size:13px;padding:3px 6px;gap:5px}
  .tr-pos{width:26px}
  .tr-full{display:none}.tr-short{display:inline}
  .tr-cards{grid-template-columns:1fr}
}
@media (prefers-color-scheme: dark){
  .tr-teams label,.tr-side h3,.tr-msg,.tr-now,.tr-moves,.tr-note,.tr .tr-t th,.tr-ppw{color:#aab7c9}
  .tr-teams select{background:#0f172a;color:#e2e8f0;border-color:#334155}
  .tr-list,.tr-card{border-color:#334155}
  .tr-p{background:#0f172a;color:#e2e8f0;border-top-color:#1e293b}
  .tr-p[aria-pressed="true"]{background:#1e3a5f;box-shadow:inset 3px 0 0 #60a5fa}
  .tr-pos{background:#1e293b;color:#cbd5e1}
  .tr-tag{color:#fca5a5}
  .tr .tr-t td.tr-was{color:#94a3b8}
  .tr .tr-t td.up,.tr-verdict .up{color:#4ade80}.tr .tr-t td.down,.tr-verdict .down{color:#f87171}
  .tr-clear{color:#60a5fa}
}
</style>"""


JS = """{% raw %}<script>
window.GSTrade = function(host, adapter){
  'use strict';
  if(!host || !adapter) return;
  var POS = {QB:0, RB:1, WR:2, TE:3, K:4, DEF:5};
  var data = null, a = null, b = null, give = {}, get = {}, seq = 0, timer = null;

  function esc(v){
    return String(v==null?'':v).replace(/[&<>"]/g, function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; });
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

  function readHash(){
    var m = /(?:^|[#&])trade=([^&]*)/.exec(location.hash);
    if(!m) return null;
    var p = decodeURIComponent(m[1]).split('~');
    return {a:p[0], b:p[1], give:(p[2]||'').split('.').filter(Boolean),
            get:(p[3]||'').split('.').filter(Boolean)};
  }
  function writeHash(){
    var g = keys(give), t = keys(get);
    var h = (a && b && (g.length || t.length))
      ? '#trade=' + encodeURIComponent([a, b, g.join('.'), t.join('.')].join('~')) : '';
    try{ history.replaceState(null, '', location.pathname + location.search + h); }catch(e){}
  }

  // ----- drawing ---------------------------------------------------------- //

  function options(selected, skip){
    return data.teams.map(function(t){
      if(t.id === skip) return '';
      return '<option value="' + esc(t.id) + '"' + (t.id === selected ? ' selected' : '')
        + '>' + esc(t.name) + '</option>';
    }).join('');
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
        + (p.tag ? '<span class="tr-tag">' + esc(p.tag) + '</span>' : '')
        + '<span class="tr-ppw">' + (p.ppw == null ? '' : p.ppw.toFixed(1)) + '</span>'
        + '</button>';
    }).join('');
  }

  function draw(){
    host.innerHTML = '<div class="tr-teams">'
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
    host.querySelector('.tr-a').addEventListener('change', function(ev){
      a = ev.target.value;
      if(b === a) b = first(a);
      give = {}; get = {};
      if(adapter.remember) adapter.remember(a);
      draw(); run();
    });
    host.querySelector('.tr-b').addEventListener('change', function(ev){
      b = ev.target.value; get = {};
      draw(); run();
    });
    Array.prototype.forEach.call(host.querySelectorAll('.tr-p'), function(el){
      el.addEventListener('click', function(){
        var set = el.getAttribute('data-side') === 'a' ? give : get;
        var id = el.getAttribute('data-id');
        set[id] = !set[id];
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
      text = (pts > 0 ? '+' : pts < 0 ? '\\u2212' : '\\u00b1') + Math.abs(pts);
      cls = pts > 0 ? 'up' : pts < 0 ? 'down' : 'flat';
    } else {
      var r = Math.round(d*10)/10;
      text = (r > 0 ? '+' : r < 0 ? '\\u2212' : '\\u00b1') + Math.abs(r).toFixed(1);
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
    var edge = mine - theirs, word;
    if(Math.abs(edge) < 0.01) word = 'About even';
    else if(mine > 0 && theirs > 0) word = 'Helps you both' + (edge > 0 ? ', you more' : ', them more');
    else word = edge > 0 ? '<span class="up">Better for you</span>'
                         : '<span class="down">Better for them</span>';
    function pts(d){
      var r = Math.round(d*100);
      return (r > 0 ? '+' : r < 0 ? '\u2212' : '\u00b1') + Math.abs(r);
    }
    return '<p class="tr-verdict">' + word + '</p><p class="tr-now">Title odds '
      + pts(mine) + ' for you, ' + pts(theirs) + ' for them.</p>';
  }

  function run(){
    writeHash();
    var g = keys(give), t = keys(get), me = ++seq;
    if(!g.length && !t.length){
      out().innerHTML = '<p class="tr-msg">Tap players on both sides to see what the trade '
        + 'does to both seasons.</p>' + now();
      return;
    }
    msg('Playing the season out ' + (data.sims ? data.sims.toLocaleString() + ' times ' : '')
        + 'each way&hellip;');
    adapter.evaluate({a:a, b:b, give:g, get:t}).then(function(res){
      if(me !== seq) return;                   // a newer pick has taken over
      var x0 = data.before[a], x1 = res.after[a], y0 = data.before[b], y1 = res.after[b];
      out().innerHTML = verdict(x0, x1, y0, y1)
        + '<div class="tr-cards">' + card(a, true, x0, x1, (res.moves || {})[a])
        + card(b, false, y0, y1, (res.moves || {})[b]) + '</div>'
        + '<button type="button" class="tr-clear">Clear the trade</button>';
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
      msg(d && d.empty ? d.empty : 'This league has no rosters to trade between yet.');
      return;
    }
    var ids = d.teams.map(function(t){ return t.id; });
    var h = readHash();
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
    msg('Could not read this league. It may be busy &mdash; try again in a minute.');
  });
};
</script>{% endraw %}"""


def section(host_id: str = "tr-host") -> str:
    """The page's slot for the analyzer; the adapter's script fills it."""
    return CSS + f"<div class='tr' id='{host_id}'></div>"


def start(host_id: str = "tr-host") -> str:
    """Runs the analyzer once the adapter is defined - include it last."""
    return ("<script>window.GSTrade(document.getElementById('" + host_id
            + "'), window.GSTradeAdapter);</script>")
