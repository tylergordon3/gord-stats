const board = document.getElementById('scoreboard')
const LEAGUE = board?.dataset.league || 'men' // default fallback

const WORKER_URL = `https://cbb-live-scores.tmgordon33.workers.dev/scores?league=${LEAGUE}`

// The Worker's data changes once a push (every ten minutes in playing hours),
// and every poll counts against the account's shared daily Workers quota -
// the same one sign-in and the other APIs run on. Two minutes, and none at all
// while the tab is hidden (the 2026-09-28 audit: every 30s, hidden or not,
// was 2,880 requests a tab a day).
const POLL_INTERVAL = 120000
const LOGO_BASE = '/assets/images/'

// Out of season the Worker keeps the last slate it was pushed - in September,
// April's championship - and on a day without games it holds none. Either way
// the board used to show only its controls: five filter chips, Expand All, a
// polling rate and a "Past Games" fold around months-old finals (the
// 2026-09-29 phone audit). A feed with no game from the last STALE_DAYS days
// gets one line instead, and the controls come back with the first slate.
// Two days, not one: before 11 ET in season the Worker still holds last
// night's games, and those are worth their "Past Games" fold.
const STALE_DAYS = 2
// Only for that line: ESPN's calendar lists every date with a game this
// season, so the board can say when the next one is. CORS-open, and asked for
// one day and at most one event: a few kilobytes, once a page view.
const ESPN_SCOREBOARD = 'https://site.api.espn.com/apis/site/v2/sports/basketball/' +
  `${LEAGUE === 'women' ? 'womens' : 'mens'}-college-basketball/scoreboard`
const controls = board?.querySelector('.meta-bar')

let lastGenerated = null

let TEAM_LOGO_MAP = {}
let TEAM_NAME_MAP = {}
let TEAM_LOGO_READY = false

let currentFilter = null
let LAST_GAMES = null
let LAST_MEDALS = null
let EXPAND_ALL = false
let EXPANDED_GAMES = new Set()

const CONF_CLASSES = new Set(['acc', 'sec', 'bigten', 'big12', 'bigeast'])
const march_madness = new Set(['ncaatournament', 'ncaawtournament'])
const nit = new Set(['nit', 'wnit'])

function normalize (s) {
  return String(s)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '')
    .trim()
}

function getTourneyClass (conf) {
  const key = normalize(conf)
  console.log(key)
  if (CONF_CLASSES.has(key)) {
    return `conf-${key}`
  } else if ((key.includes('ncaatournament')) || (key.includes('ncaawtournament'))) {
    return 'march-madness'
  } else if (key.includes('nit')) {
    return 'nit'
  }
  return 'conf' // default class
}

function isToday (isoDate) {
  const today = new Date()
  const d = new Date(isoDate + 'T00:00:00')

  return (
    today.getFullYear() === d.getFullYear() &&
    today.getMonth() === d.getMonth() &&
    today.getDate() === d.getDate()
  )
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

  // The Worker is refreshed every ten minutes and polled every thirty
  // seconds. Rebuilding the board on every poll closed any section the reader
  // had opened ("Past Games") twenty times between updates.
  if (data.generated && data.generated === lastGenerated) return
  lastGenerated = data.generated

  let medalByDate = {}

  const games = scrub((data.leagues && data.leagues[LEAGUE]) || {})

  if (!hasCurrentGames(games)) {
    LAST_GAMES = null
    await renderNoGames()
    return
  }
  showControls(true)

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

// Today's date where the games are dated: Eastern, as YYYY-MM-DD.
function etToday () {
  return new Date().toLocaleDateString('en-CA', {
    timeZone: 'America/New_York',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  })
}

// YYYY-MM-DD minus n days. Worked at noon UTC so no DST change can land it on
// the wrong day.
function daysBefore (iso, n) {
  const d = new Date(iso + 'T12:00:00Z')
  d.setUTCDate(d.getUTCDate() - n)
  return d.toISOString().slice(0, 10)
}

function hasCurrentGames (games) {
  const cutoff = daysBefore(etToday(), STALE_DAYS)
  return Object.values(games).some(g => g && (!g.date || g.date >= cutoff))
}

// The chips, Expand All, the legend and the polling rate all act on games;
// with none they are only chrome. style.display rather than `hidden`: the
// bar's CSS display would beat the attribute.
function showControls (on) {
  if (controls) controls.style.display = on ? '' : 'none'
}
// Hidden until the first poll says there is a board to control, so an empty
// day does not flash five chips and then drop them.
showControls(false)

// The one line for a board with nothing on it. Every branch is something the
// calendar actually says; when it says nothing (the request failed, or the
// season's dates are all behind us) the line claims no more than today.
async function nextGameText (today) {
  try {
    const res = await fetch(`${ESPN_SCOREBOARD}?dates=${today.replace(/-/g, '')}&limit=1`)
    const days = (((await res.json())?.leagues?.[0]?.calendar) || [])
      .map(c => String(c).slice(0, 10))
      .filter(d => /^\d{4}-\d\d-\d\d$/.test(d))
      .sort()
    const next = days.find(d => d >= today)
    if (!next) return 'No games today.'
    // They arrive with the Worker's first push of the day, at 11 ET.
    if (next === today) return 'Today’s games aren’t posted yet.'
    const when = new Date(next + 'T12:00:00').toLocaleDateString('en-US', {
      weekday: 'short',
      month: 'short',
      day: 'numeric'
    })
    return `No games until ${when}.`
  } catch (e) {
    return 'No games today.'
  }
}

let noGamesLine = null // { day, text }: one ESPN request a day, not a poll

async function renderNoGames () {
  showControls(false)
  const container = document.getElementById('games')
  if (!container) return
  const today = etToday()
  if (!noGamesLine || noGamesLine.day !== today) {
    noGamesLine = { day: today, text: nextGameText(today) }
  }
  container.innerHTML = boardLine(await noGamesLine.text)
}

// Body colour and a readable size: it is the whole page on a day like this,
// and .scoreboard-empty's grey has no dark-mode shade.
function boardLine (text) {
  return '<p class="scoreboard-empty" style="color:inherit;font-size:17px;margin:12px 0">' +
    `${text}</p>`
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

// Seconds left on a game clock, or null when there is no reading. "4:12" is
// minutes and seconds; under a minute the feed sends seconds alone ("45.3"),
// which used to come back Infinity - never "late", and an Infinity in the
// sort's arithmetic made the comparator NaN.
function parseClockToSeconds (clock) {
  if (clock === null || clock === undefined) return null
  const s = String(clock).trim()
  if (!s) return null
  const parts = s.split(':')
  if (parts.length > 2) return null
  const nums = parts.map(Number)
  if (nums.some(n => !isFinite(n) || n < 0)) return null
  return parts.length === 2 ? nums[0] * 60 + nums[1] : nums[0]
}

// Where a game is: the period as a number, and whether it is past
// regulation. The feed's periods are text - "1st", "2nd", "OT", "2OT" - and
// parseInt('OT') is NaN while parseInt('2OT') is 2, so an overtime read as
// the first half (or the second) and was never "close late". `g.overtime` is
// the feed's own flag.
function periodOf (g, regulation) {
  const p = String(g.period === null || g.period === undefined ? '' : g.period)
    .trim().toUpperCase()
  const m = /(\d*)\s*OT/.exec(p)
  if (m || g.overtime === true) {
    const extra = m && m[1] ? parseInt(m[1], 10) : 1
    return { num: regulation + extra, ot: true }
  }
  const n = parseInt(p, 10)
  return { num: isNaN(n) ? null : n, ot: false }
}

function enrichGame (g) {
  g.isP5 = g.is_p5 === true
  g.isAP = g.is_ap === true
  g.isMM = g.is_mm === true
  g.isNIT = g.is_nit === true

  const homeScore = Number(g.home_score)
  const awayScore = Number(g.away_score)
  const scoreDiff = Math.abs(homeScore - awayScore)

  const status = (g.status || '').toLowerCase()

  const isLive = status === 'in_progress' || status === 'live'
  const isFinal = status === 'final'
  const isHalftime = status === 'half_over'

  const clockSeconds = parseClockToSeconds(g.clock)

  const isWomens = LEAGUE === 'men' ? false : true

  // Final regulation period
  const finalPeriod = isWomens ? 4 : 2

  const period = periodOf(g, finalPeriod)
  // Any overtime is late: five minutes, every possession counts.
  const isLate =
    isLive &&
    (period.ot ||
      (period.num !== null &&
        period.num >= finalPeriod &&
        clockSeconds !== null &&
        clockSeconds <= 240))

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
  const regulation = LEAGUE === 'men' ? 2 : 4
  // The feed's status is lowercased above, so comparing it to 'OT' never
  // matched: an overtime is read from the period (or the feed's flag).
  const isOT = periodOf(g, regulation).ot

  function gameProgressScore (g) {
    const period = periodOf(g, regulation)
    const periodLength = LEAGUE === 'men' ? 1200 : 600 // 1200 sec - 20 min men | 600 sec - 10 min women
    const left = parseClockToSeconds(g.clock)

    if (period.ot) {
      // Past all of regulation, then into the overtimes (five minutes each).
      const extra = period.num - regulation
      return regulation * periodLength + (extra - 1) * 300 +
        (300 - Math.min(left === null ? 0 : left, 300))
    }

    const currentPeriod = period.num || 1
    const clockSeconds = left === null ? 0 : Math.min(left, periodLength)

    // Estimate % complete
    const secondsIntoGame =
      (currentPeriod - 1) * periodLength + (periodLength - clockSeconds)
    return secondsIntoGame
  }

  if (isLive && !isHalftime) {
    return gameProgressScore(g)
  }

  if (isOT && !isFinal) return gameProgressScore(g)
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
  return d.toLocaleDateString('en-US', {
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

// Every string in the feed is text - team names, venues, descriptions from
// theScore - but the board is built as HTML. Neutralised once, on arrival, so
// no render path can forget: < > and " are all markup needs to break out of
// text or a double-quoted attribute. & and ' stay, because the names are also
// the keys for logo lookups ("Texas A&M", "St. John's").
function scrub (v) {
  if (typeof v === 'string') {
    return v.replace(/[<>"]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c])
  }
  if (Array.isArray(v)) return v.map(scrub)
  if (v && typeof v === 'object') {
    const out = {}
    for (const k of Object.keys(v)) out[scrub(k)] = scrub(v[k])
    return out
  }
  return v
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

  const tourneyType = safe(g.game_type)
  const homeConf = safe(g.conference_home)
  const awayConf = safe(g.conference_away)
  const game_descrip = safe(g.game_description, null)

  // --- detect conference tournament ---
  g.isTournament = false
  g.tourneyName = null

  if (tourneyType === 'Postseason Tournament') {
    g.isTournament = true
    g.tourneyName = game_descrip
  }

  // --- LOCATION ROW (top) ---
  if (venue && loc) {
    parts.push({
      type: 'location',
      text: `${venue} • ${loc}`
    })
  } else if (venue) {
    parts.push({
      type: 'location',
      text: venue
    })
  } else if (loc) {
    parts.push({
      type: 'location',
      text: loc
    })
  }

  // --- BETTING ROW (bottom) ---
  const spread = safe(g.spread_close, null)
  const total = safe(g.total_close, null)

  if (spread !== null || total !== null) {
    const bits = []

    if (spread !== null && spread !== '') bits.push(`Spread: ${spread}`)
    if (total !== null && total !== '') bits.push(`O/U: ${total}`)

    parts.push({
      type: 'betting',
      text: bits.join(' • ')
    })
  }

  // --- GORDSTATS' CALL (cbb.game_model): favourite, margin, chance ---
  const hp = safe(g.pred_home, null)
  const ap = safe(g.pred_away, null)
  const hw = safe(g.home_win_prob, null)
  if (hp !== null && ap !== null && hw !== null) {
    const homeFav = hw >= 0.5
    const fav = homeFav ? (g.home_abb || getTeamName(g.home_team)) : (g.away_abb || getTeamName(g.away_team))
    const by = Math.abs(hp - ap).toFixed(1)
    const pct = Math.round((homeFav ? hw : 1 - hw) * 100)
    parts.push({
      type: 'pick',
      text: `GordStats: ${fav} by ${by} • ${pct}%`
    })
  }

  return parts
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

  function compareNumsGreater (a, b) {
    if (a == '—') {
      a = -999
    }
    if (b == '—') {
      b = -999
    }
    const na = Number(a)
    const nb = Number(b)

    if (isNaN(na) || isNaN(nb)) return { left: '', right: '' }

    if (na > nb) return { left: 'better', right: '' }
    if (nb > na) return { left: '', right: 'better' }
    return { left: '', right: '' }
  }

  function compareRecords (a, b) {
    function pct (rec) {
      if (!rec || rec === '—') return null

      const parts = rec.trim().split('-')
      if (parts.length !== 2) return null

      const w = Number(parts[0])
      const l = Number(parts[1])

      if (isNaN(w) || isNaN(l)) return null

      return w / (w + l)
    }

    const pa = pct(a)
    const pb = pct(b)

    if (pa === null || pb === null) return { left: '', right: '' }

    if (Math.abs(pa - pb) < 0.0001) {
      return { left: 'better', right: 'better' }
    }

    if (pa > pb) return { left: 'better', right: '' }

    return { left: '', right: 'better' }
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

  const wabAway = safe(g.wab_away, '—')
  const wabHome = safe(g.wab_home, '—')
  const lastTenHome = safe(g.home_last_ten, '—')
  const lastTenAway = safe(g.away_last_ten, '—')

  const rankCompare = compareNums(awayRank, homeRank)
  const recordCompare = compareRecords(lastTenAway, lastTenHome)
  const modelCompare = compareNums(awayModel, homeModel)
  const netCompare = compareNums(netAway, netHome)
  const bpiCompare = compareNums(bpiAway, bpiHome)
  const wabCompare = compareNumsGreater(wabAway, wabHome)

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
        <div class="label">Seed</div>
        <div class="value right">
        <span class="${rankCompare.right}">${homeRank}</span>
      </div>
      </div>

       <!-- RECORD LAST TEN -->
      <div class="expanded-row">
        <div class="value left">
          <span class="${recordCompare.left}">${lastTenAway}</span>
        </div>
        <div class="label">Record Last 10</div>
        <div class="value right">
          <span class="${recordCompare.right}">${lastTenHome}</span>
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

      <!-- WAB -->
      <div class="expanded-row">
        <div class="value left">
        <span class="${wabCompare.left}">${wabAway}</span>
      </div>
        <div class="label">WAB</div>
        <div class="value right">
        <span class="${wabCompare.right}">${wabHome}</span>
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

      case 'mm':
        return g.isMM === true

      case 'nit':
        return g.isNIT === true

      default:
        return true
    }
  })
}

function renderGames (games, medalByDate = {}) {
  if (!games) return

  Object.values(games).forEach(enrichGame)

  const filteredIds = filterGameIds(games)

  const container = document.getElementById('games')
  if (!container) return

  if (!filteredIds.length) {
    container.innerHTML = `<div class="scoreboard-empty">No games match this filter.</div>`
    return
  }

  const todayStr = etToday()

  const activeByDate = {}
  const pastByDate = {}

  for (const id of filteredIds) {
    const g = games[id]
    if (!g) continue

    const dateKey = g.date || 'unknown'

    const isPastFinal = g.status === 'final' && dateKey < todayStr

    const target = isPastFinal ? pastByDate : activeByDate

    if (!target[dateKey]) target[dateKey] = []
    target[dateKey].push({ id, g })
  }

  const activeDates = Object.keys(activeByDate).sort(
    (a, b) => new Date(a) - new Date(b)
  )

  const pastDates = Object.keys(pastByDate).sort(
    (a, b) => new Date(b) - new Date(a)
  )

  let html = ''

  function renderDay (date, source) {
    const gamesForDay = source[date]

    gamesForDay.sort((a, b) => {
      const pa = gamePriority(a.g)
      const pb = gamePriority(b.g)

      if (pa !== pb) return pb - pa

      const ta = gameTime(a.g)
      const tb = gameTime(b.g)

      if (ta !== tb) return ta - tb

      return 0
    })

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
              <span class="status-pill ${stCls}">${stText}</span>
            </div>

            <div class="game-head-center">
              ${renderTime(g)}
            </div>

            <div class="game-head-right">
              ${isAP ? `<span class="game-badge ap">TOP 25</span>` : ''}
              ${isP5 ? `<span class="game-badge p5">P5</span>` : ''}
              ${
                medal
                  ? `<span class="game-badge medal ${medalClass}" title="Top 3 rating">${medal}</span>`
                  : ''
              }
            </div>
          </header>

          <div class="teams">

            <div class="team-row ${g.awayWon ? 'winner' : ''}">
              <div class="team-left">
                <span class="team">
                  <img class="team-logo"
                       src="${teamLogo(awayTeam)}"
                       alt="${awayTeam}"
                       loading="lazy"
                       onerror="this.src='/assets/images/default.png'"/>
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
                  <img class="team-logo"
                       src="${teamLogo(homeTeam)}"
                       alt="${homeTeam}"
                       loading="lazy"
                       onerror="this.src='/assets/images/default.png'"/>
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

          <div class="tourney-slot">
            ${
              g.isTournament
                ? `<div class="tourney-bar ${getTourneyClass(
                    g.game_description
                  )}">
                    ${g.game_description}
                  </div>`
                : ''
            }
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

  // active section (today + future games)
  for (const date of activeDates) {
    renderDay(date, activeByDate)
  }

  // past games collapsible
  if (pastDates.length) {
    html += `
      <details class="past-games">
        <summary class="date-header">Past Games</summary>
    `

    for (const date of pastDates) {
      renderDay(date, pastByDate)
    }

    html += `</details>`
  }

  container.innerHTML = html

  // restore expanded state
  container.querySelectorAll('.game-card').forEach(card => {
    const id = card.dataset.gameId
    const expand = card.querySelector('.game-expand')
    if (!expand) return

    if (EXPAND_ALL || EXPANDED_GAMES.has(id)) {
      expand.hidden = false
      card.classList.add('open')
    }
  })

  // expand click handler
  container.querySelectorAll('.expand-toggle').forEach(toggle => {
    toggle.addEventListener('click', e => {
      const card = toggle.closest('.game-card')
      const expand = card.querySelector('.game-expand')
      const id = card.dataset.gameId

      if (!expand) return

      const isOpen = !expand.hidden

      container.querySelectorAll('.game-expand').forEach(el => {
        el.hidden = true
      })

      container.querySelectorAll('.game-card').forEach(c => {
        c.classList.remove('open')
      })

      if (!isOpen) {
        expand.hidden = false
        card.classList.add('open')
        EXPANDED_GAMES.clear()
        EXPANDED_GAMES.add(id)
      } else {
        EXPANDED_GAMES.delete(id)
      }

      e.stopPropagation()
    })
  })
}

// A failed first fetch (offline, the Worker slow to wake) used to throw out of
// start() before the interval was set, and the board never polled again.
async function safePoll () {
  try {
    await pollScores()
  } catch (e) {
    console.warn('scoreboard poll failed', e)
    // With the controls hidden until a poll lands, a first poll that fails
    // would otherwise leave nothing under the heading at all.
    const container = document.getElementById('games')
    if (container && !container.innerHTML.trim()) {
      container.innerHTML = boardLine('Scores didn’t load — trying again shortly.')
    }
  }
}

async function start () {
  try {
    await loadTeamLogos()
  } catch (e) {
    console.warn('team logos failed to load', e)
  }
  await safePoll()
  setInterval(() => { if (!document.hidden) safePoll() }, POLL_INTERVAL)
  // Back to a tab after a while: catch up at once rather than on the next tick.
  document.addEventListener('visibilitychange', () => { if (!document.hidden) safePoll() })
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
