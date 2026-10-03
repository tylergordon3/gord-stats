/*
 * "How this works" (gordstats.how): the explanation behind a .gs-how link,
 * shown in a dialog over the page instead of on it.
 *
 * Each explanation is a page of its own at /how/<topic>/. The link goes
 * there, and without this script that is all it does. With it, a plain tap
 * fetches that page once, takes its <article class="how-article"> and shows
 * it in a <dialog>: centered on a desktop, a sheet from the bottom on a phone
 * (custom.css, HOW THIS WORKS). Esc, the close button, a tap on the dimmed
 * page and Android's back gesture close it; focus goes back to the link. The
 * address never changes, and the page behind neither moves nor scrolls.
 *
 * A tap with a modifier key (new tab, new window) is left to the browser, and
 * so is everything on a browser with no <dialog>.
 */
(function () {
  'use strict';
  if (window.GSHow) return;

  var cache = {};          // page URL -> Promise of the parsed <article>
  var dlg = null;
  var opener = null;
  var openUrl = null;

  function supported() {
    return typeof window.HTMLDialogElement === 'function' &&
      typeof document.createElement('dialog').showModal === 'function' &&
      typeof window.fetch === 'function' && typeof window.DOMParser === 'function';
  }

  // The explainer's article, fetched and parsed once per page view. A failed
  // fetch is forgotten, so the next tap tries again.
  function load(url) {
    if (!cache[url]) {
      cache[url] = fetch(url, { credentials: 'same-origin' }).then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.text();
      }).then(function (text) {
        var doc = new DOMParser().parseFromString(text, 'text/html');
        var art = doc.querySelector('article.how-article');
        if (!art) throw new Error('no explanation on ' + url);
        Array.prototype.forEach.call(art.querySelectorAll('script'), function (s) { s.remove(); });
        return art;
      });
      cache[url].catch(function () { delete cache[url]; });
    }
    return cache[url];
  }

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  function build() {
    dlg = el('dialog', 'gs-how-dlg');
    dlg.setAttribute('aria-labelledby', 'gs-how-title');
    var sheet = el('div', 'gs-how-sheet');
    var head = el('div', 'gs-how-head');
    var title = el('h2', 'gs-how-title', 'How this works');
    title.id = 'gs-how-title';
    var x = el('button', 'gs-how-x');
    x.type = 'button';
    x.setAttribute('aria-label', 'Close');
    x.innerHTML = '<span aria-hidden="true">&times;</span>';
    head.appendChild(title);
    head.appendChild(x);
    var body = el('div', 'gs-how-body');
    body.tabIndex = -1;
    var foot = el('div', 'gs-how-foot');
    var page = el('a', 'gs-how-page', 'Open as a page');
    var all = el('a', 'gs-how-all', 'All explainers');
    all.href = '/how/';
    foot.appendChild(page);
    foot.appendChild(all);
    sheet.appendChild(head);
    sheet.appendChild(body);
    sheet.appendChild(foot);
    dlg.appendChild(sheet);
    document.body.appendChild(dlg);

    x.addEventListener('click', function () { dlg.close(); });
    // The dialog box is the sheet's frame: a click that lands on the dialog
    // itself, not inside the sheet, landed on the dimmed page around it.
    dlg.addEventListener('click', function (e) { if (e.target === dlg) dlg.close(); });
    // A modal <dialog> keeps focus off the page, but Tab past its last link
    // would go on to the browser's own controls: it wraps instead.
    dlg.addEventListener('keydown', function (e) {
      if (e.key !== 'Tab') return;
      var f = Array.prototype.filter.call(
        dlg.querySelectorAll('a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])'),
        function (n) { return n.offsetParent !== null || n === document.activeElement; });
      if (!f.length) return;
      var first = f[0], last = f[f.length - 1];
      if (e.shiftKey && (document.activeElement === first || !dlg.contains(document.activeElement))) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    });
    dlg.addEventListener('close', function () {
      unlock();
      openUrl = null;
      var back = opener;
      opener = null;
      if (back && document.contains(back)) {
        try { back.focus({ preventScroll: true }); } catch (err) { back.focus(); }
      }
    });
  }

  // Scrolling the page behind is locked while the dialog is open. Where the
  // page has a classic scrollbar, its gutter is kept so nothing reflows.
  function lock() {
    var root = document.documentElement;
    var bar = window.innerWidth - root.clientWidth;
    root.classList.add('gs-how-lock');
    if (bar > 0) {
      if (window.CSS && CSS.supports && CSS.supports('scrollbar-gutter', 'stable')) {
        root.style.scrollbarGutter = 'stable';
      } else {
        document.body.style.paddingRight = bar + 'px';
      }
      root.setAttribute('data-gs-how-bar', '1');
    }
  }

  function unlock() {
    var root = document.documentElement;
    root.classList.remove('gs-how-lock');
    if (root.hasAttribute('data-gs-how-bar')) {
      root.style.scrollbarGutter = '';
      document.body.style.paddingRight = '';
      root.removeAttribute('data-gs-how-bar');
    }
  }

  function fill(url, art) {
    if (!dlg || openUrl !== url) return;     // closed, or another one opened
    var body = dlg.querySelector('.gs-how-body');
    body.textContent = '';
    var copy = document.importNode(art, true);
    body.appendChild(copy);
    var t = art.getAttribute('data-title');
    if (t) dlg.querySelector('.gs-how-title').textContent = t;
    body.scrollTop = 0;
  }

  function fail(url) {
    if (!dlg || openUrl !== url) return;
    var body = dlg.querySelector('.gs-how-body');
    body.textContent = '';
    var p = el('p', 'gs-how-msg', 'This explanation did not load. ');
    var a = el('a', null, 'Open it as a page');
    a.href = url;
    p.appendChild(a);
    body.appendChild(p);
  }

  function open(link) {
    if (!dlg) build();
    var url = link.getAttribute('href');
    // A link inside the dialog (a related explainer) swaps what it shows;
    // focus still goes back to the link on the page when it closes.
    if (!dlg.open) opener = link;
    openUrl = url;
    var title = dlg.querySelector('.gs-how-title');
    title.textContent = link.getAttribute('data-how-title') || 'How this works';
    var body = dlg.querySelector('.gs-how-body');
    body.textContent = '';
    body.appendChild(el('p', 'gs-how-msg', 'Loading…'));
    dlg.querySelector('.gs-how-page').href = url;
    if (!dlg.open) {
      lock();
      dlg.showModal();
    }
    dlg.querySelector('.gs-how-x').focus({ preventScroll: true });
    load(url).then(function (art) { fill(url, art); }, function () { fail(url); });
  }

  function linkOf(target) {
    return target && target.closest ? target.closest('a.gs-how[data-how]') : null;
  }

  if (!supported()) {
    window.GSHow = { open: function () {}, load: function () {} };
    return;
  }

  document.addEventListener('click', function (e) {
    var a = linkOf(e.target);
    if (!a || e.defaultPrevented || e.button !== 0 ||
        e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    open(a);
  });

  // Fetch ahead on the first sign of intent, so the tap finds it loaded.
  function warm(e) {
    var a = linkOf(e.target);
    if (a) load(a.getAttribute('href')).catch(function () {});
  }
  document.addEventListener('pointerover', warm, { passive: true });
  document.addEventListener('focusin', warm);
  document.addEventListener('touchstart', warm, { passive: true });

  window.GSHow = { open: open, load: load };
})();
