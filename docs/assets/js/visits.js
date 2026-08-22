/**
 * VISIT COUNTER
 * --------------------------------------------------
 * Fills #visit-counter in the footer from /api/visits (a Pages Function
 * backed by KV). Counts once per browser tab — sessionStorage remembers —
 * so clicking around the site is one visit, not ten. Stays hidden if the
 * API is missing (local Jekyll serve, a deploy without Functions) so the
 * footer never shows a broken number.
 */
(function () {
  const el = document.getElementById("visit-counter");
  if (!el) return;

  let counted = false;
  try { counted = sessionStorage.getItem("gs-visit") === "1"; } catch (_) {}

  fetch("/api/visits" + (counted ? "" : "?count=1"), { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
    .then((d) => {
      try { sessionStorage.setItem("gs-visit", "1"); } catch (_) {}
      if (!d || !(d.total > 0)) return;
      const fmt = (n) => Number(n).toLocaleString("en-US");
      el.textContent = fmt(d.total) + " visits · " + fmt(d.today) + " today";
      el.hidden = false;
    })
    .catch(() => {});
})();
