/*
 * Column names that stay in view down a long table.
 *
 * The rankings tables (CFB 138 rows, CBB 365) sit in a sideways scroller
 * (.power-wrap, overflow-x:auto) so a phone can reach every column - and a
 * scroller is exactly what `position: sticky` cannot stick out of, so their
 * header rows scrolled away with the page and left 300 rows of unlabelled
 * numbers under the pinned controls. This draws a copy of the header under
 * whatever is pinned (the .pin-bar, when it is stuck) while the real one is
 * out of sight: the same table classes, so the same styles and the same
 * hidden columns; the same widths, measured off the real cells; slid
 * sideways with the scroller. A tap on a copied header taps the real one, so
 * sorting still works from it.
 *
 * Opt-in by position (a table directly inside .power-wrap) or by attribute
 * (data-sticky-head), and only for tables long enough to lose their header.
 */
(function () {
  "use strict";
  var MIN_ROWS = 30;
  var tables = [].filter.call(
    document.querySelectorAll(".power-wrap > table, table[data-sticky-head]"),
    function (t) { return t.tHead && t.tBodies[0] && t.tBodies[0].rows.length >= MIN_ROWS; });
  if (!tables.length) return;

  var items = tables.map(function (t) {
    var box = document.createElement("div");
    // Not the wrapper's class: a page script that looks for its table by
    // `.power-wrap > table` must not find the copy.
    box.className = "gs-sticky-head";
    box.hidden = true;
    document.body.appendChild(box);
    return { t: t, wrap: t.parentElement, box: box, inner: null, dirty: true };
  });

  function build(it) {
    var clone = it.t.cloneNode(false);
    clone.removeAttribute("id");
    clone.appendChild(it.t.tHead.cloneNode(true));
    var src = it.t.tHead.rows, dst = clone.tHead.rows;
    for (var r = 0; r < src.length; r++) {
      for (var c = 0; c < src[r].cells.length; c++) {
        var w = src[r].cells[c].getBoundingClientRect().width + "px";
        var d = dst[r].cells[c];
        d.style.width = d.style.minWidth = d.style.maxWidth = w;
        d.style.boxSizing = "border-box";
        d.removeAttribute("id");
      }
    }
    clone.style.width = it.t.getBoundingClientRect().width + "px";
    clone.style.tableLayout = "fixed";
    clone.style.margin = "0";
    it.box.innerHTML = "";
    it.box.appendChild(clone);
    it.inner = clone;
    it.dirty = false;
  }

  /* The bottom of the pinned chrome, when there is any stuck at the top. */
  function pinned() {
    var bar = document.querySelector(".pin-bar, .filter-bar");
    if (!bar) return 0;
    var r = bar.getBoundingClientRect();
    var top = parseFloat(getComputedStyle(bar).top) || 0;
    return r.top <= top + 1 ? Math.max(0, r.bottom) : 0;
  }

  var frame = 0;
  function update() {
    frame = 0;
    var off = pinned();
    items.forEach(function (it) {
      var head = it.t.tHead.getBoundingClientRect();
      var body = it.t.getBoundingClientRect();
      var show = head.top < off && body.bottom > off + head.height * 2;
      if (show) {
        if (it.dirty || !it.inner) build(it);
        var w = it.wrap.getBoundingClientRect();
        it.box.style.top = off + "px";
        it.box.style.left = w.left + "px";
        it.box.style.width = it.wrap.clientWidth + "px";
        it.inner.style.transform = "translateX(" + (-it.wrap.scrollLeft) + "px)";
      }
      it.box.hidden = !show;
    });
  }
  function soon() { if (!frame) frame = requestAnimationFrame(update); }
  function stale() { items.forEach(function (it) { it.dirty = true; }); soon(); }

  window.addEventListener("scroll", soon, { passive: true });
  window.addEventListener("resize", stale);
  items.forEach(function (it) {
    it.wrap.addEventListener("scroll", soon, { passive: true });
    it.box.addEventListener("click", function (e) {
      var th = e.target.closest("th");
      if (!th) return;
      var row = th.parentElement;
      var r = [].indexOf.call(row.parentElement.rows, row);
      var c = [].indexOf.call(row.cells, th);
      var real = it.t.tHead.rows[r] && it.t.tHead.rows[r].cells[c];
      if (real) real.click();
    });
  });
  // A sort, a view switch or a change-since window rewrites the header:
  // copy it again the next time it shows.
  document.addEventListener("click", function () { setTimeout(stale, 0); });
  soon();
})();
