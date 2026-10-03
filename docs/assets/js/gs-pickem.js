/*
 * Reader pick'em (/pickem/, gordstats.pickem_page): the week's games with
 * the reader's picks and confidence points, both leaderboards and past
 * weeks, from /api/pickem (functions/api/pickem.js).
 *
 * The page carries the current week's slate (#pk-data), so the games draw
 * at once, read-only; the API's answer then fills in the reader's picks, the
 * name they play under and the leaderboards. Every box was given its height
 * by the page, so none of that moves anything.
 *
 * Picking: tap a team to pick it (tap it again to take the pick back). A new
 * pick gets the lowest free value; the <select> under it sets any other -
 * choosing a value another open game holds swaps the two, and a value a
 * locked game holds is disabled. Each change saves itself a moment later,
 * the whole week at once. What is locked is judged on the server's clock
 * (`now` in every answer), and the server enforces it whatever the page says.
 *
 * Config: window.GSCFG.pickem = { api, card, login }.
 */
(function () {
  'use strict';
  var host = document.getElementById('pk');
  if (!host || host.getAttribute('data-pk-on')) return;
  host.setAttribute('data-pk-on', '1');

  var CFG = (window.GSCFG && window.GSCFG.pickem) || {};
  var API = CFG.api || '/api/pickem';
  var LOGIN = CFG.login || '/api/auth/login';
  var CARD = CFG.card || 148;
  var seed = {};
  try { seed = JSON.parse(document.getElementById('pk-data').textContent) || {}; } catch (e) {}

  // What favorites.js last heard from /api/me ("in", "out", "off"): the bar
  // starts right, and /api/pickem's own answer settles it.
  var guess = null;
  try { guess = localStorage.getItem('gs:acct'); } catch (e) {}

  var S = {
    season: seed.season || null, current: seed.current || null, week: seed.week || null,
    weeks: seed.weeks || [], slate: seed.slate || null, board: null, known: false,
    offset: 0, signedIn: guess === 'in', configured: guess !== 'off', migrating: false,
    me: null, mine: {}, ver: 0, which: 'week', editing: false, failed: false
  };

  function $(sel) { return host.querySelector(sel); }
  var el = {
    prev: $('.pk-prev'), next: $('.pk-next'), wkT: $('.pk-wk-t'), wkS: $('.pk-wk-s'),
    player: $('.pk-player'), games: $('.pk-games'), board: $('.pk-board'), past: $('.pk-past')
  };

  function esc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  var SAFE_IMG = /^https:\/\/a\.espncdn\.com\//;
  var WHEN = new Intl.DateTimeFormat('en-US', { weekday: 'short', month: 'short', day: 'numeric',
                                                hour: 'numeric', minute: '2-digit' });
  var DAY = new Intl.DateTimeFormat('en-US', { weekday: 'short', month: 'short', day: 'numeric' });

  function now() { return Date.now() + S.offset; }
  function locked(g) {
    var t = Date.parse(g.lock);
    return !isFinite(t) || now() >= t;
  }
  function games() {
    var list = (S.slate && Array.isArray(S.slate.games)) ? S.slate.games.slice() : [];
    return list.filter(function (g) { return g && /^(cfb|nfl):\d+$/.test(String(g.id)); })
      .sort(function (a, b) {
        return a.ko < b.ko ? -1 : a.ko > b.ko ? 1 : (a.id < b.id ? -1 : 1);
      });
  }
  function byId(id) {
    var list = games();
    for (var i = 0; i < list.length; i++) if (list[i].id === id) return list[i];
    return null;
  }
  function N() { return games().length; }
  function teamName(t) { return (t && (t.nm || t.ab)) || 'TBD'; }
  function shortName(t) { return (t && (t.ab || t.nm)) || 'TBD'; }
  function matchup(g) { return shortName(g.a) + ' at ' + shortName(g.h); }
  function when(g) {
    var d = new Date(g.ko);
    if (isNaN(d)) return '';
    return g.tk === false ? DAY.format(d) + ' · Time TBA' : WHEN.format(d);
  }
  function holder(v, except) {
    for (var id in S.mine) if (id !== except && S.mine[id][1] === v) return id;
    return null;
  }
  function freeValues(except) {
    var used = {}, out = [];
    for (var id in S.mine) if (id !== except) used[S.mine[id][1]] = 1;
    for (var v = 1; v <= N(); v++) if (!used[v]) out.push(v);
    return out;
  }
  // A week's points from the slate's results: {you, gs}.
  function tally() {
    var out = { you: 0, gs: 0 };
    games().forEach(function (g) {
      if (g.res !== 'h' && g.res !== 'a') return;
      var p = S.mine[g.id];
      if (p && p[0] === g.res) out.you += p[1];
      if (g.gs && g.gs.s === g.res) out.gs += g.gs.c;
    });
    return out;
  }
  function editable() {
    return S.known && S.configured && S.signedIn && !!S.me && !S.migrating;
  }

  /* ---------------- the player bar ---------------- */

  var msgTimer = null;
  function flash(text, cls) {
    var m = el.player.querySelector('.pk-msg');
    if (!m) return;
    m.className = 'pk-msg' + (cls ? ' ' + cls : '');
    m.textContent = text || '';
    clearTimeout(msgTimer);
    if (text && cls !== 'keep') {
      msgTimer = setTimeout(function () { m.textContent = ''; m.className = 'pk-msg'; }, 8000);
    }
  }
  function loginHref() { return LOGIN; }

  function drawPlayer() {
    var t = tally(), html;
    var model = S.slate ? 'GordStats has ' + t.gs + ' this week.' : '';
    if (!S.configured) {
      html = '<p>Picks open once sign-in is switched on here.</p><div class="pk-row">'
        + '<span>' + esc(model) + '</span></div><p class="pk-msg"></p>';
    } else if (S.migrating) {
      html = '<p>Picks open soon.</p><div class="pk-row"><span>' + esc(model)
        + '</span></div><p class="pk-msg"></p>';
    } else if (!S.signedIn) {
      html = '<p>Sign in to make your picks. ' + esc(model) + '</p>'
        + '<div class="pk-row"><a class="pk-btn" href="' + esc(loginHref()) + '">Sign in to play'
        + '</a></div><p class="pk-msg"></p>';
    } else if (!S.known) {
      html = '<p>Loading your picks&hellip;</p><div class="pk-row"></div><p class="pk-msg"></p>';
    } else if (!S.me || S.editing) {
      html = '<p>' + (S.me ? 'Change the name shown on the leaderboard'
        : 'Choose a name for the leaderboard to play') + '</p>'
        + '<form class="pk-form" novalidate><input class="pk-name" type="text" maxlength="20" '
        + 'autocomplete="nickname" autocapitalize="words" spellcheck="false" '
        + 'aria-label="Your name on the leaderboard" placeholder="3-20 letters or numbers" value="'
        + esc(S.me ? S.me.name : '') + '"><button type="submit" class="pk-btn">'
        + (S.me ? 'Save' : 'Join') + '</button>'
        + (S.me ? '<button type="button" class="pk-link pk-cancel">Cancel</button>' : '')
        + '</form><p class="pk-msg"></p>';
    } else {
      html = '<div class="pk-row"><span class="pk-who">Playing as <b>' + esc(S.me.name)
        + '</b></span><button type="button" class="pk-link pk-rename">Change</button></div>'
        + '<p class="pk-score">This week: you <b>' + t.you + '</b> &middot; GordStats <b>'
        + t.gs + '</b></p><p class="pk-msg"></p>';
    }
    el.player.innerHTML = html;
  }

  /* ---------------- the games ---------------- */

  function team(g, side, mine, open) {
    var t = g[side] || {};
    var picked = !!(mine && mine[0] === side);
    var decided = g.res === 'h' || g.res === 'a';
    var cls = 'pk-team' + (picked ? ' on' : '') + (decided && g.res === side ? ' won' : '');
    var rank = t.rk ? '<small>#' + esc(t.rk) + (t.rec ? ' · ' + esc(t.rec) : '') + '</small>'
      : (t.rec ? '<small>' + esc(t.rec) + '</small>' : '<small>&nbsp;</small>');
    var sc = g.score && g.score[side] != null ? esc(g.score[side]) : '';
    var img = SAFE_IMG.test(String(t.lg || '')) ? '<img src="' + esc(t.lg)
      + '" alt="" width="28" height="28" loading="lazy">' : '<img alt="" width="28" height="28">';
    return '<button type="button" class="' + cls + '" data-side="' + side + '" aria-pressed="'
      + picked + '"' + (open ? '' : ' aria-disabled="true"') + ' aria-label="'
      + esc((picked ? 'Picked: ' : 'Pick ') + teamName(t) + ' to win') + '">' + img
      + '<span class="pk-tn">' + esc(teamName(t)) + rank + '</span><span class="pk-sc">' + sc
      + '</span></button>';
  }

  function options(g, mine, open) {
    var n = N(), out = [];
    if (!mine) out.push('<option value="">Points</option>');
    for (var v = n; v >= 1; v--) {
      var other = holder(v, g.id), label = String(v), off = false;
      if (other && !(mine && mine[1] === v)) {
        var og = byId(other);
        if (og && locked(og)) { label += ' · locked'; off = true; }
        else if (og) label += ' · swap with ' + matchup(og);
      }
      out.push('<option value="' + v + '"' + (mine && mine[1] === v ? ' selected' : '')
        + (off ? ' disabled' : '') + '>' + esc(label) + '</option>');
    }
    return '<select class="pk-conf" aria-label="' + esc('Confidence points for ' + matchup(g))
      + '"' + (open && mine ? '' : ' disabled') + '>' + out.join('') + '</select>';
  }

  function card(g) {
    var lk = locked(g), mine = S.mine[g.id] || null;
    var open = !lk && editable();
    var st = g.res === 'v' ? 'No contest' : g.st === 'post' ? 'Final'
      : g.st === 'in' ? 'Live' : lk ? '&#128274; Locked' : '';
    var mark = '';
    if (mine && (g.res === 'h' || g.res === 'a')) {
      mark = mine[0] === g.res ? '<span class="pk-mark good">+' + mine[1] + '</span>'
        : '<span class="pk-mark bad">0</span>';
    } else if (mine && g.res === 'v') {
      mark = '<span class="pk-mark">0</span>';
    }
    var model = '';
    if (g.gs && (g.gs.s === 'h' || g.gs.s === 'a')) {
      var right = g.res === g.gs.s, wrong = (g.res === 'h' || g.res === 'a') && !right;
      model = 'GordStats: <b>' + esc(shortName(g[g.gs.s])) + ' ' + esc(g.gs.c) + '</b>'
        + (right ? ' &#10003;' : wrong ? ' &#10007;' : '');
    }
    return '<article class="pk-g" data-id="' + esc(g.id) + '">'
      + '<div class="pk-meta"><span class="pk-sp ' + (g.sp === 'nfl' ? 'nfl' : 'cfb') + '">'
      + (g.sp === 'nfl' ? 'NFL' : 'CFB') + '</span>'
      + (g.gotw ? '<span class="pk-sp">Game of the week</span>' : '')
      + '<span class="pk-when">' + esc(when(g)) + (g.tv ? ' · ' + esc(g.tv) : '') + '</span>'
      + '<span class="pk-st' + (g.st === 'in' && g.res == null ? ' live' : '') + '">' + st
      + '</span></div>'
      + '<div class="pk-teams">' + team(g, 'a', mine, open) + team(g, 'h', mine, open) + '</div>'
      + '<div class="pk-ctl">' + options(g, mine, open) + mark
      + '<span class="pk-model">' + model + '</span></div></article>';
  }

  function drawGames() {
    var list = games();
    if (!S.slate) {
      el.games.innerHTML = '<div class="pk-empty">' + (S.failed
        ? 'Pick&#39;em could not load just now. Try again in a minute.'
        : 'The first slate posts with the NFL season.') + '</div>';
    } else if (!list.length) {
      el.games.innerHTML = '<div class="pk-empty">No games this week.</div>';
    } else {
      el.games.innerHTML = list.map(card).join('');
    }
    el.games.style.minHeight = (list.length ? list.length * CARD : 168) + 'px';
    el.games.removeAttribute('aria-busy');
  }

  /* ---------------- the week bar ---------------- */

  function weekList() {
    return (S.weeks || []).filter(function (w) { return w && w.w; })
      .sort(function (a, b) { return a.w - b.w; });
  }
  function drawWeek() {
    var list = weekList(), i = -1;
    for (var k = 0; k < list.length; k++) if (list[k].w === S.week) i = k;
    var w = list[i] || {};
    el.wkT.textContent = (S.slate && S.slate.label) || w.label || "Pick'em";
    el.wkS.textContent = (S.slate && S.slate.sub) || w.sub || '';
    el.prev.disabled = i <= 0;
    el.next.disabled = i < 0 || i >= list.length - 1;
    el.prev.setAttribute('data-w', i > 0 ? list[i - 1].w : '');
    el.next.setAttribute('data-w', i >= 0 && i < list.length - 1 ? list[i + 1].w : '');
  }

  /* ---------------- leaderboards and past weeks ---------------- */

  function drawBoard() {
    [].forEach.call(host.querySelectorAll('.pk-which button'), function (b) {
      b.setAttribute('aria-pressed', String(b.getAttribute('data-b') === S.which));
    });
    var rows = S.board && S.board[S.which];
    if (!rows) {
      el.board.innerHTML = S.failed ? '<p>The leaderboard could not load just now.</p>' : '';
      return;
    }
    var week = S.which === 'week';
    if (!rows.length) {
      el.board.innerHTML = '<p>No picks yet' + (week ? ' this week' : '') + '.</p>';
      el.board.removeAttribute('aria-busy');
      return;
    }
    var me = S.me && S.me.name;
    el.board.innerHTML = '<table class="pk-tbl"><thead><tr><th scope="col">#</th>'
      + '<th scope="col" class="nm">Player</th><th scope="col">Pts</th>'
      + '<th scope="col" title="Right picks of those decided">Right</th>'
      + (week ? '<th scope="col" title="The most still possible">Max</th>' : '<th scope="col">Wks</th>')
      + '</tr></thead><tbody>' + rows.map(function (r) {
        var cls = r.gs ? 'gs' : (me && r.name === me ? 'me' : '');
        return '<tr' + (cls ? ' class="' + cls + '"' : '') + '><td>' + esc(r.r) + '</td>'
          + '<td class="nm">' + esc(r.name) + (r.gs ? '<span class="pk-badge">Model</span>' : '')
          + (cls === 'me' ? '<span class="pk-badge">You</span>' : '') + '</td>'
          + '<td><b>' + esc(r.pts) + '</b></td><td>' + esc(r.right) + '/' + esc(r.of) + '</td>'
          + '<td>' + esc(week ? r.max : r.wk) + '</td></tr>';
      }).join('') + '</tbody></table>';
    el.board.removeAttribute('aria-busy');
  }

  function drawPast() {
    var list = weekList().filter(function (w) { return w.w !== S.current; }).reverse();
    if (!list.length) {
      el.past.innerHTML = S.known ? '<li><p>Past weeks show up here once one is played.</p></li>' : '';
      return;
    }
    el.past.innerHTML = list.map(function (w) {
      var top = (w.top || []).map(function (t) { return esc(t.name) + ' ' + esc(t.pts); }).join(', ');
      var line = (top ? 'Winner: ' + top : (w.done ? 'No picks' : 'In progress'))
        + (w.gs != null ? ' &middot; GordStats ' + esc(w.gs) : '')
        + (w.players ? ' &middot; ' + esc(w.players) + (w.players === 1 ? ' player' : ' players') : '');
      return '<li><button type="button" data-w="' + esc(w.w) + '"><b>' + esc(w.label) + '</b> '
        + esc(w.sub || '') + '<br>' + line + '</button></li>';
    }).join('');
    el.past.removeAttribute('aria-busy');
  }

  function draw() {
    drawWeek();
    drawPlayer();
    drawGames();
    drawBoard();
    drawPast();
  }

  /* ---------------- picking and saving ---------------- */

  function ready(g) {
    if (!S.known) return false;
    if (!S.configured || S.migrating) { flash('Picks are not open here yet.', 'err'); return false; }
    if (!S.signedIn) {
      var m = el.player.querySelector('.pk-msg');
      if (m) {
        m.className = 'pk-msg';
        m.innerHTML = '<a href="' + esc(loginHref()) + '">Sign in</a> to make your picks.';
      }
      return false;
    }
    if (!S.me) {
      flash('Choose a name first - it is what the leaderboard shows.', 'err');
      var input = el.player.querySelector('.pk-name');
      if (input) input.focus();
      return false;
    }
    if (locked(g)) { flash('That game has kicked off - its pick is locked.', 'err'); return false; }
    return true;
  }

  function pickSide(id, side) {
    var g = byId(id);
    if (!g || !ready(g)) return;
    var cur = S.mine[id];
    if (cur && cur[0] === side) delete S.mine[id];
    else if (cur) S.mine[id] = [side, cur[1]];
    else {
      var free = freeValues(id);
      if (!free.length) return;
      S.mine[id] = [side, free[0]];
    }
    changed();
  }

  function setConf(id, v) {
    var g = byId(id);
    if (!g || !ready(g) || !S.mine[id]) { drawGames(); return; }
    var prev = S.mine[id][1];
    if (!(v >= 1 && v <= N()) || v === prev) { drawGames(); return; }
    var other = holder(v, id);
    if (other) {
      var og = byId(other);
      if (!og || locked(og)) {
        flash('That value is on a game that has kicked off.', 'err');
        drawGames();
        return;
      }
      S.mine[other] = [S.mine[other][0], prev];
    }
    S.mine[id] = [S.mine[id][0], v];
    changed();
  }

  var saveTimer = null, inflight = false, again = false;
  function changed() {
    S.ver++;
    drawGames();
    drawPlayer();
    flash('Saving…', 'keep');
    clearTimeout(saveTimer);
    saveTimer = setTimeout(save, 600);
  }

  function post(path, body) {
    return fetch(API + path, { method: 'POST', credentials: 'same-origin',
      headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (j) {
          return { ok: r.ok, status: r.status, j: j || {} };
        });
      }, function (e) {
        console.warn('pickem: no answer', e);
        return { ok: false, status: 0, j: { error: "Couldn't reach the server. Try again in a minute." } };
      });
  }

  function save() {
    clearTimeout(saveTimer);
    saveTimer = null;
    if (inflight) { again = true; return Promise.resolve(); }
    inflight = true;
    var sent = S.ver, week = S.week, season = S.season, picks = {};
    for (var id in S.mine) picks[id] = [S.mine[id][0], S.mine[id][1]];
    return post('/picks', { season: season, week: week, picks: picks }).then(function (a) {
      if (S.week !== week) return;
      if (a.ok && a.j.ok) {
        if (S.ver === sent) S.mine = a.j.picks || {};
        flash('Saved', 'ok');
      } else {
        if (a.status === 401) { S.signedIn = false; S.me = null; }
        if (a.j.need_name) S.me = null;
        if (a.j.picks && typeof a.j.picks === 'object') { S.mine = a.j.picks; S.ver++; }
        drawPlayer();
        flash(a.j.error || ('Not saved (' + a.status + ').'), 'err');
      }
      drawGames();
    }).then(function () {
      inflight = false;
      if (again) { again = false; save(); }
    });
  }

  function saveName(name) {
    var btn = el.player.querySelector('.pk-form [type=submit]');
    if (btn) btn.disabled = true;
    return post('/name', { name: name }).then(function (a) {
      if (a.ok && a.j.ok) {
        S.me = { name: a.j.name };
        S.editing = false;
        draw();
        flash(a.j.saved === false ? '' : 'You are in. Make your picks below.', 'ok');
        return;
      }
      if (a.status === 401) { S.signedIn = false; draw(); }
      if (btn) btn.disabled = false;
      flash(a.j.error || ('That did not go through (' + a.status + ').'), 'err');
    });
  }

  /* ---------------- tabs, weeks, loading ---------------- */

  function tab(name) {
    ['picks', 'board', 'past'].forEach(function (t) {
      var b = document.getElementById('pk-t-' + t), p = document.getElementById('pk-p-' + t);
      var on = t === name;
      b.setAttribute('aria-selected', String(on));
      b.tabIndex = on ? 0 : -1;
      p.hidden = !on;
    });
  }

  function apply(d) {
    S.known = true;
    S.failed = false;
    S.offset = typeof d.now === 'number' ? d.now - Date.now() : 0;
    S.configured = d.configured !== false;
    S.signedIn = !!d.signedIn;
    S.migrating = !!d.migrating;
    S.season = d.season || null;
    S.current = d.current || null;
    S.week = d.week || null;
    S.weeks = Array.isArray(d.weeks) ? d.weeks : [];
    S.slate = d.slate || null;
    S.board = d.board || { week: [], season: [] };
    S.me = d.me && typeof d.me.name === 'string' ? { name: d.me.name } : null;
    S.mine = {};
    var mine = d.mine && typeof d.mine === 'object' ? d.mine : {};
    for (var id in mine) {
      var p = mine[id];
      if (Array.isArray(p) && (p[0] === 'h' || p[0] === 'a') && p[1] >= 1) S.mine[id] = [p[0], +p[1]];
    }
    S.ver++;
    draw();
  }

  var seq = 0;
  function load(week) {
    var mine = ++seq;
    var flush = saveTimer ? save() : Promise.resolve();
    return flush.then(function () {
      return fetch(API + (week ? '?week=' + encodeURIComponent(week) : ''), { credentials: 'same-origin' });
    }).then(function (r) {
      return r.json().then(function (j) { return { ok: r.ok, j: j }; });
    }).then(function (a) {
      if (mine !== seq) return;
      if (!a.ok || !a.j || !a.j.ok) throw new Error((a.j && a.j.error) || 'not ok');
      apply(a.j);
    }).catch(function (e) {
      if (mine !== seq) return;
      console.warn('pickem: could not load', e);
      S.known = true;
      S.failed = true;
      if (!S.slate) drawGames();
      drawPlayer();
      drawBoard();
      flash("Couldn't load the latest just now.", 'err');
    });
  }

  host.addEventListener('click', function (ev) {
    var t = ev.target;
    if (!t.closest) return;
    var b = t.closest('.pk-team');
    if (b) {
      var c = b.closest('.pk-g');
      if (c) pickSide(c.getAttribute('data-id'), b.getAttribute('data-side'));
      return;
    }
    var tb = t.closest('[role=tab]');
    if (tb) { tab(tb.id.replace('pk-t-', '')); return; }
    var wb = t.closest('.pk-prev, .pk-next');
    if (wb && !wb.disabled && wb.getAttribute('data-w')) { load(+wb.getAttribute('data-w')); return; }
    var which = t.closest('.pk-which button');
    if (which) { S.which = which.getAttribute('data-b') === 'season' ? 'season' : 'week'; drawBoard(); return; }
    var past = t.closest('.pk-past button');
    if (past) { tab('picks'); load(+past.getAttribute('data-w')); return; }
    if (t.closest('.pk-rename')) { S.editing = true; drawPlayer(); var i = el.player.querySelector('.pk-name'); if (i) i.focus(); return; }
    if (t.closest('.pk-cancel')) { S.editing = false; drawPlayer(); }
  });
  host.addEventListener('change', function (ev) {
    var s = ev.target;
    if (!s.classList || !s.classList.contains('pk-conf')) return;
    var c = s.closest('.pk-g');
    if (c) setConf(c.getAttribute('data-id'), parseInt(s.value, 10));
  });
  host.addEventListener('submit', function (ev) {
    var f = ev.target;
    if (!f.classList || !f.classList.contains('pk-form')) return;
    ev.preventDefault();
    var input = f.querySelector('.pk-name');
    var name = input ? input.value.trim() : '';
    if (name.length < 3) { flash('Names are 3 to 20 characters.', 'err'); return; }
    saveName(name);
  });
  // Arrow keys move between the tabs, as a tablist does.
  host.querySelector('[role=tablist]').addEventListener('keydown', function (ev) {
    if (ev.key !== 'ArrowRight' && ev.key !== 'ArrowLeft') return;
    var order = ['picks', 'board', 'past'];
    var at = order.indexOf((document.activeElement.id || '').replace('pk-t-', ''));
    if (at < 0) return;
    var next = order[(at + (ev.key === 'ArrowRight' ? 1 : order.length - 1)) % order.length];
    tab(next);
    document.getElementById('pk-t-' + next).focus();
  });
  // A game that locks while the page is open stops taking picks.
  setInterval(function () {
    if (document.hidden || !S.slate) return;
    var shown = [].map.call(el.games.querySelectorAll('.pk-g'), function (c) {
      return c.querySelector('.pk-team[aria-disabled]') ? 1 : 0;
    }).join('');
    var want = games().map(function (g) { return locked(g) || !editable() ? 1 : 0; }).join('');
    if (shown !== want) drawGames();
  }, 20000);

  if (/^#(leaderboard|board)$/.test(location.hash)) tab('board');
  else if (location.hash === '#past') tab('past');
  var asked = /^#week-(\d{1,2})$/.exec(location.hash);
  draw();
  load(asked ? +asked[1] : null);

  window.GSPickem = { state: S, load: load, pickSide: pickSide, setConf: setConf, save: save,
                      locked: locked };
})();
