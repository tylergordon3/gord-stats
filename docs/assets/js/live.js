const board = document.getElementById('scoreboard')
const LEAGUE = board?.dataset.league || 'men' // default fallback

const WORKER_URL = `https://cbb-live-scores.tmgordon33.workers.dev/scores?league=${LEAGUE}`

const POLL_INTERVAL = 30000
const LOGO_BASE = '/assets/images/'

let lastGenerated = null

let TEAM_LOGO_MAP = {}
let TEAM_NAME_MAP = {}
let TEAM_LOGO_READY = false

let currentFilter = null
let LAST_GAMES = null
let LAST_MEDALS = null
let EXPAND_ALL = false
let EXPANDED_GAMES = new Set()

function normalize (s) {
  return String(s)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '')
    .trim()
}

async function loadTeamLogos () {
  const res = await fetch('/assets/data/master.json')
  const data = await res.json()

  const map = {}

  const name_map = {}

  const teams = data.team
  const names = data.names
  const paths = data.path

  for (const i in teams) {
    const team = teams[i]
    const path = paths?.[i]
    const aliases = names?.[i]

    if (!team || !path) continue
    let full_path = LOGO_BASE + path
    // primary team name
    console.log(full_path)
    map[normalize(team)] = full_path

    // aliases / abbreviations
    if (Array.isArray(aliases)) {
      for (const n of aliases) {
        map[normalize(n)] = full_path
        name_map[n] = team
      }
    }
  }

  TEAM_LOGO_MAP = map
  TEAM_NAME_MAP = name_map
  TEAM_LOGO_READY = true

  console.log('Loaded team logos:', Object.keys(map).length)
}

function teamLogo (teamName) {
  if (!TEAM_LOGO_READY || !teamName) {
    return '/assets/images/default.png'
  }

  return TEAM_LOGO_MAP[normalize(teamName)] || '/assets/images/default.png'
}

async function pollScores () {
  const res = await fetch(WORKER_URL)
  const data = await res.json()

  let medalByDate = {}

  const games = LEAGUE === 'men' ? data.leagues.men : data.leagues.women

  medalByDate = getBottom3MedalsByDate(games)
  applyMedalsToGames(games, medalByDate)

  LAST_GAMES = games
  LAST_MEDALS = medalByDate

  renderGames(games, medalByDate)

  if (data.meta?.poll_interval_sec) {
    const el = document.getElementById('poll-rate')
    if (el) {
      const sec = data.meta.poll_interval_sec
      el.textContent =
        sec >= 60
          ? `Polling: every ${Math.round(sec / 60)} min`
          : `Polling: every ${sec}s`
    }
  }
}

function applyMedalsToGames (games, medalByDate) {
  for (const date in medalByDate) {
    const medalMap = medalByDate[date]

    for (const [id] of medalMap.entries()) {
      if (games[id]) {
        games[id].hasMedal = true
      }
    }
  }
}

function parseClockToSeconds (clock) {
  if (!clock || typeof clock !== 'string') return Infinity

  const parts = clock.split(':')
  if (parts.length !== 2) return Infinity

  const minutes = Number(parts[0])
  const seconds = Number(parts[1])

  return minutes * 60 + seconds
}

function enrichGame (g) {
  g.isP5 = g.is_p5 === true
  g.isAP = g.is_ap === true

  const homeScore = Number(g.home_score)
  const awayScore = Number(g.away_score)
  const scoreDiff = Math.abs(homeScore - awayScore)

  const status = (g.status || '').toLowerCase()

  const isLive = status === 'in_progress' || status === 'live'
  const isFinal = status === 'final'
  const isHalftime = status === 'half_over'

  const clockSeconds = g.clock ? parseClockToSeconds(g.clock) : null

  const isWomens = LEAGUE === 'men' ? false : true

  // Final regulation period
  const finalPeriod = isWomens ? 4 : 2

  const periodNum = parseInt(g.period, 10)
  const isLate =
    isLive &&
    periodNum >= finalPeriod &&
    clockSeconds !== null &&
    clockSeconds <= 240

  g.isCloseLate = isLive && !isNaN(scoreDiff) && scoreDiff <= 8 && isLate

  g.isActiveLive = isLive && !isHalftime && !g.isCloseLate

  g.homeWon = false
  g.awayWon = false

  if (isFinal && !isNaN(homeScore) && !isNaN(awayScore)) {
    if (homeScore > awayScore) g.homeWon = true
    if (awayScore > homeScore) g.awayWon = true
  }

  return g
}

function gamePriority (g) {
  const status = (g.status || '').toLowerCase()

  const isLive = status === 'in_progress' || status === 'live'

  const isHalftime = status === 'half_over'
  const isFinal = status === 'final'
  const isPre = status === 'pre_game' || status === 'scheduled'
  const isOT = status === 'OT'

  function gameProgressScore (g) {
    let currentPeriod
    if (isOT) {
      currentPeriod = LEAGUE === 'men' ? 3 : 5
    } else {
      currentPeriod = parseInt(g.period, 10) || 1
    }

    const clockSeconds = g.clock ? parseClockToSeconds(g.clock) : 0

    // Estimate % complete
    const periodLength = LEAGUE === 'men' ? 1200 : 600 // 1200 sec - 20 min men | 600 sec - 10 min women

    const secondsIntoGame =
      ((currentPeriod - 1) * periodLength) + (periodLength - clockSeconds)
    return secondsIntoGame
  }

  if (isLive && !isHalftime) {
    return gameProgressScore(g)
  }

  if (isOT) return 2700
  // 3️⃣ Halftime
  if (isHalftime) return 0

  // 4️⃣ Pregame
  if (isPre) return -1

  // 5️⃣ Final always bottom
  if (isFinal) return -2

  return -3
}

function gameTime (g) {
  return g.start_time_utc ? new Date(g.start_time_utc).getTime() : Infinity
}

function formatDateHeader (isoDate) {
  const d = new Date(isoDate + 'T00:00:00')
  return d.toLocaleDateString(undefined, {
    weekday: 'long',
    month: 'long',
    day: 'numeric'
  })
}

function statusLabel (status) {
  if (!status) return { text: '—', cls: 'st-unk' }

  const s = String(status).toLowerCase()
  if (s === 'in_progress' || s === 'live')
    return { text: 'LIVE', cls: 'st-live' }
  if (s === 'half_over') return { text: 'HALFTIME', cls: 'st-ht' }
  if (s === 'final') return { text: 'FINAL', cls: 'st-final' }
  if (s === 'pre_game' || s === 'scheduled')
    return { text: 'PRE', cls: 'st-pre' }
  if (s === 'delay' || s === 'delayed')
    return { text: 'DELAY', cls: 'st-delay' }
  return { text: status.toString().toUpperCase(), cls: 'st-unk' }
}

function safe (v, fallback = '') {
  return v === null || v === undefined ? fallback : v
}

function getTeamName (team) {
  print_name = TEAM_NAME_MAP[team]
  if (!print_name) {
    return team
  }

  return print_name
}

function formatMeta (g) {
  const parts = []

  const venue = safe(g.venue)
  const loc = safe(g.location)

  if (venue) parts.push({ type: 'venue', text: venue })
  if (loc) parts.push({ type: 'location', text: loc })

  // optional: betting
  const spread = safe(g.spread_close, null)
  const total = safe(g.total_close, null)
  if (spread !== null || total !== null) {
    const bits = []
    if (spread !== null && spread !== '') bits.push(`Spread: ${spread}`)
    if (total !== null && total !== '') bits.push(`O/U: ${total}`)
    parts.push(bits.join(' • '))
  }

  return parts.filter(Boolean)
}

function renderTime (g) {
  // PRE games: show tip-off
  if (g.status === 'pre_game' && g.start_time) {
    return `<span class="game-time">${g.start_time}</span>`
  }

  if (g.status === 'final') {
    return `<span class="game-time"></span>`
  }

  // LIVE / FINAL games: show period + clock
  const period = safe(g.period)
  const clock = safe(g.clock)

  if (period || clock) {
    return `
      <span class="game-time">
        ${[period, clock].filter(Boolean).join(' • ')}
      </span>
    `
  }

  return `<span class="game-time">—</span>`
}

function getLowestRatings (games, n = 3) {
  const vals = []

  for (const id in games) {
    const r = games[id]?.rating
    if (typeof r === 'number' && !Number.isNaN(r)) {
      vals.push(r)
    }
  }

  vals.sort((a, b) => a - b)

  return new Set(vals.slice(0, n))
}

function getBottom3MedalsByDate (games) {
  const byDate = {}
  const result = {}

  // group by date
  for (const id in games) {
    const g = games[id]
    const date = g.date
    const rating = g.rating

    if (!date) continue
    if (typeof rating !== 'number' || Number.isNaN(rating)) continue

    if (!byDate[date]) byDate[date] = []
    byDate[date].push({ id, rating })
  }

  // assign medals
  for (const date in byDate) {
    byDate[date].sort((a, b) => a.rating - b.rating)

    result[date] = new Map()

    const medals = ['🥇', '🥈', '🥉']

    byDate[date].slice(0, 3).forEach((g, i) => {
      result[date].set(g.id, medals[i])
    })
  }

  return result
}

function renderExpandedStats (g) {
  function compareNums (a, b) {
    if (a == '—') {
      a = 99
    }
    if (b == '—') {
      b = 99
    }
    const na = Number(a)
    const nb = Number(b)

    if (isNaN(na) || isNaN(nb)) return { left: '', right: '' }

    if (na < nb) return { left: 'better', right: '' }
    if (nb < na) return { left: '', right: 'better' }
    return { left: '', right: '' }
  }

  const awayTeam = safe(g.away_team, 'Away')
  const homeTeam = safe(g.home_team, 'Home')

  const awayAbb = safe(g.away_abb, 'Away')
  const homeAbb = safe(g.home_abb, 'Home')

  const awayRank = safe(g.away_rank, '—')
  const homeRank = safe(g.home_rank, '—')

  const awayModel = safe(g.away_model, '—')
  const homeModel = safe(g.home_model, '—')

  const atsAway = safe(g.ats_away, '—')
  const atsHome = safe(g.ats_home, '—')

  const ouAway = safe(g.ou_away, '—')
  const ouHome = safe(g.ou_home, '—')

  const netAway = safe(g.net_away, '—')
  const netHome = safe(g.net_home, '—')

  const bpiAway = safe(g.bpi_away, '—')
  const bpiHome = safe(g.bpi_home, '—')

  const lastTenHome = safe(g.home_last_ten)
  const lastTenAway = safe(g.away_last_ten)
  
  const rankCompare = compareNums(awayRank, homeRank)
  const modelCompare = compareNums(awayModel, homeModel)
  const netCompare = compareNums(netAway, netHome)
  const bpiCompare = compareNums(bpiAway, bpiHome)

  return `
    <div class="expanded-compare">

      <!-- HEADER -->
      <div class="expanded-header">
        <div class="team-col">
          <img 
            src="${teamLogo(awayTeam)}"
            alt="${awayTeam}"
            class="expanded-logo"
            onerror="this.src='/assets/images/default.png'"
          />
          <span>${awayAbb ? awayAbb : getTeamName(awayTeam)}</span>
        </div>

        <div></div>

        <div class="team-col">
          <img 
            src="${teamLogo(homeTeam)}"
            alt="${homeTeam}"
            class="expanded-logo"
            onerror="this.src='/assets/images/default.png'"
          />
          <span>${homeAbb ? homeAbb : getTeamName(homeTeam)}</span>
        </div>
      </div>

      <!-- AP RANK -->
      <div class="expanded-row">
        <div class="value left">
          <span class="${rankCompare.left}">${awayRank}</span>
        </div>
        <div class="label">AP Rank</div>
        <div class="value right">
        <span class="${rankCompare.right}">${homeRank}</span>
      </div>
      </div>

      <!-- MODEL -->
      <div class="expanded-row">
        <div class="value left">
        <span class="${modelCompare.left}">#${awayModel}</span>
      </div>
        <div class="label">GORD</div>
        <div class="value right">
        <span class="${modelCompare.right}">#${homeModel}</span>
        </div>
      </div>

      <!-- NET -->
      <div class="expanded-row">
        <div class="value left">
        <span class="${netCompare.left}">#${netAway}</span>
      </div>
        <div class="label">NET</div>
        <div class="value right">
        <span class="${netCompare.right}">#${netHome}</span>
      </div>
      </div>

       ${
         LEAGUE === 'men'
           ? `

      <!-- BPI -->
      <div class="expanded-row">
        <div class="value left">
        <span class="${bpiCompare.left}">#${bpiAway}</span>
      </div>
        <div class="label">ESPN BPI</div>
        <div class="value right">
        <span class="${bpiCompare.right}">#${bpiHome}</span>
      </div>
      </div>

      <!-- ATS -->
      <div class="expanded-row">
        <div class="value left">${atsAway}</div>
        <div class="label">Cover %</div>
        <div class="value right">${atsHome}</div>
      </div>

      <!-- O/U -->
      <div class="expanded-row">
        <div class="value left">${ouAway}</div>
        <div class="label">Over %</div>
        <div class="value right">${ouHome}</div>
      </div>
      `
           : ''
       }
      
      <!-- Last 10 -->
      <div class="expanded-row">
        <div class="value left">${lastTenAway}</div>
        <div class="label">Last 10</div>
        <div class="value right">${lastTenHome}</div>
      </div>

    </div>
  `
}

function filterGameIds (games) {
  const ids = Object.keys(games || {})

  if (!currentFilter) return ids

  return ids.filter(id => {
    const g = games[id]

    switch (currentFilter) {
      case 'ap25':
        return g.isAP === true

      case 'p5':
        return g.isP5 === true

      case 'top3':
        return g.hasMedal === true

      default:
        return true
    }
  })
}

function renderGames (games, medalByDate = {}) {
  if (!games) return
  console.log(
    'renderGames',
    Object.keys(games || {}).length,
    'filter:',
    currentFilter
  )

  // enrich once
  Object.values(games).forEach(enrichGame)

  const filteredIds = filterGameIds(games)

  const container = document.getElementById('games')
  if (!container) return

  if (!filteredIds.length) {
    container.innerHTML = `<div class="scoreboard-empty">No games match this filter.</div>`
    return
  }

  /// ---- group by date ----
  const byDate = {}

  for (const id of filteredIds) {
    const g = games[id]
    if (!g) continue

    const dateKey = g.date || 'unknown'
    if (!byDate[dateKey]) byDate[dateKey] = []

    byDate[dateKey].push({ id, g })
  }

  // ---- sort dates chronologically ----
  const dates = Object.keys(byDate).sort((a, b) => new Date(a) - new Date(b))

  // ---- build HTML ----
  let html = ''

  for (const date of dates) {
    const gamesForDay = byDate[date]

    // ---- sort within the day ----
    gamesForDay.sort((a, b) => {
      const pa = gamePriority(a.g)
      const pb = gamePriority(b.g)

      if (pa !== pb) return pb - pa

      return gameTime(a.g) - gameTime(b.g)
    })

    // ---- date header ----
    html += `
      <h2 class="date-header">${formatDateHeader(date)}</h2>
      <div class="scoreboard-grid">
    `

    for (const { id, g } of gamesForDay) {
      const awayTeam = safe(g.away_team, 'AWAY')
      const homeTeam = safe(g.home_team, 'HOME')

      const awayAbb = safe(g.away_abb, null)
      const homeAbb = safe(g.home_abb, null)

      const awayRank = safe(g.away_rank, null)
      const homeRank = safe(g.home_rank, null)
      const isAP = g.isAP
      const isP5 = g.isP5

      const awayRecord = safe(g.away_record, null)
      const homeRecord = safe(g.home_record, null)

      const homeModel = safe(g.home_model, null)
      const awayModel = safe(g.away_model, null)

      const awayScore = safe(g.away_score, '—')
      const homeScore = safe(g.home_score, '—')

      const { text: stText, cls: stCls } = statusLabel(g.status)
      const metaLines = formatMeta(g)

      const medal = medalByDate[date]?.get(id)

      const medalClass =
        medal === '🥇'
          ? 'gold'
          : medal === '🥈'
          ? 'silver'
          : medal === '🥉'
          ? 'bronze'
          : ''

      html += `
        <article class="game-card 
          ${g.isCloseLate ? 'close-late' : ''} 
          ${g.isActiveLive ? 'live-active' : ''}"
          id="game-${id}" 
          data-game-id="${id}">
          <header class="game-head">
          <div class="game-head-left">
          <span class="status-pill ${stCls}">${stText} </span>
          </div>
           <div class="game-head-center">
            ${renderTime(g)}
          </div>
          <div class="game-head-right">
           ${isAP ? `<span class="game-badge ap">TOP 25</span>` : ''}
           ${isP5 ? `<span class="game-badge p5">P5</span>` : ''}
           ${
             medal
               ? `<span class="game-badge medal  ${medalClass}" title="Top 3 rating">${medal}</span>`
               : ''
           }
           </div>
        </header>

          <div class="teams">
           <div class="team-row ${g.awayWon ? 'winner' : ''}">
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
                <span class="team-name">${
                  awayAbb ? awayAbb : getTeamName(awayTeam)
                }</span>
                <strong>${awayModel ? `#${awayModel}` : ''}</strong>
                ${awayRecord ? `(${awayRecord})` : ''}
              </span>
              </div>
              <div class="score">${awayScore}</div>
            </div>

            <div class="team-row ${g.homeWon ? 'winner' : ''}">
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
                <span class="team-name">${
                  homeAbb ? homeAbb : getTeamName(homeTeam)
                }</span>
                <strong>${homeModel ? `#${homeModel}` : ''}</strong>
                ${homeRecord ? `(${homeRecord})` : ''}
              </span>
              </div>
              <div class="score">${homeScore}</div>
            </div>
          </div>

          ${
            metaLines.length
              ? `
            <div class="meta">
              ${metaLines
                .map(
                  m => `
              <div class="meta-line meta-${m.type || 'misc'}">
                ${m.text || m}
              </div>
            `
                )
                .join('')}
            </div>
          `
              : ''
          }
          <div class="expand-toggle">
            <span class="expand-indicator">▼</span>
          </div>

          <div class="game-expand" hidden>
            ${renderExpandedStats(g)}
          </div>
        </article>
      `
    }

    html += `</div>`
  }

  container.innerHTML = html
  // Restore expanded state after re-render
  container.querySelectorAll('.game-card').forEach(card => {
    const id = card.dataset.gameId
    const expand = card.querySelector('.game-expand')
    if (!expand) return

    if (EXPAND_ALL || EXPANDED_GAMES.has(id)) {
      expand.hidden = false
      card.classList.add('open')
    } else {
      expand.hidden = true
      card.classList.remove('open')
    }
  })

  container.querySelectorAll('.expand-toggle').forEach(toggle => {
    toggle.addEventListener('click', e => {
      if (EXPAND_ALL) return
      const card = toggle.closest('.game-card')
      const expand = card.querySelector('.game-expand')
      const id = card.dataset.gameId

      if (!expand || !id) return

      const isOpen = !expand.hidden

      // Close all others (accordion behavior)
      container.querySelectorAll('.game-expand').forEach(el => {
        el.hidden = true
      })

      container.querySelectorAll('.game-card').forEach(c => {
        c.classList.remove('open')
      })

      if (isOpen) {
        // closing
        expand.hidden = true
        card.classList.remove('open')
        EXPANDED_GAMES.delete(id)
      } else {
        // opening (accordion style)
        EXPANDED_GAMES.clear()

        container.querySelectorAll('.game-expand').forEach(el => {
          el.hidden = true
        })

        container.querySelectorAll('.game-card').forEach(c => {
          c.classList.remove('open')
        })

        expand.hidden = false
        card.classList.add('open')
        EXPANDED_GAMES.add(id)
      }

      e.stopPropagation()
    })
  })
}

async function start () {
  await loadTeamLogos()
  await pollScores()
  setInterval(pollScores, POLL_INTERVAL)
}

start()

document.addEventListener('DOMContentLoaded', () => {
  const legendOverlay = document.getElementById('legend-overlay')
  const openLegend = document.getElementById('open-legend')
  const closeLegend = document.getElementById('close-legend')

  if (!legendOverlay || !openLegend || !closeLegend) return

  openLegend.addEventListener('click', () => {
    legendOverlay.hidden = false
    document.body.style.overflow = 'hidden'
  })

  closeLegend.addEventListener('click', () => {
    legendOverlay.hidden = true
    document.body.style.overflow = ''
  })

  legendOverlay.addEventListener('click', e => {
    if (e.target === legendOverlay) {
      legendOverlay.hidden = true
      document.body.style.overflow = ''
    }
  })

  // ESC key support (nice UX)
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && !legendOverlay.hidden) {
      legendOverlay.hidden = true
      document.body.style.overflow = ''
    }
  })
})

document.querySelectorAll('.sort-chip[data-sort]').forEach(btn => {
  btn.addEventListener('click', () => {
    const filter = btn.dataset.sort

    // toggle on/off
    currentFilter = currentFilter === filter ? null : filter

    document
      .querySelectorAll('.sort-chip')
      .forEach(b =>
        b.classList.toggle('active', b.dataset.sort === currentFilter)
      )

    if (LAST_GAMES && LAST_MEDALS) {
      renderGames(LAST_GAMES, LAST_MEDALS)
    }
  })
})

document.addEventListener('DOMContentLoaded', () => {
  const expandBtn = document.getElementById('expand-all-btn')
  if (!expandBtn) return

  expandBtn.addEventListener('click', () => {
    EXPAND_ALL = !EXPAND_ALL

    expandBtn.textContent = EXPAND_ALL ? 'Collapse All' : 'Expand All'
    expandBtn.classList.toggle('active', EXPAND_ALL)

    if (LAST_GAMES && LAST_MEDALS) {
      renderGames(LAST_GAMES, LAST_MEDALS)
    }
  })
})
