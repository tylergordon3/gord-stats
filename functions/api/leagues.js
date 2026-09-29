/**
 * The signed-in reader's own fantasy leagues.
 *
 *   GET    /api/leagues                          -> { leagues: [...] }
 *
 * `provider_user_id` comes back with each row - the reader's own Sleeper user
 * id. It is what tells a page which of the twelve rosters is theirs, so "My
 * Team" opens on their team rather than on whoever holds roster 1.
 *   POST   /api/leagues  <- { provider, username }    every league they are in
 *   POST   /api/leagues  <- { provider, league_id }   one league, by id
 *   DELETE /api/leagues?provider=..&league_id=..      remove
 *
 * The username form is the one people should use: Sleeper will say which
 * leagues an account is in, so nobody has to go and copy a sixteen-digit id
 * out of a URL - once per league, which is where the old flow lost people.
 * Each league's own team name is stored with it, because two leagues named
 * the same thing are otherwise indistinguishable in a picker, and people do
 * name them the same thing.
 *
 * Sleeper, and ESPN leagues set public. No credentials are stored because
 * none are needed: Sleeper's API is keyless, and ESPN's answers a public
 * league to anyone (see addEspn). Yahoo was here briefly and came out again - its public API serves
 * only leagues a commissioner has set public, and reaching a private one means
 * OAuth, an app registration and stored refresh tokens. That would turn a
 * database worth very little if taken into one holding read access to other
 * people's accounts, which is not a trade worth making for a league nobody has
 * asked for yet. "Ask your commissioner to make it public" costs nothing.
 *
 * The `provider` column holds "sleeper" or "espn".
 *
 * Adding a league verifies it against Sleeper first, so a typo is caught here
 * rather than becoming a row that never resolves to anything.
 *
 * What one POST may cost is bounded three ways, because each used to be
 * open. Calls to Sleeper: at most FETCH_BUDGET a request (a username once fanned
 * out to ~480, and Workers Free stops a request at 50), spent on what matters
 * most first, with anything it could not cover said so in the answer. How
 * often: one sync per account per REFRESH_SECONDS, claimed atomically on the
 * users row - it was a read-then-write on the leagues' own timestamps, which
 * parallel POSTs all passed and which deleting a league reset. And rows: MAX
 * leagues and MAX_ROWS rows for the account as a whole, not per sync, only
 * the rows that changed written, all inside the daily allowance in
 * _lib/limits.js.
 */
import { configured, json, readSession } from "./_lib/session.js";
import { claim, secondsLeft, spend, waiting } from "./_lib/limits.js";

/**
 * The leagues table arrives in a migration, which is applied by hand and can
 * lag the deploy that needs it. Until it lands, every query here throws "no
 * such table" - a 500 and a blank page. Answer 503 with something true
 * instead, so the page can say the feature is not switched on yet rather than
 * looking broken.
 */
async function db(run) {
  try {
    return { ok: true, value: await run() };
  } catch (err) {
    if (String(err && err.message || err).includes("no such table")) {
      return { ok: false, response: json({ ok: false, migrating: true,
        error: "League sync is not switched on for this site yet." }, 503) };
    }
    throw err;
  }
}

// Distinct leagues one account can hold - a lineage, however many seasons it
// has. It used to be compared with a count of rows, so a reader in four
// leagues with five seasons each could never add a fifth by id.
const MAX = 20;
const MAX_SEASONS = 12;    // seasons walked back per league
const MAX_ROWS = 120;      // rows one account can hold, across every sync
// Sleeper ids are long digit strings. An ESPN league is stored per season as
// "espn:<season>:<id>" (gordstats/league_api.py), and may be given bare.
const SHAPES = { sleeper: /^[0-9]{6,32}$/, espn: /^(?:espn:(\d{4}):)?(\d{1,12})$/ };
const SPORT = { sleeper: "nfl", espn: "nfl" };
const ESPN = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl";
// How long a reader has to wait between syncs. The providers are generous,
// but a refresh button with no floor is a button that gets held down. Adding
// one league by id costs a dozen calls rather than dozens, so it waits less.
const REFRESH_SECONDS = 300;
const ADD_SECONDS = 60;
// Workers Free allows 50 subrequests a request, and D1 queries count among
// them; this leaves room for the half-dozen this endpoint makes.
const FETCH_BUDGET = 40;
const TIMEOUT_MS = 8000;
const SLEEPER = "https://api.sleeper.app/v1";
// Sleeper usernames: what its own signup allows, and nothing that could be
// read as a path.
const USERNAME = /^[A-Za-z0-9_.-]{1,64}$/;
const CLAIM = "last_league_sync";

export async function onRequestGet({ request, env }) {
  // Signed out is an answer here, not an error: every fantasy page asks this
  // on load, and a 401 put a red console error on each of them for every
  // reader who never signs in (the 2026-09-28 phone audit). POST and DELETE
  // still answer 401.
  if (configured(env) && !(await readSession(request, env))) {
    return json({ ok: true, signedIn: false, leagues: [] });
  }
  const session = await guard(request, env);
  if (session instanceof Response) return session;

  const got = await db(() => env.DB.prepare(
    `SELECT provider, sport, league_id, name, season, team_name, lineage_id,
            provider_user_id, last_synced_at
       FROM leagues WHERE user_id = ? ORDER BY name, season DESC`)
    .bind(session.uid).all());
  if (!got.ok) return got.response;

  return json({ leagues: got.value.results || [] });
}

export async function onRequestPost({ request, env }) {
  const session = await guard(request, env);
  if (session instanceof Response) return session;

  let body;
  try {
    body = await request.json();
  } catch {
    return json({ ok: false, error: "expected JSON" }, 400);
  }

  const provider = String(body?.provider || "").toLowerCase();
  if (!SHAPES[provider]) return json({ ok: false, error: "unknown provider" }, 400);

  const username = String(body?.username || "").trim();
  if (username) return syncAll(env, session, provider, username);

  const leagueId = String(body?.league_id || "").trim();
  if (!SHAPES[provider].test(leagueId)) {
    return json({ ok: false, error: provider === "espn"
      ? "An ESPN league id is the leagueId number in the league's web address."
      : "A Sleeper league id is the long number in the league's web address." }, 400);
  }
  if (provider === "espn") return addEspn(env, session, leagueId);
  return addOne(env, session, provider, leagueId);
}

export async function onRequestDelete({ request, env }) {
  const session = await guard(request, env);
  if (session instanceof Response) return session;

  const url = new URL(request.url);
  const provider = String(url.searchParams.get("provider") || "").toLowerCase();
  const leagueId = String(url.searchParams.get("league_id") || "").trim();
  if (!SHAPES[provider] || !leagueId) {
    return json({ ok: false, error: "provider and league_id are required" }, 400);
  }

  // Removing a league means the league, not one season of it: a row's
  // lineage takes its whole history with it. Falling back to the single id
  // covers rows stored before lineage existed.
  const row = await db(() => env.DB.prepare(
    "SELECT lineage_id FROM leagues WHERE user_id = ? AND provider = ? AND league_id = ?")
    .bind(session.uid, provider, leagueId).first());
  if (!row.ok) return row.response;

  const lineage = row.value?.lineage_id;
  const gone = await db(() => (lineage
    ? env.DB.prepare(
        "DELETE FROM leagues WHERE user_id = ? AND provider = ? AND lineage_id = ?")
        .bind(session.uid, provider, lineage)
    : env.DB.prepare(
        "DELETE FROM leagues WHERE user_id = ? AND provider = ? AND league_id = ?")
        .bind(session.uid, provider, leagueId)).run());
  if (!gone.ok) return gone.response;

  return json({ ok: true });
}

// Every row of a sync in one statement, the rows as one JSON parameter: a
// statement per row could meet D1's limit on queries per request (50 on the
// free plan) well short of MAX_ROWS. "WHERE true" is SQLite's price for an
// upsert fed by a SELECT.
const UPSERT =
  `INSERT INTO leagues (user_id, provider, sport, league_id, name, season,
                        team_name, provider_user_id, lineage_id,
                        created_at, last_synced_at)
   SELECT ?1, ?2, ?3,
          json_extract(value, '$.league_id'), json_extract(value, '$.name'),
          json_extract(value, '$.season'), json_extract(value, '$.team_name'),
          json_extract(value, '$.provider_user_id'), json_extract(value, '$.lineage_id'),
          ?4, ?4
     FROM json_each(?5) WHERE true
   ON CONFLICT (user_id, provider, league_id)
   DO UPDATE SET name = excluded.name, season = excluded.season,
                 team_name = COALESCE(excluded.team_name, leagues.team_name),
                 provider_user_id = COALESCE(excluded.provider_user_id,
                                             leagues.provider_user_id),
                 lineage_id = COALESCE(excluded.lineage_id, leagues.lineage_id),
                 last_synced_at = excluded.last_synced_at`;

const STORED =
  `SELECT league_id, name, season, team_name, provider_user_id, lineage_id,
          last_synced_at
     FROM leagues WHERE user_id = ? AND provider = ?`;

/**
 * Sleeper, on a budget: at most `limit` calls for the whole request, counted
 * before each goes out so calls made in parallel cannot overshoot it. A call
 * the budget will not cover is never made - it resolves to { skipped: true }
 * and the caller reports it, rather than treating it as Sleeper's answer.
 */
export function asker(limit) {
  const ask = async (path) => {
    if (ask.used >= limit) {
      ask.skipped += 1;
      return { skipped: true };
    }
    ask.used += 1;
    try {
      const r = await fetch(`${SLEEPER}/${path}`, { signal: AbortSignal.timeout(TIMEOUT_MS) });
      if (!r.ok) return { ok: false, status: r.status };
      return { ok: true, data: await r.json() };
    } catch {
      return { ok: false, status: 0 };             // unreachable, or timed out
    }
  };
  ask.used = 0;
  ask.skipped = 0;
  ask.left = () => limit - ask.used;
  return ask;
}

/**
 * The reader's team name in one league: null when Sleeper has none to give,
 * undefined when the budget did not cover asking - which the answer reports.
 */
async function teamIn(ask, leagueId, userId) {
  const got = await ask(`league/${leagueId}/users`);
  if (got.skipped) return undefined;
  if (!got.ok || !Array.isArray(got.data)) return null;
  const mine = got.data.find((x) => x.user_id === userId);
  return (mine?.metadata?.team_name) || mine?.display_name || null;
}

function chainFrom(data, current) {
  const id = String(data.league_id);
  return {
    rows: [{ league_id: id, name: data.name || null, season: String(data.season || ""),
             team_name: null, current }],
    next: data.previous_league_id ? String(data.previous_league_id) : null,
  };
}

/**
 * Walk every chain back through its earlier seasons, one step for each league
 * in turn, so a budget that runs short cuts the oldest seasons of every
 * league rather than all of the last one.
 *
 * Sleeper gives every season its own league id and links them backwards with
 * previous_league_id - the site's own league chains 2026 to 2023 that way.
 * Capped, and guarded against a cycle: these ids come from an API, and a loop
 * here would be an endless one. A chain left with `next` set ran out of
 * budget; one whose call failed simply ends, as it always did.
 */
async function walkBack(ask, chains) {
  const seen = new Set(chains.flatMap((c) => c.rows.map((r) => r.league_id)));
  for (;;) {
    const step = chains.filter((c) => c.next && c.rows.length < MAX_SEASONS);
    if (!step.length || ask.left() <= 0) break;
    await Promise.all(step.map(async (c) => {
      const got = await ask(`league/${c.next}`);
      if (got.skipped) return;
      c.next = null;
      if (!got.ok || !got.data?.league_id || seen.has(String(got.data.league_id))) return;
      const older = chainFrom(got.data, false);
      seen.add(older.rows[0].league_id);
      c.rows.push(older.rows[0]);
      c.next = older.next;
    }));
  }
}

/**
 * The oldest id in the chain names the lineage, so every season of one league
 * groups under it however many seasons are added later. A chain the budget
 * cut short has not reached its oldest id, so it keeps the lineage already
 * stored for that league, if there is one, rather than inventing another.
 */
function lineageOf(chain, stored) {
  const oldest = chain.rows[chain.rows.length - 1].league_id;
  if (!chain.next) return oldest;
  return stored.get(chain.rows[0].league_id)?.lineage_id || oldest;
}

/** Rows in the order they should claim room: this season of every league, then back. */
function flatten(chains, stored) {
  const out = [];
  const depth = Math.max(0, ...chains.map((c) => c.rows.length));
  chains.forEach((c) => { c.lineage = lineageOf(c, stored); });
  for (let d = 0; d < depth; d += 1) {
    for (const c of chains) if (c.rows[d]) out.push({ ...c.rows[d], lineage_id: c.lineage });
  }
  return out;
}

function moved(old, r) {
  return old.name !== r.name || old.season !== r.season
    || (r.team_name != null && r.team_name !== old.team_name)
    || (r.provider_user_id != null && r.provider_user_id !== old.provider_user_id)
    || (r.lineage_id != null && r.lineage_id !== old.lineage_id);
}

/**
 * Which fetched rows to write, against what the account already holds.
 *
 * A stored row is written again only if something in it moved, or if it is a
 * current season - its last_synced_at is the "synced" time the page shows. A
 * new row needs room: MAX distinct leagues and MAX_ROWS rows for the account
 * as a whole, however many syncs and usernames it took to get there. Rows
 * arrive current seasons first, so a full account keeps this season of every
 * league ahead of the history of a few.
 * -> { write, kept, dropped: { leagues, rows } }
 */
export function plan(stored, fetched, maxLeagues = MAX, maxRows = MAX_ROWS) {
  const have = new Map(stored.map((r) => [r.league_id, r]));
  const incoming = new Set(fetched.map((r) => r.league_id));
  // Leagues held by rows this sync does not touch; the rest are counted by
  // the lineage this sync gives them, so a row from before lineage existed
  // is not one league under its own id and another under its lineage.
  const leagues = new Set(stored.filter((r) => !incoming.has(r.league_id))
    .map((r) => r.lineage_id || r.league_id));
  let rows = stored.length;
  const write = [];
  const kept = [];
  for (const r of fetched) {
    const old = have.get(r.league_id);
    if (!old) {
      if (!leagues.has(r.lineage_id) && leagues.size >= maxLeagues) continue;
      if (rows >= maxRows) continue;
      rows += 1;
    }
    leagues.add(r.lineage_id);
    kept.push(r);
    if (!old || r.current || moved(old, r)) write.push(r);
  }
  const keptLeagues = new Set(kept.map((r) => r.lineage_id));
  return {
    write, kept,
    dropped: {
      leagues: new Set(fetched.map((r) => r.lineage_id).filter((l) => !keptLeagues.has(l))).size,
      rows: fetched.length - kept.length,
    },
  };
}

/**
 * The early answer, from a plain read: 429 if this account synced too
 * recently, 503 if the leagues table is not there yet, otherwise null.
 *
 * Before migration 004 there is no users.last_league_sync; the old per-row
 * timestamps stand in for it, so deploying ahead of the migration is no
 * weaker than what ran before.
 */
async function tooSoon(env, uid, seconds, legacy) {
  let left = await waiting(env.DB, uid, CLAIM, seconds);
  if (left === null) {
    const got = await db(() => legacy.first());
    if (!got.ok) return got.response;
    left = secondsLeft(got.value?.at, REFRESH_SECONDS, new Date());
  }
  return left > 0 ? wait(left, "just refreshed") : null;
}

function wait(seconds, error) {
  return json({ ok: false, error, retry_after: seconds }, 429,
    { "retry-after": String(seconds) });
}

/** This account's stored rows for `provider`. -> { ok, rows } | { ok: false, response } */
async function storedRows(env, session, provider) {
  const got = await db(() => env.DB.prepare(STORED).bind(session.uid, provider).all());
  return got.ok ? { ok: true, rows: got.value.results || [] } : got;
}

/** Plan against what is stored, spend the allowance, write. -> Response | result */
async function store(env, session, provider, stored, fetched) {
  const { write, kept, dropped } = plan(stored, fetched);

  const allowed = await spend(env.DB, session.uid, write.length);
  if (!allowed.ok) return wait(allowed.retryAfter, "too many changes today");

  const now = new Date().toISOString();
  if (write.length) {
    const rows = write.map((r) => ({
      league_id: r.league_id, name: r.name, season: r.season, team_name: r.team_name ?? null,
      provider_user_id: r.provider_user_id ?? null, lineage_id: r.lineage_id }));
    const wrote = await db(() => env.DB.prepare(UPSERT).bind(
      session.uid, provider, SPORT[provider], now, JSON.stringify(rows)).run());
    if (!wrote.ok) return wrote.response;
  }

  // What the account now holds of what was fetched, as it is stored.
  const written = new Set(write.map((r) => r.league_id));
  const byId = new Map(stored.map((r) => [r.league_id, r]));
  const leagues = kept.map((r) => {
    const old = byId.get(r.league_id) || {};
    return { provider, sport: SPORT[provider], league_id: r.league_id, name: r.name,
             season: r.season, team_name: r.team_name ?? old.team_name ?? null,
             lineage_id: r.lineage_id,
             last_synced_at: written.has(r.league_id) ? now : old.last_synced_at };
  });
  return { leagues, dropped, now };
}

/**
 * What a sync could not do, or null when it did everything. Said in the
 * answer rather than left for the reader to notice a league missing.
 */
function unfinished(parts) {
  const out = Object.fromEntries(Object.entries(parts).filter(([, n]) => n > 0));
  if (!Object.keys(out).length) return null;
  const why = [];
  if (out.leagues_not_added || out.seasons_not_added) {
    why.push(`an account holds at most ${MAX} leagues and ${MAX_ROWS} seasons in all`);
  }
  if (out.history_cut_short || out.team_names_missing) {
    why.push(`one sync asks Sleeper at most ${FETCH_BUDGET} times`);
  }
  out.note = `Not everything was synced: ${why.join("; ")}.`;
  return out;
}

/** One league by id, with the seasons behind it. */
async function addOne(env, session, provider, leagueId) {
  const early = await tooSoon(env, session.uid, ADD_SECONDS, env.DB.prepare(
    "SELECT last_synced_at AS at FROM leagues WHERE user_id = ? AND provider = ? AND league_id = ?")
    .bind(session.uid, provider, leagueId));
  if (early) return early;

  const ask = asker(FETCH_BUDGET);
  // Asked before anything is claimed, so a mistyped id costs one call and no
  // wait before the corrected one.
  const first = await ask(`league/${leagueId}`);
  if (first.status === 0) return json({ ok: false, error: "could not reach Sleeper" }, 502);
  if (!first.ok && first.status !== 404) {
    return json({ ok: false, error: "Sleeper did not answer" }, 502);
  }
  if (!first.ok || !first.data?.league_id) {
    return json({ ok: false, error: "no Sleeper league with that id" }, 404);
  }

  const claimed = await claim(env.DB, session.uid, CLAIM, ADD_SECONDS);
  if (claimed.ok === false) return wait(claimed.retryAfter, "just refreshed");

  // Its earlier seasons too, the same as the username flow - a league added by
  // id should not be a poorer relation.
  const chain = chainFrom(first.data, true);
  await walkBack(ask, [chain]);

  const stored = await storedRows(env, session, provider);
  if (!stored.ok) return stored.response;
  const known = new Map(stored.rows.map((r) => [r.league_id, r]));
  const done = await store(env, session, provider, stored.rows, flatten([chain], known));
  if (done instanceof Response) return done;

  const mine = done.leagues.find((l) => l.league_id === String(first.data.league_id));
  if (!mine) return json({ ok: false, error: "too many leagues" }, 413);

  const left = unfinished({
    seasons_not_added: done.dropped.rows,
    history_cut_short: chain.next && chain.rows.length < MAX_SEASONS ? 1 : 0,
  });
  return json({ ok: true, synced: done.leagues.length, complete: !left,
    ...(left ? { unfinished: left } : {}),
    league: { provider, sport: SPORT[provider], league_id: leagueId,
              name: first.data.name || null, season: first.data.season || null,
              last_synced_at: done.now } });
}

/** One ESPN league season's settings: { ok, status, data }. */
async function espnLeague(season, league) {
  const url = season >= 2018
    ? `${ESPN}/seasons/${season}/segments/0/leagues/${league}?view=mSettings&view=mStatus`
    : `${ESPN}/leagueHistory/${league}?seasonId=${season}&view=mSettings&view=mStatus`;
  try {
    const r = await fetch(url, { signal: AbortSignal.timeout(TIMEOUT_MS),
                                 headers: { accept: "application/json" } });
    if (!r.ok) return { ok: false, status: r.status };
    const d = await r.json();
    return { ok: true, status: 200, data: Array.isArray(d) ? d[0] : d };
  } catch {
    return { ok: false, status: 0 };
  }
}

/**
 * One ESPN league and every season ESPN lists for it.
 *
 * ESPN keeps a league's id from year to year where Sleeper issues a new one,
 * so the season is part of the id stored here and the seasons before come
 * from this one's status.previousSeasons - one request, not a walk. Without a
 * season this one is tried, then last year's (a league not yet renewed).
 *
 * Public leagues only, deliberately: the request carries no ESPN login and
 * none is ever stored. A private league is refused with the one setting its
 * commissioner can change, rather than an offer to hold anybody's cookies.
 */
async function addEspn(env, session, raw) {
  const [, given, league] = SHAPES.espn.exec(raw);
  const early = await tooSoon(env, session.uid, ADD_SECONDS, env.DB.prepare(
    `SELECT MAX(last_synced_at) AS at FROM leagues
      WHERE user_id = ? AND provider = 'espn' AND league_id LIKE ?`)
    .bind(session.uid, `espn:%:${league}`));
  if (early) return early;

  const now = new Date();
  const current = now.getUTCMonth() < 2 ? now.getUTCFullYear() - 1 : now.getUTCFullYear();
  let found = null;
  let status = 404;
  for (const season of given ? [Number(given)] : [current, current - 1]) {
    const got = await espnLeague(season, league);
    status = got.status;
    if (got.ok && got.data) { found = { season, data: got.data }; break; }
    if (status === 0 || status === 401 || status === 403) break;
  }
  if (!found) {
    if (status === 401 || status === 403) {
      return json({ ok: false, private: true, error: "ESPN keeps that league private. Its "
        + "commissioner can open it to the public in the league's settings (League "
        + "Manager, Basic Settings); no ESPN login is needed after that." }, 403);
    }
    if (status === 0) return json({ ok: false, error: "could not reach ESPN" }, 502);
    return json({ ok: false, error: "ESPN has no football league with that id." }, 404);
  }

  const claimed = await claim(env.DB, session.uid, CLAIM, ADD_SECONDS);
  if (claimed.ok === false) return wait(claimed.retryAfter, "just refreshed");

  const name = found.data.settings?.name || null;
  const earlier = (found.data.status?.previousSeasons || [])
    .map(Number).filter((y) => y < found.season).sort((a, b) => b - a);
  const seasons = [found.season, ...earlier].slice(0, MAX_SEASONS);
  const lineage = `espn:${seasons[seasons.length - 1]}:${league}`;
  const rows = seasons.map((y, i) => ({
    league_id: `espn:${y}:${league}`, name, season: String(y), team_name: null,
    lineage_id: lineage, current: i === 0 }));

  const stored = await storedRows(env, session, "espn");
  if (!stored.ok) return stored.response;
  const done = await store(env, session, "espn", stored.rows, rows);
  if (done instanceof Response) return done;
  const id = rows[0].league_id;
  if (!done.leagues.find((l) => l.league_id === id)) {
    return json({ ok: false, error: "too many leagues" }, 413);
  }
  const left = unfinished({ seasons_not_added: done.dropped.rows });
  return json({ ok: true, synced: done.leagues.length, complete: !left,
    ...(left ? { unfinished: left } : {}),
    league: { provider: "espn", sport: "nfl", league_id: id, name,
              season: String(found.season), last_synced_at: done.now } });
}

/**
 * Every league a Sleeper account is in this season, with the name of their
 * team in each.
 *
 * Rate-limited on the whole account rather than per league: this is one
 * button, and it is the one worth holding down.
 */
async function syncAll(env, session, provider, username) {
  if (provider !== "sleeper") {
    return json({ ok: false, error: "only Sleeper can be synced by username" }, 400);
  }
  if (!USERNAME.test(username)) {
    return json({ ok: false, error: "That does not look like a Sleeper username." }, 400);
  }

  const early = await tooSoon(env, session.uid, REFRESH_SECONDS, env.DB.prepare(
    "SELECT MAX(last_synced_at) AS at FROM leagues WHERE user_id = ?").bind(session.uid));
  if (early) return early;

  // The three calls that say whether there is anything to sync come before
  // the claim, so a mistyped username costs the reader nothing but the answer.
  const ask = asker(FETCH_BUDGET);
  const [state, who] = await Promise.all([
    ask("state/nfl"), ask(`user/${encodeURIComponent(username)}`)]);
  if (who.status === 0) return json({ ok: false, error: "could not reach Sleeper" }, 502);
  const user = who.ok ? who.data : null;
  if (!user || !user.user_id) {
    return json({ ok: false, error: `Sleeper has no user called "${username}".` }, 404);
  }
  const season = String(state.data?.season || new Date().getFullYear());
  const list = await ask(`user/${user.user_id}/leagues/nfl/${season}`);
  if (list.status === 0) return json({ ok: false, error: "could not reach Sleeper" }, 502);
  const found = Array.isArray(list.data) ? list.data : [];
  if (!found.length) {
    return json({ ok: false,
      error: `Sleeper shows no ${season} NFL leagues for "${username}".` }, 404);
  }

  const claimed = await claim(env.DB, session.uid, CLAIM, REFRESH_SECONDS);
  if (claimed.ok === false) return wait(claimed.retryAfter, "just refreshed");

  const stored = await storedRows(env, session, provider);
  if (!stored.ok) return stored.response;
  const known = new Map(stored.rows.map((r) => [r.league_id, r]));

  // The list already carries each league's name, season and link to the
  // season before, so this season costs no call of its own. What the budget
  // is spent on, in the order it matters when it runs short:
  //   1. this season's team names - they label the league picker;
  //   2. the seasons behind each league;
  //   3. those seasons' team names, where none is stored yet (a finished
  //      season's name does not change, so one fetch is enough for ever).
  const taken = found.slice(0, MAX);
  const chains = taken.map((lg) => chainFrom({ ...lg, season: lg.season || season }, true));
  await Promise.all(chains.map(async (c) => {
    c.rows[0].team_name = await teamIn(ask, c.rows[0].league_id, user.user_id);
  }));
  await walkBack(ask, chains);
  const earlier = chains.flatMap((c) => c.rows.slice(1))
    .filter((r) => !known.get(r.league_id)?.team_name);
  await Promise.all(earlier.map(async (r) => {
    r.team_name = await teamIn(ask, r.league_id, user.user_id);
  }));

  const rows = flatten(chains, known).map((r) => ({ ...r, provider_user_id: user.user_id }));
  const done = await store(env, session, provider, stored.rows, rows);
  if (done instanceof Response) return done;
  if (!done.leagues.length) return json({ ok: false, error: "too many leagues" }, 413);

  const unnamed = new Set(rows.filter((r) => r.team_name === undefined).map((r) => r.league_id));
  const left = unfinished({
    leagues_not_added: found.length - taken.length + done.dropped.leagues,
    seasons_not_added: done.dropped.rows,
    history_cut_short: chains.filter((c) => c.next && c.rows.length < MAX_SEASONS).length,
    team_names_missing: done.leagues.filter((l) => unnamed.has(l.league_id)).length,
  });
  return json({ ok: true, synced: done.leagues.length, leagues_found: taken.length,
    username, complete: !left, ...(left ? { unfinished: left } : {}),
    sleeper_calls: ask.used, leagues: done.leagues });
}

async function guard(request, env) {
  if (!configured(env)) return json({ ok: false, error: "accounts are not configured" }, 503);
  const session = await readSession(request, env);
  if (!session) return json({ ok: false, error: "not signed in" }, 401);
  return session;
}
