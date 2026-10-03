/*
 * Live win probability on a game preview (/cfb/game/<id>/, /nfl/game/<id>/):
 * ESPN's own number, after every play, as a small chart.
 *
 * The page carries a hidden <section data-gs-wp> naming the game
 * (gordstats.preview_page.winprob_block). A line of inline script right after
 * it un-hides it before the first paint once the game has kicked off, so its
 * fixed-height box is there from the start and nothing under it moves when
 * the chart arrives. This file fills it from ESPN's game summary
 * (site.api.espn.com, which answers any origin): `winprobability` is the home
 * team's chance after each play, by play id; `drives` gives each play's
 * quarter and clock, which put it on a 60-minute axis (overtime periods get a
 * short stretch each after it, their plays spaced evenly). While the game is
 * on it reads the summary again every minute the tab is visible; a finished
 * game is read once.
 *
 * Before kickoff there is nothing to show and the section stays hidden; a
 * page left open across kickoff shows it then. A game ESPN never charted
 * (called off) hides it again.
 *
 * window.GSWinProb holds the pieces the tests drive: series(), svg(), pct(),
 * boot().
 */
(function () {
  'use strict';
  if (window.GSWinProb) return;

  var BASE = 'https://site.api.espn.com/apis/site/v2/sports/football/';
  var Q = 900, REG = 3600, OTW = 450;          // seconds: a quarter, regulation, an OT's stretch
  var EVERY = 60e3, RETRY = 120e3, WAIT = 6 * 3600e3;
  var HEIGHT = 170;                             // the chart box's CSS height (preview_page.CSS)

  function num(v) {
    var n = parseFloat(v);
    return isFinite(n) ? n : null;
  }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  // A chance as the page shows it: whole percents, and a game still going is
  // never "100%" until ESPN says so.
  function pct(p) {
    if (p >= 1) return '100%';
    if (p >= 0.995) return '>99%';
    if (p <= 0) return '0%';
    if (p < 0.005) return '<1%';
    return Math.round(p * 100) + '%';
  }

  // "4:32" -> 272. Plays carry the clock as text.
  function clockSec(c) {
    if (!c) return null;
    var s = String(c.displayValue != null ? c.displayValue : c);
    var m = /^(\d+):(\d\d)/.exec(s);
    if (m) return +m[1] * 60 + +m[2];
    return num(s);
  }
  function perName(per) {
    return per <= 4 ? 'Q' + per : (per === 5 ? 'OT' : (per - 4) + 'OT');
  }

  /* The summary as the chart reads it:
     {state, detail, completed, home: {abbr, score}, away, pts: [{x, p, per,
      clk, hs, as, text}], span, ots, timed}
     x is seconds of game time (0 at kickoff, 3600 at the end of the fourth),
     p the home team's chance. Where too few plays can be found to place them
     on the clock, x is just the play's index (timed: false) and the chart has
     no quarter marks. */
  function series(d) {
    d = d || {};
    var comp = ((d.header || {}).competitions || [])[0] || {};
    var st = (comp.status || {}).type || {};
    var out = { state: st.state || 'pre', detail: st.shortDetail || st.detail || '',
                completed: !!st.completed, name: st.name || '',
                home: { abbr: '', score: null }, away: { abbr: '', score: null },
                pts: [], span: REG, ots: 0, timed: true };
    (comp.competitors || []).forEach(function (c) {
      out[c.homeAway === 'away' ? 'away' : 'home'] = {
        abbr: (c.team || {}).abbreviation || '', score: num(c.score) };
    });
    var plays = {}, dr = d.drives || {};
    (dr.previous || []).concat(dr.current ? [dr.current] : []).forEach(function (v) {
      (v.plays || []).forEach(function (p) { plays[p.id] = p; });
    });
    var rows = [], found = 0;
    (d.winprobability || []).forEach(function (w) {
      var p = num(w.homeWinPercentage);
      if (p === null) return;
      var pl = plays[w.playId] || null;
      if (pl) found++;
      rows.push({ p: Math.max(0, Math.min(1, p)), pl: pl });
    });
    if (!rows.length) return out;
    var pt = function (r, x) {
      var pl = r.pl || {};
      return { x: x, p: r.p, per: r.per || 0,
               clk: pl.clock ? String(pl.clock.displayValue || '') : '',
               hs: num(pl.homeScore), as: num(pl.awayScore), text: pl.text || '' };
    };
    if (found < rows.length / 2) {
      out.timed = false;
      out.span = Math.max(rows.length - 1, 1);
      rows.forEach(function (r, i) { out.pts.push(pt(r, i)); });
      return out;
    }
    // Quarter of every row (a row with no play keeps the one before it),
    // and how many plays each overtime holds, to space them.
    var per = 1, most = 1, otN = {}, otJ = {}, last = 0;
    rows.forEach(function (r) {
      var n = r.pl ? num((r.pl.period || {}).number) : null;
      if (n) per = n;
      r.per = per;
      if (per > most) most = per;
      if (per > 4) otN[per] = (otN[per] || 0) + 1;
    });
    rows.forEach(function (r) {
      var x;
      if (r.per <= 4) {
        var c = r.pl ? clockSec(r.pl.clock) : null;
        x = c === null ? last : (r.per - 1) * Q + Q - Math.max(0, Math.min(Q, c));
      } else {
        otJ[r.per] = (otJ[r.per] || 0) + 1;
        x = REG + (r.per - 5) * OTW + otJ[r.per] / otN[r.per] * OTW;
      }
      // ESPN now and then files a play a second out of order; the line
      // never runs backwards.
      x = Math.max(x, last);
      last = x;
      out.pts.push(pt(r, x));
    });
    out.ots = Math.max(0, most - 4);
    out.span = REG + out.ots * OTW;
    return out;
  }

  /* The chart: the home team's chance from 0 (the visitors certain) to 100%,
     the 50% line, a mark at each quarter (the half a little firmer). The
     line and its wash take the home color above 50% and the visitors' below,
     and each half is named in the margin, so the color is never the only
     key. Drawn at the box's own pixel size: text stays text-sized. */
  function svg(s, w, h, o) {
    o = o || {};
    var L = 58, R = 10, T = 8, B = 22;
    var pw = Math.max(w - L - R, 10), ph = Math.max(h - T - B, 10);
    var span = s.span || REG;
    var X = function (x) { return L + x / span * pw; };
    var Y = function (p) { return T + (1 - p) * ph; };
    var f = function (v) { return Math.round(v * 10) / 10; };
    var id = 'gswp' + String(o.id || '').replace(/\W/g, '');
    var mid = Y(0.5), out = [];
    out.push('<svg xmlns="http://www.w3.org/2000/svg" width="' + w + '" height="' + h +
             '" viewBox="0 0 ' + w + ' ' + h + '" tabindex="0" role="img" aria-label="' +
             esc(o.label || 'Win probability') + '">');
    out.push('<defs><clipPath id="' + id + 't"><rect x="' + L + '" y="' + (T - 4) + '" width="' +
             (pw + 8) + '" height="' + f(mid - T + 4) + '"/></clipPath><clipPath id="' + id +
             'b"><rect x="' + L + '" y="' + f(mid) + '" width="' + (pw + 8) + '" height="' +
             f(T + ph - mid + 4) + '"/></clipPath></defs>');
    // The frame: top and bottom rules; each half named in the margin, a dot
    // of its color beside the name.
    out.push('<line class="wp-grid" x1="' + L + '" x2="' + (L + pw) + '" y1="' + T + '" y2="' +
             T + '"/><line class="wp-grid" x1="' + L + '" x2="' + (L + pw) + '" y1="' +
             (T + ph) + '" y2="' + (T + ph) + '"/>');
    out.push('<circle class="wp-key-h" cx="' + (L - 8) + '" cy="' + (T + 6) + '" r="3.5"/>' +
             '<circle class="wp-key-a" cx="' + (L - 8) + '" cy="' + (T + ph - 6) + '" r="3.5"/>');
    out.push('<text class="wp-yl" x="' + (L - 15) + '" y="' + (T + 10) + '" text-anchor="end">' +
             esc(o.home || s.home.abbr) + '</text><text class="wp-yl wp-yl-m" x="' + (L - 6) +
             '" y="' + f(mid + 4) + '" text-anchor="end">50%</text><text class="wp-yl" x="' +
             (L - 15) + '" y="' + (T + ph - 2) + '" text-anchor="end">' + esc(o.away || s.away.abbr) +
             '</text>');
    if (s.timed) {
      var periods = 4 + (s.ots || 0);
      for (var k = 1; k <= periods; k++) {
        var a = k <= 4 ? (k - 1) * Q : REG + (k - 5) * OTW;
        var b = k <= 4 ? k * Q : a + OTW;
        if (k > 1) {
          out.push('<line class="wp-q' + (k === 3 ? ' wp-half' : '') + '" x1="' + f(X(a)) +
                   '" x2="' + f(X(a)) + '" y1="' + T + '" y2="' + (T + ph) + '"/>');
        }
        out.push('<text class="wp-ql" x="' + f((X(a) + X(b)) / 2) + '" y="' + (h - 6) +
                 '" text-anchor="middle">' + perName(k) + '</text>');
      }
    }
    out.push('<line class="wp-mid" x1="' + L + '" x2="' + (L + pw) + '" y1="' + f(mid) +
             '" y2="' + f(mid) + '"/>');
    var pts = s.pts || [];
    if (pts.length) {
      var line = pts.map(function (q, i) {
        return (i ? 'L' : 'M') + f(X(q.x)) + ' ' + f(Y(q.p));
      }).join('');
      var area = 'M' + f(X(pts[0].x)) + ' ' + f(mid) + line.replace(/^M/, 'L') + 'L' +
        f(X(pts[pts.length - 1].x)) + ' ' + f(mid) + 'Z';
      out.push('<path class="wp-fill-h" clip-path="url(#' + id + 't)" d="' + area + '"/>');
      out.push('<path class="wp-fill-a" clip-path="url(#' + id + 'b)" d="' + area + '"/>');
      out.push('<path class="wp-line-h" clip-path="url(#' + id + 't)" d="' + line + '"/>');
      out.push('<path class="wp-line-a" clip-path="url(#' + id + 'b)" d="' + line + '"/>');
      if (o.live) {
        var e = pts[pts.length - 1];
        out.push('<circle class="wp-dot ' + (e.p >= 0.5 ? 'wp-dot-h' : 'wp-dot-a') + '" cx="' +
                 f(X(e.x)) + '" cy="' + f(Y(e.p)) + '" r="4"/>');
      }
    }
    // The crosshair, moved by pointer, touch or arrow keys.
    out.push('<g class="wp-x" style="display:none"><line class="wp-xl" x1="0" x2="0" y1="' + T +
             '" y2="' + (T + ph) + '"/><circle class="wp-xd" cx="0" cy="0" r="4"/></g>');
    out.push('</svg>');
    return { html: out.join(''), X: X, Y: Y, L: L, pw: pw };
  }

  /* One section: fetch, draw, keep it current. */
  function boot(sec) {
    if (!sec || sec._gswp) return;
    sec._gswp = true;
    var league = sec.getAttribute('data-league'), gid = sec.getAttribute('data-id');
    var ko = Date.parse(sec.getAttribute('data-ko') || '');
    var tk = sec.getAttribute('data-tk') === '1';
    var built = sec.getAttribute('data-state') || 'pre';
    var names = { home: sec.getAttribute('data-home') || '', away: sec.getAttribute('data-away') || '' };
    var el = { big: sec.querySelector('.pv-lwp-big'), lab: sec.querySelector('.pv-lwp-lab'),
               at: sec.querySelector('.pv-lwp-at'), play: sec.querySelector('.pv-lwp-play'),
               chart: sec.querySelector('.pv-lwp-chart') };
    var data = null, drawn = null, timer = null, busy = false, done = false, pick = -1, width = 0;

    function due() { return built !== 'pre' || (tk && isFinite(ko) && Date.now() >= ko - 60e3); }
    function wait(ms) { clearTimeout(timer); timer = setTimeout(poll, ms); }
    function nm(side) { return names[side] || (data && data[side].abbr) || side; }
    function score(h, a) {
      return h == null || a == null ? '' : nm('away') + ' ' + a + ', ' + nm('home') + ' ' + h;
    }
    function lead(p) { return p >= 0.5 ? nm('home') + ' ' + pct(p) : nm('away') + ' ' + pct(1 - p); }
    function text(node, s) { if (node) node.textContent = s; }

    function poll() {
      if (busy || done) return;
      clearTimeout(timer); timer = null;
      if (document.hidden) return;                     // visibilitychange calls again
      busy = true;
      fetch(BASE + league + '/summary?event=' + encodeURIComponent(gid))
        .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .then(function (d) { busy = false; take(series(d)); })
        .catch(function () {
          busy = false;
          if (!data) {
            text(el.at, 'ESPN\u2019s win probability could not be loaded just now.');
          }
          wait(RETRY);
        });
    }

    function take(s) {
      data = s;
      if ((s.state === 'post' && !s.pts.length) || /POSTPONED|CANCEL/.test(s.name)) {
        // called off, put off, or never charted
        sec.hidden = true; done = true; return;
      }
      sec.hidden = false;
      head(s);
      draw();
      if (s.state === 'in') wait(EVERY);
      else if (s.state === 'pre') { if (!isFinite(ko) || Date.now() < ko + WAIT) wait(EVERY); }
      else done = true;
    }

    // The score in the page's header, which was drawn when the page was built.
    function head(s) {
      if (s.state === 'pre' || s.home.score == null || s.away.score == null) return;
      var mid = document.querySelector('.pv-head .pv-mid');
      if (!mid) return;
      if (!mid.classList.contains('pv-score')) {
        mid.className = 'pv-mid pv-score';
        mid.innerHTML = '<b></b><span>\u2013</span><b></b><small></small>';
      }
      var b = mid.querySelectorAll('b'), sm = mid.querySelector('small');
      if (b.length < 2 || !sm) return;
      b[0].textContent = s.away.score;
      b[1].textContent = s.home.score;
      sm.textContent = s.detail || (s.state === 'post' ? 'Final' : 'Live');
      sm.className = s.state === 'in' ? 'pv-live' : '';
    }

    // The resting readout: where the game is and the last play while it is
    // on; once it is over, how close the winner came to losing it.
    function rest() {
      var s = data, pts = s.pts, e = pts[pts.length - 1];
      if (s.state === 'pre') {
        text(el.at, 'Waiting for kickoff');
        text(el.play, '');
        return;
      }
      var sc = score(s.home.score, s.away.score);
      if (s.state === 'in') {
        text(el.at, [s.detail, sc].filter(Boolean).join(' \u00b7 '));
        text(el.play, e && e.text ? 'Last play: ' + e.text : '');
        return;
      }
      text(el.at, [s.detail || 'Final', sc].filter(Boolean).join(' \u00b7 '));
      var h = s.home.score, a = s.away.score;
      if (h == null || a == null || h === a || !pts.length) { text(el.play, ''); return; }
      var homeWon = h > a, low = null;
      pts.forEach(function (q) {
        var w = homeWon ? q.p : 1 - q.p;
        if (low === null || w < low.w) low = { w: w, q: q };
      });
      var who = nm(homeWon ? 'home' : 'away');
      var when = low.q.per ? ' (' + perName(low.q.per) + (low.q.clk ? ' ' + low.q.clk : '') + ')' : '';
      text(el.play, low.w < 0.5
        ? who + ' won after its chance fell to ' + pct(low.w) + when + '.'
        : who + '\u2019s chance never fell below ' + pct(low.w) + '.');
    }

    function draw() {
      if (!data || !el.chart) return;
      var s = data, pts = s.pts, e = pts[pts.length - 1];
      if (s.state === 'in' && e) {
        text(el.big, lead(e.p));
        text(el.lab, 'to win \u00b7 ESPN live');
      } else if (s.state === 'post') {
        var h = s.home.score, a = s.away.score;
        text(el.big, h == null || a == null ? 'Final' : h === a ? 'Tie'
          : nm(h > a ? 'home' : 'away') + ' won');
        text(el.lab, 'ESPN win probability');
      } else {
        text(el.big, s.state === 'in' ? 'Kickoff' : 'Not started');
        text(el.lab, 'ESPN live, from the first play');
      }
      width = el.chart.clientWidth || 320;
      var label = 'ESPN win probability for ' + nm('home') + ' over the game' +
        (pts.length ? ': ' + pct(pts[0].p) + ' at kickoff, ' + pct(e.p) +
         (s.state === 'in' ? ' now' : ' at the end') : '');
      drawn = svg(s, width, el.chart.clientHeight || HEIGHT,
                  { id: gid, home: nm('home'), away: nm('away'), live: s.state === 'in',
                    label: label });
      el.chart.innerHTML = drawn.html;
      if (pick >= pts.length) pick = -1;
      show(pick);
    }

    // The crosshair on play i, or the resting readout for -1.
    function show(i) {
      pick = i;
      var g = el.chart.querySelector('.wp-x');
      if (!data || i < 0 || !data.pts[i]) {
        if (g) g.style.display = 'none';
        if (data) rest();
        return;
      }
      var q = data.pts[i], x = drawn.X(q.x), y = drawn.Y(q.p);
      if (g) {
        g.style.display = '';
        g.querySelector('.wp-xl').setAttribute('x1', x);
        g.querySelector('.wp-xl').setAttribute('x2', x);
        var dot = g.querySelector('.wp-xd');
        dot.setAttribute('cx', x);
        dot.setAttribute('cy', y);
        dot.setAttribute('class', 'wp-xd ' + (q.p >= 0.5 ? 'wp-dot-h' : 'wp-dot-a'));
      }
      var when = q.per ? perName(q.per) + (q.clk ? ' ' + q.clk : '') : '';
      text(el.at, [when, score(q.hs, q.as), lead(q.p)].filter(Boolean).join(' \u00b7 '));
      text(el.play, q.text || '');
    }
    function nearest(clientX) {
      if (!data || !data.pts.length || !drawn) return -1;
      var box = el.chart.getBoundingClientRect();
      var px = clientX - box.left, best = -1, gap = Infinity;
      data.pts.forEach(function (q, i) {
        var d = Math.abs(drawn.X(q.x) - px);
        if (d <= gap) { gap = d; best = i; }     // ties go to the later play
      });
      return best;
    }
    if (el.chart) {
      el.chart.addEventListener('pointermove', function (ev) {
        if (ev.pointerType === 'mouse' || ev.buttons || ev.pointerType === 'pen') show(nearest(ev.clientX));
      });
      el.chart.addEventListener('pointerdown', function (ev) { show(nearest(ev.clientX)); });
      el.chart.addEventListener('pointerleave', function (ev) {
        if (ev.pointerType === 'mouse') show(-1);
      });
      el.chart.addEventListener('keydown', function (ev) {
        if (!data || !data.pts.length) return;
        var n = data.pts.length, i = pick < 0 ? n - 1 : pick;
        if (ev.key === 'ArrowLeft') i = Math.max(0, i - 1);
        else if (ev.key === 'ArrowRight') i = Math.min(n - 1, i + 1);
        else if (ev.key === 'Home') i = 0;
        else if (ev.key === 'End') i = n - 1;
        else if (ev.key === 'Escape') i = -1;
        else return;
        ev.preventDefault();
        show(i);
      });
      el.chart.addEventListener('focusout', function () { show(-1); });
    }
    var frame = 0;
    window.addEventListener('resize', function () {
      if (frame || !data) return;
      frame = requestAnimationFrame(function () {
        frame = 0;
        if (el.chart && el.chart.clientWidth !== width) draw();
      });
    });
    // Back to the tab: read at once (poll() refuses while a read is out).
    document.addEventListener('visibilitychange', function () {
      if (document.hidden || done || !(data || due())) return;
      sec.hidden = false;
      poll();
    });

    if (due()) { sec.hidden = false; poll(); return; }
    // Not yet: open at kickoff if that is today and the page is still here.
    if (tk && isFinite(ko) && ko - Date.now() < 12 * 3600e3) {
      setTimeout(function () { if (!data) { sec.hidden = false; poll(); } }, ko - Date.now() + 15e3);
    }
  }

  function start() {
    var all = document.querySelectorAll('[data-gs-wp]');
    for (var i = 0; i < all.length; i++) boot(all[i]);
  }

  window.GSWinProb = { series: series, svg: svg, pct: pct, boot: boot, clockSec: clockSec };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
