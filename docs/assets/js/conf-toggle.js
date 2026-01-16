(function () {
  const tables = document.querySelectorAll(".rank-table[data-conference]");
  if (!tables.length) return;

  tables.forEach(table => {
    const conf = table.dataset.conference;

    const block = document.createElement("div");
    block.className = "conference-block";
    block.dataset.conference = conf;

    const title = document.createElement("h2");
    title.className = "conference-title";
    title.textContent = conf;

    const container = document.createElement("div");
    container.className = "table-container";

    table.parentNode.insertBefore(block, table);
    container.appendChild(table);
    block.appendChild(title);
    block.appendChild(container);
  });
})();
(function () {
  const select = document.getElementById("conference-select");
  const blocks = Array.from(document.querySelectorAll(".conference-block"));

  if (!select || !blocks.length) return;

  // Collect unique conferences
  const conferences = [...new Set(
    blocks.map(b => b.dataset.conference)
  )].sort();

  // Populate dropdown
  conferences.forEach(conf => {
    const opt = document.createElement("option");
    opt.value = conf;
    opt.textContent = conf;
    select.appendChild(opt);
  });

  // Restore previous selection
  const saved = localStorage.getItem("conference");
  if (saved) select.value = saved;

  function updateConference() {
    const selected = select.value;

    blocks.forEach(block => {
      const conf = block.dataset.conference;
      block.style.display =
        selected === "ALL" || conf === selected ? "" : "none";
    });

    localStorage.setItem("conference", selected);
  }

  select.addEventListener("change", updateConference);

  // Initialize
  updateConference();
})();
