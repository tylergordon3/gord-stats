console.log("live.js loaded");
const WORKER_URL =
  "https://cbb-live-scores.tmgordon33.workers.dev/scores?league=men";

const POLL_INTERVAL = 30000;
let lastGenerated = null;

async function pollScores() {
  const res = await fetch(WORKER_URL);
  const data = await res.json();

  const raw = document.getElementById("raw");
  if (raw) {
    raw.textContent = JSON.stringify(data, null, 2);
  }

  renderGames(data.games);
}

function statusLabel(status) {
  if (!status) return { text: "—", cls: "st-unk" };

  const s = String(status).toLowerCase();
  if (s === "in_progress" || s === "live") return { text: "LIVE", cls: "st-live" };
  if (s === "halftime") return { text: "HT", cls: "st-ht" };
  if (s === "final") return { text: "FINAL", cls: "st-final" };
  if (s === "pre" || s === "scheduled") return { text: "PRE", cls: "st-pre" };
  if (s === "delay" || s === "delayed") return { text: "DELAY", cls: "st-delay" };
  return { text: status.toString().toUpperCase(), cls: "st-unk" };
}

function safe(v, fallback = "") {
  return (v === null || v === undefined) ? fallback : v;
}

function formatMeta(g) {
  const parts = [];
  const period = safe(g.period);
  const clock = safe(g.clock);

  if (period || clock) parts.push([period, clock].filter(Boolean).join(" • "));

  // optional: venue/location
  const venue = safe(g.venue);
  const loc = safe(g.location);
  if (venue || loc) parts.push([venue, loc].filter(Boolean).join(" — "));

  // optional: betting
  const spread = safe(g.spread_close, null);
  const total = safe(g.total_close, null);
  if (spread !== null || total !== null) {
    const bits = [];
    if (spread !== null && spread !== "") bits.push(`Spread: ${spread}`);
    if (total !== null && total !== "") bits.push(`O/U: ${total}`);
    parts.push(bits.join(" • "));
  }

  return parts.filter(Boolean);
}

function renderGames(games) {
  const container = document.getElementById("games");
  if (!container) return;

  const ids = Object.keys(games || {});
  if (!ids.length) {
    container.innerHTML = `<div class="scoreboard-empty">No games right now.</div>`;
    return;
  }

  // Optional: simple sort (live first, then by date if present)
  ids.sort((a, b) => {
    const ga = games[a], gb = games[b];
    const sa = String(ga.status || ""), sb = String(gb.status || "");
    const liveA = (sa === "in_progress" || sa === "halftime" || sa === "delay") ? 0 : 1;
    const liveB = (sb === "in_progress" || sb === "halftime" || sb === "delay") ? 0 : 1;
    if (liveA !== liveB) return liveA - liveB;

    // fallback: keep stable order
    return 0;
  });

  const html = ids.map((id) => {
    const g = games[id];

    const startTime = safe(g.start_time, "")

    const awayTeam = safe(g.away_team, "AWAY");
    const homeTeam = safe(g.home_team, "HOME");

    const awayRank = safe(g.away_rank, null);
    const homeRank = safe(g.home_rank, null);

    const awayScore = safe(g.away_score, "—");
    const homeScore = safe(g.home_score, "—");

    const { text: stText, cls: stCls } = statusLabel(g.status);
    const metaLines = formatMeta(g);

    return `
      <article class="game-card" id="game-${id}">
        <header class="game-head">
          <span class="status-pill ${stCls}">${stText} ${startTime}</span>
          <span class="game-id">#${id}</span>
        </header>

        <div class="teams">
          <div class="team-row">
            <div class="team-left">
              ${awayRank ? `<span class="rank">#${awayRank}</span>` : `<span class="rank rank-empty"></span>`}
              <span class="team">${awayTeam}</span>
            </div>
            <div class="score">${awayScore}</div>
          </div>

          <div class="team-row">
            <div class="team-left">
              ${homeRank ? `<span class="rank">#${homeRank}</span>` : `<span class="rank rank-empty"></span>`}
              <span class="team">${homeTeam}</span>
            </div>
            <div class="score">${homeScore}</div>
          </div>
        </div>

        ${metaLines.length ? `
          <div class="meta">
            ${metaLines.map(line => `<div class="meta-line">${line}</div>`).join("")}
          </div>
        ` : ""}

      </article>
    `;
  }).join("");

  container.innerHTML = `<div class="scoreboard-grid">${html}</div>`;
}


pollScores();
setInterval(pollScores, POLL_INTERVAL);
