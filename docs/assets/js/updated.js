/*
 * "Updated ..." under a page's title (gordstats.frontmatter.updated_line).
 *
 * The page is built with the time in Eastern, which is right for nobody west
 * of it and says nothing about how old the numbers are. This rewrites it in
 * the reader's own clock with the age first - "Updated 2 hr ago · Tue, Sep
 * 29, 8:30 PM" - and keeps the age current while the page stays open. The
 * built text is the fallback, so a page without the script still says when.
 */
(function () {
  "use strict";
  var lines = document.querySelectorAll(".page-updated[data-updated]");
  if (!lines.length) return;

  function ago(ms) {
    var min = Math.round(ms / 60000);
    if (min < 1) return "just now";
    if (min < 60) return min + " min ago";
    var hr = Math.round(min / 60);
    if (hr < 36) return hr + " hr ago";
    var days = Math.round(hr / 24);
    return days + " days ago";
  }

  function paint() {
    var now = Date.now();
    for (var i = 0; i < lines.length; i++) {
      var p = lines[i];
      var t = Date.parse(p.getAttribute("data-updated"));
      if (isNaN(t)) continue;
      var when = new Date(t).toLocaleString(undefined, {
        weekday: "short", month: "short", day: "numeric",
        hour: "numeric", minute: "2-digit"
      });
      p.textContent = "Updated " + ago(Math.max(0, now - t)) + " · " + when;
      p.title = new Date(t).toString();
    }
  }

  paint();
  setInterval(function () { if (!document.hidden) paint(); }, 60000);
})();
