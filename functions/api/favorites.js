/**
 * The signed-in reader's starred teams.
 *
 *   GET  /api/favorites   -> { favorites: ["cfb:194", ...] }
 *   PUT  /api/favorites   <- { favorites: [...] }   replaces the whole list
 *
 * A whole-list PUT rather than add/remove calls, because the browser already
 * holds the list as one array and a replace cannot drift out of step with it
 * the way a missed DELETE would.
 *
 * Whole-list on the wire, but not in the database: a PUT writes only the rows
 * that changed. It used to delete the reader's list and insert it again, so
 * starring one team rewrote all of them - up to 500 rows, three writes each
 * with the old index - and a few dozen scripted PUTs spent D1's whole day of
 * writes, which is also the day nobody could sign in. What a PUT may change
 * is capped per account per day as well, and by the site's own daily ceiling
 * (_lib/limits.js): over that, a 503 with Retry-After and nothing written.
 *
 * Keys are "sport:team_id" on the wire and split across two columns in the
 * table - see deploy/d1-schema.sql for why.
 */
import { configured, json, readSession } from "./_lib/session.js";
import { refusal, spend } from "./_lib/limits.js";

// A reader following more teams than this has hit a bug or is probing; either
// way the row count per user stays bounded.
const MAX = 500;
const KEY = /^[a-z0-9-]{1,32}:[A-Za-z0-9_.~:@+-]{1,64}$/;

// Two statements whatever the size of the change: each list travels as one
// JSON parameter, which keeps a PUT inside D1's 100 bound parameters and the
// Workers cap on queries per request however many teams it touches.
//
// The delete is "everything not in the new list" rather than "what this
// request saw removed", so two tabs saving at once still leave the list one
// of them sent. A key splits at its first ':'; a sport never contains one.
const REMOVE =
  `DELETE FROM favorites
    WHERE user_id = ?1
      AND sport || ':' || team_id NOT IN (SELECT value FROM json_each(?2))`;
const ADD =
  `INSERT OR IGNORE INTO favorites (user_id, sport, team_id, created_at)
   SELECT ?1, substr(value, 1, instr(value, ':') - 1),
          substr(value, instr(value, ':') + 1), ?2
     FROM json_each(?3)`;

/**
 * The keys worth keeping from a PUT body, in order.
 *
 * Anything that is not a well-formed key is dropped rather than rejected: one
 * bad entry in a synced list should not cost the reader the other forty-nine,
 * and the shape is pinned so a key can never carry a payload.
 */
export function clean(keys) {
  const out = [];
  const seen = new Set();
  for (const key of keys) {
    if (typeof key !== "string" || !KEY.test(key) || seen.has(key)) continue;
    seen.add(key);
    out.push(key);
  }
  return out;
}

/** What turning list `have` into list `want` adds and removes. */
export function diff(have, want) {
  const had = new Set(have);
  const wanted = new Set(want);
  return {
    added: want.filter((k) => !had.has(k)),
    removed: have.filter((k) => !wanted.has(k)),
  };
}

export async function onRequestGet({ request, env }) {
  const session = await guard(request, env);
  if (session instanceof Response) return session;

  return json({ favorites: await stored(env.DB, session.uid) });
}

export async function onRequestPut({ request, env }) {
  const session = await guard(request, env);
  if (session instanceof Response) return session;

  let body;
  try {
    body = await request.json();
  } catch {
    return json({ ok: false, error: "expected JSON" }, 400);
  }

  const keys = Array.isArray(body?.favorites) ? body.favorites : null;
  if (!keys) return json({ ok: false, error: "expected { favorites: [...] }" }, 400);
  if (keys.length > MAX) return json({ ok: false, error: "too many favorites" }, 413);

  const want = clean(keys);
  const { added, removed } = diff(await stored(env.DB, session.uid), want);
  // The browser pushes after every star and again on each first sign-in, so
  // plenty of PUTs change nothing - and those now write nothing either.
  if (!added.length && !removed.length) return json({ ok: true, count: want.length });

  const allowed = await spend(env.DB, session.uid, added.length + removed.length);
  if (!allowed.ok) return refusal(allowed, "too many changes today");

  const statements = [];
  if (removed.length) {
    statements.push(env.DB.prepare(REMOVE).bind(session.uid, JSON.stringify(want)));
  }
  if (added.length) {
    statements.push(env.DB.prepare(ADD)
      .bind(session.uid, new Date().toISOString(), JSON.stringify(added)));
  }
  // One batch, so a reader is never left with the delete applied and the
  // insert not.
  await env.DB.batch(statements);

  return json({ ok: true, count: want.length });
}

async function stored(db, uid) {
  const { results } = await db
    .prepare("SELECT sport, team_id FROM favorites WHERE user_id = ?")
    .bind(uid).all();
  return (results || []).map((r) => `${r.sport}:${r.team_id}`);
}

async function guard(request, env) {
  if (!configured(env)) return json({ ok: false, error: "accounts are not configured" }, 503);
  const session = await readSession(request, env);
  if (!session) return json({ ok: false, error: "not signed in" }, 401);
  return session;
}
