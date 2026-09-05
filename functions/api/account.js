/**
 * DELETE /api/account -> erase this reader entirely.
 *
 * Shipped with the feature rather than after it: the moment the site stores an
 * email address, being able to remove it stops being optional. The favourites
 * go with the row through ON DELETE CASCADE, and the session cookie is cleared
 * so the browser does not keep presenting a token for a user that is gone.
 */
import {
  SESSION_COOKIE, configured, json, readSession, setCookie,
} from "./_lib/session.js";

export async function onRequestDelete({ request, env }) {
  if (!configured(env)) return json({ ok: false, error: "accounts are not configured" }, 503);
  const session = await readSession(request, env);
  if (!session) return json({ ok: false, error: "not signed in" }, 401);

  await env.DB.batch([
    env.DB.prepare("DELETE FROM favorites WHERE user_id = ?").bind(session.uid),
    env.DB.prepare("DELETE FROM users WHERE id = ?").bind(session.uid),
  ]);

  return json({ ok: true }, 200, {
    "set-cookie": setCookie(SESSION_COOKIE, "", { maxAge: 0 }),
  });
}
