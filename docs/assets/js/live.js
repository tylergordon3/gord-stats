const WORKER_URL =
  "https://cbb-live-scores.tmgordon33.workers.dev/scores?league=men";

const POLL_INTERVAL = 30000; // 30 seconds

let lastGenerated = null;
const rendered = new Map();

async function pollScores() {
  try {
    const res = await fetch(WORKER_URL);
    const data = await res.json();

    // Skip if nothing changed
    if (data.generated === lastGenerated) return;
    lastGenerated = data.generated;

    renderGames(data.games);
  } catch (err) {
    console.error("Failed to fetch scores", err);
  }
}

function renderGames(games) {
  const container = document.getElementById("games");

  for (const [id, g] of Object.entries(games)) {
    let el = document.getElementById(`game-${id}`);

    if (!el) {
      el = document.createElement("div");
      el.className = "game";
      el.id = `game-${id}`;
      container.appendChild(el);
    }

    el.innerHTML = `
      <span class="away">${g.away_team}</span>
      <span class="score">${g.away_score ?? "-"}</span>
      <span class="clock">${g.clock ?? ""}</span>
      <span class="score">${g.home_score ?? "-"}</span>
      <span class="home">${g.home_team}</span>
      <span class="status">${g.status}</span>
    `;
  }
}

// Initial load + polling
pollScores();
setInterval(pollScores, POLL_INTERVAL);
