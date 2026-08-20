/**
 * WIDE TABLES ON A PHONE
 *
 * Every wide table on the site already sits in its own scroll box
 * (.table-scroll, .table-container, .adp-wrap), so the page itself never pans
 * sideways. What was missing is any sign that the box scrolls: at 390px the
 * schedule grid runs 1263px past its right edge, the draft board 906px, and a
 * reader sees a table that looks merely cut off. Measured across the site, nine
 * pages had at least one table in that state.
 *
 * This marks each scroller with which edge it continues past, so the stylesheet
 * can fade that edge, and shows a one-time "swipe" hint on the widest ones. It
 * is all measurement — a box whose content fits is left alone, so nothing
 * appears on a desktop or beside a narrow table.
 */
(function () {
  "use strict";

  // Tables get the fade and, when there is a lot off screen, a worded hint.
  var TABLES = ".table-scroll, .table-container, .adp-wrap, .ld-wrap";
  // Control strips scroll too — the draft page's season and round switchers run
  // 276px past their box — but they only get the fade. A "swipe" label sitting
  // inside a row of buttons reads as another button.
  var STRIPS = ".view-switch, .section-nav";
  // Under this, the hint is noise: the reader can see most of the table and a
  // short nudge sideways reveals the rest.
  var HINT_MIN_OVERFLOW = 120;

  function edges(box) {
    var over = box.scrollWidth - box.clientWidth;
    box.classList.remove("scroll-start", "scroll-mid", "scroll-end");
    if (over <= 2) {
      box.classList.remove("is-scrollable");
      return;
    }
    box.classList.add("is-scrollable");
    var x = box.scrollLeft;
    box.classList.add(x <= 2 ? "scroll-start"
                    : x >= over - 2 ? "scroll-end"
                    : "scroll-mid");
  }

  function hint(box) {
    if (box.scrollWidth - box.clientWidth < HINT_MIN_OVERFLOW) return;
    // Once per page, on the first wide table the reader meets. The draft page
    // has six visible tables and the fantasy homepage five; the point is made
    // the first time, and after that a label per table is just clutter. The
    // fade still marks every one of them.
    if (document.querySelector(".scroll-hint")) return;
    var tag = document.createElement("span");
    tag.className = "scroll-hint";
    tag.setAttribute("aria-hidden", "true");     // the table itself is reachable
    tag.textContent = "Swipe for more →";
    // First child, not last: appended, it sat at the bottom of the box, and the
    // WNBA pickups table is 1400px tall — the reader met the table at the top
    // and never saw it. Sticky-left in the stylesheet keeps it in view while
    // the table scrolls under it.
    box.insertBefore(tag, box.firstChild);
    // The hint has done its job the moment the reader scrolls.
    box.addEventListener("scroll", function () {
      box.classList.add("scrolled-once");
    }, { once: true, passive: true });
  }

  /**
   * The pickups table freezes two columns: the row number and the player beside
   * it. The second one has to be offset by the exact width of the first, and
   * that width is whatever the browser's table layout decides — a hard-coded
   * 24px in the stylesheet rendered 33px and the name sat on top of the number.
   * Measured here and handed back as a custom property.
   */
  function pinOffset(box) {
    box.querySelectorAll("table.pickups-table").forEach(function (t) {
      var first = t.querySelector("thead th:first-child") ||
                  t.querySelector("tbody td:first-child");
      if (!first) return;
      var w = first.getBoundingClientRect().width;
      if (w) t.style.setProperty("--pin-2nd", Math.round(w) + "px");
    });
  }

  function wire(box, withHint) {
    if (!box.dataset.scrollWired) {
      box.dataset.scrollWired = "1";
      box.addEventListener("scroll", function () { edges(box); }, { passive: true });
    }
    pinOffset(box);                              // column widths move with the viewport
    edges(box);
    if (withHint) hint(box);
  }

  function sync() {
    document.querySelectorAll(TABLES).forEach(function (b) { wire(b, true); });
    document.querySelectorAll(STRIPS).forEach(function (b) { wire(b, false); });
  }

  document.addEventListener("DOMContentLoaded", sync);
  window.addEventListener("load", sync);         // fonts and images change widths
  window.addEventListener("resize", sync);

  // The ADP board and the season switchers rebuild their tables after load, and
  // <details> boxes measure zero until they are opened.
  document.addEventListener("click", function (e) {
    if (e.target.closest("details, .view-switch, .adp-controls, .archive-controls")) {
      setTimeout(sync, 0);
    }
  });
})();
