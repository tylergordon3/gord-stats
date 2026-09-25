/**
 * The signed-in reader's own fantasy leagues.
 *
 *   GET    /api/leagues                          -> { leagues: [...] }
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
 * Sleeper only. No credentials are stored because none are needed: its API is
 * keyless. Yahoo was here briefly and came out again - its public API serves
 * only leagues a commissioner has set public, and reaching a private one means
 * OAuth, an app registration and stored refresh tokens. That would turn a
 * database worth very little if taken into one holding read access to other
 * people's accounts, which is not a trade worth making for a league nobody has
 * asked for yet. "Ask your commissioner to make it public" costs nothing.
 *
 * The `provider` column stays in the table so a second platform later needs no
 * migration; today it only ever holds "sleeper".
 *
 * Adding a league verifies it against Sleeper first, so a typo is caught here
 * rather than becoming a row that never resolves to anything.
 */
import { configured, json, readSession } from "./_lib/session.js";

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

// A reader with more leagues than this is probing; the row count stays bounded.
// One row per league per season, so a reader in four leagues with a few years
// of history each is normal - the old limit of 20 would have cut them off.
const MAX = 20;            // leagues, before history
const MAX_SEASONS = 12;    // seasons walked back per league
const MAX_ROWS = 120;      // total rows one account can hold
// Sleeper ids are long digit strings.
const SHAPES = { sleeper: /^[0-9]{6,32}$/ };
const SPORT = { sleeper: "nfl" };
// How long a reader has to wait before pulling the same league again. The
// providers are generous, but a refresh button with no floor is a button that
// gets held down.
const REFRESH_SECONDS = 300;
// Sleeper usernames: what its own signup allows, and nothing that could be
// read as a path.
const USERNAME = /^[A-Za-z0-9_.-]{1,64}$/;

export async function onRequestGet({ request, env }) {
  const session = await guard(request, env);
  if (session instanceof Response) return session;

  const got = await db(() => env.DB.prepare(
    `SELECT provider, sport, league_id, name, season, team_name, lineage_id,
            last_synced_at
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
    return json({ ok: false,
      error: "A Sleeper league id is the long number in the league's web address." }, 400);
  }

  const found0 = await db(() => env.DB.prepare(
    "SELECT last_synced_at FROM leagues WHERE user_id = ? AND provider = ? AND league_id = ?")
    .bind(session.uid, provider, leagueId).first());
  if (!found0.ok) return found0.response;
  const existing = found0.value;

  // The rate limit is on the stored timestamp rather than anything in the
  // browser, so it holds across reloads and second tabs.
  if (existing) {
    const age = (Date.now() - Date.parse(existing.last_synced_at)) / 1000;
    if (age < REFRESH_SECONDS) {
      return json({ ok: false, error: "just refreshed",
        retry_after: Math.ceil(REFRESH_SECONDS - age) }, 429);
    }
  } else {
    const { count } = await env.DB.prepare(
      "SELECT COUNT(*) AS count FROM leagues WHERE user_id = ?").bind(session.uid).first();
    if (count >= MAX) return json({ ok: false, error: "too many leagues" }, 413);
  }

  const found = await lookup(provider, leagueId);
  if (!found.ok) return json(found, found.status || 502);

  // Its earlier seasons too, the same as the username flow - a league added by
  // id should not be a poorer relation.
  const chain = await history(leagueId);
  const lineage = chain.length ? chain[chain.length - 1].league_id : leagueId;
  const now = new Date().toISOString();
  const rows = chain.length ? chain
    : [{ league_id: leagueId, name: found.name, season: found.season }];
  const wrote = await db(() => env.DB.batch(rows.map((r) => env.DB.prepare(UPSERT).bind(
    session.uid, provider, SPORT[provider], r.league_id, r.name, r.season,
    null, null, lineage, now, now))));
  if (!wrote.ok) return wrote.response;

  return json({ ok: true, synced: rows.length,
    league: { provider, sport: SPORT[provider], league_id: leagueId,
              name: found.name, season: found.season, last_synced_at: now } });
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

const UPSERT =
  `INSERT INTO leagues (user_id, provider, sport, league_id, name, season,
                        team_name, provider_user_id, lineage_id,
                        created_at, last_synced_at)
   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
   ON CONFLICT (user_id, provider, league_id)
   DO UPDATE SET name = excluded.name, season = excluded.season,
                 team_name = COALESCE(excluded.team_name, leagues.team_name),
                 provider_user_id = COALESCE(excluded.provider_user_id,
                                             leagues.provider_user_id),
                 lineage_id = COALESCE(excluded.lineage_id, leagues.lineage_id),
                 last_synced_at = excluded.last_synced_at`;

/**
 * A league's earlier seasons.
 *
 * Sleeper gives every season its own league id and links them backwards with
 * previous_league_id, so one walk gets the whole history - the site's own
 * league chains 2026 to 2023 that way. Capped, and guarded against a cycle:
 * these ids come from an API, and a loop here would be an endless one.
 */
async function history(leagueId) {
  const chain = [];
  const seen = new Set();
  let id = leagueId;
  while (id && !seen.has(id) && chain.length < MAX_SEASONS) {
    seen.add(id);
    let data;
    try {
      const r = await fetch(`https://api.sleeper.app/v1/league/${id}`);
      if (!r.ok) break;
      data = await r.json();
    } catch { break; }
    if (!data || !data.league_id) break;
    chain.push({ league_id: String(data.league_id), name: data.name || null,
                 season: String(data.season || "") });
    id = data.previous_league_id ? String(data.previous_league_id) : null;
  }
  return chain;
}

/** The reader's team name in one league, or null. */
async function teamIn(leagueId, userId) {
  try {
    const r = await fetch(`https://api.sleeper.app/v1/league/${leagueId}/users`);
    if (!r.ok) return null;
    const mine = (await r.json()).find((x) => x.user_id === userId);
    return (mine?.metadata?.team_name) || mine?.display_name || null;
  } catch {
    return null;
  }
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

  const last = await db(() => env.DB.prepare(
    "SELECT MAX(last_synced_at) AS at FROM leagues WHERE user_id = ?")
    .bind(session.uid).first());
  if (!last.ok) return last.response;
  if (last.value?.at) {
    const age = (Date.now() - Date.parse(last.value.at)) / 1000;
    if (age < REFRESH_SECONDS) {
      return json({ ok: false, error: "just refreshed",
        retry_after: Math.ceil(REFRESH_SECONDS - age) }, 429);
    }
  }

  let season, user, leagues;
  try {
    const state = await fetch("https://api.sleeper.app/v1/state/nfl").then((r) => r.json());
    season = String(state?.season || new Date().getFullYear());

    const u = await fetch(
      `https://api.sleeper.app/v1/user/${encodeURIComponent(username)}`);
    user = u.ok ? await u.json() : null;
    if (!user || !user.user_id) {
      return json({ ok: false, error: `Sleeper has no user called "${username}".` }, 404);
    }

    const r = await fetch(
      `https://api.sleeper.app/v1/user/${user.user_id}/leagues/nfl/${season}`);
    leagues = r.ok ? await r.json() : [];
  } catch {
    return json({ ok: false, error: "could not reach Sleeper" }, 502);
  }

  if (!leagues.length) {
    return json({ ok: false,
      error: `Sleeper shows no ${season} NFL leagues for "${username}".` }, 404);
  }
  leagues = leagues.slice(0, MAX);

  // Each league, then every season behind it. The team name is fetched per
  // season because it changes - people rename their team most years - and a
  // season that will not answer is still worth storing without one.
  const perLeague = await Promise.all(leagues.map(async (lg) => {
    const chain = await history(String(lg.league_id));
    if (!chain.length) {
      chain.push({ league_id: String(lg.league_id), name: lg.name || null,
                   season: String(lg.season || season) });
    }
    // The oldest id in the chain names the lineage, so every season of one
    // league groups under it however many seasons are added later.
    const lineage = chain[chain.length - 1].league_id;
    return Promise.all(chain.map(async (s) => ({
      ...s,
      team_name: await teamIn(s.league_id, user.user_id),
      lineage_id: lineage,
    })));
  }));

  const rows = perLeague.flat().slice(0, MAX_ROWS);

  const now = new Date().toISOString();
  const wrote = await db(() => env.DB.batch(rows.map((r) => env.DB.prepare(UPSERT).bind(
    session.uid, provider, SPORT[provider], r.league_id, r.name, r.season,
    r.team_name, user.user_id, r.lineage_id, now, now))));
  if (!wrote.ok) return wrote.response;

  return json({ ok: true, synced: rows.length, leagues_found: leagues.length,
    username,
    leagues: rows.map((r) => ({ provider, sport: SPORT[provider], ...r,
                                last_synced_at: now })) });
}

/** Ask Sleeper whether this league exists, and what it is called. */
async function lookup(provider, leagueId) {
  try {
    const r = await fetch(`https://api.sleeper.app/v1/league/${leagueId}`);
    if (r.status === 404) return { ok: false, error: "no Sleeper league with that id", status: 404 };
    if (!r.ok) return { ok: false, error: "Sleeper did not answer", status: 502 };
    const data = await r.json();
    if (!data || !data.league_id) {
      return { ok: false, error: "no Sleeper league with that id", status: 404 };
    }
    return { ok: true, name: data.name || null, season: data.season || null };
  } catch {
    return { ok: false, error: "could not reach Sleeper", status: 502 };
  }
}

async function guard(request, env) {
  if (!configured(env)) return json({ ok: false, error: "accounts are not configured" }, 503);
  const session = await readSession(request, env);
  if (!session) return json({ ok: false, error: "not signed in" }, 401);
  return session;
}
