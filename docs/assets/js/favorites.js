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

  // What /api/me last said. `configured` false means this deploy has no
  // accounts wired at all, and the page must look exactly as it did before
  // any of this existed - no sign-in control, no network chatter.
  var account = { signedIn: false, configured: false };
  var SYNC_KEY = "gs:favorites:sync";

  function readSyncedAs() {
    try {
      return window.localStorage.getItem(SYNC_KEY) || "";
    } catch (e) {
      return "";
    }
  }

  function writeSyncedAs(who) {
    try {
      window.localStorage.setItem(SYNC_KEY, who);
    } catch (e) {}
  }

  function has(key) {
    return favorites.indexOf(key) !== -1;
  }

  function toggle(key) {
    var i = favorites.indexOf(key);
    if (i === -1) favorites.push(key);
    else favorites.splice(i, 1);
    write(favorites);
    push();
  }

  /* ---------- sync ---------- */

  var pushTimer = null;

  // Starring five teams in five seconds is one write, not five. The local list
  // is already saved and already painted by the time this fires, so a slow or
  // failed push costs the reader nothing on this device.
  function push() {
    if (!account.signedIn) return;
    if (pushTimer) clearTimeout(pushTimer);
    pushTimer = setTimeout(function () {
      pushTimer = null;
      fetch("/api/favorites", {
        method: "PUT",
        credentials: "same-origin",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ favorites: favorites }),
      }).catch(function () {
        /* Offline or signed out elsewhere; the browser copy still stands. */
      });
    }, 600);
  }

  function union(a, b) {
    var out = a.slice();
    for (var i = 0; i < b.length; i++) if (out.indexOf(b[i]) === -1) out.push(b[i]);
    return out;
  }

  function sync() {
    fetch("/api/me", { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (me) {
        account = me || account;
        if (!account.configured || !account.signedIn) return null;
        return fetch("/api/favorites", { credentials: "same-origin" })
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (data) {
            if (!data) return;
            var remote = data.favorites || [];
            // First sign-in on this device: the reader has stars here and
            // stars on the account, and losing either would be indefensible,
            // so they are merged once. After that the server is the truth -
            // otherwise un-starring on one device could never stick, because
            // the next load would merge the team straight back in.
            if (readSyncedAs() !== account.email) {
              favorites = union(favorites, remote);
              write(favorites);
              writeSyncedAs(account.email);
              push();
            } else {
              favorites = remote;
              write(favorites);
            }
          });
      })
      .catch(function () {
        /* No network, or accounts not deployed. Local favourites are enough. */
      })
      .then(paint, paint);
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

      paintAccount(box.querySelector(".fav-account"));
    }
  }

  // The sign-in control exists only where accounts are actually deployed, and
  // says what signing in is for rather than just "Sign in" - the reason is the
  // whole feature, and it is not obvious from a bare verb.
  function paintAccount(slot) {
    if (!slot) return;
    if (!account.configured) {
      slot.hidden = true;
      return;
    }
    slot.hidden = false;
    var next = encodeURIComponent(location.pathname + location.search);
    if (account.signedIn) {
      slot.innerHTML = "";
      var who = document.createElement("span");
      who.className = "fav-who";
      who.textContent = "Synced";
      who.title = account.email + " \u00b7 favourites follow you between devices";
      var out = document.createElement("a");
      out.className = "fav-auth";
      out.href = "/api/auth/logout?next=" + next;
      out.textContent = "Sign out";
      slot.appendChild(who);
      slot.appendChild(out);
    } else {
      slot.innerHTML = "";
      var link = document.createElement("a");
      link.className = "fav-auth";
      link.href = "/api/auth/login?next=" + next;
      link.textContent = "Sign in to sync";
      slot.appendChild(link);
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

  function boot() {
    // Paint from the browser copy first, then reconcile. The stars a reader
    // already has must never wait on a network round trip.
    paint();
    sync();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
