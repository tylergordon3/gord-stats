/**
 * The signed-in reader's own fantasy leagues.
 *
 *   GET    /api/leagues                     -> { leagues: [...] }
 *   POST   /api/leagues  <- { provider, league_id }   add, after checking it
 *   POST   /api/leagues  <- { provider, league_id, refresh: true }  re-fetch
 *   DELETE /api/leagues?provider=..&league_id=..      remove
 *
 * No provider credentials are stored, because none are needed: Sleeper's API
 * is keyless, and Yahoo's pub-api-ro serves a league whose owner has made it
 * public. A private Yahoo league answers 401 there, and this says so plainly
 * rather than pretending it can sign the reader in to Yahoo.
 *
 * Adding a league verifies it against the provider first, so a typo is caught
 * here rather than becoming a row that never resolves to anything.
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
const MAX = 20;
// Sleeper ids are long digit strings; Yahoo keys are "<game>.l.<id>".
const SHAPES = {
  sleeper: /^[0-9]{6,32}$/,
  yahoo: /^[0-9]{1,4}\.l\.[0-9]{1,12}$/,
};
const SPORT = { sleeper: "nfl", yahoo: "cfb" };
// How long a reader has to wait before pulling the same league again. The
// providers are generous, but a refresh button with no floor is a button that
// gets held down.
const REFRESH_SECONDS = 300;

export async function onRequestGet({ request, env }) {
  const session = await guard(request, env);
  if (session instanceof Response) return session;

  const got = await db(() => env.DB.prepare(
    `SELECT provider, sport, league_id, name, season, last_synced_at
       FROM leagues WHERE user_id = ? ORDER BY created_at`)
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
  const leagueId = String(body?.league_id || "").trim();
  if (!SHAPES[provider]) return json({ ok: false, error: "unknown provider" }, 400);
  if (!SHAPES[provider].test(leagueId)) {
    return json({ ok: false, error: provider === "sleeper"
      ? "A Sleeper league id is the long number in the league's web address."
      : "A Yahoo league key looks like 474.l.21318." }, 400);
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

  const now = new Date().toISOString();
  await env.DB.prepare(
    `INSERT INTO leagues (user_id, provider, sport, league_id, name, season,
                          created_at, last_synced_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT (user_id, provider, league_id)
     DO UPDATE SET name = excluded.name, season = excluded.season,
                   last_synced_at = excluded.last_synced_at`)
    .bind(session.uid, provider, SPORT[provider], leagueId,
          found.name, found.season, now, now).run();

  return json({ ok: true, league: { provider, sport: SPORT[provider],
    league_id: leagueId, name: found.name, season: found.season,
    last_synced_at: now } });
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

  const gone = await db(() => env.DB.prepare(
    "DELETE FROM leagues WHERE user_id = ? AND provider = ? AND league_id = ?")
    .bind(session.uid, provider, leagueId).run());
  if (!gone.ok) return gone.response;

  return json({ ok: true });
}

/** Ask the provider whether this league exists, and what it is called. */
async function lookup(provider, leagueId) {
  try {
    if (provider === "sleeper") {
      const r = await fetch(`https://api.sleeper.app/v1/league/${leagueId}`);
      if (r.status === 404) return { ok: false, error: "no Sleeper league with that id", status: 404 };
      if (!r.ok) return { ok: false, error: "Sleeper did not answer", status: 502 };
      const data = await r.json();
      if (!data || !data.league_id) {
        return { ok: false, error: "no Sleeper league with that id", status: 404 };
      }
      return { ok: true, name: data.name || null, season: data.season || null };
    }

    // Yahoo's public API answers for a league its owner has made public and
    // 401s for one they have not. That distinction is the whole message here:
    // there is nothing the reader can type that fixes a private league.
    const r = await fetch(
      `https://pub-api-ro.fantasysports.yahoo.com/fantasy/v2/league/${leagueId}?format=json`,
      { headers: { "User-Agent": "Mozilla/5.0" } });
    if (r.status === 401 || r.status === 403) {
      return { ok: false, status: 403, error:
        "Yahoo only shares a league that is set to public. Change the league's "
        + "visibility in Yahoo, or ask its commissioner to." };
    }
    if (r.status === 404) return { ok: false, error: "no Yahoo league with that key", status: 404 };
    if (!r.ok) return { ok: false, error: "Yahoo did not answer", status: 502 };
    const data = await r.json();
    const league = data?.fantasy_content?.league;
    // Yahoo nests everything as a list of single-key objects; the league's own
    // fields are the first entry.
    const fields = Array.isArray(league) ? league[0] : league;
    if (!fields) return { ok: false, error: "no Yahoo league with that key", status: 404 };
    return { ok: true, name: fields.name || null, season: fields.season || null };
  } catch {
    return { ok: false, error: "could not reach the provider", status: 502 };
  }
}

async function guard(request, env) {
  if (!configured(env)) return json({ ok: false, error: "accounts are not configured" }, 503);
  const session = await readSession(request, env);
  if (!session) return json({ ok: false, error: "not signed in" }, 401);
  return session;
}
