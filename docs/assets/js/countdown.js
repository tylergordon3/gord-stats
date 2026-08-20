/**
 * COUNTDOWN CLOCKS
 *
 * Drives every [data-countdown] card on the page — the homepage now carries
 * two, one in each preview box, which the previous per-card scripts could not
 * have done: each hardcoded id="days" and its own setInterval.
 *
 * The target is read as local time (an ISO string with no zone), so the draft
 * reads 8:00 PM whether you are in Denver or Boston. One interval drives all
 * the cards, and it stops itself once they have all expired.
 *
 * window.Countdown.retarget(card, iso, title) points a card at a new time. The
 * live draft board uses it: its clock comes from Sleeper rather than from
 * _data/countdowns.yml, so the date can move under a page that is already open.
 * Expiry is therefore reversible — a card that ran out hides its units instead
 * of destroying them — and retarget restarts the interval if it had stopped.
 */
(function () {
  "use strict";

  function pad(n) {
    return n < 10 ? "0" + n : "" + n;
  }

  function expire(card) {
    var msg = card.getAttribute("data-expired") || "It's here.";
    var units = card.querySelector(".countdown-units");
    if (!units) return;
    // Hidden rather than replaced, and the message appended rather than swapped
    // in: a target that moves (see retarget) has to be able to put the clock
    // back, which it could not do if the units markup had been destroyed.
    var done = card.querySelector(".countdown-done");
    if (!done) {
      done = document.createElement("p");
      done.className = "countdown-done";
      units.insertAdjacentElement("afterend", done);
    }
    done.textContent = msg;
    done.style.display = "";
    units.style.display = "none";
    var note = card.querySelector(".countdown-note");
    if (note) note.style.display = "none";
    card.removeAttribute("data-countdown");      // done; stop looking at it
  }

  function revive(card) {
    var units = card.querySelector(".countdown-units");
    if (units) units.style.display = "";
    var done = card.querySelector(".countdown-done");
    if (done) done.style.display = "none";
    var note = card.querySelector(".countdown-note");
    if (note) note.style.display = "";
  }

  /** Point a card at a new time (and optionally relabel it), then run it. */
  function retarget(card, target, title) {
    if (!card || !target) return;
    if (card.getAttribute("data-target") === target && card.hasAttribute("data-countdown")) {
      return;                                    // already counting to this
    }
    card.setAttribute("data-target", target);
    if (title) {
      var label = card.querySelector(".countdown-title");
      if (label) label.textContent = title;
    }
    if (new Date(target).getTime() > Date.now()) {
      revive(card);
      card.setAttribute("data-countdown", "");
    }
    start();
  }

  function tick() {
    var cards = document.querySelectorAll("[data-countdown]");
    if (!cards.length) return false;

    cards.forEach(function (card) {
      var target = new Date(card.getAttribute("data-target")).getTime();
      if (isNaN(target)) {                       // malformed date: leave the dashes
        card.removeAttribute("data-countdown");
        return;
      }
      var left = target - Date.now();
      if (left <= 0) {
        expire(card);
        return;
      }
      var s = Math.floor(left / 1000);
      var parts = {
        d: String(Math.floor(s / 86400)),
        h: pad(Math.floor(s / 3600) % 24),
        m: pad(Math.floor(s / 60) % 60),
        s: pad(s % 60),
      };
      card.querySelectorAll("[data-unit]").forEach(function (el) {
        var v = parts[el.getAttribute("data-unit")];
        if (v !== undefined && el.textContent !== v) el.textContent = v;
      });
    });
    return true;
  }

  // Held at module scope so start() can tell a live interval from a stopped one:
  // retarget calls it again, and two intervals on the same cards would double
  // the work for no visible difference.
  var timer = null;

  function start() {
    if (timer) return;
    if (!tick()) return;                         // nothing on this page
    timer = setInterval(function () {
      if (!tick()) {
        clearInterval(timer);
        timer = null;
      }
    }, 1000);
  }

  window.Countdown = { start: start, retarget: retarget };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
