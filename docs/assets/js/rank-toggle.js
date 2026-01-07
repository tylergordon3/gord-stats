function normText(s) {
  return (s || "")
    .replace(/\u00A0/g, " ")     // NBSP -> space
    .replace(/\s+/g, " ")       // collapse whitespace
    .trim();
}

function setChange(period, btn) {
  const cols = {
    "7d": "Δ 7d",
    "14d": "Δ 14d",
    "1mo": "Δ 1mo"
  };

  const table = document.querySelector(".rank-table");
  if (!table) return;

  const headers = Array.from(table.querySelectorAll("thead th"));
  const rows = Array.from(table.querySelectorAll("tbody tr"));

  // find exact column indices by header text
  const indices = {};
  for (let i = 0; i < headers.length; i++) {
    const t = normText(headers[i].textContent);
    for (const [key, name] of Object.entries(cols)) {
      if (t === name) indices[key] = i;
    }
  }

  // If we didn't find the selected column, do nothing (prevents "active disappears")
  if (indices[period] === undefined) return;

  // hide/show headers + cells
  for (const [key, idx] of Object.entries(indices)) {
    headers[idx].classList.toggle("hidden-col", key !== period);
  }

  for (const row of rows) {
    const cells = row.children;
    for (const [key, idx] of Object.entries(indices)) {
      if (cells[idx]) cells[idx].classList.toggle("hidden-col", key !== period);
    }
  }

  // active button styling
  document.querySelectorAll(".change-toggle button").forEach(b => b.classList.remove("active"));
  if (btn) btn.classList.add("active");
}

// default = whatever button has class active (yours is 2 Weeks)
document.addEventListener("DOMContentLoaded", () => {
  const defaultBtn = document.querySelector(".change-toggle button.active");
  if (defaultBtn) defaultBtn.click();
});