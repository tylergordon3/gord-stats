/**
 * The Share button (gordstats/share_button.py): a page's link, sent to a chat.
 *
 * On a phone it opens the phone's own share sheet - Messages, WhatsApp, the
 * group chat - with the page's address and a line about it, and the chat draws
 * the page's own preview card (gordstats/share_card.py). Where there is no
 * share sheet (most desktop browsers) it copies the line and the address, and
 * says so on the button for a moment.
 *
 * One listener for the whole page, so a button written by any page, or drawn
 * later by a page's own script, works without wiring of its own.
 *
 *   <button class="gs-share" data-url="/fantasy/recap/week-3/"
 *           data-text="Week 3: ..." data-title="NFL Week 3 Recap">Share</button>
 */
(function () {
  function absolute(path) {
    try { return new URL(path || location.pathname, location.origin).href; }
    catch (e) { return location.href; }
  }

  function flash(btn, text) {
    var label = btn.querySelector(".gs-share-label");
    if (!label) return;
    if (!btn.dataset.label) btn.dataset.label = label.textContent;
    label.textContent = text;
    btn.classList.add("done");
    clearTimeout(btn._gsTimer);
    btn._gsTimer = setTimeout(function () {
      label.textContent = btn.dataset.label;
      btn.classList.remove("done");
    }, 1800);
  }

  function copy(btn, text, url) {
    var line = text ? text + " " + url : url;
    var done = function () { flash(btn, "Link copied"); };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(line).then(done, function () {
        window.prompt("Copy this link", url);
      });
    } else {
      window.prompt("Copy this link", url);
    }
  }

  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest(".gs-share");
    if (!btn) return;
    e.preventDefault();
    var url = absolute(btn.dataset.url);
    var text = btn.dataset.text || "";
    var data = { title: btn.dataset.title || document.title, text: text, url: url };
    if (navigator.share && (!navigator.canShare || navigator.canShare(data))) {
      navigator.share(data).catch(function (err) {
        // Closing the sheet is a choice, not a failure; anything else falls
        // back to copying.
        if (!err || err.name !== "AbortError") copy(btn, text, url);
      });
      return;
    }
    copy(btn, text, url);
  });
})();
