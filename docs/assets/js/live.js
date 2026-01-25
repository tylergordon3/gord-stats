const board = document.getElementById("scoreboard");
const LEAGUE = board?.dataset.league || "men"; // default fallback

const WORKER_URL =
  `https://cbb-live-scores.tmgordon33.workers.dev/scores?league=${LEAGUE}`;

const POLL_INTERVAL = 30000;
const LOGO_BASE = "/assets/images/";

let lastGenerated = null;

let TEAM_LOGO_MAP = {};
let TEAM_NAME_MAP = {};
let TEAM_LOGO_READY = false;

function normalize(s) {
  return String(s)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "")
    .trim();
}

async function loadTeamLogos() {
  const res = await fetch("/assets/data/master.json");
  const data = await res.json();

  const map = {};

  const name_map = {};

  const teams = data.team;
  const names = data.names;
  const paths = data.path;

  for (const i in teams) {
    const team = teams[i];
    const path = paths?.[i];
    const aliases = names?.[i];

    if (!team || !path) continue;
    let full_path = LOGO_BASE + path;
    // primary team name
    console.log(full_path);
    map[normalize(team)] = full_path;

    // aliases / abbreviations
    if (Array.isArray(aliases)) {
      for (const n of aliases) {
        map[normalize(n)] = full_path;
        name_map[n] = team;
      }
    }
  }

  TEAM_LOGO_MAP = map;
  TEAM_NAME_MAP = name_map;
  TEAM_LOGO_READY = true;

  console.log("Loaded team logos:", Object.keys(map).length);
}

function teamLogo(teamName) {
  if (!TEAM_LOGO_READY || !teamName) {
    return "/assets/images/default.png";
  }

  return (
    TEAM_LOGO_MAP[normalize(teamName)] ||
    "/assets/images/default.png"
  );
}


async function pollScores() {
  const res = await fetch(WORKER_URL);
  const data = await res.json();

  if (data.meta?.poll_interval_sec) {
    const el = document.getElementById("poll-rate");
    if (el) {
      const sec = data.meta.poll_interval_sec;
      el.textContent =
        sec >= 60
          ? `Polling: every ${Math.round(sec / 60)} min`
          : `Polling: every ${sec}s`;
    }
  }
  if (LEAGUE == "men") {
    renderGames(data.leagues.men);
  } else if (LEAGUE == "women") {
    renderGames(data.leagues.women);
  }
}

function statusRank(g) {
  const s = (g.status || "").toLowerCase();

  if (
    s === "in_progress" ||
    s === "live" ||
    s === "half_over" ||
    s === "delay"
  ) return 0; // LIVE

  if (
    s === "pre" ||
    s === "scheduled" ||
    s === "pre_game" ||
    s === "not_started"
  ) return 1; // PRE

  if (s === "final") return 2; // FINAL

  return 3;
}

function gameTime(g) {
  return g.start_time_utc
    ? new Date(g.start_time_utc).getTime()
    : Infinity;
}

function formatDateHeader(isoDate) {
  const d = new Date(isoDate + "T00:00:00");
  return d.toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric"
  });
}

function statusLabel(status) {
  if (!status) return { text: "—", cls: "st-unk" };

  const s = String(status).toLowerCase();
  if (s === "in_progress" || s === "live") return { text: "LIVE", cls: "st-live" };
  if (s === "half_over") return { text: "HALFTIME", cls: "st-ht" };
  if (s === "final") return { text: "FINAL", cls: "st-final" };
  if (s === "pre_game" || s === "scheduled") return { text: "PRE", cls: "st-pre" };
  if (s === "delay" || s === "delayed") return { text: "DELAY", cls: "st-delay" };
  return { text: status.toString().toUpperCase(), cls: "st-unk" };
}

function safe(v, fallback = "") {
  return (v === null || v === undefined) ? fallback : v;
}

function getTeamName(team) {
  print_name = TEAM_NAME_MAP[team];
  if (!print_name) {
    return team;
  }

  return print_name
}

function formatMeta(g) {
  const parts = [];

  const venue = safe(g.venue);
  const loc = safe(g.location);

  if (venue) parts.push({ type: "venue", text: venue });
  if (loc) parts.push({ type: "location", text: loc });

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

function renderTime(g) {
  // PRE games: show tip-off
  if (g.status === "pre_game" && g.start_time) {
    return `<span class="game-time">${g.start_time}</span>`;
  }

  if (g.status === "final") {
    return `<span class="game-time"></span>`;
  }

  // LIVE / FINAL games: show period + clock
  const period = safe(g.period);
  const clock = safe(g.clock);

  if (period || clock) {
    return `
      <span class="game-time">
        ${[period, clock].filter(Boolean).join(" • ")}
      </span>
    `;
  }

  return `<span class="game-time">—</span>`;
}

function renderGames(games) {
  const container = document.getElementById("games");
  if (!container) return;

  const ids = Object.keys(games || {});
  if (!ids.length) {
    container.innerHTML =
      `<div class="scoreboard-empty">No games right now.</div>`;
    return;
  }

  // ---- group by date ----
  const byDate = {};

  for (const id of ids) {
    const g = games[id];
    const dateKey = g.date || "unknown";

    if (!byDate[dateKey]) byDate[dateKey] = [];
    byDate[dateKey].push({ id, g });
  }

  // ---- sort dates chronologically ----
  const dates = Object.keys(byDate).sort(
    (a, b) => new Date(a) - new Date(b)
  );

  // ---- build HTML ----
  let html = "";

  for (const date of dates) {
    const gamesForDay = byDate[date];

    // ---- sort within the day ----
    gamesForDay.sort((a, b) => {
      const ra = statusRank(a.g);
      const rb = statusRank(b.g);
      if (ra !== rb) return ra - rb;

      return gameTime(a.g) - gameTime(b.g);
    });

    // ---- date header ----
    html += `
      <h2 class="date-header">${formatDateHeader(date)}</h2>
      <div class="scoreboard-grid">
    `;

    for (const { id, g } of gamesForDay) {
      const awayTeam = safe(g.away_team, "AWAY");
      const homeTeam = safe(g.home_team, "HOME");

      const awayRank = safe(g.away_rank, null);
      const homeRank = safe(g.home_rank, null);
      const isAP = safe(g.is_ap, null);
      const isP4 = safe(g.is_p4, null);

      const awayRecord = safe(g.away_record, null);
      const homeRecord = safe(g.home_record, null);

      const homeModel = safe(g.home_model, null);
      const awayModel = safe(g.away_model, null);

      const awayScore = safe(g.away_score, "—");
      const homeScore = safe(g.home_score, "—");

      const { text: stText, cls: stCls } = statusLabel(g.status);
      const metaLines = formatMeta(g);

      html += `
        <article class="game-card" id="game-${id}">
          <header class="game-head">
          <div class="game-head-left">
          <span class="status-pill ${stCls}">${stText} </span>
          </div>
           <div class="game-head-center">
            ${renderTime(g)}
          </div>
           ${isAP ? `<div class="game-head-right"><span class="game-badge ap">TOP 25</span></div>` : ''}
           ${isP4 ? `<div class="game-head-right"><span class="game-badge p4">P4</span></div>` : ''}
        </header>

          <div class="teams">
            <div class="team-row">
              <div class="team-left">
                <span class="team">
                <img
                  class="team-logo"
                  src="${teamLogo(awayTeam)}"
                  alt="${awayTeam}"
                  loading="lazy"
                  onerror="this.src='/assets/images/default.png'"
                />
                ${awayRank ? `(${awayRank})` : ''}
                <span class="team-name">${getTeamName(awayTeam)}</span>
                <strong>${awayModel ? `#${awayModel}` : ''}</strong>
                ${awayRecord ? `(${awayRecord})` : ''}
              </span>
              </div>
              <div class="score">${awayScore}</div>
            </div>

            <div class="team-row">
              <div class="team-left">
                <span class="team">
                <img
                  class="team-logo"
                  src="${teamLogo(homeTeam)}"
                  alt="${homeTeam}"
                  loading="lazy"
                  onerror="this.src='/assets/images/default.png'"
                />
                ${homeRank ? `(${homeRank})` : ''}
                <span class="team-name">${getTeamName(homeTeam)}</span>
                <strong>${homeModel ? `#${homeModel}` : ''}</strong>
                ${homeRecord ? `(${homeRecord})` : ''}
              </span>
              </div>
              <div class="score">${homeScore}</div>
            </div>
          </div>

          ${metaLines.length ? `
            <div class="meta">
              ${metaLines.map(m => `
              <div class="meta-line meta-${m.type || "misc"}">
                ${m.text || m}
              </div>
            `).join("")}
            </div>
          ` : ""}
        </article>
      `;
    }

    html += `</div>`;
  }

  container.innerHTML = html;
}

async function start() {
  await loadTeamLogos();
  await pollScores();
  setInterval(pollScores, POLL_INTERVAL);
}

start();