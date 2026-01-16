
(function () {
  const select = document.getElementById("conference-select");
  const tables = Array.from(document.querySelectorAll(".rank-table[data-conference]"));

  if (!select || !tables.length) return;

  // Collect unique conferences from tables
  const conferences = [...new Set(
    tables.map(t => t.dataset.conference)
  )].sort();

  // Populate dropdown
  conferences.forEach(conf => {
    const opt = document.createElement("option");
    opt.value = conf;
    opt.textContent = conf;
    select.appendChild(opt);
  });

  function updateConference() {
  const selected = select.value;

  tables.forEach(table => {
    const conf = table.dataset.conference;
    const show = selected === "ALL" || conf === selected;

    table.style.display = show ? "" : "none";

    const title = document.querySelector(
      `.conference-title[data-conference="${conf}"]`
    );
    if (title) {
      title.style.display = show ? "" : "none";
    }
  });
}

  // Event
  select.addEventListener("change", updateConference);

  // Initialize
  updateConference();

    // Restore previous selection
    const saved = localStorage.getItem("conference");
    if (saved) select.value = saved;

    // Save on change
    select.addEventListener("change", () => {
    localStorage.setItem("conference", select.value);
    });
})();

(function () {
  const tables = document.querySelectorAll(".rank-table[data-conference]");
  if (!tables.length) return;

  tables.forEach(table => {
    const conf = table.dataset.conference;

    // Create heading
    const h = document.createElement("h2");
    h.className = "conference-title";
    h.textContent = conf;

    // Insert heading before table
    table.parentNode.insertBefore(h, table);

    // Link heading to table for filtering
    table.dataset.titleId = conf;
    h.dataset.conference = conf;
  });
})();


