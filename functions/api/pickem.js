/**
 * Reader pick'em: each week, pick the winners of about ten college games and
 * every NFL game, and rank them by confidence - 1 to N, N the number of games,
 * each value once. A correct pick earns its value; a tie, a cancelled or a
 * postponed game earns nothing. A "GordStats" entry plays the model's
 * favorites, ranked by its win chance.
 *
 *   GET  /api/pickem[?week=N]                 the week's slate, results, the
 *                                             weekly and season leaderboards;
 *                                             signed in, your name and picks too
 *   POST /api/pickem/picks <- { season, week, picks: { "<game id>": ["h"|"a", value] } }
 *                                             the reader's whole week (pickem/[[route]].js)
 *   POST /api/pickem/name  <- { name }        join, or rename (pickem/[[route]].js)
 *
 * The games are not in the database. The pipeline (gordstats.pickem) publishes
 * each week's slate - games, kickoffs, lock times, finals, the GordStats picks
 * - as static files beside the page, and this Function reads them through the
 * site's own assets (env.ASSETS):
 *
 *   /pickem/season.json              every week: [id, lock (epoch s), result,
 *                                    GordStats side, GordStats value] per game
 *   /pickem/<season>/week_NN.json    one week's slate as the page shows it
 *
 * Locking is enforced here, from those lock times and this Function's own
 * clock - never the reader's. A locked game's pick and its value cannot be
 * changed or added; the values it holds stay held, and the others are free
 * for the games still open.
 *
 * Scores are worked out at read time: the site is small, a week is one row a
 * reader (pickem_entries), and the public answer - the same for everyone
 * signed out - is shared through the Workers cache for a minute, as
 * functions/api/tweets.js shares its list. A signed-in reader's answer adds
 * their own row and name and is never cached. Nothing here ever reads or
 * returns an email address: the leaderboard shows the display name a reader
 * chose (pickem_players), and the GordStats name is reserved.
 *
 * Writes go through _lib/limits.js like every other: a save is one row, taken
 * from the reader's daily allowance and the site's ceiling.
 */
import { configured, json, readSession } from "./_lib/session.js";
import { refusal, spend } from "./_lib/limits.js";
import { cached } from "./_lib/cache.js";
import { readBody } from "./_lib/body.js";

export const SEASON_FILE = "/pickem/season.json";
export const CACHE_SECONDS = 60;
// Rows each leaderboard carries. The site is small; this only bounds a page.
export const BOARD_MAX = 100;
export const NAME_MIN = 3;
export const NAME_MAX = 20;
export const MODEL_NAME = "GordStats";
// A whole week's picks is under a kilobyte (30 games at ~25 bytes); a name
// is a few dozen bytes.
export const MAX_BODY = 4096;
const SIDES = new Set(["h", "a"]);
const WEEK = /^[1-9][0-9]?$/;
const GAME_ID = /^(cfb|nfl):[0-9]{1,15}$/;

export function weekFile(season, week) {
  return `/pickem/${season}/week_${String(week).padStart(2, "0")}.json`;
}

// --------------------------------------------------------------------------
// Display names
// --------------------------------------------------------------------------

// Slurs, base64 so this file does not read as a list of them: [stems matched
// anywhere in the name, words matched whole]. Short words are matched whole
// only, so "Spicy", "Raccoon" and "Tycoon" are fine.
const BLOCK = JSON.parse(atob(
  "W1sibmlnZ2VyIiwibmlnZ2EiLCJuaWdnYWgiLCJuaWdndWgiLCJmYWdnb3QiLCJmYWdvdCIsInJldGFyZCIsInRy"
  + "YW5ueSIsImtpa2UiLCJreWtlIiwiY2hpbmsiLCJ3ZXRiYWNrIiwiYmVhbmVyIiwicmFnaGVhZCIsInRvd2VsaGVh"
  + "ZCIsInNwaWNrIiwiZ29vayIsImdvbGxpd29nIiwic2hlbWFsZSIsImNvb25hc3MiLCJwb3JjaG1vbmtleSIsImp1"
  + "bmdsZWJ1bm55IiwiemlwcGVyaGVhZCJdLFsiZmFnIiwiZmFncyIsInNwaWMiLCJzcGljcyIsImNvb24iLCJjb29u"
  + "cyIsImR5a2UiLCJqYXAiLCJqYXBzIiwid29wIiwid29wcyIsInBha2kiLCJwYWtpcyIsIm5pZyIsIm5pZ3MiXV0="));
const RESERVED = new Set(["admin", "administrator", "moderator", "mod", "owner", "official",
  "support", "staff", "system", "null", "undefined", "anonymous", "model", "you"]);
const LEET = { 0: "o", 1: "i", 3: "e", 4: "a", 5: "s", 7: "t", 8: "b", 9: "g" };
const ALLOWED = /^[A-Za-z0-9](?:[A-Za-z0-9 ._'-]*[A-Za-z0-9])?$/;

/** The uniqueness key: lowercase letters and digits only ("Big Ten" = "bigten"). */
export function nameKey(name) {
  return String(name ?? "").toLowerCase().replace(/[^a-z0-9]/g, "");
}

function offensive(name) {
  const low = name.toLowerCase();
  const plain = low.replace(/[0-9]/g, (d) => LEET[d] || d);
  const joined = plain.replace(/[^a-z]/g, "");
  const words = plain.split(/[^a-z]+/).filter(Boolean);
  const [stems, whole] = BLOCK;
  if (stems.some((s) => joined.includes(s))) return true;
  return words.some((w) => whole.includes(w));
}

/**
 * A display name, checked -> { ok: true, name, key } | { ok: false, error }.
 * 3-20 characters of letters, digits, spaces and . _ ' -, starting and ending
 * with a letter or digit, at least one letter; spaces run together are one.
 * Not the site's own name or a staff-sounding one, and no slurs.
 */
export function validName(raw) {
  if (typeof raw !== "string") return { ok: false, error: "Choose a name to play under." };
  const name = raw.normalize("NFKC").trim().replace(/\s+/g, " ");
  if (name.length < NAME_MIN || name.length > NAME_MAX) {
    return { ok: false, error: `Names are ${NAME_MIN} to ${NAME_MAX} characters.` };
  }
  if (!ALLOWED.test(name) || !/[A-Za-z]/.test(name)) {
    return { ok: false, error: "Use letters, numbers, spaces and . _ ' - only, starting and "
      + "ending with a letter or number." };
  }
  const key = nameKey(name);
  if (key.length < NAME_MIN) return { ok: false, error: "That name is too short." };
  if (key.includes("gordstat") || RESERVED.has(key)) {
    return { ok: false, error: "That name is reserved - try another." };
  }
  if (offensive(name)) return { ok: false, error: "Please choose a different name." };
  return { ok: true, name, key };
}

// --------------------------------------------------------------------------
// The published files
// --------------------------------------------------------------------------

/**
 * One of the pipeline's files -> { status, data }. Through env.ASSETS - the
 * Pages project's own static files, no trip out - or, where a deploy has no
 * such binding, a plain fetch of the same address. `data` is null for
 * anything but a JSON 200.
 */
export async function asset(env, request, path) {
  const url = new URL(path, request.url).toString();
  let res;
  try {
    res = env.ASSETS && typeof env.ASSETS.fetch === "function"
      ? await env.ASSETS.fetch(url) : await fetch(url);
  } catch {
    return { status: 0, data: null };
  }
  if (!res || res.status !== 200) return { status: res ? res.status : 0, data: null };
  try {
    const data = await res.json();
    return { status: 200, data: data && typeof data === "object" ? data : null };
  } catch {
    return { status: 200, data: null };
  }
}

function weekOf(index, week) {
  return (index?.weeks || []).find((w) => w.w === week) || null;
}

/** {game id: [lock epoch s, result]} for one week of the season file. */
function gamesOf(wk) {
  const out = new Map();
  for (const g of wk?.g || []) {
    if (Array.isArray(g) && GAME_ID.test(String(g[0]))) out.set(String(g[0]), g);
  }
  return out;
}

// --------------------------------------------------------------------------
// Grading
// --------------------------------------------------------------------------

/** A stored week's picks -> {game id: [side, value, set at]}, anything malformed dropped. */
export function parsePicks(text) {
  let raw;
  try {
    raw = typeof text === "string" ? JSON.parse(text) : text;
  } catch {
    return {};
  }
  const out = {};
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return out;
  for (const [gid, p] of Object.entries(raw)) {
    if (!GAME_ID.test(gid) || !Array.isArray(p) || !SIDES.has(p[0])) continue;
    const conf = Number(p[1]);
    if (!Number.isInteger(conf) || conf < 1) continue;
    out[gid] = [p[0], conf, Number(p[2]) || 0];
  }
  return out;
}

/**
 * One reader's week -> { pts, right, of, max, n }: points, correct picks,
 * picks on decided games, the most still possible, picks made. A void game
 * (tie, cancelled, postponed) is decided and worth nothing.
 */
export function grade(picks, games) {
  const out = { pts: 0, right: 0, of: 0, max: 0, n: 0 };
  for (const [gid, p] of Object.entries(picks)) {
    const g = games.get(gid);
    if (!g) continue;
    out.n += 1;
    const res = g[2];
    if (res === "h" || res === "a") {
      out.of += 1;
      if (p[0] === res) {
        out.pts += p[1];
        out.right += 1;
      }
    } else if (res !== "v") {
      out.max += p[1];
    }
  }
  out.max += out.pts;
  return out;
}

/** The GordStats entry's picks for one week of the season file. */
export function modelPicks(wk) {
  const out = {};
  for (const g of wk?.g || []) {
    if (SIDES.has(g[3]) && Number.isInteger(g[4])) out[g[0]] = [g[3], g[4], 0];
  }
  return out;
}

/** Highest points first, then most right; equal on both share a rank. */
export function ranked(rows) {
  const sorted = [...rows].sort((x, y) => y.pts - x.pts || y.right - x.right
    || x.name.toLowerCase().localeCompare(y.name.toLowerCase()));
  let rank = 0;
  return sorted.map((row, i) => {
    const prev = sorted[i - 1];
    if (!prev || prev.pts !== row.pts || prev.right !== row.right) rank = i + 1;
    return { r: rank, ...row };
  });
}

/**
 * Both leaderboards and every week's summary, from the season file and the
 * stored entries ([{week, name, picks}]). Entries with no picks are left off.
 */
export function boards(index, entries, week) {
  const weeks = new Map((index?.weeks || []).map((wk) => [wk.w, gamesOf(wk)]));
  const perWeek = new Map();
  const season = new Map();
  const add = (w, name, g, model) => {
    if (!g.n) return;
    if (!perWeek.has(w)) perWeek.set(w, []);
    perWeek.get(w).push({ name, pts: g.pts, right: g.right, of: g.of, max: g.max,
                          ...(model ? { gs: true } : {}) });
    const key = model ? "\u0000model" : name.toLowerCase();
    const s = season.get(key) || { name, pts: 0, right: 0, of: 0, wk: 0,
                                   ...(model ? { gs: true } : {}) };
    s.pts += g.pts;
    s.right += g.right;
    s.of += g.of;
    s.wk += 1;
    season.set(key, s);
  };
  for (const e of entries) {
    const games = weeks.get(Number(e.week));
    if (!games || typeof e.name !== "string") continue;
    add(Number(e.week), e.name, grade(parsePicks(e.picks), games), false);
  }
  for (const wk of index?.weeks || []) {
    add(wk.w, MODEL_NAME, grade(modelPicks(wk), weeks.get(wk.w)), true);
  }
  const summary = (index?.weeks || []).map((wk) => {
    const rows = ranked(perWeek.get(wk.w) || []);
    const people = rows.filter((r) => !r.gs);
    const model = rows.find((r) => r.gs);
    const top = people.length && people[0].pts > 0
      ? people.filter((r) => r.r === people[0].r).slice(0, 3).map((r) => ({ name: r.name, pts: r.pts }))
      : [];
    return { w: wk.w, label: String(wk.label || `Week ${wk.w}`), sub: String(wk.sub || ""),
             n: (wk.g || []).length, done: Boolean(wk.done), players: people.length,
             top, gs: model ? model.pts : null };
  });
  return {
    weeks: summary,
    week: ranked(perWeek.get(week) || []).slice(0, BOARD_MAX),
    season: ranked([...season.values()]).slice(0, BOARD_MAX),
  };
}

// --------------------------------------------------------------------------
// Errors
// --------------------------------------------------------------------------

/**
 * The tables arrive in a migration applied by hand, which can lag the deploy:
 * "no such table" is an answer, not a 500. A session whose account has since
 * been deleted fails the foreign key on a write: "signed out".
 */
class Migrating extends Error {}
class SignedOut extends Error {}
class Taken extends Error {}

async function db(run) {
  try {
    return await run();
  } catch (err) {
    const text = String(err && err.message || err);
    if (text.includes("no such table")) throw new Migrating(text);
    if (text.includes("FOREIGN KEY constraint failed")) throw new SignedOut(text);
    if (text.includes("UNIQUE constraint failed") && text.includes("name_key")) throw new Taken(text);
    throw err;
  }
}

const TAKEN = "That name is taken - try another.";

function answerFor(err) {
  if (err instanceof Migrating) {
    return json({ ok: false, migrating: true,
      error: "Pick'em is not switched on for this site yet." }, 503);
  }
  if (err instanceof SignedOut) return json({ ok: false, error: "Sign in again to do that." }, 401);
  if (err instanceof Taken) return json({ ok: false, taken: true, error: TAKEN }, 409);
  throw err;
}

async function guard(request, env) {
  if (!configured(env)) return json({ ok: false, error: "accounts are not configured" }, 503);
  const session = await readSession(request, env);
  if (!session) return json({ ok: false, signedIn: false, error: "Sign in to play." }, 401);
  return session;
}

/** A JSON object body, capped -> { body } | { error: Response }. */
async function readJson(request) {
  const read = await readBody(request, MAX_BODY);
  if (read.error) return { error: read.error };
  const body = read.data;
  return body && typeof body === "object" && !Array.isArray(body)
    ? { body } : { error: json({ ok: false, error: "expected JSON" }, 400) };
}

// --------------------------------------------------------------------------
// GET
// --------------------------------------------------------------------------

// Every entry of the season with its player's name: one row per reader per
// week, a range of pickem_entries' key; names by pickem_players' key.
const ENTRIES =
  `SELECT e.week, e.picks, p.name
     FROM pickem_entries e JOIN pickem_players p ON p.user_id = e.user_id
    WHERE e.season = ?`;

/** The answer everyone signed out gets: { status, body } for _lib/cache.js. */
async function publicView(request, env, want) {
  const idx = await asset(env, request, SEASON_FILE);
  if (idx.status === 404) {
    // Nothing published yet (before the season's first slate).
    return { status: 200, body: JSON.stringify({ ok: true, configured: configured(env),
      season: null, current: null, week: null, weeks: [], slate: null,
      board: { week: [], season: [] } }) };
  }
  const index = idx.data;
  if (!index || !Array.isArray(index.weeks)) {
    return { status: 503, body: JSON.stringify({ ok: false, error: "Pick'em could not load just now." }) };
  }
  const week = want ?? index.current;
  if (!weekOf(index, week)) {
    return { status: 404, body: JSON.stringify({ ok: false, error: "There is no such week." }) };
  }
  const slate = await asset(env, request, weekFile(index.season, week));
  if (!slate.data || !Array.isArray(slate.data.games)) {
    return { status: 503, body: JSON.stringify({ ok: false, error: "Pick'em could not load just now." }) };
  }
  let entries = [];
  let migrating = false;
  if (env.DB) {
    try {
      entries = (await db(() => env.DB.prepare(ENTRIES).bind(index.season).all())).results || [];
    } catch (err) {
      if (!(err instanceof Migrating)) throw err;
      migrating = true;
    }
  }
  const b = boards(index, entries, week);
  const body = { ok: true, configured: configured(env), season: index.season,
                 current: index.current, week, weeks: b.weeks, slate: slate.data,
                 board: { week: b.week, season: b.season } };
  if (migrating) body.migrating = true;
  return { status: 200, body: JSON.stringify(body) };
}

/** {game id: [side, value]}: a reader's picks as the page takes them. */
function shown(picks) {
  const out = {};
  for (const [gid, p] of Object.entries(picks)) out[gid] = [p[0], p[1]];
  return out;
}

export async function onRequestGet(context) {
  const { request, env } = context;
  const url = new URL(request.url);
  const raw = url.searchParams.get("week");
  if (raw !== null && !WEEK.test(raw)) return json({ ok: false, error: "There is no such week." }, 400);
  const want = raw === null ? null : Number(raw);

  let session = null;
  if (configured(env)) {
    try {
      session = await readSession(request, env);
    } catch (err) {
      // The database did not answer: still show the slate, as signed out.
      console.error("pickem: session", err);
    }
  }
  const key = `${url.origin}/api/pickem?public=1&week=${want ?? "current"}`;
  const out = await cached(context, key, CACHE_SECONDS, () => publicView(request, env, want));
  const now = Date.now();

  if (!session || out.status !== 200) {
    // Lock times are judged against the server's clock: `now` rides along
    // outside the cached part, so the page can say what is locked even if
    // the reader's own clock is off.
    const body = out.status === 200
      ? `{"now":${now},"signedIn":false,${out.body.slice(1)}` : out.body;
    return new Response(body, { status: out.status, headers: {
      "content-type": "application/json; charset=utf-8", "cache-control": "no-store" } });
  }

  const view = JSON.parse(out.body);
  view.now = now;
  view.signedIn = true;
  view.me = null;
  view.mine = {};
  if (view.season && !view.migrating) {
    try {
      const me = await db(() => env.DB.prepare(
        "SELECT name FROM pickem_players WHERE user_id = ?").bind(session.uid).first());
      view.me = me ? { name: me.name } : null;
      if (view.week) {
        const row = await db(() => env.DB.prepare(
          "SELECT picks FROM pickem_entries WHERE season = ? AND user_id = ? AND week = ?")
          .bind(view.season, session.uid, view.week).first());
        view.mine = shown(parsePicks(row?.picks));
      }
    } catch (err) {
      if (!(err instanceof Migrating)) throw err;
      view.migrating = true;
    }
  }
  return json(view);
}

// --------------------------------------------------------------------------
// POST /api/pickem/picks
// --------------------------------------------------------------------------

/**
 * The reader's week as it should be once `want` is applied at `nowMs`
 * -> { ok: true, picks } | { ok: false, status, error, game? }.
 *
 * `want` is the whole week as the page holds it. For a game still open it is
 * the truth (absent = no pick). For a locked game the stored pick stands: a
 * different side or value - or a pick where there was none - is refused, and
 * leaving it out changes nothing. Every value is used once, 1..N.
 */
export function merge(old, want, games, nowMs) {
  const n = games.size;
  const sec = Math.floor(nowMs / 1000);
  const out = {};
  for (const [gid, g] of games) {
    const o = old[gid];
    const w = want[gid];
    const locked = nowMs >= Number(g[1]) * 1000;
    if (locked) {
      if (w && (!o || o[0] !== w[0] || o[1] !== w[1])) {
        return { ok: false, status: 409, game: gid,
                 error: "A game has kicked off since - its pick is locked and was not changed." };
      }
      if (o) out[gid] = o;
    } else if (w) {
      out[gid] = o && o[0] === w[0] && o[1] === w[1] ? o : [w[0], w[1], sec];
    }
  }
  const seen = new Set();
  for (const p of Object.values(out)) {
    if (p[1] < 1 || p[1] > n) {
      return { ok: false, status: 400, error: `Points go from 1 to ${n}.` };
    }
    if (seen.has(p[1])) {
      return { ok: false, status: 400, error: "Each point value can be used only once." };
    }
    seen.add(p[1]);
  }
  return { ok: true, picks: out };
}

/** The body's picks -> {game id: [side, value]} | null if malformed. */
function wanted(raw, games) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const out = {};
  const entries = Object.entries(raw);
  if (entries.length > games.size) return null;
  for (const [gid, p] of entries) {
    if (!games.has(gid) || !Array.isArray(p) || p.length < 2 || !SIDES.has(p[0])) return null;
    const conf = p[1];
    if (!Number.isInteger(conf)) return null;
    out[gid] = [p[0], conf];
  }
  return out;
}

function same(a, b) {
  const ka = Object.keys(a);
  if (ka.length !== Object.keys(b).length) return false;
  return ka.every((k) => b[k] && a[k][0] === b[k][0] && a[k][1] === b[k][1]);
}

const READ_ENTRY =
  "SELECT picks, rev FROM pickem_entries WHERE season = ? AND user_id = ? AND week = ?";
// Written against the revision read: of two saves racing, the second finds
// the row moved on and starts again from what the first wrote.
const UPDATE_ENTRY =
  `UPDATE pickem_entries SET picks = ?1, rev = rev + 1, updated_at = ?2
    WHERE season = ?3 AND user_id = ?4 AND week = ?5 AND rev = ?6`;
const INSERT_ENTRY =
  `INSERT INTO pickem_entries (season, user_id, week, picks, rev, updated_at)
   VALUES (?1, ?2, ?3, ?4, 1, ?5)
   ON CONFLICT (season, user_id, week) DO NOTHING`;

export async function savePicks({ request, env }) {
  const session = await guard(request, env);
  if (session instanceof Response) return session;
  const read = await readJson(request);
  if (read.error) return read.error;
  const body = read.body;

  const idx = await asset(env, request, SEASON_FILE);
  if (!idx.data || !Array.isArray(idx.data.weeks)) {
    return json({ ok: false, error: "Pick'em could not load just now. Try again in a minute." }, 503);
  }
  const index = idx.data;
  if (Number(body.season) !== Number(index.season)) {
    return json({ ok: false, error: "That season is over." }, 409);
  }
  const wk = weekOf(index, Number(body.week));
  if (!wk) return json({ ok: false, error: "There is no such week." }, 404);
  const games = gamesOf(wk);
  const want = wanted(body.picks, games);
  if (!want) return json({ ok: false, error: "Those picks don't match this week's games." }, 400);

  try {
    const player = await db(() => env.DB.prepare(
      "SELECT name FROM pickem_players WHERE user_id = ?").bind(session.uid).first());
    if (!player) {
      return json({ ok: false, need_name: true,
                    error: "Choose a name to play under first." }, 409);
    }
    for (let attempt = 0; attempt < 3; attempt += 1) {
      const row = await db(() => env.DB.prepare(READ_ENTRY)
        .bind(index.season, session.uid, wk.w).first());
      const old = parsePicks(row?.picks);
      const now = Date.now();
      const merged = merge(old, want, games, now);
      if (!merged.ok) {
        return json({ ok: false, error: merged.error, game: merged.game || null,
                      picks: shown(old) }, merged.status);
      }
      if (same(merged.picks, old) && (row || !Object.keys(merged.picks).length)) {
        return json({ ok: true, saved: false, picks: shown(old) });
      }
      const allowed = await spend(env.DB, session.uid, 1);
      if (!allowed.ok) return refusal(allowed, "That's a lot of saves for one day - try again tomorrow.");
      const stamp = new Date(now).toISOString();
      const text = JSON.stringify(merged.picks);
      const put = row
        ? await db(() => env.DB.prepare(UPDATE_ENTRY)
          .bind(text, stamp, index.season, session.uid, wk.w, row.rev).run())
        : await db(() => env.DB.prepare(INSERT_ENTRY)
          .bind(index.season, session.uid, wk.w, text, stamp).run());
      if (put?.meta?.changes) return json({ ok: true, saved: true, picks: shown(merged.picks) });
    }
    return json({ ok: false, error: "Saved from somewhere else at the same moment - try again." }, 409);
  } catch (err) {
    return answerFor(err);
  }
}

// --------------------------------------------------------------------------
// POST /api/pickem/name
// --------------------------------------------------------------------------

const UPSERT_NAME =
  `INSERT INTO pickem_players (user_id, name, name_key, created_at, updated_at)
   VALUES (?1, ?2, ?3, ?4, ?4)
   ON CONFLICT (user_id) DO UPDATE
      SET name = excluded.name, name_key = excluded.name_key, updated_at = excluded.updated_at`;

export async function saveName({ request, env }) {
  const session = await guard(request, env);
  if (session instanceof Response) return session;
  const read = await readJson(request);
  if (read.error) return read.error;
  const body = read.body;
  const check = validName(body.name);
  if (!check.ok) return json({ ok: false, error: check.error }, 400);
  try {
    const mine = await db(() => env.DB.prepare(
      "SELECT name FROM pickem_players WHERE user_id = ?").bind(session.uid).first());
    if (mine && mine.name === check.name) return json({ ok: true, saved: false, name: mine.name });
    // The cheap refusal first: a name someone else holds costs no write.
    const holder = await db(() => env.DB.prepare(
      "SELECT user_id FROM pickem_players WHERE name_key = ?").bind(check.key).first());
    if (holder && holder.user_id !== session.uid) {
      return json({ ok: false, taken: true, error: TAKEN }, 409);
    }
    const allowed = await spend(env.DB, session.uid, 1);
    if (!allowed.ok) return refusal(allowed, "Too many changes today - try again tomorrow.");
    await db(() => env.DB.prepare(UPSERT_NAME)
      .bind(session.uid, check.name, check.key, new Date().toISOString()).run());
    return json({ ok: true, saved: true, name: check.name });
  } catch (err) {
    return answerFor(err);
  }
}
