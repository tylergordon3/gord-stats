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
    var done = document.createElement("p");
    done.className = "countdown-done";
    done.textContent = msg;
    units.replaceWith(done);
    var note = card.querySelector(".countdown-note");
    if (note) note.remove();
    card.removeAttribute("data-countdown");      // done; stop looking at it
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

  function start() {
    if (!tick()) return;                         // nothing on this page
    var timer = setInterval(function () {
      if (!tick()) clearInterval(timer);
    }, 1000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
