function normText(s) {
  return (s || "")
    .replace(/\u00A0/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

const COLS = {
  "7d": "Δ 7d",
  "14d": "Δ 14d",
  "1mo": "Δ 1mo"
};

function setChange(period, btn) {
  const tables = document.querySelectorAll(".rank-table");
  if (!tables.length) return;

  tables.forEach(table => {
    const headers = Array.from(table.querySelectorAll("thead th"));
    const rows = Array.from(table.querySelectorAll("tbody tr"));

    // find column indices per table
    const indices = {};
    headers.forEach((th, i) => {
      const t = normText(th.textContent);
      for (const [key, name] of Object.entries(COLS)) {
        if (t === name) indices[key] = i;
      }
    });

    // skip tables missing this period
    if (indices[period] === undefined) return;

    // toggle headers
    for (const [key, idx] of Object.entries(indices)) {
      headers[idx].classList.toggle("hidden-col", key !== period);
    }

    // toggle rows
    rows.forEach(row => {
      for (const [key, idx] of Object.entries(indices)) {
        if (row.children[idx]) {
          row.children[idx].classList.toggle("hidden-col", key !== period);
        }
      }
    });
  });

  // active button styling (global)
  document
    .querySelectorAll(".change-toggle button")
    .forEach(b => b.classList.remove("active"));
  if (btn) btn.classList.add("active");
}

// global click handler
document.addEventListener("click", e => {
  const btn = e.target.closest(".change-toggle button[data-period]");
  if (!btn) return;
  setChange(btn.dataset.period, btn);
});

// initialize on load
document.addEventListener("DOMContentLoaded", () => {
  const defaultBtn = document.querySelector(".change-toggle button.active");
  if (defaultBtn) {
    setChange(defaultBtn.dataset.period, defaultBtn);
  }
});
