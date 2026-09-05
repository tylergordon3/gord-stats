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
 * Keys are "sport:team_id" on the wire and split across two columns in the
 * table - see deploy/d1-schema.sql for why.
 */
import { configured, json, readSession } from "./_lib/session.js";

// A reader following more teams than this has hit a bug or is probing; either
// way the row count per user stays bounded.
const MAX = 500;
const KEY = /^[a-z0-9-]{1,32}:[A-Za-z0-9_.~:@+-]{1,64}$/;

export async function onRequestGet({ request, env }) {
  const session = await guard(request, env);
  if (session instanceof Response) return session;

  const { results } = await env.DB
    .prepare("SELECT sport, team_id FROM favorites WHERE user_id = ?")
    .bind(session.uid).all();

  return json({ favorites: (results || []).map((r) => `${r.sport}:${r.team_id}`) });
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

  // Anything that is not a well-formed key is dropped rather than rejected:
  // one bad entry in a synced list should not cost the reader the other
  // forty-nine, and the shape is pinned so a key can never carry a payload.
  const rows = [];
  const seen = new Set();
  for (const key of keys) {
    if (typeof key !== "string" || !KEY.test(key) || seen.has(key)) continue;
    seen.add(key);
    const cut = key.indexOf(":");
    rows.push([key.slice(0, cut), key.slice(cut + 1)]);
  }

  const now = new Date().toISOString();
  const statements = [
    env.DB.prepare("DELETE FROM favorites WHERE user_id = ?").bind(session.uid),
    ...rows.map(([sport, team]) => env.DB.prepare(
      "INSERT INTO favorites (user_id, sport, team_id, created_at) VALUES (?, ?, ?, ?)")
      .bind(session.uid, sport, team, now)),
  ];
  // One batch, so a reader is never left with the delete applied and the
  // insert not.
  await env.DB.batch(statements);

  return json({ ok: true, count: rows.length });
}

async function guard(request, env) {
  if (!configured(env)) return json({ ok: false, error: "accounts are not configured" }, 503);
  const session = await readSession(request, env);
  if (!session) return json({ ok: false, error: "not signed in" }, 401);
  return session;
}
