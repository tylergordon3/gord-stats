/* ---------- utils ---------- */
// Storage blocked outright throws on every touch; the toggle still works for
// this view without it.
function rankLoad(key) {
  try { return localStorage.getItem(key); } catch (e) { return null; }
}
function rankStore(key, value) {
  try { localStorage.setItem(key, value); } catch (e) { /* this view only */ }
}
function normText(s) {
  return (s || "")
    .replace(/\u00A0/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

/* ---------- core ---------- */
function setChange(period) {
  const tables = document.querySelectorAll(".rank-table");
  if (!tables.length) return;

  tables.forEach(table => {
    const headers = Array.from(table.querySelectorAll("thead th"));
    const rows = Array.from(table.querySelectorAll("tbody tr"));

    // find delta columns by period
    const indices = {};
    headers.forEach((th, i) => {
      const t = normText(th.textContent);
      if (!t.startsWith("δ")) return;
      if (t.includes("1d")) indices["1d"] = i;
      if (t.includes("7d")) indices["7d"] = i;
      if (t.includes("14d")) indices["14d"] = i;
      if (t.includes("1mo")) indices["1mo"] = i;
    });

    if (indices[period] === undefined) return;

    // toggle headers
    headers.forEach((th, i) => {
      const isDelta = Object.values(indices).includes(i);
      if (!isDelta) return;
      th.classList.toggle("hidden-col", i !== indices[period]);
    });

    // toggle rows
    rows.forEach(row => {
      Object.values(indices).forEach(i => {
        const cell = row.children[i];
        if (!cell) return;
        cell.classList.toggle("hidden-col", i !== indices[period]);
      });
    });
  });

  rankStore("rankPeriod", period);
}

/* ---------- events ---------- */
document.addEventListener("change", e => {
  if (e.target.id === "period-select") {
    setChange(e.target.value);
  }
});

/* ---------- init ---------- */
document.addEventListener("DOMContentLoaded", () => {
  const select = document.getElementById("period-select");
  if (!select) return;

  // Only a period this page still offers: anything else left the dropdown
  // blank.
  const saved = rankLoad("rankPeriod");
  if (saved && Array.prototype.some.call(select.options, o => o.value === saved)) {
    select.value = saved;
  }

  setChange(select.value);
});
