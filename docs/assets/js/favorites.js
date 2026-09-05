/**
 * TEAM FAVOURITES
 * --------------------------------------------------
 * Stars a team, highlights its row on every table that carries it, and
 * optionally hides everything else.
 *
 * Rows are marked server-side by gordstats.favorites: `data-fav="cfb:333"` on
 * the <tr>, and a `.fav-star` button in the team cell carrying the same key in
 * `data-fav-for`. Nothing here creates markup that wasn't rendered, so a page
 * that hasn't opted in is untouched and a reader with JS off sees the table
 * exactly as it was.
 *
 * Two rules the rest of the file follows from:
 *
 *   Never reorder. These tables are ranked, and lifting a starred team out of
 *   rank order costs the reader the one thing a ranking is for. Starring tints
 *   the row and leaves it where it is; the filter is how you get a short list.
 *
 *   Never assume storage works. Private windows, cleared site data and
 *   browsers set to block it all throw on access rather than returning null,
 *   and a page that can't remember a star must still render and still sort.
 */
(function () {
  "use strict";

  var KEY = "gs:favorites";
  var FILTER_KEY = "gs:favorites:filter";

  /* ---------- storage ---------- */

  function read() {
    try {
      var raw = window.localStorage.getItem(KEY);
      if (!raw) return [];
      var list = JSON.parse(raw);
      // Anything but a list of strings is a key written by an older or broken
      // build; drop it rather than letting it poison every comparison below.
      return Array.isArray(list) ? list.filter(function (k) {
        return typeof k === "string" && k;
      }) : [];
    } catch (e) {
      return [];
    }
  }

  function write(list) {
    try {
      window.localStorage.setItem(KEY, JSON.stringify(list));
    } catch (e) {
      /* Storage full or blocked. The stars still work for this page view. */
    }
  }

  function readFilter() {
    try {
      return window.localStorage.getItem(FILTER_KEY) === "1";
    } catch (e) {
      return false;
    }
  }

  function writeFilter(on) {
    try {
      window.localStorage.setItem(FILTER_KEY, on ? "1" : "0");
    } catch (e) {}
  }

  /* ---------- state ---------- */

  var favorites = read();
  var filtering = readFilter();

  function has(key) {
    return favorites.indexOf(key) !== -1;
  }

  function toggle(key) {
    var i = favorites.indexOf(key);
    if (i === -1) favorites.push(key);
    else favorites.splice(i, 1);
    write(favorites);
  }

  /* ---------- painting ---------- */

  // Stars on the page, and the keys they stand for. A key can appear more than
  // once (a team in two tables on one page), so every button for a key is
  // updated together rather than only the one that was clicked.
  function buttons() {
    return document.querySelectorAll(".fav-star[data-fav-for]");
  }

  // Any element, not just a row: the predictions page marks <article> game
  // cards and the team pages mark opponent rows, and all of them light up the
  // same way.
  function rows() {
    return document.querySelectorAll("[data-fav]");
  }

  // A game belongs to two teams, so data-fav holds one or more space-separated
  // keys and the element is a favourite if the reader has starred any of them.
  function marks(el) {
    return (el.getAttribute("data-fav") || "").split(/\s+/).filter(Boolean);
  }

  function hasAny(el) {
    var keys = marks(el);
    for (var i = 0; i < keys.length; i++) if (has(keys[i])) return true;
    return false;
  }

  // The filter is a stored, site-wide preference, but only pages that render a
  // control may act on it. Without this, turning it on once made every later
  // page hide rows with no visible way to undo it - and on the schedule page,
  // which runs filters of its own, two things would be hiding rows at once.
  function hiding() {
    return filtering && document.querySelector(".fav-controls") !== null;
  }

  function paint() {
    var i, el, on, glyph;

    var stars = buttons();
    for (i = 0; i < stars.length; i++) {
      el = stars[i];
      on = has(el.getAttribute("data-fav-for"));
      el.setAttribute("aria-pressed", on ? "true" : "false");
      el.classList.toggle("is-on", on);
      // The glyph carries the state for anyone reading the page in high
      // contrast, where a tint alone is invisible.
      glyph = el.querySelector("span");
      if (glyph) glyph.textContent = on ? "\u2605" : "\u2606";
    }

    var list = rows();
    for (i = 0; i < list.length; i++) {
      el = list[i];
      on = hasAny(el);
      el.classList.toggle("is-fav", on);
      // `hidden` rather than display:none so a row hidden by the filter is
      // hidden from assistive tech too, and so the page's own sort - which
      // moves rows around without knowing about any of this - can't leave a
      // hidden row looking visible.
      el.hidden = hiding() && !on;
    }

    paintControls();
  }

  function paintControls() {
    var boxes = document.querySelectorAll(".fav-controls");
    var count = 0;
    var list = rows();
    var seen = {};

    // Count teams, not elements: one team in two tables, or on both sides of a
    // game, is one favourite.
    for (var i = 0; i < list.length; i++) {
      var keys = marks(list[i]);
      for (var k = 0; k < keys.length; k++) {
        if (has(keys[k]) && !seen[keys[k]]) {
          seen[keys[k]] = true;
          count++;
        }
      }
    }

    for (var j = 0; j < boxes.length; j++) {
      var box = boxes[j];

      // The bar itself always shows. Which half of it shows depends on whether
      // there is anything to filter: the hint teaches the feature, the filter
      // uses it, and neither is any use in the other's state.
      var hint = box.querySelector(".fav-hint");
      if (hint) hint.hidden = count > 0;

      var btn = box.querySelector(".fav-filter");
      if (btn) {
        btn.hidden = count === 0;
        btn.setAttribute("aria-pressed", filtering ? "true" : "false");
        btn.classList.toggle("is-on", filtering);
      }

      var label = box.querySelector(".fav-count");
      if (label) {
        label.textContent = count === 0
          ? "" : (count === 1 ? "1 team" : count + " teams");
      }
    }
  }

  /* ---------- events ---------- */

  // Delegated from the document: the CFB power table rebuilds its own rows on
  // a tab change, and a listener bound to a button that gets replaced stops
  // firing. One listener on the document outlives all of it.
  document.addEventListener("click", function (ev) {
    var star = ev.target.closest && ev.target.closest(".fav-star[data-fav-for]");
    if (star) {
      ev.preventDefault();
      toggle(star.getAttribute("data-fav-for"));
      paint();
      return;
    }

    var filter = ev.target.closest && ev.target.closest(".fav-filter");
    if (filter) {
      ev.preventDefault();
      filtering = !filtering;
      writeFilter(filtering);
      paint();
    }
  });

  // A star set in another tab should show up here without a reload. Only fires
  // for other documents, so this can't loop with our own writes.
  window.addEventListener("storage", function (ev) {
    if (ev.key === KEY) {
      favorites = read();
      paint();
    } else if (ev.key === FILTER_KEY) {
      filtering = readFilter();
      paint();
    }
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", paint);
  } else {
    paint();
  }
})();
