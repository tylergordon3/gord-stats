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
    // Anything drawn from the stars (the home page's "My teams" card) redraws:
    // a star set elsewhere on the page, or a list the account sync brought in.
    try { document.dispatchEvent(new CustomEvent("gs:favorites")); } catch (e) { /* old browser */ }
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
  // Whether /api/me has answered. Until it has, the invite the page drew is
  // left alone: removing it on the first paint (account still unknown) and
  // putting it back a moment later was the layout shift it was drawn to avoid.
  var known = false;
  var ACCT_KEY = "gs:acct";
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
    changed();
  }

  /* ---------- sync ---------- */

  // "This browser has a change the account has not confirmed." Set on every
  // local edit, cleared only by a PUT that came back 2xx. Without it the push
  // was fire-and-forget and the next page load took the server's list as the
  // truth - so a star set in the 600ms before navigating away, or before the
  // account lookup answered, or refused by the server, silently came undone.
  var DIRTY_KEY = "gs:favorites:dirty";

  function isDirty() {
    try {
      return window.localStorage.getItem(DIRTY_KEY) === "1";
    } catch (e) {
      return false;
    }
  }

  function setDirty(on) {
    try {
      if (on) window.localStorage.setItem(DIRTY_KEY, "1");
      else window.localStorage.removeItem(DIRTY_KEY);
    } catch (e) {}
  }

  function changed() {
    setDirty(true);
    push();
  }

  var pushTimer = null;

  // A refused save waits as long as the server asks. A 429 is this account's
  // day of changes spent, a 503 with site_limit the whole site's; both say
  // when to come back in Retry-After (UTC midnight), and asking every 15
  // seconds meanwhile only spent the server's reads on a known "no". Anything
  // else that failed without saying (a 500, a 503 from a sick deploy) backs
  // off from 15 seconds, doubling. Either way never past RETRY_MAX, so a tab
  // left open across midnight still saves within the hour. The time is kept
  // in storage: the next page has the same unsaved change, and would
  // otherwise spend a request learning the same answer.
  var RETRY_KEY = "gs:favorites:retry";
  var RETRY_MIN = 15000;
  var RETRY_MAX = 3600000;
  var failures = 0;

  function retryAt() {
    try {
      var at = Number(window.localStorage.getItem(RETRY_KEY)) || 0;
      // Clamped, so a value from a clock that has since been corrected (or a
      // broken write) can never hold saves off for longer than the cap.
      return Math.min(at, Date.now() + RETRY_MAX);
    } catch (e) {
      return 0;
    }
  }

  function setRetryAt(at) {
    try {
      if (at) window.localStorage.setItem(RETRY_KEY, String(at));
      else window.localStorage.removeItem(RETRY_KEY);
    } catch (e) {}
  }

  // Milliseconds to wait after the refusal `r`: its Retry-After (seconds or
  // an HTTP date) if it sent one, the doubling back-off if not.
  function backoff(r) {
    var said = r.headers && r.headers.get ? r.headers.get("retry-after") : null;
    var ms = NaN;
    if (said) {
      said = String(said).trim();
      ms = /^\d+$/.test(said) ? Number(said) * 1000 : Date.parse(said) - Date.now();
    }
    failures++;
    if (!(ms >= 0)) ms = RETRY_MIN * Math.pow(2, Math.min(failures - 1, 10));
    return Math.min(RETRY_MAX, Math.max(RETRY_MIN, ms));
  }

  function send(keepalive) {
    // The list is sent as it stands when the request goes, and the flag is only
    // cleared if nothing changed while it was in flight.
    var sent = favorites.slice();
    return fetch("/api/favorites", {
      method: "PUT",
      credentials: "same-origin",
      keepalive: !!keepalive,
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ favorites: sent }),
    }).then(function (r) {
      if (r.ok) {
        failures = 0;
        setRetryAt(0);
        if (JSON.stringify(sent) === JSON.stringify(favorites)) setDirty(false);
      } else if (r.status !== 401) {                 // throttled, full or down
        var wait = backoff(r);
        setRetryAt(Date.now() + wait);
        later(wait);
      }
    }).catch(function () {
      /* Offline; the flag stays set and the next load sends it. */
    });
  }

  function later(ms) {
    if (pushTimer) clearTimeout(pushTimer);
    pushTimer = setTimeout(function () {
      pushTimer = null;
      send(false);
    }, ms);
  }

  // Starring five teams in five seconds is one write, not five. The local list
  // is already saved and already painted by the time this fires, so a slow or
  // failed push costs the reader nothing on this device. Inside a refusal's
  // wait, a new star waits with it.
  function push() {
    if (!account.signedIn) return;
    later(Math.max(600, retryAt() - Date.now()));
  }

  // Leaving inside the debounce: send now, with keepalive so the request
  // outlives the page - unless the server has asked for quiet, when the
  // change stays marked unsaved and a later page sends it.
  window.addEventListener("pagehide", function () {
    if (!pushTimer) return;
    clearTimeout(pushTimer);
    pushTimer = null;
    if (retryAt() > Date.now()) return;
    send(true);
  });

  function union(a, b) {
    var out = a.slice();
    for (var i = 0; i < b.length; i++) if (out.indexOf(b[i]) === -1) out.push(b[i]);
    return out;
  }

  function sync() {
    fetch("/api/me", { credentials: "same-origin" })
      // No API at this address (a local build, a pages.dev deployment) is an
      // answer too: no accounts here.
      .then(function (r) { return r.ok === false ? { configured: false, signedIn: false } : r.json(); })
      .then(function (me) {
        account = me || account;
        known = true;
        // For the layout's inline check on the next page: drop the invite
        // before it paints for a reader it is not for.
        try {
          window.localStorage.setItem(ACCT_KEY, !account.configured ? "off"
            : (account.signedIn ? "in" : "out"));
        } catch (e) {}
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
              changed();
            } else if (isDirty()) {
              // A change from this browser the server never confirmed: it is
              // newer than the server's copy, so it is sent, not overwritten.
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
    paintAccount();
    paintInvite();
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

  // The account control lives in the site header, top right, on every page -
  // not in the favourites bar, which only exists on three of them. Signed out
  // it says what signing in is for rather than a bare "Sign in", because the
  // reason is the whole feature and is not obvious from the verb.
  function paintAccount() {
    var slot = document.querySelector(".site-account");
    if (!slot) return;

    if (!account.configured) {
      slot.hidden = true;
      slot.textContent = "";
      return;
    }
    slot.hidden = false;
    var next = encodeURIComponent(location.pathname + location.search);

    if (!account.signedIn) {
      slot.innerHTML = "";
      var link = document.createElement("a");
      link.className = "acct-link";
      link.href = "/api/auth/login?next=" + next;
      link.textContent = "Sign in";
      link.title = "Sync your starred teams and leagues across devices";
      slot.appendChild(link);

      var prof = document.createElement("a");
      prof.className = "acct-link";
      prof.href = "/profile/";
      prof.textContent = "Profile";
      prof.title = "Your leagues and followed teams";
      slot.appendChild(prof);
      return;
    }

    // Signed in: an initial, and a menu behind it. <details> rather than a
    // hand-rolled dropdown so it opens on a keyboard and on a phone without
    // any of this file knowing what a tap is.
    slot.innerHTML = "";
    var wrap = document.createElement("details");
    wrap.className = "acct";

    var summary = document.createElement("summary");
    summary.className = "acct-badge";
    summary.setAttribute("aria-label", "Account: " + account.email);
    summary.title = account.email;
    summary.textContent = (account.email || "?").charAt(0).toUpperCase();
    wrap.appendChild(summary);

    var menu = document.createElement("div");
    menu.className = "acct-menu";

    var who = document.createElement("p");
    who.className = "acct-email";
    who.textContent = account.email;
    menu.appendChild(who);

    var synced = document.createElement("p");
    synced.className = "acct-note";
    synced.textContent = "Starred teams and leagues sync across your devices.";
    menu.appendChild(synced);

    var prof = document.createElement("a");
    prof.className = "acct-out";
    prof.href = "/profile/";
    prof.textContent = "Your profile";
    menu.appendChild(prof);

    var out = document.createElement("a");
    out.className = "acct-out";
    out.href = "/api/auth/logout?next=" + next;
    out.textContent = "Sign out";
    menu.appendChild(out);

    wrap.appendChild(menu);
    slot.appendChild(wrap);
  }

  // Signed out, nothing on the page says the site can hold anything for you.
  // The header's "Sign in" is a verb with no reason attached, and a reader who
  // has never seen the account control does not go looking for one. So one
  // line, once, at the top of the page, saying what signing in is for - and a
  // dismiss that sticks, because a banner that comes back is an advert.
  var INVITE_KEY = "gs:invite";

  function inviteDismissed() {
    try {
      return window.localStorage.getItem(INVITE_KEY) === "off";
    } catch (e) {
      return false;
    }
  }

  // The invite's dismiss button and its way back here, on whichever invite is
  // on the page - the one the layout drew, or one built below.
  function wireInvite(bar) {
    if (bar.getAttribute("data-wired")) return;
    bar.setAttribute("data-wired", "1");
    var go = bar.querySelector(".gs-invite-go");
    if (go) go.href = "/api/auth/login?next="
      + encodeURIComponent(location.pathname + location.search);
    var shut = bar.querySelector(".gs-invite-shut");
    if (shut) shut.addEventListener("click", function () {
      try {
        window.localStorage.setItem(INVITE_KEY, "off");
      } catch (e) {}
      bar.remove();
    });
  }

  function paintInvite() {
    var bar = document.getElementById("gs-invite");
    if (!known) {
      if (bar) wireInvite(bar);
      return;
    }
    var wanted = account.configured && !account.signedIn && !inviteDismissed()
      // The profile page makes this offer itself, in more room than a banner
      // has, and so does every fantasy page's league bar (#ml-bar, with a
      // Sign in button of its own). Two of them on one screen is one too many
      // - on a phone, 240px of sign-in before the table.
      && location.pathname.indexOf("/profile") !== 0
      && !document.getElementById("ml-bar");

    if (!wanted) {
      if (bar) bar.remove();
      return;
    }
    if (bar) {
      wireInvite(bar);
      return;
    }

    var host = document.getElementById("main_content");
    if (!host) return;

    bar = document.createElement("aside");
    bar.id = "gs-invite";
    bar.className = "gs-invite";

    var text = document.createElement("p");
    text.className = "gs-invite-text";
    text.textContent = "Follow teams and keep your fantasy leagues on every device.";
    bar.appendChild(text);

    var links = document.createElement("p");
    links.className = "gs-invite-links";

    var go = document.createElement("a");
    go.className = "gs-invite-go";
    go.href = "/api/auth/login?next="
      + encodeURIComponent(location.pathname + location.search);
    go.textContent = "Sign in";
    links.appendChild(go);

    var more = document.createElement("a");
    more.className = "gs-invite-more";
    more.href = "/profile/";
    more.textContent = "What you get";
    links.appendChild(more);

    bar.appendChild(links);

    var shut = document.createElement("button");
    shut.type = "button";
    shut.className = "gs-invite-shut";
    shut.setAttribute("aria-label", "Dismiss");
    shut.textContent = "\u00d7";
    bar.appendChild(shut);

    host.insertBefore(bar, host.firstChild);
    wireInvite(bar);
  }

  // A menu that only closes by clicking the badge again is a menu people leave
  // open. Anything outside it shuts it.
  document.addEventListener("click", function (ev) {
    var open = document.querySelector("details.acct[open]");
    if (open && !open.contains(ev.target)) open.removeAttribute("open");
  });

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

  // The one way in from outside this file. The profile page lists a reader's
  // starred teams and takes them off, and writing localStorage behind this
  // script's back would not survive: `favorites` is held in a variable here,
  // the storage event only fires for *other* documents, and the next push()
  // would put the stale list back. So there is one owner of the list and
  // everybody else asks it.
  window.GSFavorites = {
    list: function () { return favorites.slice(); },
    // Rows that arrive after boot - the schedule page fetches a week at a
    // time now - have never been painted, so their stars would sit empty
    // whatever the reader had starred.
    repaint: function () { paint(); },
    remove: function (key) {
      favorites = favorites.filter(function (k) { return k !== key; });
      write(favorites);
      paint();
      changed();
      return favorites.slice();
    },
  };

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
